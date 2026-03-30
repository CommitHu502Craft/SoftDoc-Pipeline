"""
API 数据模型 (Pydantic Schemas)
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class ProjectStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    SUBMITTED = "submitted"


class ProjectFiles(BaseModel):
    plan: bool = False
    spec: bool = False
    html: bool = False
    screenshots: bool = False
    code: bool = False
    verify: bool = False
    document: bool = False
    pdf: bool = False
    freeze: bool = False


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    charter: Optional[Dict[str, Any]] = Field(default=None, description="项目章程")


class ProjectResponse(BaseModel):
    id: str
    name: str
    progress: int = 0
    status: ProjectStatus = ProjectStatus.IDLE
    created_at: str
    current_step: Optional[str] = None
    files: ProjectFiles = Field(default_factory=ProjectFiles)
    charter_completed: bool = False
    charter_summary: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    projects: List[ProjectResponse]
    total: int


class PipelineStep(str, Enum):
    PLAN = "plan"
    SPEC = "spec"
    HTML = "html"
    SCREENSHOT = "screenshot"
    CODE = "code"
    VERIFY = "verify"
    DOCUMENT = "document"
    PDF = "pdf"
    FREEZE = "freeze"


class RunPipelineRequest(BaseModel):
    steps: List[PipelineStep] = Field(
        default=[
            PipelineStep.PLAN,
            PipelineStep.SPEC,
            PipelineStep.HTML,
            PipelineStep.SCREENSHOT,
            PipelineStep.CODE,
            PipelineStep.VERIFY,
            PipelineStep.DOCUMENT,
            PipelineStep.PDF,
            PipelineStep.FREEZE,
        ],
        description="要执行的步骤列表"
    )
    code_generation_overrides: Optional[Dict[str, Any]] = Field(
        default=None,
        description="代码质量闸门覆盖配置（写入 project_plan.code_generation_config）"
    )
    project_charter: Optional[Dict[str, Any]] = Field(
        default=None,
        description="项目章程（可覆盖项目已有章程）",
    )


class ProjectCharterResponse(BaseModel):
    project_id: str
    project_name: str
    charter: Dict[str, Any]
    charter_completed: bool
    charter_summary: Optional[Dict[str, Any]] = None
    validation_errors: List[str] = Field(default_factory=list)
    charter_path: str = ""


class ProjectCharterUpdateRequest(BaseModel):
    charter: Dict[str, Any]


class ProjectCharterDraftRequest(BaseModel):
    context_hint: Optional[str] = ""


class BatchCharterDraftRequest(BaseModel):
    project_ids: List[str]
    context_hint: Optional[str] = ""
    force_overwrite: bool = True


class SelfHealRunRequest(BaseModel):
    steps: List[PipelineStep] = Field(
        default=[
            PipelineStep.PLAN,
            PipelineStep.SPEC,
            PipelineStep.HTML,
            PipelineStep.SCREENSHOT,
            PipelineStep.CODE,
            PipelineStep.VERIFY,
            PipelineStep.DOCUMENT,
            PipelineStep.PDF,
            PipelineStep.FREEZE,
        ],
        description="自愈后继续执行的步骤",
    )
    context_hint: Optional[str] = ""
    auto_confirm_spec: bool = True
    code_generation_overrides: Optional[Dict[str, Any]] = Field(
        default=None,
        description="代码质量闸门覆盖配置（写入 project_plan.code_generation_config）",
    )


class BatchSelfHealRunRequest(SelfHealRunRequest):
    project_ids: List[str]
    max_parallel: int = 2


class SubmissionRiskCheckRequest(BaseModel):
    block_threshold: int = 75
    enable_auto_fix: bool = True
    max_fix_rounds: int = 2


class SubmissionRiskResponse(BaseModel):
    project_id: str
    project_name: str
    report_path: str = ""
    report: Dict[str, Any]


class UiSkillStudioRequest(BaseModel):
    intent_text: str = ""
    domain: Optional[str] = ""
    ui_mode: Optional[str] = ""
    token_policy: Optional[str] = ""
    page_count: Optional[int] = None
    feature_preferences: List[str] = Field(default_factory=list)
    preset_template: Optional[str] = ""
    apply_to_plan: bool = True
    rebuild_ui_skill: bool = True


class UiSkillPolicyAutofixRequest(BaseModel):
    max_rounds: int = 2
    block_threshold: int = 75


class UiSkillPolicyAutofixResponse(BaseModel):
    project_id: str
    project_name: str
    attempted: bool = False
    fixed: bool = False
    policy_actions: List[str] = Field(default_factory=list)
    remaining_blockers: List[str] = Field(default_factory=list)
    skill_autorepair_report_path: str = ""
    submission_risk_report_path: str = ""
    final_report: Dict[str, Any] = Field(default_factory=dict)


class UiSkillStudioResponse(BaseModel):
    project_id: str
    project_name: str
    studio_plan_path: str = ""
    runtime_skill_override_path: str = ""
    actions: List[str] = Field(default_factory=list)
    decisions: Dict[str, Any] = Field(default_factory=dict)
    ui_skill_artifacts: Dict[str, Any] = Field(default_factory=dict)
    spec_path: str = ""
    spec_digest: str = ""
    spec_review_status: str = ""
    override_validation: Dict[str, Any] = Field(default_factory=dict)


class SpecReviewStatusResponse(BaseModel):
    approved: bool = False
    review_status: str = "missing_spec"
    spec_digest: str = ""
    status_path: str = ""
    guide_path: str = ""
    reviewer: str = ""
    reviewed_at: str = ""


class SpecReviewApproveRequest(BaseModel):
    reviewer: Optional[str] = "api-user"


class LogLevel(str, Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogEntry(BaseModel):
    id: str
    timestamp: str
    level: LogLevel
    message: str


class TaskProgress(BaseModel):
    task_id: str
    project_id: str
    status: str  # running, completed, error
    progress: int
    current_step: Optional[str] = None
    message: Optional[str] = None
    logs: List[LogEntry] = []


class SettingsUpdate(BaseModel):
    current_provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    transport: Optional[str] = None
    api_style: Optional[str] = None
    http_retries: Optional[int] = None
    retry_max_tokens_cap: Optional[int] = None
    use_env_proxy: Optional[bool] = None
    auto_bypass_proxy_on_error: Optional[bool] = None


class SettingsResponse(BaseModel):
    current_provider: str
    providers: Dict[str, Any]


class SubmitItem(BaseModel):
    id: str
    project_name: str
    status: str  # pending, submitting, completed, failed
    added_at: str
    error: Optional[str] = None


# ==================== 账号管理模型 ====================

class AccountBase(BaseModel):
    username: str
    password: str = ""
    description: str = ""


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None


class AccountResponse(BaseModel):
    id: str
    username: str
    description: str
    created_at: str


class AccountListResponse(BaseModel):
    accounts: List[AccountResponse]
    total: int


# ==================== 提交队列模型 ====================

class SubmitQueueItem(BaseModel):
    id: str
    project_id: str
    project_name: str
    status: str  # pending, submitting, completed, failed
    added_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class SubmitQueueResponse(BaseModel):
    items: List[SubmitQueueItem]
    total: int
    is_running: bool = False


class AddToQueueRequest(BaseModel):
    project_ids: List[str]


class StartSubmitRequest(BaseModel):
    account_id: Optional[str] = None


# ==================== 签章流程模型 ====================

class SignatureStatus(BaseModel):
    step: str  # idle, downloading, signing, scanning, uploading, completed
    progress: int = 0
    total_files: int = 0
    processed_files: int = 0
    current_file: Optional[str] = None
    message: Optional[str] = None
    logs: List[str] = []


class SignatureStepRequest(BaseModel):
    account_id: Optional[str] = None


class SignatureStatsResponse(BaseModel):
    pending_download: int = 0
    downloaded: int = 0
    signed: int = 0
    scan_effected: int = 0


# ==================== 输出目录扫描模型 ====================

class ScanOutputRequest(BaseModel):
    import_projects: bool = True


class ScanOutputResponse(BaseModel):
    found: int
    imported: int
    projects: List[str]


# ==================== 通用设置模型 ====================

class GeneralSettingsUpdate(BaseModel):
    captcha_wait_seconds: Optional[int] = None
    output_directory: Optional[str] = None
    ui_skill_enabled: Optional[bool] = None
    ui_skill_mode: Optional[str] = None
    ui_token_policy: Optional[str] = None


class GeneralSettingsResponse(BaseModel):
    captcha_wait_seconds: int = 60
    output_directory: str = ""
    ui_skill_enabled: bool = True
    ui_skill_mode: str = "narrative_tool_hybrid"
    ui_token_policy: str = "balanced"
