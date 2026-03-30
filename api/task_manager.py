"""
任务管理器 - 处理异步流水线任务
支持日志持久化和单步测试
"""
import asyncio
import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

from config import BASE_DIR, OUTPUT_DIR, load_api_config
from core.llm_budget import llm_budget
from core.pipeline_config import STEP_NAMES
from core.pipeline_orchestrator import PipelineOrchestrator
from modules.project_charter import (
    default_project_charter_template,
    load_project_charter,
    normalize_project_charter,
    save_project_charter,
    validate_project_charter,
)
from modules.executable_spec_builder import (
    build_executable_spec,
    save_executable_spec,
    validate_executable_spec,
)
from modules.runtime_verifier import run_runtime_verification
from modules.freeze_package import build_freeze_package
from modules.semantic_homogeneity_gate import apply_semantic_homogeneity_gate
from modules.spec_review import (
    approve_spec_review,
    get_spec_review_status,
    save_spec_review_artifacts,
)
from modules.pre_submission_risk import run_submission_risk_precheck
from modules.artifact_naming import preferred_artifact_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 日志持久化目录
TASK_LOGS_DIR = BASE_DIR / "data" / "task_logs"
TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)

SPEC_APPROVAL_REQUIRED_STEPS = {"code", "verify", "document", "pdf", "freeze"}


class TaskManager:
    """异步任务管理器"""

    def __init__(self):
        self._tasks: Dict[str, Dict] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=10)  # 支持更多并行任务
        self._callbacks: Dict[str, List[Callable]] = {}  # WebSocket 回调
        self._project_task_map: Dict[str, str] = {}  # project_id -> latest task_id

    def _run_api_preflight(
        self,
        task_id: str,
        provider_override: str = "",
        model_override: str = "",
    ) -> bool:
        """在流水线启动前预检 API 连通性，避免跑到中途才发现鉴权/网络错误"""
        from core.deepseek_client import DeepSeekClient

        provider = str(provider_override or "").strip()
        model = str(model_override or "").strip()
        if provider or model:
            self.add_log(
                task_id,
                "INFO",
                f"执行 API 连通性预检（代码步骤覆盖）provider={provider or '(follow-global)'}, model={model or '(provider-default)'}...",
            )
        else:
            self.add_log(task_id, "INFO", "执行 API 连通性预检...")
        try:
            client = DeepSeekClient(
                provider_name=provider or None,
                model=model or None,
            )
            ok = client.test_connection()
            if ok:
                self.add_log(task_id, "SUCCESS", "API 连通性预检通过")
                return True
            self.add_log(task_id, "ERROR", "API 连通性预检失败")
            return False
        except Exception as e:
            self.add_log(task_id, "ERROR", f"API 连通性预检异常: {e}")
            return False

    @staticmethod
    def _auto_confirm_spec_review_enabled() -> bool:
        """是否开启自动规格确认（API/Web 端默认开启）。"""
        try:
            config = load_api_config() or {}
        except Exception:
            return True
        return bool(config.get("auto_confirm_spec_review", True))

    def _auto_approve_spec_if_enabled(self, project_name: str, task_id: str, stage: str = "") -> bool:
        """尝试自动确认规格；返回当前规格是否已确认。"""
        project_dir = OUTPUT_DIR / project_name
        spec_path = project_dir / "project_executable_spec.json"
        status = get_spec_review_status(project_dir, spec_path)
        if status.get("approved"):
            return True

        if not self._auto_confirm_spec_review_enabled():
            return False

        result = approve_spec_review(project_dir, reviewer="api-auto")
        if result.get("ok"):
            refreshed = get_spec_review_status(project_dir, spec_path)
            if refreshed.get("approved"):
                self.add_log(
                    task_id,
                    "INFO",
                    f"规格已自动确认{f'（{stage}）' if stage else ''}。",
                )
                return True

        self.add_log(
            task_id,
            "WARNING",
            "规格自动确认失败"
            + (f"（{stage}）" if stage else "")
            + f"：{result.get('message') if isinstance(result, dict) else 'unknown'}",
        )
        return False

    def create_task(
        self,
        project_id: str,
        project_name: str,
        code_generation_overrides: Optional[Dict[str, Any]] = None,
        project_charter: Optional[Dict[str, Any]] = None,
    ) -> str:
        """创建新任务"""
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "project_id": project_id,
                "project_name": project_name,
                "status": "pending",
                "progress": 0,
                "current_step": None,
                "message": None,
                "logs": [],
                "created_at": datetime.now().isoformat(),
                "code_generation_overrides": code_generation_overrides or {},
                "project_charter": project_charter or {},
                "cancel_requested": False,
            }
            # 记录项目与任务的映射
            self._project_task_map[project_id] = task_id
        return task_id

    def get_project_logs(self, project_id: str) -> List[Dict]:
        """获取项目的历史日志（从文件加载）"""
        log_file = TASK_LOGS_DIR / f"{project_id}.json"
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("logs", [])
            except Exception as e:
                logger.error(f"读取日志文件失败: {e}")
        return []

    def _save_logs_to_file(self, task_id: str):
        """保存任务日志到文件"""
        task = self._tasks.get(task_id)
        if not task:
            return

        project_id = task.get("project_id")
        if not project_id:
            return

        log_file = TASK_LOGS_DIR / f"{project_id}.json"
        try:
            data = {
                "project_id": project_id,
                "project_name": task.get("project_name"),
                "last_task_id": task_id,
                "last_updated": datetime.now().isoformat(),
                "status": task.get("status"),
                "logs": task.get("logs", [])
            }
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存日志文件失败: {e}")

    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs):
        """更新任务状态"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(kwargs)
                # 触发 WebSocket 回调
                self._notify_callbacks(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """请求取消任务。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.get("status") not in {"pending", "running"}:
                return False
            task["cancel_requested"] = True
            self._notify_callbacks(task_id)
            return True

    def add_log(self, task_id: str, level: str, message: str, console_only: bool = False):
        """
        添加日志

        Args:
            task_id: 任务ID
            level: 日志级别
            message: 日志消息
            console_only: 仅在控制台显示，不发送到前端（用于技术细节）
        """
        # 始终在控制台输出
        logger.info(f"[{level}] {message}")

        # 如果标记为 console_only，不发送到前端
        if console_only:
            return

        with self._lock:
            if task_id in self._tasks:
                log_entry = {
                    "id": str(uuid.uuid4())[:8],
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": message
                }
                self._tasks[task_id]["logs"].append(log_entry)
                self._notify_callbacks(task_id)
                # 持久化保存日志
                self._save_logs_to_file(task_id)

    def register_callback(self, task_id: str, callback: Callable):
        """注册 WebSocket 回调"""
        with self._lock:
            if task_id not in self._callbacks:
                self._callbacks[task_id] = []
            self._callbacks[task_id].append(callback)

    def unregister_callback(self, task_id: str, callback: Callable):
        """注销回调"""
        with self._lock:
            if task_id in self._callbacks and callback in self._callbacks[task_id]:
                self._callbacks[task_id].remove(callback)

    def _notify_callbacks(self, task_id: str):
        """通知所有注册的回调"""
        if task_id in self._callbacks:
            task_data = self._tasks.get(task_id)
            for callback in self._callbacks[task_id]:
                try:
                    callback(task_data)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

    async def run_pipeline(
        self,
        task_id: str,
        steps: List[str],
        db_update_callback: Callable,
        code_generation_overrides: Optional[Dict[str, Any]] = None,
        project_charter: Optional[Dict[str, Any]] = None,
    ):
        """
        运行流水线任务

        Args:
            task_id: 任务ID
            steps: 要执行的步骤列表
            db_update_callback: 更新数据库的回调函数
        """
        task = self.get_task(task_id)
        if not task:
            return

        project_name = task["project_name"]
        project_id = task["project_id"]
        budget_run_id = f"api:{task_id}"
        llm_budget.reset_run(budget_run_id)
        effective_code_cfg = code_generation_overrides
        if effective_code_cfg is None:
            effective_code_cfg = task.get("code_generation_overrides") or {}
        effective_charter = project_charter
        if effective_charter is None:
            effective_charter = task.get("project_charter") or {}

        self.update_task(task_id, status="running", progress=0)
        self.add_log(task_id, "INFO", f"开始执行流水线: {project_name}")

        # 若调用方没传步骤，使用统一默认步骤
        steps = PipelineOrchestrator.resolve_steps(steps)

        # 任务前预检（仅在包含 LLM 步骤时执行）
        if PipelineOrchestrator.needs_llm_preflight(steps):
            if any(step in {"plan", "html"} for step in steps):
                if not self._run_api_preflight(task_id):
                    self.update_task(task_id, status="error", message="API 连通性预检失败")
                    db_update_callback(project_id, {"status": "error", "current_step": None})
                    return

            if "code" in steps:
                provider_override = str((effective_code_cfg or {}).get("llm_provider_override", "") or "").strip()
                model_override = str((effective_code_cfg or {}).get("llm_model_override", "") or "").strip()
                if not self._run_api_preflight(task_id, provider_override, model_override):
                    self.update_task(task_id, status="error", message="代码步骤 API 连通性预检失败")
                    db_update_callback(project_id, {"status": "error", "current_step": None})
                    return

        step_config = PipelineOrchestrator.build_step_config(steps)

        total_weight = sum(step_config[s]["weight"] for s in steps if s in step_config)
        current_progress = 0

        try:
            for step in steps:
                if step not in step_config:
                    continue
                current_task = self.get_task(task_id) or {}
                if current_task.get("cancel_requested"):
                    raise Exception("任务已取消")
                if step in SPEC_APPROVAL_REQUIRED_STEPS and not self._ensure_spec_review_approved(project_name, task_id, step):
                    raise Exception("规格未确认，已阻断后续实现阶段。请先确认规格后重试。")
                if step == "freeze" and not self._ensure_authorization_grade(project_name, task_id, step):
                    raise Exception("授权级材料门禁未通过，已阻断冻结步骤。")

                step_info = step_config[step]
                self.update_task(task_id, current_step=step_info["name"])
                self.add_log(task_id, "INFO", f"开始: {step_info['name']}")

                # 在线程池中执行同步任务（使用更安全的方式）
                try:
                    loop = asyncio.get_running_loop()
                    success = await loop.run_in_executor(
                        self._executor,
                        self._execute_step_with_budget,
                        step,
                        project_name,
                        task_id,
                        effective_code_cfg,
                        effective_charter,
                    )
                except RuntimeError as e:
                    # 事件循环已关闭，直接同步执行
                    logger.warning(f"事件循环异常，同步执行: {e}")
                    success = self._execute_step_with_budget(
                        step,
                        project_name,
                        task_id,
                        effective_code_cfg,
                        effective_charter,
                    )

                if success:
                    current_progress += int(step_info["weight"] / total_weight * 100)
                    self.update_task(task_id, progress=min(current_progress, 100))
                    self.add_log(task_id, "SUCCESS", f"完成: {step_info['name']}")

                    # 更新文件状态
                    try:
                        db_update_callback(project_id, {
                            "progress": current_progress,
                            "status": "running",
                            "current_step": step_info["name"]
                        })
                    except Exception as db_err:
                        logger.warning(f"更新数据库失败: {db_err}")
                else:
                    self.add_log(task_id, "ERROR", f"失败: {step_info['name']}")
                    raise Exception(f"{step_info['name']}执行失败")

            # 完成
            self.update_task(task_id, status="completed", progress=100, current_step=None)
            self.add_log(task_id, "SUCCESS", "流水线执行完成!")
            budget_state = llm_budget.get_state(budget_run_id)
            self.add_log(
                task_id,
                "INFO",
                f"LLM 预算统计: calls={budget_state.get('total_calls', 0)}, failures={budget_state.get('total_failures', 0)}",
                console_only=True,
            )
            try:
                db_update_callback(project_id, {"progress": 100, "status": "completed", "current_step": None})
            except Exception as db_err:
                logger.warning(f"更新数据库失败: {db_err}")

        except Exception as e:
            is_cancelled = "任务已取消" in str(e)
            if is_cancelled:
                self.update_task(task_id, status="error", message="任务已取消", current_step=None)
                self.add_log(task_id, "WARNING", "流水线已取消（当前步骤完成后停止）")
                db_update_callback(project_id, {"status": "idle", "current_step": None})
            else:
                self.update_task(task_id, status="error", message=str(e))
                self.add_log(task_id, "ERROR", f"流水线执行失败: {e}")
                budget_state = llm_budget.get_state(budget_run_id)
                self.add_log(
                    task_id,
                    "INFO",
                    f"LLM 预算统计: calls={budget_state.get('total_calls', 0)}, failures={budget_state.get('total_failures', 0)}",
                    console_only=True,
                )
                db_update_callback(project_id, {"status": "error", "current_step": None})

    def _execute_step_with_budget(
        self,
        step: str,
        project_name: str,
        task_id: str,
        code_generation_overrides: Optional[Dict[str, Any]] = None,
        project_charter: Optional[Dict[str, Any]] = None,
    ) -> bool:
        run_id = f"api:{task_id}"
        with llm_budget.run_scope(run_id):
            with llm_budget.stage_scope(step):
                return self._execute_step(
                    step,
                    project_name,
                    task_id,
                    code_generation_overrides,
                    project_charter,
                )

    def _execute_step(
        self,
        step: str,
        project_name: str,
        task_id: str,
        code_generation_overrides: Optional[Dict[str, Any]] = None,
        project_charter: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """执行单个步骤 (同步)"""
        try:
            if step == "plan":
                return self._run_plan(
                    project_name,
                    task_id,
                    code_generation_overrides,
                    project_charter,
                )
            elif step == "spec":
                return self._run_spec(project_name, task_id, project_charter)
            elif step == "html":
                return self._run_html(project_name, task_id)
            elif step == "screenshot":
                return self._run_screenshot(project_name, task_id)
            elif step == "code":
                return self._run_code(project_name, task_id, code_generation_overrides)
            elif step == "verify":
                return self._run_verify(project_name, task_id)
            elif step == "document":
                return self._run_document(project_name, task_id)
            elif step == "pdf":
                return self._run_pdf(project_name, task_id)
            elif step == "freeze":
                return self._run_freeze(project_name, task_id)
            return False
        except Exception as e:
            self.add_log(task_id, "ERROR", f"步骤执行异常: {e}")
            return False

    def _ensure_spec_review_approved(self, project_name: str, task_id: str, step: str) -> bool:
        """实现阶段必须使用已确认规格。"""
        project_dir = OUTPUT_DIR / project_name
        spec_path = project_dir / "project_executable_spec.json"
        status = get_spec_review_status(project_dir, spec_path)
        if status.get("approved"):
            return True

        review_status = str(status.get("review_status") or "pending")
        if review_status == "missing_spec":
            self.add_log(
                task_id,
                "ERROR",
                f"缺少可执行规格，无法进入{STEP_NAMES.get(step, step)}。请先执行 plan/spec 并确认规格。",
            )
            return False

        if self._auto_approve_spec_if_enabled(project_name, task_id, stage=step):
            return True

        digest = str(status.get("spec_digest") or "")[:12] or "-"
        self.add_log(
            task_id,
            "ERROR",
            f"规格未确认（status={review_status}, digest={digest}），已阻断{STEP_NAMES.get(step, step)}。请先确认规格后重试。",
        )
        return False

    def _ensure_authorization_grade(
        self,
        project_name: str,
        task_id: str,
        step: str,
        block_threshold: int = 75,
        max_fix_rounds: int = 2,
    ) -> bool:
        """
        最终授权级材料门禁：
        在提交敏感步骤前执行硬门禁 + 自动修复闭环。
        """
        project_dir = OUTPUT_DIR / project_name
        html_dir = BASE_DIR / "temp_build" / project_name / "html"
        passed, report_path, report = run_submission_risk_precheck(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            block_threshold=block_threshold,
            enable_auto_fix=True,
            max_fix_rounds=max_fix_rounds,
        )

        auto_fix = report.get("auto_fix") or {}
        fixed_actions: List[str] = []
        for round_item in auto_fix.get("rounds") or []:
            for action in round_item.get("action_results") or []:
                if action.get("ok") and action.get("action"):
                    fixed_actions.append(str(action.get("action")))
        fixed_actions = sorted(set(fixed_actions))

        if fixed_actions:
            self.add_log(task_id, "INFO", f"门禁自动修复动作: {', '.join(fixed_actions)}")

        if not passed:
            issues = report.get("blocking_issues") or []
            self.add_log(
                task_id,
                "ERROR",
                f"授权门禁未通过，已阻断{STEP_NAMES.get(step, step)}。"
                f"剩余阻断项: {'；'.join(issues[:5]) if issues else '未知'}",
            )
            self.add_log(task_id, "INFO", f"门禁报告: {report_path}")
            return False

        self.add_log(task_id, "SUCCESS", f"授权门禁通过: {report_path}")
        return True

    def _apply_semantic_gate(self, project_name: str, task_id: str, project_dir: Path) -> Dict[str, Any]:
        """执行同质化语义闸门，必要时自动重写规格。"""
        try:
            report = apply_semantic_homogeneity_gate(
                project_name=project_name,
                project_dir=project_dir,
                output_root=OUTPUT_DIR,
                threshold=0.82,
                auto_rewrite=True,
            )
            top_similarity = float(report.get("top_similarity") or 0.0)
            rewritten = bool(report.get("rewritten"))
            self.add_log(
                task_id,
                "INFO",
                f"同质化检测完成: top_similarity={top_similarity:.3f}"
                + ("，已自动重写规格语义" if rewritten else ""),
            )
            return report
        except Exception as e:
            self.add_log(task_id, "WARNING", f"同质化检测执行失败，已跳过: {e}")
            return {}

    def _run_plan(
        self,
        project_name: str,
        task_id: str,
        code_generation_overrides: Optional[Dict[str, Any]] = None,
        project_charter: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """运行项目规划"""
        from modules import generate_project_plan
        from modules.project_planner import ProjectPlanner

        project_dir = OUTPUT_DIR / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        raw_charter = project_charter or load_project_charter(project_dir) or {}
        charter = normalize_project_charter(raw_charter, project_name=project_name)
        charter_errors = validate_project_charter(charter)
        if charter_errors:
            if not raw_charter:
                template = default_project_charter_template(project_name)
                save_project_charter(project_dir, template)
            self.add_log(
                task_id,
                "ERROR",
                "项目章程不完整，已阻断规划阶段。请补全："
                + "；".join(charter_errors)
                + f"（参考文件: {project_dir / 'project_charter.json'}）",
            )
            return False
        save_project_charter(project_dir, charter)
        self.add_log(task_id, "INFO", "项目章程校验通过")

        self.add_log(task_id, "INFO", "调用 AI 生成项目规划...")
        plan = generate_project_plan(
            project_name,
            code_generation_overrides=code_generation_overrides or {},
            project_charter=charter,
        )

        # 保存到项目专属目录
        json_path = project_dir / "project_plan.json"

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        self.add_log(task_id, "INFO", f"项目规划已保存: {json_path}")
        if plan.get("executable_spec"):
            spec_path = save_executable_spec(project_dir, plan["executable_spec"])
            self.add_log(task_id, "INFO", f"可执行规格已保存: {spec_path}")
            self._apply_semantic_gate(project_name, task_id, project_dir)
            try:
                with open(spec_path, "r", encoding="utf-8") as sf:
                    final_spec = json.load(sf)
                plan["executable_spec"] = final_spec
                with open(json_path, "w", encoding="utf-8") as pf:
                    json.dump(plan, pf, ensure_ascii=False, indent=2)
            except Exception:
                final_spec = plan["executable_spec"]
            review_artifacts = save_spec_review_artifacts(project_dir, project_name, final_spec)
            if review_artifacts.get("ok"):
                self.add_log(task_id, "INFO", f"规格评审清单已生成: {review_artifacts.get('guide_path')}")
                self._auto_approve_spec_if_enabled(project_name, task_id, stage="plan")

        # 生成软著填写辅助文档 (txt)
        try:
            txt_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="guide_txt")
            planner = ProjectPlanner()
            planner._save_copyright_helper_txt(plan, txt_path)
            self.add_log(task_id, "INFO", f"软著填写手册已生成: {txt_path}")
        except Exception as e:
            self.add_log(task_id, "WARNING", f"软著填写手册生成失败: {e}")

        return True

    def _run_html(self, project_name: str, task_id: str) -> bool:
        """生成 HTML 页面"""
        from modules import generate_html_pages

        json_path = OUTPUT_DIR / project_name / "project_plan.json"
        if not json_path.exists():
            self.add_log(task_id, "ERROR", f"project_plan.json 不存在: {json_path}")
            return False

        self.add_log(task_id, "INFO", "生成 HTML 页面...")
        html_dir = generate_html_pages(json_path)
        self.add_log(task_id, "INFO", f"HTML 已生成: {html_dir}")
        return True

    def _run_spec(self, project_name: str, task_id: str, project_charter: Optional[Dict[str, Any]] = None) -> bool:
        """生成可执行规格（Spec-first）。"""
        project_dir = OUTPUT_DIR / project_name
        plan_path = project_dir / "project_plan.json"
        if not plan_path.exists():
            self.add_log(task_id, "ERROR", f"project_plan.json 不存在: {plan_path}")
            return False

        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)

        raw_charter = project_charter or load_project_charter(project_dir) or plan.get("project_charter") or {}
        charter = normalize_project_charter(raw_charter, project_name=project_name)
        charter_errors = validate_project_charter(charter)
        if charter_errors:
            self.add_log(
                task_id,
                "ERROR",
                "项目章程校验失败，无法生成规格：" + "；".join(charter_errors),
            )
            return False
        save_project_charter(project_dir, charter)

        spec = build_executable_spec(plan, charter)
        spec_errors = validate_executable_spec(spec)
        if spec_errors:
            self.add_log(task_id, "ERROR", "可执行规格校验失败：" + "；".join(spec_errors))
            return False
        spec_path = save_executable_spec(project_dir, spec)
        self.add_log(task_id, "INFO", f"可执行规格已生成: {spec_path}")
        self._apply_semantic_gate(project_name, task_id, project_dir)
        try:
            with open(spec_path, "r", encoding="utf-8") as sf:
                final_spec = json.load(sf)
        except Exception:
            final_spec = spec
        review_artifacts = save_spec_review_artifacts(project_dir, project_name, final_spec)
        if review_artifacts.get("ok"):
            self.add_log(task_id, "INFO", f"规格评审清单已生成: {review_artifacts.get('guide_path')}")
            self._auto_approve_spec_if_enabled(project_name, task_id, stage="spec")
        return True

    def _run_screenshot(self, project_name: str, task_id: str) -> bool:
        """截图"""
        from modules import capture_screenshots_sync

        html_dir = BASE_DIR / "temp_build" / project_name / "html"
        if not html_dir.exists():
            self.add_log(task_id, "ERROR", f"HTML 目录不存在: {html_dir}")
            return False

        screenshot_dir = OUTPUT_DIR / project_name / "screenshots"
        contract_path = OUTPUT_DIR / project_name / "screenshot_contract.json"
        self.add_log(task_id, "INFO", "开始截图...")
        capture_screenshots_sync(html_dir, screenshot_dir, contract_path=contract_path)
        self.add_log(task_id, "INFO", f"截图已保存: {screenshot_dir}")
        return True

    def _run_code(
        self,
        project_name: str,
        task_id: str,
        code_generation_overrides: Optional[Dict[str, Any]] = None
    ) -> bool:
        """生成代码"""
        from modules.code_generator import generate_code_from_plan

        json_path = OUTPUT_DIR / project_name / "project_plan.json"
        if not json_path.exists():
            self.add_log(task_id, "ERROR", f"project_plan.json 不存在: {json_path}")
            return False
        spec_path = OUTPUT_DIR / project_name / "project_executable_spec.json"
        if not spec_path.exists():
            self.add_log(task_id, "WARNING", "未找到可执行规格，自动补建...")
            if not self._run_spec(project_name, task_id):
                return False
        if not self._ensure_spec_review_approved(project_name, task_id, "code"):
            return False

        # 在 code 步骤前统一注入 code_generation_overrides 与 executable_spec
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
            merged_cfg = dict(plan_data.get("code_generation_config", {}) or {})
            if code_generation_overrides:
                merged_cfg.update(code_generation_overrides)
            plan_data["code_generation_config"] = merged_cfg
            if spec_path.exists():
                with open(spec_path, "r", encoding="utf-8") as sf:
                    plan_data["executable_spec"] = json.load(sf)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(plan_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.add_log(task_id, "WARNING", f"写入 code/spec 配置失败，继续使用原配置: {e}")

        code_dir = OUTPUT_DIR / project_name / "aligned_code"
        self.add_log(task_id, "INFO", "生成业务代码...")
        files = generate_code_from_plan(str(json_path), str(code_dir))
        if not files:
            self.add_log(task_id, "ERROR", "代码生成未产出文件，判定为失败")
            return False
        self.add_log(task_id, "INFO", f"代码生成完成，共 {len(files)} 个文件")
        return True

    def _run_document(self, project_name: str, task_id: str) -> bool:
        """生成说明书（Word + PDF）"""
        from modules.document_generator import generate_document
        from modules.word_to_pdf import convert_word_to_pdf

        json_path = OUTPUT_DIR / project_name / "project_plan.json"
        if not json_path.exists():
            self.add_log(task_id, "ERROR", f"project_plan.json 不存在: {json_path}")
            return False

        screenshot_dir = OUTPUT_DIR / project_name / "screenshots"
        template_path = BASE_DIR / "templates" / "manual_template.docx"
        project_dir = OUTPUT_DIR / project_name
        output_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="manual_docx")
        pdf_output_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="manual_pdf")

        if not template_path.exists():
            self.add_log(task_id, "WARNING", f"模板不存在: {template_path}")
            return False

        verify_report_path = OUTPUT_DIR / project_name / "runtime_verification_report.json"
        verify_passed = False
        if verify_report_path.exists():
            try:
                with open(verify_report_path, "r", encoding="utf-8") as f:
                    verify_report = json.load(f)
                verify_passed = bool(verify_report.get("overall_passed"))
            except Exception:
                verify_passed = False
        if not verify_passed:
            self.add_log(task_id, "INFO", "说明书前置检查：执行运行验证...")
            if not self._run_verify(project_name, task_id):
                self.add_log(task_id, "ERROR", "运行验证未通过，说明书阶段中止")
                return False

        # 1. 生成Word说明书
        self.add_log(task_id, "INFO", "生成 Word 说明书...")
        success = generate_document(
            str(json_path), str(screenshot_dir), str(template_path), str(output_path)
        )
        if not success:
            self.add_log(task_id, "WARNING", "Word 说明书生成失败，触发授权门禁自动修复并重试...")
            html_dir = BASE_DIR / "temp_build" / project_name / "html"
            passed, report_path, report = run_submission_risk_precheck(
                project_name=project_name,
                project_dir=project_dir,
                html_dir=html_dir,
                block_threshold=75,
                enable_auto_fix=True,
                max_fix_rounds=2,
                gate_profile="document_preflight",
            )
            auto_fix = report.get("auto_fix") or {}
            fixed_actions: List[str] = []
            for round_item in auto_fix.get("rounds") or []:
                for action in round_item.get("action_results") or []:
                    if action.get("ok") and action.get("action"):
                        fixed_actions.append(str(action.get("action")))
            fixed_actions = sorted(set(fixed_actions))
            if fixed_actions:
                self.add_log(task_id, "INFO", f"自动修复动作: {', '.join(fixed_actions)}")

            if not passed:
                issues = report.get("blocking_issues") or []
                self.add_log(
                    task_id,
                    "ERROR",
                    f"Word 说明书生成失败且自动修复未收敛: {'；'.join(issues[:5]) if issues else '未知阻断项'}",
                )
                self.add_log(task_id, "INFO", f"门禁报告: {report_path}")
                return False

            if not output_path.exists():
                success = generate_document(
                    str(json_path), str(screenshot_dir), str(template_path), str(output_path)
                )
                if not success:
                    self.add_log(task_id, "ERROR", "Word 说明书重试生成失败")
                    return False

        self.add_log(task_id, "INFO", f"Word 说明书已生成: {output_path}")

        # 2. 转换为PDF（自动更新目录）
        self.add_log(task_id, "INFO", "转换为 PDF（更新目录）...")
        if pdf_output_path.exists():
            self.add_log(task_id, "SUCCESS", f"PDF 说明书已存在: {pdf_output_path}")
            return True
        try:
            pdf_success = convert_word_to_pdf(output_path, pdf_output_path)
            if pdf_success:
                self.add_log(task_id, "SUCCESS", f"PDF 说明书已生成: {pdf_output_path}")
            else:
                self.add_log(task_id, "ERROR", "PDF 转换失败，说明书步骤未通过")
                return False
        except Exception as e:
            self.add_log(task_id, "ERROR", f"PDF 转换出错: {e}")
            return False

        return True

    def _run_pdf(self, project_name: str, task_id: str) -> bool:
        """生成源码 PDF"""
        from modules.code_pdf_generator import generate_code_pdf

        code_dir = OUTPUT_DIR / project_name / "aligned_code"
        project_dir = OUTPUT_DIR / project_name
        output_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="code_pdf")
        html_dir = BASE_DIR / "temp_build" / project_name / "html"

        if not code_dir.exists():
            self.add_log(task_id, "ERROR", f"代码目录不存在: {code_dir}")
            return False

        self.add_log(task_id, "INFO", "生成源代码 PDF...")
        success = generate_code_pdf(
            project_name=project_name,
            code_dir=str(code_dir),
            output_path=str(output_path),
            version="V1.0.0",
            html_dir=str(html_dir) if html_dir.exists() else None,
            include_html=False
        )
        if success:
            self.add_log(task_id, "INFO", f"源码 PDF 已生成: {output_path}")
        return success

    def _run_verify(self, project_name: str, task_id: str) -> bool:
        """运行验证：先证明可运行，再进入文档阶段。"""
        project_dir = OUTPUT_DIR / project_name
        html_dir = BASE_DIR / "temp_build" / project_name / "html"
        self.add_log(task_id, "INFO", "执行运行验证（smoke + 业务路径回放）...")
        passed, report_path, report = run_runtime_verification(project_name, project_dir, html_dir)
        self.add_log(task_id, "INFO", f"运行验证报告已生成: {report_path}")
        if not passed:
            self.add_log(task_id, "ERROR", f"运行验证失败: {report.get('summary', {})}")
            return False
        self.add_log(task_id, "SUCCESS", "运行验证通过")
        return True

    def _run_freeze(self, project_name: str, task_id: str) -> bool:
        """构建冻结提交包（开发事实链）。"""
        project_dir = OUTPUT_DIR / project_name
        html_dir = BASE_DIR / "temp_build" / project_name / "html"
        self.add_log(task_id, "INFO", "构建冻结提交包...")
        result = build_freeze_package(project_name, project_dir, html_dir)
        self.add_log(task_id, "SUCCESS", f"冻结包已生成: {result.get('zip_path')}")
        return True

    async def run_single_step(self, task_id: str, step: str, db_update_callback: Callable):
        """
        运行单个步骤测试

        Args:
            task_id: 任务ID
            step: 步骤名称 (plan, spec, html, screenshot, code, verify, document, pdf, freeze)
            db_update_callback: 更新数据库的回调函数
        """
        task = self.get_task(task_id)
        if not task:
            return

        project_name = task["project_name"]
        project_id = task["project_id"]
        budget_run_id = f"api:{task_id}"
        llm_budget.reset_run(budget_run_id)
        code_generation_overrides = task.get("code_generation_overrides") or {}

        step_name = STEP_NAMES.get(step, step)

        self.update_task(task_id, status="running", progress=0, current_step=step_name)
        self.add_log(task_id, "INFO", f"开始单步测试: {step_name}")
        if step in SPEC_APPROVAL_REQUIRED_STEPS and not self._ensure_spec_review_approved(project_name, task_id, step):
            self.update_task(task_id, status="error", message="规格未确认，已阻断当前步骤", current_step=None)
            db_update_callback(project_id, {"status": "error", "current_step": None})
            return
        if step == "freeze" and not self._ensure_authorization_grade(project_name, task_id, step):
            self.update_task(task_id, status="error", message="授权级材料门禁未通过，已阻断当前步骤", current_step=None)
            db_update_callback(project_id, {"status": "error", "current_step": None})
            return

        if PipelineOrchestrator.needs_llm_preflight([step]):
            if step in {"plan", "html"}:
                if not self._run_api_preflight(task_id):
                    self.update_task(task_id, status="error", message="API 连通性预检失败")
                    db_update_callback(project_id, {"status": "error", "current_step": None})
                    return
            elif step == "code":
                provider_override = str(code_generation_overrides.get("llm_provider_override", "") or "").strip()
                model_override = str(code_generation_overrides.get("llm_model_override", "") or "").strip()
                if not self._run_api_preflight(task_id, provider_override, model_override):
                    self.update_task(task_id, status="error", message="代码步骤 API 连通性预检失败")
                    db_update_callback(project_id, {"status": "error", "current_step": None})
                    return

        try:
            # 在线程池中执行同步任务
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                self._executor,
                self._execute_step_with_budget,
                step,
                project_name,
                task_id,
                code_generation_overrides,
                task.get("project_charter") or {},
            )

            if success:
                self.update_task(task_id, status="completed", progress=100, current_step=None)
                self.add_log(task_id, "SUCCESS", f"单步测试完成: {step_name}")
                budget_state = llm_budget.get_state(budget_run_id)
                self.add_log(
                    task_id,
                    "INFO",
                    f"LLM 预算统计: calls={budget_state.get('total_calls', 0)}, failures={budget_state.get('total_failures', 0)}",
                    console_only=True,
                )
                db_update_callback(project_id, {"status": "completed", "current_step": None})
            else:
                self.update_task(task_id, status="error", message=f"{step_name}执行失败")
                self.add_log(task_id, "ERROR", f"单步测试失败: {step_name}")
                db_update_callback(project_id, {"status": "error", "current_step": None})

        except Exception as e:
            self.update_task(task_id, status="error", message=str(e))
            self.add_log(task_id, "ERROR", f"单步测试异常: {e}")
            budget_state = llm_budget.get_state(budget_run_id)
            self.add_log(
                task_id,
                "INFO",
                f"LLM 预算统计: calls={budget_state.get('total_calls', 0)}, failures={budget_state.get('total_failures', 0)}",
                console_only=True,
            )
            db_update_callback(project_id, {"status": "error", "current_step": None})


# 全局单例
task_manager = TaskManager()
