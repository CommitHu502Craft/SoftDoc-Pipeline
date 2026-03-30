"""
FastAPI 后端主入口
提供 REST API 和 WebSocket 接口
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.models import (
    ProjectCreate, ProjectResponse, ProjectListResponse,
    RunPipelineRequest, TaskProgress, SettingsUpdate, SettingsResponse,
    PipelineStep,
    SpecReviewStatusResponse, SpecReviewApproveRequest,
    ProjectCharterResponse, ProjectCharterUpdateRequest,
    ProjectCharterDraftRequest, BatchCharterDraftRequest,
    SelfHealRunRequest, BatchSelfHealRunRequest,
    SubmissionRiskCheckRequest, SubmissionRiskResponse,
    UiSkillStudioRequest, UiSkillStudioResponse,
    UiSkillPolicyAutofixRequest, UiSkillPolicyAutofixResponse,
    # New models
    AccountCreate, AccountUpdate, AccountResponse, AccountListResponse,
    SubmitQueueItem, SubmitQueueResponse, AddToQueueRequest, StartSubmitRequest,
    SignatureStatus, SignatureStepRequest, SignatureStatsResponse,
    ScanOutputRequest, ScanOutputResponse,
    GeneralSettingsUpdate, GeneralSettingsResponse
)
from api.database import db, account_db, submit_queue_db
from api.task_manager import task_manager
from modules.spec_review import approve_spec_review, get_spec_review_status
from modules.project_charter import (
    draft_project_charter_with_ai,
    load_project_charter,
    normalize_project_charter,
    save_project_charter,
    validate_project_charter,
)
from modules.artifact_naming import (
    candidate_artifact_paths,
    first_existing_artifact_path,
    preferred_artifact_path,
)
from modules.pre_submission_risk import run_submission_risk_precheck
from modules.ui_skill_orchestrator import build_ui_skill_artifacts
from modules.skill_studio import run_skill_studio
from modules.skill_autorepair_runner import run_skill_autorepair
from config import BASE_DIR, OUTPUT_DIR, load_api_config, save_api_config, get_provider_config
from core.pipeline_config import DEFAULT_PIPELINE_STEPS
from core.pipeline_orchestrator import PipelineOrchestrator
from core.llm_budget import llm_budget
import config as config_module
import api.database as database_module
import api.task_manager as task_manager_module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


GENERAL_SETTINGS_PATH = BASE_DIR / "config" / "general_settings.json"


def _load_general_settings() -> Dict[str, Any]:
    defaults = {
        "captcha_wait_seconds": int(getattr(config_module, "CAPTCHA_WAIT_SECONDS", 60) or 60),
        "output_directory": str(OUTPUT_DIR),
        "ui_skill_enabled": True,
        "ui_skill_mode": "narrative_tool_hybrid",
        "ui_token_policy": "balanced",
    }
    if not GENERAL_SETTINGS_PATH.exists():
        return defaults
    try:
        with open(GENERAL_SETTINGS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return defaults
        merged = {**defaults, **payload}
        merged["captcha_wait_seconds"] = int(merged.get("captcha_wait_seconds") or defaults["captcha_wait_seconds"])
        merged["output_directory"] = str(merged.get("output_directory") or defaults["output_directory"])
        merged["ui_skill_enabled"] = bool(merged.get("ui_skill_enabled", defaults["ui_skill_enabled"]))
        merged["ui_skill_mode"] = str(merged.get("ui_skill_mode") or defaults["ui_skill_mode"])
        merged["ui_token_policy"] = str(merged.get("ui_token_policy") or defaults["ui_token_policy"])
        return merged
    except Exception:
        return defaults


def _save_general_settings(settings: Dict[str, Any]) -> None:
    GENERAL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GENERAL_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def _apply_runtime_general_settings(settings: Dict[str, Any]) -> None:
    global OUTPUT_DIR
    captcha_wait_seconds = int(settings.get("captcha_wait_seconds") or 60)
    output_directory = Path(str(settings.get("output_directory") or str(OUTPUT_DIR))).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    config_module.CAPTCHA_WAIT_SECONDS = captcha_wait_seconds
    config_module.OUTPUT_DIR = output_directory

    OUTPUT_DIR = output_directory
    database_module.OUTPUT_DIR = output_directory
    task_manager_module.OUTPUT_DIR = output_directory


_apply_runtime_general_settings(_load_general_settings())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("SoftDoc Pipeline API starting...")
    yield
    logger.info("API 关闭")


app = FastAPI(
    title="SoftDoc Pipeline API",
    description="Backend API for the public SoftDoc Pipeline snapshot.",
    version="3.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 项目管理 API ====================

@app.get("/api/projects", response_model=ProjectListResponse)
async def list_projects():
    """获取所有项目列表"""
    projects = db.get_all_projects()
    return ProjectListResponse(
        projects=[ProjectResponse(**p) for p in projects],
        total=len(projects)
    )


@app.post("/api/projects", response_model=ProjectResponse)
async def create_project(data: ProjectCreate):
    """创建新项目"""
    project = db.create_project(data.name, charter=data.charter)
    return ProjectResponse(**project)


@app.post("/api/projects/batch")
async def create_projects_batch(data: dict):
    """批量创建项目（支持换行分隔的项目名）"""
    names = data.get("names", [])
    if isinstance(names, str):
        # 支持换行分隔的字符串
        names = [n.strip() for n in names.split("\n") if n.strip()]

    projects = db.create_projects_batch(names)
    return {
        "message": f"已创建 {len(projects)} 个项目",
        "projects": [ProjectResponse(**p) for p in projects]
    }


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    """获取单个项目详情"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ProjectResponse(**project)


@app.get("/api/projects/{project_id}/charter", response_model=ProjectCharterResponse)
async def get_project_charter(project_id: str):
    """获取项目章程及校验状态。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    charter = _resolve_project_charter(project_name, project)
    _save_project_charter_state(project_id, project_name, charter)
    return _build_charter_response(project_id, project_name, charter)


@app.put("/api/projects/{project_id}/charter", response_model=ProjectCharterResponse)
async def update_project_charter(project_id: str, data: ProjectCharterUpdateRequest):
    """更新项目章程。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    charter = normalize_project_charter(data.charter or {}, project_name=project_name)
    _save_project_charter_state(project_id, project_name, charter)
    return _build_charter_response(project_id, project_name, charter)


@app.post("/api/projects/{project_id}/charter/draft", response_model=ProjectCharterResponse)
async def draft_project_charter(project_id: str, data: Optional[ProjectCharterDraftRequest] = None):
    """AI 草拟/补全项目章程。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    charter = draft_project_charter_with_ai(
        project_name=project_name,
        context_hint=str((data.context_hint if data else "") or ""),
    )
    _save_project_charter_state(project_id, project_name, charter)
    return _build_charter_response(project_id, project_name, charter)


@app.post("/api/projects/batch-charter/draft")
async def draft_project_charter_batch(data: BatchCharterDraftRequest):
    """批量 AI 草拟/补全章程。"""
    results = []
    updated = 0
    skipped = 0
    failed = 0

    for project_id in data.project_ids:
        project = db.get_project(project_id)
        if not project:
            failed += 1
            results.append(
                {
                    "project_id": project_id,
                    "status": "failed",
                    "message": "项目不存在",
                }
            )
            continue

        project_name = str(project["name"])
        existing_charter = _resolve_project_charter(project_name, project)
        existing_errors = validate_project_charter(existing_charter)
        if (not data.force_overwrite) and len(existing_errors) == 0:
            skipped += 1
            results.append(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "status": "skipped",
                    "message": "章程已完整，跳过",
                }
            )
            continue

        try:
            charter = draft_project_charter_with_ai(
                project_name=project_name,
                context_hint=str(data.context_hint or ""),
            )
            _save_project_charter_state(project_id, project_name, charter)
            updated += 1
            results.append(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "status": "updated",
                    "charter_completed": len(validate_project_charter(charter)) == 0,
                }
            )
        except Exception as e:
            failed += 1
            results.append(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "status": "failed",
                    "message": str(e),
                }
            )

    return {
        "message": f"批量章程草拟完成：更新 {updated}，跳过 {skipped}，失败 {failed}",
        "total": len(data.project_ids),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "items": results,
    }


@app.get("/api/projects/{project_id}/spec-review", response_model=SpecReviewStatusResponse)
async def get_project_spec_review_status(project_id: str):
    """获取项目规格评审状态。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    project_dir = OUTPUT_DIR / project["name"]
    status = get_spec_review_status(project_dir, project_dir / "project_executable_spec.json")
    return SpecReviewStatusResponse(**status)


@app.post("/api/projects/{project_id}/spec-review/approve", response_model=SpecReviewStatusResponse)
async def approve_project_spec_review(project_id: str, data: Optional[SpecReviewApproveRequest] = None):
    """确认当前规格（绑定当前规格哈希）。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    project_dir = OUTPUT_DIR / project["name"]
    reviewer = str((data.reviewer if data else "") or "api-user").strip() or "api-user"
    result = approve_spec_review(project_dir, reviewer=reviewer)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or "规格确认失败")

    status = get_spec_review_status(project_dir, project_dir / "project_executable_spec.json")
    return SpecReviewStatusResponse(**status)


@app.get("/api/projects/{project_id}/submission-risk", response_model=SubmissionRiskResponse)
async def get_submission_risk(project_id: str):
    """获取项目申报前风险报告（若不存在则即时生成）。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    html_dir = BASE_DIR / "temp_build" / project_name / "html"
    report_path = project_dir / "submission_risk_report.json"
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    else:
        _, report_path, report = run_submission_risk_precheck(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            block_threshold=75,
        )
    return SubmissionRiskResponse(
        project_id=project_id,
        project_name=project_name,
        report_path=str(report_path),
        report=report,
    )


@app.post("/api/projects/{project_id}/submission-risk/check", response_model=SubmissionRiskResponse)
async def check_submission_risk(project_id: str, data: SubmissionRiskCheckRequest):
    """执行一次申报前风险预检并落盘。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    html_dir = BASE_DIR / "temp_build" / project_name / "html"
    _, report_path, report = run_submission_risk_precheck(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=int(data.block_threshold),
        enable_auto_fix=bool(data.enable_auto_fix),
        max_fix_rounds=max(1, int(data.max_fix_rounds)),
    )
    return SubmissionRiskResponse(
        project_id=project_id,
        project_name=project_name,
        report_path=str(report_path),
        report=report,
    )


@app.get("/api/projects/{project_id}/ui-skill/plan")
async def get_ui_skill_plan(project_id: str):
    """获取或构建项目 UI 技能规划产物。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=400, detail="缺少 project_plan.json，请先执行规划阶段")

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)
    artifacts = build_ui_skill_artifacts(
        project_name=project_name,
        plan=plan,
        project_dir=project_dir,
        force=False,
    )
    blueprint = artifacts.get("blueprint") or {}
    profile = artifacts.get("profile") or {}
    report = artifacts.get("report") or {}
    return {
        "project_id": project_id,
        "project_name": project_name,
        "profile_path": str(artifacts.get("profile_path")),
        "blueprint_path": str(artifacts.get("blueprint_path")),
        "contract_path": str(artifacts.get("contract_path")),
        "runtime_skill_path": str(artifacts.get("runtime_skill_path") or ""),
        "runtime_rule_graph_path": str(artifacts.get("runtime_rule_graph_path") or ""),
        "skill_compliance_report_path": str(project_dir / "skill_compliance_report.json"),
        "skill_autorepair_report_path": str(project_dir / "skill_autorepair_report.json"),
        "skill_policy_report_path": str(project_dir / "skill_policy_decision_report.json"),
        "report_path": str(artifacts.get("report_path")),
        "profile": profile,
        "blueprint_summary": blueprint.get("summary") or {},
        "report": report,
    }


@app.post("/api/projects/{project_id}/ui-skill/plan")
async def build_ui_skill_plan(project_id: str, force: bool = False):
    """构建（或强制重建）项目 UI 技能规划产物。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        raise HTTPException(status_code=400, detail="缺少 project_plan.json，请先执行规划阶段")

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)
    artifacts = build_ui_skill_artifacts(
        project_name=project_name,
        plan=plan,
        project_dir=project_dir,
        force=bool(force),
    )
    blueprint = artifacts.get("blueprint") or {}
    return {
        "message": "UI 技能规划已重建" if bool(force) else "UI 技能规划已生成",
        "project_id": project_id,
        "project_name": project_name,
        "profile_path": str(artifacts.get("profile_path")),
        "blueprint_path": str(artifacts.get("blueprint_path")),
        "contract_path": str(artifacts.get("contract_path")),
        "runtime_skill_path": str(artifacts.get("runtime_skill_path") or ""),
        "runtime_rule_graph_path": str(artifacts.get("runtime_rule_graph_path") or ""),
        "skill_compliance_report_path": str(project_dir / "skill_compliance_report.json"),
        "skill_autorepair_report_path": str(project_dir / "skill_autorepair_report.json"),
        "skill_policy_report_path": str(project_dir / "skill_policy_decision_report.json"),
        "report_path": str(artifacts.get("report_path")),
        "profile": artifacts.get("profile") or {},
        "blueprint_summary": blueprint.get("summary") or {},
        "report": artifacts.get("report") or {},
    }


@app.post("/api/projects/{project_id}/ui-skill/plan/rebuild")
async def rebuild_ui_skill_plan(project_id: str):
    """兼容旧接口：强制重建项目 UI 技能规划产物。"""
    return await build_ui_skill_plan(project_id=project_id, force=True)


@app.get("/api/projects/{project_id}/ui-skill/studio", response_model=UiSkillStudioResponse)
async def get_ui_skill_studio(project_id: str):
    """读取最近一次 Skill Studio 决策结果。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    studio_path = project_dir / "skill_studio_plan.json"
    payload = {}
    if studio_path.exists():
        with open(studio_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    spec_meta = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
    return UiSkillStudioResponse(
        project_id=project_id,
        project_name=project_name,
        studio_plan_path=str(studio_path),
        runtime_skill_override_path=str(project_dir / "runtime_skill_override.json"),
        actions=list(payload.get("actions") or []),
        decisions=payload.get("decisions") or {},
        ui_skill_artifacts=payload.get("ui_skill_artifacts") or {},
        spec_path=str(spec_meta.get("spec_path") or ""),
        spec_digest=str(spec_meta.get("spec_digest") or ""),
        spec_review_status=str(spec_meta.get("spec_review_status") or ""),
        override_validation=payload.get("override_validation") or {},
    )


@app.post("/api/projects/{project_id}/ui-skill/studio", response_model=UiSkillStudioResponse)
async def run_ui_skill_studio(project_id: str, data: UiSkillStudioRequest):
    """使用自然语言意图驱动 runtime skills，并可接管规划重建。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    try:
        result = run_skill_studio(
            project_name=project_name,
            project_dir=project_dir,
            intent_text=str(data.intent_text or ""),
            apply_to_plan=bool(data.apply_to_plan),
            rebuild_ui_skill=bool(data.rebuild_ui_skill),
            domain_override=str(data.domain or ""),
            ui_mode_override=str(data.ui_mode or ""),
            token_policy_override=str(data.token_policy or ""),
            page_count_override=int(data.page_count or 0),
            feature_preferences=list(data.feature_preferences or []),
            preset_template=str(data.preset_template or ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    actions = list(result.get("actions") or [])
    decisions = result.get("decisions") or {}
    ui_skill_artifacts = result.get("ui_skill_artifacts") or {}
    spec_meta = {
        "spec_path": str(result.get("spec_path") or (project_dir / "project_executable_spec.json")),
        "spec_digest": str(result.get("spec_digest") or ""),
        "spec_review_status": str(result.get("spec_review_status") or ""),
    }
    override_validation = result.get("override_validation") or {}

    # 回写 skill_studio_plan.json，补充回传字段。
    studio_path = Path(result.get("skill_studio_plan_path") or (project_dir / "skill_studio_plan.json"))
    studio_payload = {}
    if studio_path.exists():
        try:
            with open(studio_path, "r", encoding="utf-8") as f:
                studio_payload = json.load(f)
        except Exception:
            studio_payload = {}
    studio_payload["actions"] = actions
    studio_payload["ui_skill_artifacts"] = ui_skill_artifacts
    studio_payload["spec"] = spec_meta
    studio_payload["override_validation"] = override_validation
    with open(studio_path, "w", encoding="utf-8") as f:
        json.dump(studio_payload, f, ensure_ascii=False, indent=2)

    return UiSkillStudioResponse(
        project_id=project_id,
        project_name=project_name,
        studio_plan_path=str(studio_path),
        runtime_skill_override_path=str(result.get("runtime_skill_override_path") or (project_dir / "runtime_skill_override.json")),
        actions=actions,
        decisions=decisions,
        ui_skill_artifacts=ui_skill_artifacts,
        spec_path=str(spec_meta.get("spec_path") or ""),
        spec_digest=str(spec_meta.get("spec_digest") or ""),
        spec_review_status=str(spec_meta.get("spec_review_status") or ""),
        override_validation=override_validation,
    )


@app.post("/api/projects/{project_id}/ui-skill/policy-autofix", response_model=UiSkillPolicyAutofixResponse)
async def run_ui_skill_policy_autofix(project_id: str, data: Optional[UiSkillPolicyAutofixRequest] = None):
    """执行策略建议的运行时技能自动修复（仅失败页面/文件），并返回剩余阻断项。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    html_dir = BASE_DIR / "temp_build" / project_name / "html"

    max_rounds = max(1, int((data.max_rounds if data else 2) or 2))
    block_threshold = int((data.block_threshold if data else 75) or 75)

    # 先拿到当前策略建议动作（不做全局 auto-fix）
    _, _, before_report = run_submission_risk_precheck(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=block_threshold,
        enable_auto_fix=False,
        max_fix_rounds=max_rounds,
    )
    runtime_detail = ((before_report.get("checks") or {}).get("runtime_skill_compliance") or {})
    policy_actions = [str(x).strip() for x in (runtime_detail.get("policy_auto_fix_actions") or []) if str(x).strip()]

    attempted = False
    if policy_actions:
        run_skill_autorepair(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            max_rounds=max_rounds,
            policy_actions=policy_actions,
        )
        attempted = True

    _, report_path, final_report = run_submission_risk_precheck(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=block_threshold,
        enable_auto_fix=False,
        max_fix_rounds=max_rounds,
    )

    remaining_blockers = [str(x) for x in (final_report.get("blocking_issues") or []) if str(x).strip()]
    fixed = (not bool(final_report.get("should_block_submission"))) and bool((final_report.get("hard_gate") or {}).get("passed"))
    return UiSkillPolicyAutofixResponse(
        project_id=project_id,
        project_name=project_name,
        attempted=attempted,
        fixed=bool(fixed),
        policy_actions=policy_actions,
        remaining_blockers=remaining_blockers,
        skill_autorepair_report_path=str(project_dir / "skill_autorepair_report.json"),
        submission_risk_report_path=str(report_path),
        final_report=final_report,
    )


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """删除项目"""
    if not db.delete_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"message": "项目已删除"}


# ==================== 流水线任务 API ====================

# 批量执行状态
batch_execution_status = {
    "is_running": False,
    "total": 0,
    "completed": 0,
    "failed": 0,
    "current_tasks": [],  # 正在执行的任务ID列表
    "pending_projects": [],  # 等待执行的项目ID列表
    "max_parallel": 2,  # 最大并行数
}

SPEC_APPROVAL_REQUIRED_STEPS = {"code", "verify", "document", "pdf", "freeze"}


def _auto_confirm_spec_review_enabled() -> bool:
    """读取 API/Web 端自动规格确认开关（默认开启）。"""
    try:
        config = load_api_config() or {}
    except Exception:
        return True
    return bool(config.get("auto_confirm_spec_review", True))


def _requires_preapproved_spec(steps: List[str]) -> bool:
    """
    仅当“先执行实现阶段、且在此之前没有 spec 步骤”时，要求启动前已有规格确认。
    例如完整流程包含 spec -> code，则不应在启动前拦截。
    """
    impl_indexes = [idx for idx, step in enumerate(steps) if step in SPEC_APPROVAL_REQUIRED_STEPS]
    if not impl_indexes:
        return False
    first_impl_index = min(impl_indexes)
    return not any(step == "spec" for step in steps[:first_impl_index])


def _resolve_project_charter(project_name: str, project_payload: Dict[str, Any]) -> Dict[str, Any]:
    project_dir = OUTPUT_DIR / project_name
    raw_charter = project_payload.get("project_charter") or load_project_charter(project_dir) or {}
    return normalize_project_charter(raw_charter, project_name=project_name)


def _save_project_charter_state(project_id: str, project_name: str, charter: Dict[str, Any]) -> None:
    project_dir = OUTPUT_DIR / project_name
    normalized = normalize_project_charter(charter or {}, project_name=project_name)
    save_project_charter(project_dir, normalized)
    db.update_project(project_id, {"project_charter": normalized})


def _build_charter_response(project_id: str, project_name: str, charter: Dict[str, Any]) -> ProjectCharterResponse:
    normalized = normalize_project_charter(charter or {}, project_name=project_name)
    errors = validate_project_charter(normalized)
    project_dir = OUTPUT_DIR / project_name
    project_state = db.get_project(project_id) or {}
    return ProjectCharterResponse(
        project_id=project_id,
        project_name=project_name,
        charter=normalized,
        charter_completed=(len(errors) == 0),
        charter_summary=project_state.get("charter_summary"),
        validation_errors=errors,
        charter_path=str(project_dir / "project_charter.json"),
    )


def _self_heal_prepare(
    project_id: str,
    project: Dict[str, Any],
    request: SelfHealRunRequest,
) -> Dict[str, Any]:
    project_name = str(project["name"])
    project_dir = OUTPUT_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    actions: List[str] = []

    charter = _resolve_project_charter(project_name, project)
    charter_errors = validate_project_charter(charter)
    if charter_errors:
        charter = draft_project_charter_with_ai(
            project_name=project_name,
            context_hint=str(request.context_hint or ""),
        )
        actions.append("charter_auto_drafted")
    _save_project_charter_state(project_id, project_name, charter)

    steps = PipelineOrchestrator.resolve_steps([s.value for s in request.steps])
    plan_path = project_dir / "project_plan.json"
    spec_path = project_dir / "project_executable_spec.json"

    if not plan_path.exists() and "plan" not in steps:
        steps = ["plan"] + steps
        actions.append("plan_inserted")

    if not spec_path.exists() and "spec" not in steps:
        if "plan" in steps:
            insert_pos = steps.index("plan") + 1
            steps = steps[:insert_pos] + ["spec"] + steps[insert_pos:]
        else:
            steps = ["spec"] + steps
        actions.append("spec_inserted")

    if (
        request.auto_confirm_spec
        and spec_path.exists()
        and _requires_preapproved_spec(steps)
    ):
        review_status = get_spec_review_status(project_dir, spec_path)
        if not review_status.get("approved") and review_status.get("review_status") != "missing_spec":
            result = approve_spec_review(project_dir, reviewer="api-self-heal")
            if result.get("ok"):
                actions.append("spec_auto_approved")

    return {
        "project_name": project_name,
        "project_charter": charter,
        "steps": steps,
        "actions": actions,
    }


@app.post("/api/projects/batch-run")
async def run_batch_pipeline(
    data: dict,
    background_tasks: BackgroundTasks
):
    """批量并行执行多个项目"""
    global batch_execution_status

    if batch_execution_status["is_running"]:
        raise HTTPException(status_code=400, detail="批量任务正在运行中")

    project_ids = data.get("project_ids", [])
    max_parallel = data.get("max_parallel", 2)
    steps = PipelineOrchestrator.resolve_steps(data.get("steps", list(DEFAULT_PIPELINE_STEPS)))
    code_generation_overrides = data.get("code_generation_overrides") or {}
    if not isinstance(code_generation_overrides, dict):
        raise HTTPException(status_code=400, detail="code_generation_overrides 必须是对象")

    if not project_ids:
        raise HTTPException(status_code=400, detail="未选择任何项目")

    # 验证项目
    valid_projects = []
    skipped_projects = []
    requires_preapproved_spec = _requires_preapproved_spec(steps)
    auto_confirm_spec = _auto_confirm_spec_review_enabled()
    for pid in project_ids:
        project = db.get_project(pid)
        if project:
            if requires_preapproved_spec:
                project_dir = OUTPUT_DIR / project["name"]
                review_status = get_spec_review_status(project_dir, project_dir / "project_executable_spec.json")
                if not review_status.get("approved"):
                    if review_status.get("review_status") != "missing_spec" and auto_confirm_spec:
                        result = approve_spec_review(project_dir, reviewer="api-auto")
                        if result.get("ok"):
                            review_status = get_spec_review_status(project_dir, project_dir / "project_executable_spec.json")

                if not review_status.get("approved"):
                    skipped_projects.append(
                        {
                            "id": pid,
                            "name": project["name"],
                            "reason": "spec_not_approved",
                            "review_status": review_status.get("review_status", "pending"),
                        }
                    )
                    continue
            valid_projects.append({
                "id": pid,
                "name": project["name"],
                "charter": project.get("project_charter") or {},
            })

    if not valid_projects:
        detail = "没有有效的项目"
        if skipped_projects:
            detail = f"没有可执行项目（{len(skipped_projects)} 个项目规格未确认）"
        raise HTTPException(status_code=400, detail=detail)

    # 初始化批量状态
    batch_execution_status = {
        "is_running": True,
        "total": len(valid_projects),
        "completed": 0,
        "failed": 0,
        "current_tasks": [],
        "pending_projects": [p["id"] for p in valid_projects],
        "max_parallel": min(max_parallel, 5),  # 最多5个并行
    }

    async def run_batch():
        """批量执行主逻辑"""
        global batch_execution_status
        import asyncio

        semaphore = asyncio.Semaphore(batch_execution_status["max_parallel"])

        async def run_single_project(project_id: str, project_name: str, project_charter: Dict[str, Any]):
            """执行单个项目"""
            task_id = ""
            async with semaphore:
                try:
                    # 从待执行列表移除
                    if project_id in batch_execution_status["pending_projects"]:
                        batch_execution_status["pending_projects"].remove(project_id)

                    # 创建任务
                    task_id = task_manager.create_task(
                        project_id,
                        project_name,
                        code_generation_overrides=code_generation_overrides,
                        project_charter=project_charter,
                    )
                    batch_execution_status["current_tasks"].append(task_id)

                    # 更新项目状态
                    db.update_project(project_id, {"status": "running", "progress": 0})

                    # 执行流水线
                    await task_manager.run_pipeline(
                        task_id,
                        steps,
                        lambda pid, updates: db.update_project(pid, updates),
                        code_generation_overrides=code_generation_overrides,
                        project_charter=project_charter,
                    )

                    batch_execution_status["completed"] += 1
                    logger.info(f"项目 {project_name} 执行完成")

                except Exception as e:
                    batch_execution_status["failed"] += 1
                    logger.error(f"项目 {project_name} 执行失败: {e}")
                    db.update_project(project_id, {"status": "error"})

                finally:
                    if task_id and task_id in batch_execution_status["current_tasks"]:
                        batch_execution_status["current_tasks"].remove(task_id)

        # 并行执行所有项目
        tasks = [
            run_single_project(p["id"], p["name"], p.get("charter") or {})
            for p in valid_projects
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # 完成
        batch_execution_status["is_running"] = False
        logger.info(f"批量执行完成: {batch_execution_status['completed']}/{batch_execution_status['total']}")

    background_tasks.add_task(run_batch)

    return {
        "message": f"已启动 {len(valid_projects)} 个项目的批量执行，跳过 {len(skipped_projects)} 个未确认规格项目",
        "total": len(valid_projects),
        "max_parallel": batch_execution_status["max_parallel"],
        "skipped": len(skipped_projects),
        "skipped_projects": skipped_projects,
    }


@app.get("/api/projects/batch-status")
async def get_batch_status():
    """获取批量执行状态"""
    return batch_execution_status


@app.post("/api/projects/batch-stop")
async def stop_batch_execution():
    """停止批量执行（仅停止未开始的）"""
    global batch_execution_status
    batch_execution_status["pending_projects"] = []
    batch_execution_status["is_running"] = False
    return {"message": "已停止批量执行"}


@app.post("/api/projects/{project_id}/run")
async def run_pipeline(
    project_id: str,
    request: RunPipelineRequest,
    background_tasks: BackgroundTasks
):
    """启动流水线任务"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 创建任务
    code_generation_overrides = request.code_generation_overrides or {}
    request_charter = request.project_charter if isinstance(request.project_charter, dict) else None
    effective_charter = request_charter or project.get("project_charter") or {}
    task_id = task_manager.create_task(
        project_id,
        project["name"],
        code_generation_overrides=code_generation_overrides,
        project_charter=effective_charter,
    )

    # 更新项目状态
    db.update_project(
        project_id,
        {
            "status": "running",
            "progress": 0,
            "project_charter": effective_charter,
        },
    )

    # 在后台运行流水线
    steps = PipelineOrchestrator.resolve_steps([s.value for s in request.steps])

    async def run_task():
        await task_manager.run_pipeline(
            task_id,
            steps,
            lambda pid, updates: db.update_project(pid, updates),
            code_generation_overrides=code_generation_overrides,
            project_charter=effective_charter,
        )

    background_tasks.add_task(run_task)

    return {"task_id": task_id, "message": "任务已启动"}


@app.post("/api/projects/{project_id}/self-heal-run")
async def self_heal_run_pipeline(
    project_id: str,
    request: SelfHealRunRequest,
    background_tasks: BackgroundTasks,
):
    """自动修复项目关键前置条件后继续执行流水线。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    heal_payload = _self_heal_prepare(project_id, project, request)
    code_generation_overrides = request.code_generation_overrides or {}
    task_id = task_manager.create_task(
        project_id,
        heal_payload["project_name"],
        code_generation_overrides=code_generation_overrides,
        project_charter=heal_payload["project_charter"],
    )
    db.update_project(
        project_id,
        {
            "status": "running",
            "progress": 0,
            "project_charter": heal_payload["project_charter"],
        },
    )

    async def run_task():
        await task_manager.run_pipeline(
            task_id,
            heal_payload["steps"],
            lambda pid, updates: db.update_project(pid, updates),
            code_generation_overrides=code_generation_overrides,
            project_charter=heal_payload["project_charter"],
        )

    background_tasks.add_task(run_task)
    return {
        "task_id": task_id,
        "message": "已执行自动修复并启动流水线",
        "actions": heal_payload["actions"],
        "resolved_steps": heal_payload["steps"],
    }


@app.post("/api/projects/batch-self-heal-run")
async def batch_self_heal_run(
    data: BatchSelfHealRunRequest,
    background_tasks: BackgroundTasks,
):
    """批量自动修复后并行执行。"""
    global batch_execution_status
    if batch_execution_status["is_running"]:
        raise HTTPException(status_code=400, detail="批量任务正在运行中")
    if not data.project_ids:
        raise HTTPException(status_code=400, detail="未选择任何项目")

    valid_projects = []
    skipped_projects = []
    for project_id in data.project_ids:
        project = db.get_project(project_id)
        if not project:
            skipped_projects.append({"project_id": project_id, "reason": "项目不存在"})
            continue
        try:
            healed = _self_heal_prepare(project_id, project, data)
            valid_projects.append(
                {
                    "project_id": project_id,
                    "project_name": healed["project_name"],
                    "project_charter": healed["project_charter"],
                    "steps": healed["steps"],
                    "actions": healed["actions"],
                }
            )
        except Exception as e:
            skipped_projects.append(
                {
                    "project_id": project_id,
                    "project_name": str(project.get("name") or ""),
                    "reason": f"自愈失败: {e}",
                }
            )

    if not valid_projects:
        raise HTTPException(status_code=400, detail="没有可执行项目（全部自愈失败或不存在）")

    max_parallel = max(1, min(int(data.max_parallel), 5))
    batch_execution_status = {
        "is_running": True,
        "total": len(valid_projects),
        "completed": 0,
        "failed": 0,
        "current_tasks": [],
        "pending_projects": [p["project_id"] for p in valid_projects],
        "max_parallel": max_parallel,
    }

    async def run_batch():
        global batch_execution_status
        semaphore = asyncio.Semaphore(batch_execution_status["max_parallel"])
        code_generation_overrides = data.code_generation_overrides or {}

        async def run_single_project(item: Dict[str, Any]):
            project_id = item["project_id"]
            project_name = item["project_name"]
            task_id = ""
            async with semaphore:
                try:
                    if project_id in batch_execution_status["pending_projects"]:
                        batch_execution_status["pending_projects"].remove(project_id)

                    task_id = task_manager.create_task(
                        project_id,
                        project_name,
                        code_generation_overrides=code_generation_overrides,
                        project_charter=item["project_charter"],
                    )
                    batch_execution_status["current_tasks"].append(task_id)
                    db.update_project(
                        project_id,
                        {
                            "status": "running",
                            "progress": 0,
                            "project_charter": item["project_charter"],
                        },
                    )
                    await task_manager.run_pipeline(
                        task_id,
                        item["steps"],
                        lambda pid, updates: db.update_project(pid, updates),
                        code_generation_overrides=code_generation_overrides,
                        project_charter=item["project_charter"],
                    )
                    batch_execution_status["completed"] += 1
                except Exception as e:
                    batch_execution_status["failed"] += 1
                    logger.error(f"批量自愈执行失败: {project_name}: {e}")
                    db.update_project(project_id, {"status": "error"})
                finally:
                    if task_id and task_id in batch_execution_status["current_tasks"]:
                        batch_execution_status["current_tasks"].remove(task_id)

        await asyncio.gather(
            *[run_single_project(item) for item in valid_projects],
            return_exceptions=True,
        )
        batch_execution_status["is_running"] = False

    background_tasks.add_task(run_batch)
    return {
        "message": f"已启动批量自动修复并执行：{len(valid_projects)} 个项目",
        "total": len(valid_projects),
        "skipped": len(skipped_projects),
        "skipped_projects": skipped_projects,
        "max_parallel": max_parallel,
        "items": [
            {
                "project_id": item["project_id"],
                "project_name": item["project_name"],
                "actions": item["actions"],
                "resolved_steps": item["steps"],
            }
            for item in valid_projects
        ],
    }


@app.get("/api/tasks/{task_id}", response_model=TaskProgress)
async def get_task_status(task_id: str):
    """获取任务状态"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskProgress(**task)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """请求取消任务（当前步骤完成后停止后续步骤）。"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task_manager.cancel_task(task_id):
        raise HTTPException(status_code=400, detail="任务当前状态不可取消")
    return {"message": "已发送取消请求"}


# ==================== WebSocket 实时进度 ====================

@app.websocket("/ws/tasks/{task_id}")
async def websocket_task_progress(websocket: WebSocket, task_id: str):
    """WebSocket 实时推送任务进度"""
    await websocket.accept()

    task = task_manager.get_task(task_id)
    if not task:
        await websocket.close(code=4004, reason="任务不存在")
        return

    # 创建异步队列用于接收更新
    queue = asyncio.Queue()

    loop = asyncio.get_running_loop()

    def on_update(data):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, data)
        except Exception as e:
            logger.warning(f"WebSocket 回调投递失败: {e}")

    task_manager.register_callback(task_id, on_update)

    try:
        # 先发送当前状态
        await websocket.send_json(task)

        # 持续监听更新
        while True:
            try:
                # 等待更新，超时 30 秒发送心跳
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(data)

                # 如果任务完成或出错，关闭连接
                if data.get("status") in ["completed", "error"]:
                    break

            except asyncio.TimeoutError:
                # 发送心跳
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: {task_id}")
    finally:
        task_manager.unregister_callback(task_id, on_update)


# ==================== 文件下载 API ====================

@app.get("/api/projects/{project_id}/files/{file_type}")
async def download_file(project_id: str, file_type: str):
    """下载项目文件"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    name = project["name"]
    project_dir = OUTPUT_DIR / name
    file_map = {
        "plan": project_dir / "project_plan.json",  # 使用项目专属路径
        "document": first_existing_artifact_path(project_dir, project_name=name, artifact_key="manual_docx")
        or preferred_artifact_path(project_dir, project_name=name, artifact_key="manual_docx"),
        "pdf": first_existing_artifact_path(project_dir, project_name=name, artifact_key="code_pdf")
        or preferred_artifact_path(project_dir, project_name=name, artifact_key="code_pdf"),
    }

    if file_type not in file_map:
        raise HTTPException(status_code=400, detail="无效的文件类型")

    file_path = file_map[file_type]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream"
    )


# ==================== 设置 API ====================

@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings():
    """获取系统设置"""
    config = load_api_config()
    # 隐藏 API Key
    providers = {}
    for name, cfg in config.get("providers", {}).items():
        providers[name] = {
            **cfg,
            "api_key": cfg.get("api_key", "")[:8] + "..." if cfg.get("api_key") else ""
        }
    return SettingsResponse(
        current_provider=config.get("current_provider", "deepseek"),
        providers=providers
    )


@app.put("/api/settings")
async def update_settings(data: SettingsUpdate):
    """更新系统设置"""
    config = load_api_config()

    if data.current_provider:
        config["current_provider"] = data.current_provider

    provider = data.current_provider or config.get("current_provider", "deepseek")

    if provider not in config.get("providers", {}):
        config.setdefault("providers", {})[provider] = {}

    if data.api_key:
        candidate_key = str(data.api_key).strip()
        if candidate_key.endswith("..."):
            logger.info("检测到脱敏 API Key，忽略覆盖写入")
        else:
            config["providers"][provider]["api_key"] = candidate_key
    if data.base_url:
        config["providers"][provider]["base_url"] = data.base_url
    if data.model:
        config["providers"][provider]["model"] = data.model
    if data.max_tokens is not None:
        config["providers"][provider]["max_tokens"] = data.max_tokens
    if data.temperature is not None:
        config["providers"][provider]["temperature"] = data.temperature
    if data.transport:
        config["providers"][provider]["transport"] = data.transport
    if data.api_style:
        config["providers"][provider]["api_style"] = data.api_style
    if data.http_retries is not None:
        config["providers"][provider]["http_retries"] = data.http_retries
    if data.retry_max_tokens_cap is not None:
        config["providers"][provider]["retry_max_tokens_cap"] = data.retry_max_tokens_cap
    if data.use_env_proxy is not None:
        config["providers"][provider]["use_env_proxy"] = data.use_env_proxy
    if data.auto_bypass_proxy_on_error is not None:
        config["providers"][provider]["auto_bypass_proxy_on_error"] = data.auto_bypass_proxy_on_error

    save_api_config(config)
    return {"message": "设置已更新"}


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "3.0.0"}


@app.get("/api/llm/usage")
async def get_llm_usage(max_runs: int = 20):
    """获取 LLM 预算/调用使用量快照。"""
    snapshot = llm_budget.get_runtime_snapshot(max_runs=max_runs)
    return snapshot


# ==================== 账号管理 API ====================

@app.get("/api/accounts", response_model=AccountListResponse)
async def list_accounts():
    """获取所有账号列表"""
    accounts = account_db.get_all_accounts()
    # 不返回密码
    safe_accounts = [
        {k: v for k, v in acc.items() if k != "password"}
        for acc in accounts
    ]
    return AccountListResponse(
        accounts=[AccountResponse(**acc) for acc in safe_accounts],
        total=len(safe_accounts)
    )


@app.post("/api/accounts", response_model=AccountResponse)
async def create_account(data: AccountCreate):
    """创建新账号"""
    account = account_db.create_account(
        username=data.username,
        password=data.password,
        description=data.description
    )
    # 不返回密码
    return AccountResponse(**{k: v for k, v in account.items() if k != "password"})


@app.put("/api/accounts/{account_id}", response_model=AccountResponse)
async def update_account(account_id: str, data: AccountUpdate):
    """更新账号"""
    updates = {k: v for k, v in data.dict(exclude_unset=True).items() if v is not None}
    account = account_db.update_account(account_id, updates)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    # 不返回密码
    return AccountResponse(**{k: v for k, v in account.items() if k != "password"})


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    """删除账号"""
    if not account_db.delete_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"message": "账号已删除"}


# ==================== 提交队列 API ====================

@app.get("/api/submit-queue", response_model=SubmitQueueResponse)
async def get_submit_queue():
    """获取提交队列"""
    items = submit_queue_db.get_queue()
    return SubmitQueueResponse(
        items=[SubmitQueueItem(**item) for item in items],
        total=len(items),
        is_running=submit_queue_db.is_running
    )


@app.post("/api/submit-queue/add")
async def add_to_queue(data: AddToQueueRequest):
    """添加项目到提交队列"""
    added = []
    for project_id in data.project_ids:
        project = db.get_project(project_id)
        if not project:
            continue
        item = submit_queue_db.add_to_queue(project_id, project["name"])
        added.append(item)
    return {"message": f"已添加 {len(added)} 个项目到队列", "items": added}


@app.delete("/api/submit-queue/{item_id}")
async def remove_from_queue(item_id: str):
    """从队列中移除项目"""
    if not submit_queue_db.remove_item(item_id):
        raise HTTPException(status_code=404, detail="队列项不存在")
    return {"message": "已从队列移除"}


@app.post("/api/submit-queue/clear-completed")
async def clear_completed_queue():
    """清除已完成的队列项"""
    count = submit_queue_db.clear_completed()
    return {"message": f"已清除 {count} 个已完成项"}


@app.post("/api/submit-queue/reset")
async def reset_submit_queue():
    """重置提交队列运行状态"""
    submit_queue_db.is_running = False
    logger.info("提交队列运行状态已重置")
    return {"message": "运行状态已重置"}


@app.post("/api/submit-queue/start")
async def start_submit_queue(data: StartSubmitRequest, background_tasks: BackgroundTasks):
    """启动提交队列处理"""
    if submit_queue_db.is_running:
        raise HTTPException(status_code=400, detail="提交任务正在运行中")

    # 获取账号信息（如果指定）
    account = None
    if data.account_id:
        account = account_db.get_account(data.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

    # 获取待提交的项目列表
    queue = submit_queue_db.get_queue()
    pending_items = [item for item in queue if item["status"] == "pending"]

    if not pending_items:
        raise HTTPException(status_code=400, detail="队列中没有待提交的项目")

    eligible_items = []
    blocked_items = []
    for item in pending_items:
        project_name = str(item["project_name"])
        project_dir = OUTPUT_DIR / project_name
        html_dir = BASE_DIR / "temp_build" / project_name / "html"
        passed, report_path, report = run_submission_risk_precheck(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            block_threshold=75,
            enable_auto_fix=True,
            max_fix_rounds=2,
        )
        if not passed:
            score = int(report.get("score") or 0)
            issues = report.get("blocking_issues") or []
            auto_fix = report.get("auto_fix") or {}
            fixed_actions = []
            for round_item in auto_fix.get("rounds") or []:
                for action_result in round_item.get("action_results") or []:
                    if action_result.get("ok") and action_result.get("action"):
                        fixed_actions.append(str(action_result.get("action")))
            fixed_actions = sorted(set(fixed_actions))
            fixed_note = f"；已自动修复: {','.join(fixed_actions)}" if fixed_actions else ""
            reason = f"风险预检未通过(score={score}): {'；'.join(issues[:3])}{fixed_note}"
            submit_queue_db.update_item(
                item["id"],
                {
                    "status": "failed",
                    "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": reason,
                },
            )
            blocked_items.append(
                {
                    "item_id": item["id"],
                    "project_name": project_name,
                    "score": score,
                    "report_path": str(report_path),
                    "auto_fix_attempted": bool(auto_fix.get("attempted")),
                    "auto_fix_fixed": bool(auto_fix.get("fixed")),
                    "auto_fixed_actions": fixed_actions,
                    "remaining_blockers": issues,
                }
            )
            continue
        eligible_items.append(
            {
                **item,
                "gate_report_path": str(report_path),
            }
        )

    if not eligible_items:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"所有待提交项目均被风险预检拦截（{len(blocked_items)} 个）",
                "blocked": len(blocked_items),
                "blocked_items": blocked_items,
            },
        )

    project_names = [item["project_name"] for item in eligible_items]

    # 在后台运行真正的提交任务（使用子进程避免事件循环冲突）
    def process_queue_sync():
        """同步执行提交任务（在子进程中运行）"""
        import subprocess
        import sys

        submit_queue_db.is_running = True
        try:
            # 更新所有待提交项目状态
            for item in eligible_items:
                submit_queue_db.update_item(item["id"], {
                    "status": "submitting",
                    "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

            # 构建账号信息
            account_username = account.get("username", "") if account else ""
            account_password = account.get("password", "") if account else ""
            account_desc = account.get("description", "") if account else ""

            # 构建子进程脚本
            script = f'''
import asyncio
import sys
sys.path.insert(0, r"{BASE_DIR}")

# Windows 上 Playwright 需要 ProactorEventLoop
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path
from modules.auto_submitter import auto_submit_batch

async def run_submit():
    project_names = {project_names}
    output_dir = Path(r"{OUTPUT_DIR}")
    config_path = Path(r"{BASE_DIR}") / "config" / "submit_config.json"

    selected_account = None
    if "{account_username}":
        selected_account = {{
            "username": "{account_username}",
            "password": "{account_password}",
            "description": "{account_desc}"
        }}

    await auto_submit_batch(
        project_names=project_names,
        output_dir=output_dir,
        config_path=config_path,
        selected_account=selected_account
    )

if __name__ == "__main__":
    asyncio.run(run_submit())
    print("SUBMIT_SUCCESS")
'''

            # 运行子进程
            logger.info(f"启动提交子进程，项目: {project_names}")
            proc = subprocess.run(
                [sys.executable, '-c', script],
                capture_output=False,  # 不捕获输出，让用户看到浏览器进度
                text=True,
                cwd=str(BASE_DIR)
            )

            if proc.returncode == 0:
                # 提交成功，更新所有项目状态
                for item in eligible_items:
                    submit_queue_db.update_item(item["id"], {
                        "status": "completed",
                        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                logger.info("批量提交完成")
            else:
                # 提交失败
                for item in eligible_items:
                    submit_queue_db.update_item(item["id"], {
                        "status": "failed",
                        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "error": "提交进程异常退出"
                    })
                logger.error(f"批量提交失败，返回码: {proc.returncode}")

        except Exception as e:
            logger.error(f"提交队列处理异常: {e}")
            for item in eligible_items:
                submit_queue_db.update_item(item["id"], {
                    "status": "failed",
                    "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": str(e)
                })
        finally:
            submit_queue_db.is_running = False

    background_tasks.add_task(process_queue_sync)
    return {
        "message": f"提交队列已启动，共 {len(project_names)} 个项目（拦截 {len(blocked_items)} 个高风险项目）",
        "eligible": len(project_names),
        "blocked": len(blocked_items),
        "eligible_items": [
            {
                "item_id": item["id"],
                "project_name": item["project_name"],
                "report_path": item.get("gate_report_path", ""),
            }
            for item in eligible_items
        ],
        "blocked_items": blocked_items,
    }


# ==================== 签章流程 API ====================

# 全局签章状态
signature_status = SignatureStatus(step="idle")
signature_lock = Lock()


@app.get("/api/signature/status", response_model=SignatureStatus)
async def get_signature_status():
    """获取签章流程状态"""
    return signature_status


@app.post("/api/signature/download")
async def start_signature_download(data: SignatureStepRequest, background_tasks: BackgroundTasks):
    """启动批量下载签章页"""
    global signature_status

    if signature_status.step != "idle":
        raise HTTPException(status_code=400, detail="签章流程正在运行中")

    account = None
    if data.account_id:
        account = account_db.get_account(data.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

    def download_task_sync():
        """同步执行下载任务（在子进程中运行）"""
        global signature_status
        import subprocess
        import sys

        with signature_lock:
            signature_status = SignatureStatus(
                step="downloading",
                message="正在下载签章页...",
                logs=["启动下载任务"]
            )

        try:
            # 构建子进程脚本
            script = f'''
import asyncio
import sys
sys.path.insert(0, r"{BASE_DIR}")

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from modules.signature.download_signs import batch_download_signs

if __name__ == "__main__":
    asyncio.run(batch_download_signs())
    print("DOWNLOAD_SUCCESS")
'''

            logger.info("启动签章页下载子进程")
            proc = subprocess.run(
                [sys.executable, '-c', script],
                capture_output=False,
                text=True,
                cwd=str(BASE_DIR)
            )

            if proc.returncode == 0:
                with signature_lock:
                    signature_status = SignatureStatus(
                        step="idle",
                        progress=100,
                        message="下载完成",
                        logs=["下载完成"]
                    )
            else:
                with signature_lock:
                    signature_status = SignatureStatus(
                        step="idle",
                        message="下载失败",
                        logs=["下载进程异常退出"]
                    )

        except Exception as e:
            logger.error(f"下载签章页失败: {e}")
            with signature_lock:
                signature_status = SignatureStatus(
                    step="idle",
                    message=f"下载失败: {str(e)}",
                    logs=[f"错误: {str(e)}"]
                )

    background_tasks.add_task(download_task_sync)
    return {"message": "下载任务已启动"}


@app.post("/api/signature/sign")
async def start_signature_sign(background_tasks: BackgroundTasks):
    """启动批量签名（签名+扫描效果）"""
    global signature_status

    if signature_status.step != "idle":
        raise HTTPException(status_code=400, detail="签章流程正在运行中")

    def sign_task_sync():
        """同步执行签名任务"""
        global signature_status
        import subprocess
        import sys

        with signature_lock:
            signature_status = SignatureStatus(
                step="signing",
                message="正在签名+扫描效果处理...",
                logs=["启动签名任务"]
            )

        try:
            # 调用 batch_sign_and_scan.py（包含签名和扫描效果）
            script = f'''
import sys
sys.path.insert(0, r"{BASE_DIR}")

from modules.signature.sign_and_scan import batch_sign_and_scan

if __name__ == "__main__":
    success, total, output_dir = batch_sign_and_scan()
    print(f"SIGN_RESULT:{{success}}/{{total}}")
'''

            logger.info("启动签名+扫描子进程")
            proc = subprocess.run(
                [sys.executable, '-c', script],
                capture_output=False,
                text=True,
                cwd=str(BASE_DIR)
            )

            if proc.returncode == 0:
                with signature_lock:
                    signature_status = SignatureStatus(
                        step="idle",
                        progress=100,
                        message="签名+扫描完成",
                        logs=["签名+扫描效果处理完成"]
                    )
            else:
                with signature_lock:
                    signature_status = SignatureStatus(
                        step="idle",
                        message="签名处理失败",
                        logs=["签名进程异常退出"]
                    )

        except Exception as e:
            logger.error(f"签名处理失败: {e}")
            with signature_lock:
                signature_status = SignatureStatus(
                    step="idle",
                    message=f"签名失败: {str(e)}",
                    logs=[f"错误: {str(e)}"]
                )

    background_tasks.add_task(sign_task_sync)
    return {"message": "签名任务已启动"}


@app.post("/api/signature/scan")
async def start_signature_scan(background_tasks: BackgroundTasks):
    """启动批量扫描生效（此步骤已合并到签名步骤中）"""
    global signature_status

    if signature_status.step != "idle":
        raise HTTPException(status_code=400, detail="签章流程正在运行中")

    # 扫描效果已经在签名步骤中一起处理了
    # 这个API保留用于兼容，直接返回成功
    with signature_lock:
        signature_status = SignatureStatus(
            step="idle",
            progress=100,
            message="扫描效果已在签名步骤中完成",
            logs=["扫描效果已在签名步骤中一并处理"]
        )

    return {"message": "扫描效果已在签名步骤中完成"}


@app.post("/api/signature/upload")
async def start_signature_upload(data: SignatureStepRequest, background_tasks: BackgroundTasks):
    """启动批量上传签章"""
    global signature_status

    if signature_status.step != "idle":
        raise HTTPException(status_code=400, detail="签章流程正在运行中")

    account = None
    if data.account_id:
        account = account_db.get_account(data.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")

    def upload_task_sync():
        """同步执行上传任务（在子进程中运行）"""
        global signature_status
        import subprocess
        import sys

        with signature_lock:
            signature_status = SignatureStatus(
                step="uploading",
                message="正在上传签章页...",
                logs=["启动上传任务"]
            )

        try:
            # 构建子进程脚本
            script = f'''
import asyncio
import sys
sys.path.insert(0, r"{BASE_DIR}")

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from modules.signature.upload_signatures import batch_upload_signatures

if __name__ == "__main__":
    asyncio.run(batch_upload_signatures())
    print("UPLOAD_SUCCESS")
'''

            logger.info("启动签章页上传子进程")
            proc = subprocess.run(
                [sys.executable, '-c', script],
                capture_output=False,
                text=True,
                cwd=str(BASE_DIR)
            )

            if proc.returncode == 0:
                with signature_lock:
                    signature_status = SignatureStatus(
                        step="idle",
                        progress=100,
                        message="上传完成",
                        logs=["上传完成"]
                    )
            else:
                with signature_lock:
                    signature_status = SignatureStatus(
                        step="idle",
                        message="上传失败",
                        logs=["上传进程异常退出"]
                    )

        except Exception as e:
            logger.error(f"上传签章页失败: {e}")
            with signature_lock:
                signature_status = SignatureStatus(
                    step="idle",
                    message=f"上传失败: {str(e)}",
                    logs=[f"错误: {str(e)}"]
                )

    background_tasks.add_task(upload_task_sync)
    return {"message": "上传任务已启动"}


@app.post("/api/signature/reset")
async def reset_signature_status():
    """重置签章流程状态"""
    global signature_status
    with signature_lock:
        signature_status = SignatureStatus(step="idle")
    return {"message": "状态已重置"}


@app.get("/api/signature/stats", response_model=SignatureStatsResponse)
async def get_signature_stats():
    """获取签章统计信息"""
    stats = SignatureStatsResponse(
        pending_download=0,
        downloaded=0,
        signed=0,
        scan_effected=0,
    )

    # 当前签章流程目录统计
    sign_dir = BASE_DIR / "签章页"
    signed_dir = BASE_DIR / "已签名"
    final_dir = BASE_DIR / "最终提交"
    submitted_root = OUTPUT_DIR / "已提交"

    if sign_dir.exists():
        stats.downloaded = len(list(sign_dir.glob("*.pdf")))
    if signed_dir.exists():
        stats.signed = len(list(signed_dir.glob("*.pdf")))
    if final_dir.exists():
        stats.scan_effected = len(list(final_dir.glob("*.pdf")))

    # 待下载签章页：已提交项目目录数（与文件级统计并列展示）
    if submitted_root.exists():
        stats.pending_download = len([p for p in submitted_root.iterdir() if p.is_dir()])

    return stats


# ==================== 输出目录扫描 API ====================

@app.post("/api/scan-output", response_model=ScanOutputResponse)
async def scan_output_directory(data: ScanOutputRequest):
    """扫描输出目录并导入项目"""
    found_projects = []
    imported_count = 0

    if not OUTPUT_DIR.exists():
        return ScanOutputResponse(found=0, imported=0, projects=[])

    # 扫描 output 目录下的所有子目录
    for project_dir in OUTPUT_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name

        # 检查是否有关键文件
        has_files = (
            any(p.exists() for p in candidate_artifact_paths(project_dir, project_name=project_name, artifact_key="manual_docx"))
            or any(p.exists() for p in candidate_artifact_paths(project_dir, project_name=project_name, artifact_key="code_pdf"))
            or (project_dir / "aligned_code").exists()
        )

        if has_files:
            found_projects.append(project_name)

            # 如果需要导入且不存在，则创建项目
            if data.import_projects:
                existing = [p for p in db.get_all_projects() if p["name"] == project_name]
                if not existing:
                    db.create_project(project_name)
                    imported_count += 1

    return ScanOutputResponse(
        found=len(found_projects),
        imported=imported_count,
        projects=found_projects
    )


# ==================== 通用设置 API ====================

@app.get("/api/general-settings", response_model=GeneralSettingsResponse)
async def get_general_settings():
    """获取通用设置"""
    settings = _load_general_settings()
    return GeneralSettingsResponse(
        captcha_wait_seconds=int(settings.get("captcha_wait_seconds") or 60),
        output_directory=str(settings.get("output_directory") or str(OUTPUT_DIR)),
        ui_skill_enabled=bool(settings.get("ui_skill_enabled", True)),
        ui_skill_mode=str(settings.get("ui_skill_mode") or "narrative_tool_hybrid"),
        ui_token_policy=str(settings.get("ui_token_policy") or "balanced"),
    )


@app.put("/api/general-settings")
async def update_general_settings(data: GeneralSettingsUpdate):
    """更新通用设置"""
    current = _load_general_settings()
    updated = dict(current)

    if data.captcha_wait_seconds is not None:
        value = int(data.captcha_wait_seconds)
        if value < 5 or value > 600:
            raise HTTPException(status_code=400, detail="captcha_wait_seconds 必须在 5-600 秒之间")
        updated["captcha_wait_seconds"] = value

    if data.output_directory is not None:
        raw = str(data.output_directory or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="output_directory 不能为空")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (BASE_DIR / candidate).resolve()
        candidate.mkdir(parents=True, exist_ok=True)
        updated["output_directory"] = str(candidate)

    if data.ui_skill_enabled is not None:
        updated["ui_skill_enabled"] = bool(data.ui_skill_enabled)

    if data.ui_skill_mode is not None:
        mode = str(data.ui_skill_mode or "").strip()
        allowed_modes = {"narrative_tool_hybrid", "tool_first", "narrative_first"}
        if mode not in allowed_modes:
            raise HTTPException(status_code=400, detail=f"ui_skill_mode 非法，支持: {', '.join(sorted(allowed_modes))}")
        updated["ui_skill_mode"] = mode

    if data.ui_token_policy is not None:
        policy = str(data.ui_token_policy or "").strip()
        allowed_policies = {"economy", "balanced", "quality_first"}
        if policy not in allowed_policies:
            raise HTTPException(status_code=400, detail=f"ui_token_policy 非法，支持: {', '.join(sorted(allowed_policies))}")
        updated["ui_token_policy"] = policy

    _save_general_settings(updated)
    _apply_runtime_general_settings(updated)
    return {
        "message": "设置已更新",
        "settings": {
            "captcha_wait_seconds": int(updated.get("captcha_wait_seconds") or 60),
            "output_directory": str(updated.get("output_directory") or str(OUTPUT_DIR)),
            "ui_skill_enabled": bool(updated.get("ui_skill_enabled", True)),
            "ui_skill_mode": str(updated.get("ui_skill_mode") or "narrative_tool_hybrid"),
            "ui_token_policy": str(updated.get("ui_token_policy") or "balanced"),
        },
    }


# ==================== 项目日志 API ====================

@app.get("/api/projects/{project_id}/logs")
async def get_project_logs(project_id: str):
    """获取项目的历史日志"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    logs = task_manager.get_project_logs(project_id)
    return {"logs": logs, "project_id": project_id}


# ==================== 单步测试 API ====================

@app.post("/api/projects/{project_id}/test/{step}")
async def run_single_step_test(
    project_id: str,
    step: str,
    background_tasks: BackgroundTasks
):
    """
    运行单步测试

    step 可选值: plan, spec, html, screenshot, code, verify, document, pdf, freeze
    """
    valid_steps = ["plan", "spec", "html", "screenshot", "code", "verify", "document", "pdf", "freeze"]
    if step not in valid_steps:
        raise HTTPException(status_code=400, detail=f"无效的步骤: {step}，有效值: {valid_steps}")

    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 创建任务
    task_id = task_manager.create_task(
        project_id,
        project["name"],
        project_charter=project.get("project_charter") or {},
    )

    # 更新项目状态
    db.update_project(project_id, {"status": "running", "progress": 0})

    # 在后台运行单步测试
    async def run_test():
        await task_manager.run_single_step(
            task_id,
            step,
            lambda pid, updates: db.update_project(pid, updates)
        )

    background_tasks.add_task(run_test)

    step_names = {
        "plan": "生成项目规划",
        "spec": "生成可执行规格",
        "html": "生成HTML页面",
        "screenshot": "截图生成",
        "code": "代码生成",
        "verify": "运行验证",
        "document": "说明书生成",
        "pdf": "源码PDF生成",
        "freeze": "冻结提交包",
    }

    return {
        "task_id": task_id,
        "message": f"单步测试已启动: {step_names.get(step, step)}"
    }


# ==================== 静态文件服务 ====================

# 挂载前端静态文件 (生产环境)
frontend_dist = BASE_DIR / "web_ui" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(BASE_DIR / "api")]
    )
