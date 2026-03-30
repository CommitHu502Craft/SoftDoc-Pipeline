"""
异步任务执行器
在后台线程中执行耗时任务，避免阻塞UI
支持任务取消功能
"""
try:
    from PyQt6.QtCore import QThread, pyqtSignal
except Exception:
    class _DummySignal:
        def emit(self, *args, **kwargs):
            return None

    def pyqtSignal(*args, **kwargs):  # type: ignore
        return _DummySignal()

    class QThread:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            self.run()

        def run(self):
            return None
from pathlib import Path
import sys
import logging
import json

# 添加项目根目录到 sys.path
BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from modules import generate_project_plan, generate_html_pages, capture_screenshots_sync
from modules.document_generator import generate_document
from modules.code_pdf_generator import generate_code_pdf
# from modules.code_generator import generate_code_from_plan # Deprecated
from modules.code_transformer import CodeTransformer
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
from modules.pre_submission_risk import run_submission_risk_precheck
from modules.artifact_naming import (
    first_existing_artifact_path,
    preferred_artifact_path,
)
from modules.spec_review import (
    approve_spec_review,
    get_spec_review_status,
    save_spec_review_artifacts,
)
from core.llm_budget import llm_budget
from core.pipeline_config import DEFAULT_PIPELINE_STEPS
from core.pipeline_orchestrator import PipelineOrchestrator
from ..common.config_manager import config_manager

logger = logging.getLogger(__name__)


class TaskCancelledException(Exception):
    """任务取消异常"""
    pass


class TaskBlockedException(Exception):
    """任务被业务门禁阻断（例如章程不完整）"""
    pass


class TaskWorker(QThread):
    """通用任务执行器"""

    # 信号
    progress = pyqtSignal(int)  # 进度百分比
    log = pyqtSignal(str)  # 日志消息
    finished = pyqtSignal(bool, str)  # (是否成功, 消息)
    cancelled = pyqtSignal()  # 任务取消信号

    def __init__(self, task_type: str, project_name: str, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.project_name = project_name
        self.kwargs = kwargs
        self.success = False
        self.message = ""
        self._is_cancelled = False  # 取消标志
        self._llm_run_id = f"qt:{self.project_name}:{self.task_type}:{id(self)}"

    def cancel(self):
        """取消任务"""
        self._is_cancelled = True
        self.log.emit("正在取消任务...")

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._is_cancelled

    def check_cancelled(self) -> bool:
        """
        检查取消状态，如果已取消则抛出异常
        在长时间操作的检查点调用此方法
        """
        if self._is_cancelled:
            raise TaskCancelledException("任务已被用户取消")
        return False

    def _auto_approve_spec_if_enabled(self, stage: str = "") -> bool:
        """
        自动确认规格（当开启 auto_approve_spec 时）。
        返回值表示当前规格是否已确认。
        """
        project_dir = BASE_DIR / "output" / self.project_name
        spec_path = project_dir / "project_executable_spec.json"
        status = get_spec_review_status(project_dir, spec_path)
        if status.get("approved"):
            return True

        if not self.kwargs.get("auto_approve_spec"):
            return False

        result = approve_spec_review(project_dir, reviewer="qt-auto")
        if result.get("ok"):
            self.log.emit(f"Auto-approved spec{f' at {stage}' if stage else ''}.")
            return True

        self.log.emit(
            "Auto spec approval failed: "
            + str(result.get("message") or "unknown error")
        )
        return False

    def _run_api_preflight(self, provider_override: str = "", model_override: str = ""):
        """任务启动前预检 API 连通性，尽早暴露配置/鉴权/网络问题"""
        from core.deepseek_client import DeepSeekClient
        provider = str(provider_override or "").strip()
        model = str(model_override or "").strip()
        if provider or model:
            self.log.emit(
                f"Preflight: checking API connectivity (code override provider={provider or '(follow-global)'}, model={model or '(provider-default)'})..."
            )
        else:
            self.log.emit("Preflight: checking API connectivity...")
        client = DeepSeekClient(
            provider_name=provider or None,
            model=model or None,
        )
        if not client.test_connection():
            raise RuntimeError("API 连通性预检失败，请检查 API Key/端点/模型/网络")
        self.log.emit("Preflight: API connectivity OK")

    @staticmethod
    def _collect_code_generation_overrides() -> dict:
        """收集代码阶段运行参数（用于 plan 持久化与 code 运行时覆盖）"""
        profile = str(config_manager.get("code_quality_profile", "economy") or "economy").strip().lower()
        if profile == "high_constraint":
            max_total_calls_default = 32
            max_total_failures_default = 10
        else:
            max_total_calls_default = 12
            max_total_failures_default = 4
        return {
            "quality_profile": profile,
            "novelty_threshold": config_manager.get("code_novelty_threshold", 0.35),
            "file_novelty_budget": config_manager.get("code_file_novelty_budget", 0.35),
            "project_novelty_threshold": config_manager.get("code_project_novelty_threshold", 0.32),
            "rewrite_candidates": config_manager.get("code_rewrite_candidates", 1),
            "max_rewrite_rounds": config_manager.get("code_max_rewrite_rounds", 1),
            "heavy_search_ratio": config_manager.get("code_heavy_search_ratio", 0.20),
            "enable_project_novelty_gate": config_manager.get("code_enable_project_novelty_gate", False),
            "enforce_file_gate": config_manager.get("code_enforce_file_gate", False),
            "enforce_file_gate_on_obfuscation": config_manager.get("code_enforce_file_gate_on_obfuscation", False),
            "max_risky_files": config_manager.get("code_max_risky_files", 8),
            "max_syntax_fail_files": config_manager.get("code_max_syntax_fail_files", 4),
            "min_ai_line_ratio": config_manager.get("code_min_ai_line_ratio", 0.10),
            "max_failed_files": config_manager.get("code_max_failed_files", 8),
            "max_llm_attempts_per_file": config_manager.get("code_max_llm_attempts_per_file", 2),
            "llm_text_retries": config_manager.get("code_llm_text_retries", 1),
            "max_total_llm_calls": config_manager.get("code_max_total_llm_calls", max_total_calls_default),
            "max_total_llm_failures": config_manager.get("code_max_total_llm_failures", max_total_failures_default),
            "disable_llm_on_budget_exhausted": config_manager.get("code_disable_llm_on_budget_exhausted", True),
            "disable_llm_on_failures": config_manager.get("code_disable_llm_on_failures", True),
            "enable_embedding_similarity": config_manager.get("code_enable_embedding_similarity", False),
            "embedding_similarity_weight": config_manager.get("code_embedding_similarity_weight", 0.15),
            "embedding_max_chars": config_manager.get("code_embedding_max_chars", 2400),
            "llm_provider_override": config_manager.get("code_llm_provider_override", ""),
            "llm_model_override": config_manager.get("code_llm_model_override", ""),
        }

    def _resolve_project_charter(self) -> dict:
        """解析并校验项目章程，不通过则阻断计划阶段。"""
        project_dir = BASE_DIR / "output" / self.project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        raw_charter = self.kwargs.get("project_charter")
        if not isinstance(raw_charter, dict) or not raw_charter:
            raw_charter = load_project_charter(project_dir) or {}
        if not raw_charter:
            # 生成模板，便于用户补全
            template = default_project_charter_template(self.project_name)
            save_project_charter(project_dir, template)
            raise TaskBlockedException(
                "项目章程缺失。已生成模板: "
                f"{project_dir / 'project_charter.json'}，请补全后重试。"
            )

        charter = normalize_project_charter(raw_charter, project_name=self.project_name)
        errors = validate_project_charter(charter)
        if errors:
            save_project_charter(project_dir, charter)
            raise TaskBlockedException(
                "项目章程不完整，已阻断生成。请补全: " + "；".join(errors)
            )
        save_project_charter(project_dir, charter)
        return charter

    def _apply_semantic_gate(self, project_dir: Path):
        """执行同质化语义闸门，必要时自动重写规格。"""
        try:
            report = apply_semantic_homogeneity_gate(
                project_name=self.project_name,
                project_dir=project_dir,
                output_root=BASE_DIR / "output",
                threshold=0.82,
                auto_rewrite=True,
            )
            top_similarity = float(report.get("top_similarity") or 0.0)
            if report.get("rewritten"):
                self.log.emit(f"Semantic homogeneity gate: top_similarity={top_similarity:.3f}, spec rewritten.")
            else:
                self.log.emit(f"Semantic homogeneity gate: top_similarity={top_similarity:.3f}, no rewrite.")
        except Exception as e:
            self.log.emit(f"Semantic homogeneity gate skipped: {e}")

    def _run_with_budget_stage(self, stage: str, fn, *args, **kwargs):
        with llm_budget.run_scope(self._llm_run_id):
            with llm_budget.stage_scope(stage):
                return fn(*args, **kwargs)
    
    def run(self):
        """执行任务"""
        try:
            self.log.emit(f"Starting {self.task_type} for {self.project_name}...")
            llm_budget.reset_run(self._llm_run_id)
            if self.task_type in {"plan", "html"}:
                self._run_api_preflight()
            elif self.task_type == "code":
                code_cfg = self._collect_code_generation_overrides()
                self._run_api_preflight(
                    code_cfg.get("llm_provider_override", ""),
                    code_cfg.get("llm_model_override", ""),
                )

            if self.task_type == "plan":
                self._run_with_budget_stage("plan", self._generate_plan)
            elif self.task_type == "spec":
                self._run_with_budget_stage("spec", self._generate_spec)
            elif self.task_type == "html":
                self._run_with_budget_stage("html", self._generate_html)
            elif self.task_type == "screenshot":
                self._run_with_budget_stage("screenshot", self._capture_screenshots)
            elif self.task_type == "code":
                self._run_with_budget_stage("code", self._generate_code)
            elif self.task_type == "verify":
                self._run_with_budget_stage("verify", self._verify_runtime)
            elif self.task_type == "document":
                self._run_with_budget_stage("document", self._generate_document)
            elif self.task_type == "pdf":
                self._run_with_budget_stage("pdf", self._generate_pdf)
            elif self.task_type == "freeze":
                self._run_with_budget_stage("freeze", self._freeze_package)
            elif self.task_type == "submit":
                self._submit()
            elif self.task_type == "submit_batch":
                self._submit_batch()
            elif self.task_type == "download_signatures":
                self._download_signatures()
            elif self.task_type == "auto_sign":
                self._auto_sign()
            elif self.task_type == "apply_scan_effect":
                self._apply_scan_effect()
            elif self.task_type == "sign_and_scan":
                self._sign_and_scan()
            elif self.task_type == "upload_signatures":
                self._upload_signatures()
            elif self.task_type == "full_pipeline":
                self._full_pipeline()
            elif self.task_type == "resume_pipeline":
                self._resume_pipeline()
            else:
                raise ValueError(f"Unknown task type: {self.task_type}")

            self.success = True
            self.message = f"{self.task_type.upper()} completed successfully"

        except TaskCancelledException:
            self.success = False
            self.message = "任务已取消"
            self.cancelled.emit()
            logger.info(f"Task {self.task_type} was cancelled")

        except TaskBlockedException as e:
            self.success = False
            self.message = str(e)
            self.log.emit(str(e))
            logger.warning(f"Task {self.task_type} blocked: {e}")

        except Exception as e:
            self.success = False
            self.message = f"Error: {str(e)}"
            logger.exception(f"Task {self.task_type} failed")

        finally:
            self.finished.emit(self.success, self.message)
    
    def _generate_plan(self):
        """生成项目规划"""
        self.log.emit("Generating project plan...")
        project_charter = self._resolve_project_charter()
        self.log.emit("Project charter validated")

        # 获取生成偏好
        genome_overrides = {}
        code_generation_overrides = {}
        target_lang = config_manager.get("target_language")
        ui_framework = config_manager.get("ui_framework")

        if target_lang and target_lang != "Random":
            genome_overrides["target_language"] = target_lang
            self.log.emit(f"Using preference: Language={target_lang}")

        if ui_framework and ui_framework != "Random":
            genome_overrides["ui_framework"] = ui_framework
            self.log.emit(f"Using preference: UI Framework={ui_framework}")

        # 读取代码质量闸门偏好（若未设置则使用 planner 默认值）
        code_generation_overrides = self._collect_code_generation_overrides()

        # 调用生成函数
        final_plan = generate_project_plan(
            project_name=self.project_name,
            genome_overrides=genome_overrides,
            code_generation_overrides=code_generation_overrides,
            project_charter=project_charter,
        )

        spec = final_plan.get("executable_spec") or build_executable_spec(final_plan, project_charter)
        spec_errors = validate_executable_spec(spec)
        if spec_errors:
            raise RuntimeError("Executable spec validation failed: " + "；".join(spec_errors))
        final_plan["executable_spec"] = spec

        # 手动保存到项目目录
        import json
        project_dir = BASE_DIR / "output" / self.project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        output_path = project_dir / "project_plan.json"

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(final_plan, f, indent=2, ensure_ascii=False)

        self.log.emit(f"Plan saved to {output_path}")
        spec_path = save_executable_spec(project_dir, spec)
        self.log.emit(f"Executable spec saved to {spec_path}")
        self._apply_semantic_gate(project_dir)
        try:
            with open(spec_path, "r", encoding="utf-8") as sf:
                final_spec = json.load(sf)
            final_plan["executable_spec"] = final_spec
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(final_plan, f, indent=2, ensure_ascii=False)
        except Exception:
            final_spec = spec
        review_artifacts = save_spec_review_artifacts(project_dir, self.project_name, final_spec)
        if review_artifacts.get("ok"):
            self.log.emit(f"Spec review guide generated: {review_artifacts.get('guide_path')}")
            self._auto_approve_spec_if_enabled(stage="plan")

        # 新增：保存软著填写辅助文档
        try:
            from modules.project_planner import ProjectPlanner
            planner = ProjectPlanner()
            helper_txt_path = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="guide_txt")
            planner._save_copyright_helper_txt(final_plan, helper_txt_path)
            self.log.emit(f"Helper document saved to {helper_txt_path}")
        except Exception as e:
            logger.warning(f"Failed to generate helper document: {e}")

        self.progress.emit(100)
    
    def _generate_html(self):
        """生成HTML"""
        self.log.emit("Generating HTML pages...")
        json_path = BASE_DIR / "output" / self.project_name / "project_plan.json"
        if not json_path.exists():
            raise FileNotFoundError(f"Plan file not found: {json_path}")
        
        # 指定输出到 temp_build 目录
        html_dir = generate_html_pages(json_path)
        self.log.emit(f"HTML generated at: {html_dir}")
        self.progress.emit(100)

    def _generate_spec(self):
        """生成可执行规格（Spec-first）"""
        self.log.emit("Generating executable spec...")
        project_dir = BASE_DIR / "output" / self.project_name
        plan_path = project_dir / "project_plan.json"
        if not plan_path.exists():
            raise FileNotFoundError(f"Plan file not found: {plan_path}")

        with open(plan_path, "r", encoding="utf-8") as f:
            plan_data = json.load(f)

        charter = self._resolve_project_charter()
        spec = build_executable_spec(plan_data, charter)
        spec_errors = validate_executable_spec(spec)
        if spec_errors:
            raise RuntimeError("Executable spec validation failed: " + "；".join(spec_errors))
        spec_path = save_executable_spec(project_dir, spec)
        self.log.emit(f"Executable spec generated: {spec_path}")
        self._apply_semantic_gate(project_dir)
        try:
            with open(spec_path, "r", encoding="utf-8") as sf:
                final_spec = json.load(sf)
        except Exception:
            final_spec = spec
        review_artifacts = save_spec_review_artifacts(project_dir, self.project_name, final_spec)
        if review_artifacts.get("ok"):
            self.log.emit(f"Spec review guide generated: {review_artifacts.get('guide_path')}")
            self._auto_approve_spec_if_enabled(stage="spec")
        self.progress.emit(100)
    
    def _capture_screenshots(self):
        """截图"""
        self.log.emit("Capturing screenshots...")
        html_dir = BASE_DIR / "temp_build" / self.project_name / "html"
        screenshot_dir = BASE_DIR / "output" / self.project_name / "screenshots"
        
        if not html_dir.exists():
            raise FileNotFoundError(f"HTML directory not found: {html_dir}")

        contract_path = BASE_DIR / "output" / self.project_name / "screenshot_contract.json"
        capture_screenshots_sync(html_dir, screenshot_dir, contract_path=contract_path)
        self.progress.emit(100)
    
    def _generate_document(self):
        """生成Word文档"""
        self.log.emit("Generating Word document...")
        project_dir = BASE_DIR / "output" / self.project_name
        plan_path = project_dir / "project_plan.json"
        screenshot_dir = project_dir / "screenshots"
        template_path = BASE_DIR / "templates" / "manual_template.docx"
        output_path = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_docx")

        if not plan_path.exists():
             raise FileNotFoundError(f"Plan file not found: {plan_path}")

        verify_report = project_dir / "runtime_verification_report.json"
        if not verify_report.exists():
            self.log.emit("Verification report missing, running verification...")
            self._verify_runtime()
        else:
            try:
                with open(verify_report, "r", encoding="utf-8") as f:
                    verify_data = json.load(f)
                if not verify_data.get("overall_passed"):
                    self.log.emit("Verification report indicates failure, rerunning...")
                    self._verify_runtime()
            except Exception:
                self._verify_runtime()

        success = generate_document(
            plan_path=str(plan_path),
            screenshot_dir=str(screenshot_dir),
            template_path=str(template_path),
            output_path=str(output_path)
        )

        if not success:
            self.log.emit("Document generation failed, triggering auto-fix gate and retry...")
            html_dir = BASE_DIR / "temp_build" / self.project_name / "html"
            passed, report_path, report = run_submission_risk_precheck(
                project_name=self.project_name,
                project_dir=project_dir,
                html_dir=html_dir,
                block_threshold=75,
                enable_auto_fix=True,
                max_fix_rounds=2,
                gate_profile="document_preflight",
            )
            fixed_actions = self._collect_auto_fixed_actions(report)
            if fixed_actions:
                self.log.emit(f"Auto-fixed actions: {', '.join(fixed_actions)}")
            if not passed:
                blockers = (report or {}).get("blocking_issues") or []
                blocker_text = "；".join([str(x) for x in blockers[:5]]) or "未知阻断项"
                raise RuntimeError(
                    f"Document generation failed and auto-fix did not converge: {blocker_text} (report={report_path})"
                )

            # 门禁修复通过后，强制重跑一次说明书生成，避免复用到失败前的旧结果。
            success = generate_document(
                plan_path=str(plan_path),
                screenshot_dir=str(screenshot_dir),
                template_path=str(template_path),
                output_path=str(output_path),
            )
            if not success:
                raise RuntimeError("Document generation failed after successful auto-fix")

        # 与 API/CLI 行为对齐：说明书步骤内自动导出 PDF
        from modules.word_to_pdf import convert_word_to_pdf
        doc_pdf_path = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_pdf")
        if doc_pdf_path.exists():
            self.log.emit(f"✓ Document PDF already exists: {doc_pdf_path.name}")
            self.progress.emit(100)
            return
        if convert_word_to_pdf(output_path, doc_pdf_path):
            self.log.emit(f"✓ Document PDF exported: {doc_pdf_path.name}")
        else:
            raise RuntimeError("Document PDF export failed")

        self.progress.emit(100)

    def _export_document_to_pdf(self):
        """将Word文档导出为PDF"""
        self.log.emit("Exporting Word document to PDF...")
        project_dir = BASE_DIR / "output" / self.project_name
        docx_path = (
            first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_docx")
            or preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_docx")
        )
        pdf_path = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_pdf")

        if not docx_path.exists():
            raise FileNotFoundError(f"Word document not found: {docx_path}")

        # 导入Word转PDF模块
        from modules.word_to_pdf import convert_word_to_pdf

        success = convert_word_to_pdf(docx_path, pdf_path)

        if not success:
            raise RuntimeError("Word to PDF conversion failed")

        self.log.emit(f"✓ PDF exported: {pdf_path.name}")
        self.progress.emit(100)
    
    def _generate_code(self):
        """生成业务代码"""
        self.log.emit("Generating business code...")
        project_dir = BASE_DIR / "output" / self.project_name
        plan_path = project_dir / "project_plan.json"
        spec_path = project_dir / "project_executable_spec.json"
        # 使用aligned_code目录，与main.py保持一致
        code_dir = project_dir / "aligned_code"

        if not plan_path.exists():
            raise FileNotFoundError(f"Plan file not found: {plan_path}")
        if not spec_path.exists():
            self.log.emit("Executable spec missing, generating...")
            self._generate_spec()
        if self.kwargs.get("require_spec_confirmation"):
            review_status = get_spec_review_status(project_dir, spec_path)
            if not review_status.get("approved"):
                if self._auto_approve_spec_if_enabled(stage="code"):
                    review_status = get_spec_review_status(project_dir, spec_path)
            if not review_status.get("approved"):
                raise TaskBlockedException(
                    "可执行规格待确认。请先确认规格后再执行代码阶段。"
                )

        self.log.emit("Calling code generator...")
        try:
            # 使用新的 CodeTransformer
            self.log.emit(f"Using CodeTransformer V2.0...")

            # 加载规划
            with open(plan_path, 'r', encoding='utf-8') as f:
                plan_data = json.load(f)
            if spec_path.exists():
                with open(spec_path, "r", encoding="utf-8") as sf:
                    plan_data["executable_spec"] = json.load(sf)

            runtime_cfg = self._collect_code_generation_overrides()
            merged_cfg = dict(plan_data.get("code_generation_config", {}) or {})
            merged_cfg.update(runtime_cfg)
            plan_data["code_generation_config"] = merged_cfg

            transformer = CodeTransformer(plan_data)

            generated_files = transformer.transform_seed_to_project(
                output_dir=code_dir
            )
            if not generated_files:
                raise RuntimeError("代码生成未产出文件，请检查日志与质量闸门结果")

            self.log.emit(f"Code generation completed: {len(generated_files)} files")
        except KeyError as e:
            if str(e) == "'0'" or "0" in str(e):
                error_msg = (
                    "项目规划数据格式错误！\n"
                    "原因：project_plan.json 中 pages 字段格式不正确\n"
                    "解决方案：\n"
                    "1. 重新生成项目规划（右键 → 单步执行 → 生成规划）\n"
                    "2. 或手动检查 project_plan.json 文件，确保 'pages' 为字典或数组结构\n"
                    f"\n错误详情: {str(e)}"
                )
            else:
                error_msg = f"代码生成数据错误: {str(e)}"
            raise RuntimeError(error_msg) from e
        except UnicodeDecodeError as e:
            error_msg = (
                "模板文件编码错误！\n"
                "解决方案：\n"
                "1. 打开 templates/code_templates/ 文件夹\n"
                "2. 将所有 .jinja 文件转换为 UTF-8 编码\n"
                "3. 用 VSCode 打开文件，点击右下角编码，选择 'Save with Encoding' -> 'UTF-8'\n"
                f"\n错误详情: {str(e)}"
            )
            raise RuntimeError(error_msg) from e

        self.progress.emit(100)

    def _generate_pdf(self):
        """生成源代码PDF"""
        self.log.emit("Generating source code PDF...")
        # 修正：使用aligned_code目录而非code
        code_dir = BASE_DIR / "output" / self.project_name / "aligned_code"
        project_dir = BASE_DIR / "output" / self.project_name
        output_path = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="code_pdf")
        html_dir = BASE_DIR / "temp_build" / self.project_name / "html"

        if not code_dir.exists():
            raise FileNotFoundError(f"Code directory not found: {code_dir}. Please generate code first.")

        generate_code_pdf(
            project_name=self.project_name,
            code_dir=str(code_dir),
            output_path=str(output_path),
            version="V1.0",
            html_dir=str(html_dir) if html_dir.exists() else None,
            include_html=False
        )
        self.progress.emit(100)

    def _verify_runtime(self):
        """运行验证（smoke + 业务路径回放）"""
        self.log.emit("Running runtime verification...")
        project_dir = BASE_DIR / "output" / self.project_name
        html_dir = BASE_DIR / "temp_build" / self.project_name / "html"
        passed, report_path, report = run_runtime_verification(self.project_name, project_dir, html_dir)
        self.log.emit(f"Verification report: {report_path}")
        if not passed:
            raise RuntimeError(f"Runtime verification failed: {report.get('summary', {})}")
        self.log.emit("Runtime verification passed")
        self.progress.emit(100)

    def _freeze_package(self):
        """构建冻结提交包"""
        self.log.emit("Building freeze package...")
        project_dir = BASE_DIR / "output" / self.project_name
        html_dir = BASE_DIR / "temp_build" / self.project_name / "html"
        result = build_freeze_package(self.project_name, project_dir, html_dir)
        self.log.emit(f"Freeze package ready: {result.get('zip_path')}")
        self.progress.emit(100)

    @staticmethod
    def _collect_auto_fixed_actions(report: dict) -> list[str]:
        actions: list[str] = []
        auto_fix = (report or {}).get("auto_fix") or {}
        for round_item in auto_fix.get("rounds") or []:
            for action in round_item.get("action_results") or []:
                if action.get("ok") and action.get("action"):
                    actions.append(str(action.get("action")))
        return sorted(set(actions))

    def _ensure_authorization_grade(self, project_name: str):
        """提交前硬门禁：不通过则阻断，并输出自动修复结果。"""
        project_dir = BASE_DIR / "output" / project_name
        html_dir = BASE_DIR / "temp_build" / project_name / "html"
        self.log.emit(f"Running authorization gate for {project_name}...")
        passed, report_path, report = run_submission_risk_precheck(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            block_threshold=75,
            enable_auto_fix=True,
            max_fix_rounds=2,
        )
        fixed_actions = self._collect_auto_fixed_actions(report)
        if fixed_actions:
            self.log.emit(f"Auto-fixed actions: {', '.join(fixed_actions)}")
        if not passed:
            blockers = (report or {}).get("blocking_issues") or []
            blocker_text = "；".join([str(x) for x in blockers[:5]]) or "未知阻断项"
            raise RuntimeError(f"授权门禁未通过: {blocker_text} (report={report_path})")
        self.log.emit(f"Authorization gate passed: {report_path}")

    def _submit(self):
        """自动提交软著材料"""
        self.log.emit("Starting auto-submit process...")
        self._ensure_authorization_grade(self.project_name)

        # 检查必需文件
        project_dir = BASE_DIR / "output" / self.project_name
        doc_path = first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_docx")
        pdf_path = first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="code_pdf")

        missing = []
        if not doc_path:
            target_doc = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_docx")
            missing.append(f"说明书 ({target_doc.name})")
        if not pdf_path:
            target_pdf = preferred_artifact_path(project_dir, project_name=self.project_name, artifact_key="code_pdf")
            missing.append(f"源码PDF ({target_pdf.name})")

        if missing:
            raise FileNotFoundError(f"缺少必需文件: {', '.join(missing)}")

        # 检查配置
        from config import BASE_DIR as PROJECT_BASE
        config_path = PROJECT_BASE / "config" / "submit_config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"未找到配置文件: {config_path}")

        # 调用异步提交（在同步线程中运行异步代码）
        import asyncio
        from modules import auto_submit
        from config import OUTPUT_DIR

        self.log.emit("Calling auto_submit module...")

        # 在新的事件循环中运行异步任务
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                auto_submit(self.project_name, OUTPUT_DIR, config_path)
            )
            loop.close()
        finally:
            asyncio.set_event_loop(None)

        self.log.emit("Auto-submit completed successfully")
        self.progress.emit(100)

    def _submit_batch(self):
        """批量提交软著材料（复用浏览器）"""
        self.log.emit("Starting batch auto-submit process...")

        project_list = self.kwargs.get("project_list", [])
        if not project_list:
            raise ValueError("No projects provided for batch submit")

        self.log.emit(f"Projects to submit: {', '.join(project_list)}")

        eligible_projects = []
        for project_name in project_list:
            try:
                self._ensure_authorization_grade(project_name)
                eligible_projects.append(project_name)
            except Exception as e:
                self.log.emit(f"Blocked by authorization gate [{project_name}]: {e}")

        if not eligible_projects:
            raise RuntimeError("所有项目均未通过授权门禁，批量提交已阻断")

        # 检查配置
        from config import BASE_DIR as PROJECT_BASE
        config_path = PROJECT_BASE / "config" / "submit_config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"未找到配置文件: {config_path}")

        # 获取选中的账号信息
        selected_account = self.kwargs.get("selected_account", None)

        # 调用异步批量提交
        import asyncio
        from modules.auto_submitter import auto_submit_batch
        from config import OUTPUT_DIR

        self.log.emit("Calling auto_submit_batch module...")

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                auto_submit_batch(eligible_projects, OUTPUT_DIR, config_path, selected_account)
            )
            loop.close()
        finally:
            asyncio.set_event_loop(None)

        self.log.emit("Batch submit completed successfully")
        self.progress.emit(100)

    def _full_pipeline(self):
        """完整流程"""
        # 先做章程门禁，避免在缺章程时发生无意义的 API 预检调用
        project_charter = self._resolve_project_charter()
        self.kwargs["project_charter"] = project_charter

        self._run_api_preflight()
        resolved_steps = PipelineOrchestrator.resolve_steps(DEFAULT_PIPELINE_STEPS)
        steps = [(name, idx + 1, len(resolved_steps)) for idx, name in enumerate(resolved_steps)]

        for task_type, step_idx, step_total in steps:
            self.log.emit(f"Running: {task_type}...")

            if task_type == "plan":
                self._run_with_budget_stage("plan", self._generate_plan)
            elif task_type == "spec":
                self._run_with_budget_stage("spec", self._generate_spec)
                self._auto_approve_spec_if_enabled(stage="full_pipeline/spec")
                if self.kwargs.get("require_spec_confirmation"):
                    spec_path = BASE_DIR / "output" / self.project_name / "project_executable_spec.json"
                    review_status = get_spec_review_status(BASE_DIR / "output" / self.project_name, spec_path)
                    if not review_status.get("approved"):
                        raise TaskBlockedException(
                            "规格已生成，待人工确认。请在项目详情中确认规格后，点击“从当前状态继续”。"
                        )
            elif task_type == "html":
                self._run_with_budget_stage("html", self._generate_html)
            elif task_type == "screenshot":
                self._run_with_budget_stage("screenshot", self._capture_screenshots)
            elif task_type == "code":
                code_cfg = self._collect_code_generation_overrides()
                self._run_api_preflight(
                    code_cfg.get("llm_provider_override", ""),
                    code_cfg.get("llm_model_override", ""),
                )
                self._run_with_budget_stage("code", self._generate_code)
            elif task_type == "verify":
                self._run_with_budget_stage("verify", self._verify_runtime)
            elif task_type == "document":
                self._run_with_budget_stage("document", self._generate_document)
            elif task_type == "pdf":
                self._run_with_budget_stage("pdf", self._generate_pdf)
            elif task_type == "freeze":
                self._run_with_budget_stage("freeze", self._freeze_package)

            self.progress.emit(int(step_idx / step_total * 100))

        self.progress.emit(100)

    def _resume_pipeline(self):
        """从当前状态继续执行流程（断点续传）"""
        self.log.emit("检测项目当前状态...")

        # 检测项目状态
        project_dir = BASE_DIR / "output" / self.project_name
        plan_file = project_dir / "project_plan.json"

        # HTML在temp_build目录下
        temp_build_base = project_dir.parent.parent / "temp_build"
        html_dir = temp_build_base / self.project_name / "html"

        # 截图在项目目录下
        screenshot_dir = project_dir / "screenshots"

        # 代码目录
        code_dir = project_dir / "aligned_code"

        # Word文档
        doc_file = first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_docx")

        # PDF文件（说明书和源代码）
        doc_pdf_file = first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="manual_pdf")
        code_pdf_file = first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="code_pdf")
        spec_file = project_dir / "project_executable_spec.json"
        verify_file = project_dir / "runtime_verification_report.json"
        freeze_zip = first_existing_artifact_path(project_dir, project_name=self.project_name, artifact_key="freeze_zip")

        # 定义流程步骤（与 API/CLI 统一）
        document_done = bool(doc_file and doc_pdf_file)
        verify_done = False
        if verify_file.exists():
            try:
                with open(verify_file, "r", encoding="utf-8") as f:
                    verify_done = bool(json.load(f).get("overall_passed"))
            except Exception:
                verify_done = False
        steps = [
            ("plan", plan_file.exists()),
            ("spec", spec_file.exists()),
            ("html", html_dir.exists() and any(html_dir.glob('*.html'))),
            ("screenshot", screenshot_dir.exists() and any(screenshot_dir.glob('*.png'))),
            ("code", code_dir.exists() and any(code_dir.rglob('*.*'))),
            ("verify", verify_done),
            ("document", document_done),
            ("pdf", bool(code_pdf_file)),
            ("freeze", bool(freeze_zip)),
        ]

        # 找到第一个未完成的步骤
        start_index = 0
        for i, (task_name, is_done) in enumerate(steps):
            if not is_done:
                start_index = i
                self.log.emit(f"从 '{task_name}' 步骤开始继续...")
                break
            else:
                self.log.emit(f"✅ {task_name} 已完成，跳过")

        # 如果全部完成
        if start_index == 0 and all(is_done for _, is_done in steps):
            self.log.emit("所有步骤已完成！")
            self.progress.emit(100)
            return

        remaining = [step_name for step_name, _ in steps[start_index:]]
        if PipelineOrchestrator.needs_llm_preflight(remaining):
            if any(step in {"plan", "html"} for step in remaining):
                self._run_api_preflight()
            if "code" in remaining:
                code_cfg = self._collect_code_generation_overrides()
                self._run_api_preflight(
                    code_cfg.get("llm_provider_override", ""),
                    code_cfg.get("llm_model_override", ""),
                )

        # 从断点开始执行
        for i in range(start_index, len(steps)):
            task_type, _ = steps[i]
            self.log.emit(f"Running: {task_type}...")

            if task_type == "plan":
                self._run_with_budget_stage("plan", self._generate_plan)
            elif task_type == "spec":
                self._run_with_budget_stage("spec", self._generate_spec)
            elif task_type == "html":
                self._run_with_budget_stage("html", self._generate_html)
            elif task_type == "screenshot":
                self._run_with_budget_stage("screenshot", self._capture_screenshots)
            elif task_type == "code":
                self._run_with_budget_stage("code", self._generate_code)
            elif task_type == "verify":
                self._run_with_budget_stage("verify", self._verify_runtime)
            elif task_type == "document":
                self._run_with_budget_stage("document", self._generate_document)
            elif task_type == "pdf":
                self._run_with_budget_stage("pdf", self._generate_pdf)
            elif task_type == "freeze":
                self._run_with_budget_stage("freeze", self._freeze_package)

            self.progress.emit(int((i + 1) / len(steps) * 100))

        self.progress.emit(100)
        self.log.emit("✅ 断点续传完成！")

    def _download_signatures(self):
        """下载签章页"""
        self.log.emit("开始下载签章页...")

        # 获取选中的账号信息
        selected_account = self.kwargs.get("selected_account", None)
        if not selected_account:
            raise ValueError("未提供账号信息")

        # 调用异步下载
        import asyncio
        import sys
        sys.path.insert(0, str(BASE_DIR))

        try:
            # 导入下载函数 - 修正函数名
            from batch_download_signs import batch_download_signs

            self.log.emit(f"使用账号: {selected_account.get('username', '')}")

            # 创建临时配置
            import json
            config_path = BASE_DIR / "config" / "submit_config.json"

            # 备份原配置
            original_config = None
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    original_config = json.load(f)

            # 写入临时配置
            temp_config = {
                "username": selected_account.get("username"),
                "password": selected_account.get("password"),
                "wait_captcha_seconds": 60
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(temp_config, f, indent=2, ensure_ascii=False)

            # 执行下载
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(batch_download_signs())
            loop.close()

            # 恢复原配置
            if original_config:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(original_config, f, indent=2, ensure_ascii=False)

            self.log.emit("签章页下载完成！")
            self.message = "签章页下载成功，文件保存在 签章页/ 目录"

        except Exception as e:
            raise RuntimeError(f"下载签章页失败: {str(e)}")
        finally:
            asyncio.set_event_loop(None)

        self.progress.emit(100)

    def _auto_sign(self):
        """自动签名"""
        self.log.emit("开始自动签名...")

        sign_folder = self.kwargs.get("sign_folder", "")
        if not sign_folder:
            raise ValueError("未提供签名文件夹路径")

        import sys
        sys.path.insert(0, str(BASE_DIR))

        try:
            # 导入签名函数
            from batch_signer import batch_sign_pdfs

            self.log.emit(f"签名文件夹: {sign_folder}")

            # 临时修改全局变量
            import batch_signer
            original_sign_dir = batch_signer.SIGN_DIR
            batch_signer.SIGN_DIR = Path(sign_folder)

            # 执行签名
            batch_sign_pdfs()

            # 恢复全局变量
            batch_signer.SIGN_DIR = original_sign_dir

            self.log.emit("自动签名完成！")
            self.message = "签名处理成功，文件已保存到 output/已签名/"

        except Exception as e:
            raise RuntimeError(f"自动签名失败: {str(e)}")

        self.progress.emit(100)

    def _apply_scan_effect(self):
        """应用扫描效果"""
        self.log.emit("开始应用扫描效果...")

        import sys
        sys.path.insert(0, str(BASE_DIR))

        try:
            # 导入扫描效果函数
            from batch_scan_effect import batch_apply_scan_effect

            self.log.emit("处理中，这可能需要几分钟...")

            # 执行扫描效果处理
            batch_apply_scan_effect()

            self.log.emit("扫描效果应用完成！")
            self.message = "扫描效果处理成功，文件已保存到 output/最终提交/"

        except Exception as e:
            raise RuntimeError(f"应用扫描效果失败: {str(e)}")

        self.progress.emit(100)

    def _sign_and_scan(self):
        """一键签名+扫描效果"""
        self.log.emit("开始一键签名+扫描效果处理...")

        import sys
        sys.path.insert(0, str(BASE_DIR))

        try:
            # 导入一键签名+扫描函数
            from batch_sign_and_scan import batch_sign_and_scan

            self.log.emit("流程: 签章页 → 已签名 → 最终提交")

            # 获取签名文件夹参数
            sign_folder = self.kwargs.get("sign_folder", None)
            if sign_folder:
                self.log.emit(f"签名文件夹: {sign_folder}")

            # 定义进度回调
            def progress_callback(current, total, message):
                if total > 0:
                    percent = int((current / total) * 100)
                    self.progress.emit(percent)
                self.log.emit(message)

            # 执行一键签名+扫描
            success_count, total_count, output_dir = batch_sign_and_scan(
                progress_callback=progress_callback,
                sign_dir=sign_folder
            )

            self.log.emit(f"处理完成: 成功 {success_count}/{total_count}")
            self.message = f"一键处理完成，成功 {success_count}/{total_count}，文件已保存到 {output_dir}"

        except Exception as e:
            raise RuntimeError(f"一键签名+扫描失败: {str(e)}")

        self.progress.emit(100)

    def _upload_signatures(self):
        """自动上传签章页"""
        self.log.emit("开始自动上传签章页...")

        # 获取选中的账号信息
        selected_account = self.kwargs.get("selected_account", None)
        if not selected_account:
            raise ValueError("未提供账号信息")

        # 调用异步上传
        import asyncio
        import sys
        sys.path.insert(0, str(BASE_DIR))

        try:
            # 导入上传函数
            from batch_upload_signatures import batch_upload_signatures

            self.log.emit(f"使用账号: {selected_account.get('username', '')}")

            # 创建临时配置
            import json
            config_path = BASE_DIR / "config" / "submit_config.json"

            # 备份原配置
            original_config = None
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    original_config = json.load(f)

            # 写入临时配置
            temp_config = {
                "username": selected_account.get("username"),
                "password": selected_account.get("password"),
                "wait_captcha_seconds": 60
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(temp_config, f, indent=2, ensure_ascii=False)

            # 执行上传
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 注意：batch_upload_signatures() 会保持浏览器打开
            # 直到用户手动关闭，这是期望的行为
            loop.run_until_complete(batch_upload_signatures())
            loop.close()

            # 恢复原配置
            if original_config:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(original_config, f, indent=2, ensure_ascii=False)

            self.log.emit("签章页上传完成！")
            self.message = "签章页上传成功，请查看浏览器确认"

        except Exception as e:
            raise RuntimeError(f"上传签章页失败: {str(e)}")
        finally:
            asyncio.set_event_loop(None)

        self.progress.emit(100)
