/**
 * API 服务层 - 封装所有后端接口调用
 */

// 开发环境使用 vite 代理，生产环境使用相对路径
const API_BASE = '';

function resolveWsBase(): string {
  if (API_BASE.startsWith('http://')) {
    return API_BASE.replace('http://', 'ws://');
  }
  if (API_BASE.startsWith('https://')) {
    return API_BASE.replace('https://', 'wss://');
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
}

// 通用请求函数（带超时控制）
async function request<T>(url: string, options?: RequestInit & { timeout?: number }): Promise<T> {
  const { timeout = 30000, ...fetchOptions } = options || {}; // 默认30秒超时

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(`${API_BASE}${url}`, {
      headers: {
        'Content-Type': 'application/json',
        ...fetchOptions?.headers,
      },
      signal: controller.signal,
      ...fetchOptions,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: '请求失败' }));
      const detail = error?.detail;
      const detailMessage = typeof detail === 'string'
        ? detail
        : (detail?.message ? String(detail.message) : JSON.stringify(detail || {}));
      throw new Error(detailMessage || `HTTP ${response.status}`);
    }

    return response.json();
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error('请求超时，服务器响应缓慢');
    }
    throw error;
  }
}

// ==================== 项目管理 API ====================

export interface Project {
  id: string;
  name: string;
  progress: number;
  status: 'idle' | 'running' | 'completed' | 'error' | 'submitted';
  created_at: string;
  current_step?: string;
  charter_completed?: boolean;
  charter_summary?: {
    business_scope?: string;
    role_count?: number;
    flow_count?: number;
    nfr_count?: number;
    acceptance_count?: number;
  };
  files: {
    plan: boolean;
    spec?: boolean;
    html: boolean;
    screenshots: boolean;
    code: boolean;
    verify?: boolean;
    document: boolean;
    pdf: boolean;
    freeze?: boolean;
  };
}

export interface ProjectListResponse {
  projects: Project[];
  total: number;
}

export interface ProjectCharter {
  project_name?: string;
  business_scope: string;
  user_roles: Array<{ name: string; responsibility?: string }>;
  core_flows: Array<{ name: string; steps: string[]; success_criteria?: string }>;
  non_functional_constraints: string[];
  acceptance_criteria: string[];
}

export interface SpecReviewStatus {
  approved: boolean;
  review_status: 'missing_spec' | 'pending' | 'approved' | string;
  spec_digest: string;
  status_path: string;
  guide_path: string;
  reviewer?: string;
  reviewed_at?: string;
}

export interface ProjectCharterResponse {
  project_id: string;
  project_name: string;
  charter: ProjectCharter;
  charter_completed: boolean;
  charter_summary?: Project['charter_summary'];
  validation_errors: string[];
  charter_path: string;
}

export interface SubmissionRiskPayload {
  project_name: string;
  generated_at: string;
  gate_mode?: string;
  score: number;
  block_threshold: number;
  risk_level: 'low' | 'medium' | 'high' | string;
  should_block_submission: boolean;
  hard_gate?: {
    passed: boolean;
    check_order: string[];
    failed_checks: string[];
  };
  failed_checks?: string[];
  blocking_issues: string[];
  recommendations: string[];
  auto_fix_actions?: string[];
  auto_fix?: {
    attempted: boolean;
    fixed: boolean;
    max_rounds: number;
    rounds: Array<Record<string, any>>;
  };
  checks: Record<string, any>;
}

export interface SubmissionRiskResponse {
  project_id: string;
  project_name: string;
  report_path: string;
  report: SubmissionRiskPayload;
}

export const projectApi = {
  // 获取所有项目
  list: () => request<ProjectListResponse>('/api/projects'),

  // 创建项目
  create: (name: string, charter?: ProjectCharter) =>
    request<Project>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name, charter }),
    }),

  // 批量创建项目
  createBatch: (names: string[]) =>
    request<{ message: string; projects: Project[] }>('/api/projects/batch', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),

  // 批量并行执行
  batchRun: (
    projectIds: string[],
    maxParallel: number = 2,
    steps?: PipelineStep[],
    codeGenerationOverrides?: Record<string, any>
  ) =>
    request<{ message: string; total: number; max_parallel: number }>('/api/projects/batch-run', {
      method: 'POST',
      body: JSON.stringify({
        project_ids: projectIds,
        max_parallel: maxParallel,
        steps: steps || DEFAULT_PIPELINE_STEPS,
        code_generation_overrides: codeGenerationOverrides || undefined,
      }),
    }),

  // 获取批量执行状态
  getBatchStatus: () =>
    request<{
      is_running: boolean;
      total: number;
      completed: number;
      failed: number;
      current_tasks: string[];
      pending_projects: string[];
      max_parallel: number;
    }>('/api/projects/batch-status'),

  // 停止批量执行
  stopBatch: () =>
    request<{ message: string }>('/api/projects/batch-stop', { method: 'POST' }),

  // 获取单个项目
  get: (id: string) => request<Project>(`/api/projects/${id}`),

  // 删除项目
  delete: (id: string) =>
    request<{ message: string }>(`/api/projects/${id}`, { method: 'DELETE' }),

  // 读取章程
  getCharter: (id: string) =>
    request<ProjectCharterResponse>(`/api/projects/${id}/charter`),

  // 更新章程
  updateCharter: (id: string, charter: ProjectCharter) =>
    request<ProjectCharterResponse>(`/api/projects/${id}/charter`, {
      method: 'PUT',
      body: JSON.stringify({ charter }),
    }),

  // AI草拟章程
  draftCharter: (id: string, context_hint: string = '') =>
    request<ProjectCharterResponse>(`/api/projects/${id}/charter/draft`, {
      method: 'POST',
      body: JSON.stringify({ context_hint }),
    }),

  // 批量AI草拟章程
  batchDraftCharter: (
    project_ids: string[],
    context_hint: string = '',
    force_overwrite: boolean = true
  ) =>
    request<{
      message: string;
      total: number;
      updated: number;
      skipped: number;
      failed: number;
      items: Array<Record<string, any>>;
    }>('/api/projects/batch-charter/draft', {
      method: 'POST',
      body: JSON.stringify({ project_ids, context_hint, force_overwrite }),
    }),

  // 单项目自动修复并继续
  selfHealRun: (
    id: string,
    options?: {
      steps?: PipelineStep[];
      context_hint?: string;
      auto_confirm_spec?: boolean;
      code_generation_overrides?: Record<string, any>;
    }
  ) =>
    request<{
      task_id: string;
      message: string;
      actions: string[];
      resolved_steps: PipelineStep[];
    }>(`/api/projects/${id}/self-heal-run`, {
      method: 'POST',
      body: JSON.stringify({
        steps: options?.steps || DEFAULT_PIPELINE_STEPS,
        context_hint: options?.context_hint || '',
        auto_confirm_spec: options?.auto_confirm_spec ?? true,
        code_generation_overrides: options?.code_generation_overrides,
      }),
    }),

  // 批量自动修复并继续
  batchSelfHealRun: (
    project_ids: string[],
    max_parallel: number = 2,
    options?: {
      steps?: PipelineStep[];
      context_hint?: string;
      auto_confirm_spec?: boolean;
      code_generation_overrides?: Record<string, any>;
    }
  ) =>
    request<{
      message: string;
      total: number;
      skipped: number;
      skipped_projects: Array<Record<string, any>>;
      max_parallel: number;
      items: Array<Record<string, any>>;
    }>('/api/projects/batch-self-heal-run', {
      method: 'POST',
      body: JSON.stringify({
        project_ids,
        max_parallel,
        steps: options?.steps || DEFAULT_PIPELINE_STEPS,
        context_hint: options?.context_hint || '',
        auto_confirm_spec: options?.auto_confirm_spec ?? true,
        code_generation_overrides: options?.code_generation_overrides,
      }),
    }),

  // 获取风险预检结果（不存在则后端自动生成）
  getSubmissionRisk: (id: string) =>
    request<SubmissionRiskResponse>(`/api/projects/${id}/submission-risk`),

  // 执行风险预检
  checkSubmissionRisk: (
    id: string,
    options: {
      block_threshold?: number;
      enable_auto_fix?: boolean;
      max_fix_rounds?: number;
    } = {}
  ) =>
    request<SubmissionRiskResponse>(`/api/projects/${id}/submission-risk/check`, {
      method: 'POST',
      body: JSON.stringify({
        block_threshold: options.block_threshold ?? 75,
        enable_auto_fix: options.enable_auto_fix ?? true,
        max_fix_rounds: options.max_fix_rounds ?? 2,
      }),
    }),

  // 获取 UI 技能规划产物
  getUiSkillPlan: (id: string) =>
    request<UiSkillPlanResponse>(`/api/projects/${id}/ui-skill/plan`),

  // 生成或重建 UI 技能规划产物
  buildUiSkillPlan: (id: string, force: boolean = false) =>
    request<{ message: string; report: Record<string, any> }>(
      `/api/projects/${id}/ui-skill/plan${force ? '?force=true' : ''}`,
      {
        method: 'POST',
      }
    ),

  // 强制重建 UI 技能规划产物
  rebuildUiSkillPlan: (id: string) =>
    request<{ message: string; report: Record<string, any> }>(`/api/projects/${id}/ui-skill/plan?force=true`, {
      method: 'POST',
    }),

  // 获取 Skill Studio 决策记录
  getUiSkillStudio: (id: string) =>
    request<UiSkillStudioResponse>(`/api/projects/${id}/ui-skill/studio`),

  // 运行 Skill Studio（自然语言接管规划）
  runUiSkillStudio: (
    id: string,
    options: {
      intent_text: string;
      domain?: string;
      ui_mode?: string;
      token_policy?: string;
      page_count?: number;
      feature_preferences?: string[];
      preset_template?: string;
      apply_to_plan?: boolean;
      rebuild_ui_skill?: boolean;
    }
  ) =>
    request<UiSkillStudioResponse>(`/api/projects/${id}/ui-skill/studio`, {
      method: 'POST',
      body: JSON.stringify({
        intent_text: options.intent_text,
        domain: options.domain || '',
        ui_mode: options.ui_mode || '',
        token_policy: options.token_policy || '',
        page_count: options.page_count ?? null,
        feature_preferences: options.feature_preferences || [],
        preset_template: options.preset_template || '',
        apply_to_plan: options.apply_to_plan ?? true,
        rebuild_ui_skill: options.rebuild_ui_skill ?? true,
      }),
    }),

  // 执行策略建议自动修复（仅运行时技能相关）
  runUiSkillPolicyAutofix: (
    id: string,
    options: {
      max_rounds?: number;
      block_threshold?: number;
    } = {}
  ) =>
    request<UiSkillPolicyAutofixResponse>(`/api/projects/${id}/ui-skill/policy-autofix`, {
      method: 'POST',
      body: JSON.stringify({
        max_rounds: options.max_rounds ?? 2,
        block_threshold: options.block_threshold ?? 75,
      }),
    }),

  // 获取项目历史日志
  getLogs: (id: string) =>
    request<{ logs: TaskProgress['logs']; project_id: string }>(`/api/projects/${id}/logs`),

  // 运行单步测试
  runSingleStep: (id: string, step: PipelineStep) =>
    request<{ task_id: string; message: string }>(`/api/projects/${id}/test/${step}`, {
      method: 'POST',
    }),
};

export const specReviewApi = {
  // 获取规格评审状态
  getStatus: (projectId: string) =>
    request<SpecReviewStatus>(`/api/projects/${projectId}/spec-review`),

  // 确认规格
  approve: (projectId: string, reviewer: string = 'web-user') =>
    request<SpecReviewStatus>(`/api/projects/${projectId}/spec-review/approve`, {
      method: 'POST',
      body: JSON.stringify({ reviewer }),
    }),
};

// ==================== 流水线任务 API ====================

export type PipelineStep =
  | 'plan'
  | 'spec'
  | 'html'
  | 'screenshot'
  | 'code'
  | 'verify'
  | 'document'
  | 'pdf'
  | 'freeze';

export const DEFAULT_PIPELINE_STEPS: PipelineStep[] = [
  'plan',
  'spec',
  'html',
  'screenshot',
  'code',
  'verify',
  'document',
  'pdf',
  'freeze',
];

export interface TaskProgress {
  task_id: string;
  project_id: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  progress: number;
  current_step?: string;
  message?: string;
  logs: Array<{
    id: string;
    timestamp: string;
    level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
    message: string;
  }>;
}

export const pipelineApi = {
  // 启动流水线
  run: (
    projectId: string,
    options?: {
      steps?: PipelineStep[];
      code_generation_overrides?: Record<string, any>;
      project_charter?: ProjectCharter;
    }
  ) =>
    request<{ task_id: string; message: string }>(`/api/projects/${projectId}/run`, {
      method: 'POST',
      body: JSON.stringify({
        steps: options?.steps || DEFAULT_PIPELINE_STEPS,
        code_generation_overrides: options?.code_generation_overrides,
        project_charter: options?.project_charter,
      }),
    }),

  // 获取任务状态
  getTask: (taskId: string) => request<TaskProgress>(`/api/tasks/${taskId}`),

  // 取消任务（当前步骤完成后停止）
  cancelTask: (taskId: string) =>
    request<{ message: string }>(`/api/tasks/${taskId}/cancel`, { method: 'POST' }),

  // WebSocket 连接
  connectWebSocket: (taskId: string, onMessage: (data: TaskProgress) => void): WebSocket => {
    const wsUrl = resolveWsBase();
    const ws = new WebSocket(`${wsUrl}/ws/tasks/${taskId}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type !== 'heartbeat') {
        onMessage(data);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    return ws;
  },
};

export interface LlmUsageSnapshot {
  generated_at: number;
  config: {
    total_calls: number;
    total_failures: number;
    stages: Record<string, number>;
    cache_ttl_seconds: number;
    cache_max_entries: number;
  };
  cache: {
    entries: number;
    max_entries: number;
  };
  summary: {
    active_runs: number;
    total_calls: number;
    total_failures: number;
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    stage_calls?: Record<string, number>;
    stage_failures?: Record<string, number>;
    stage_input_tokens?: Record<string, number>;
    stage_output_tokens?: Record<string, number>;
    stage_total_tokens?: Record<string, number>;
  };
  provider_summary?: Record<
    string,
    {
      calls: number;
      failures: number;
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      models: Record<string, number>;
      api_styles: Record<string, number>;
    }
  >;
  runs: Array<{
    run_id: string;
    started_at: number;
    total_calls: number;
    total_failures: number;
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    stage_calls: Record<string, number>;
    stage_failures: Record<string, number>;
    stage_input_tokens?: Record<string, number>;
    stage_output_tokens?: Record<string, number>;
    stage_total_tokens?: Record<string, number>;
    provider_calls?: Record<string, number>;
    provider_failures?: Record<string, number>;
    provider_input_tokens?: Record<string, number>;
    provider_output_tokens?: Record<string, number>;
    provider_total_tokens?: Record<string, number>;
    provider_models?: Record<string, Record<string, number>>;
    provider_api_styles?: Record<string, Record<string, number>>;
    exhausted_by_failures?: boolean;
  }>;
}

export const usageApi = {
  getLlmUsage: (max_runs: number = 20) =>
    request<LlmUsageSnapshot>(`/api/llm/usage?max_runs=${max_runs}`),
};

// ==================== 文件下载 API ====================

export const fileApi = {
  // 获取下载链接
  getDownloadUrl: (projectId: string, fileType: 'plan' | 'document' | 'pdf') =>
    `${API_BASE}/api/projects/${projectId}/files/${fileType}`,

  // 触发下载
  download: async (projectId: string, fileType: 'plan' | 'document' | 'pdf') => {
    const url = fileApi.getDownloadUrl(projectId, fileType);
    const link = document.createElement('a');
    link.href = url;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  },
};

// ==================== 设置 API ====================

export interface Settings {
  current_provider: string;
  providers: Record<string, {
    api_key: string;
    base_url: string;
    model: string;
    max_tokens?: number;
    temperature?: number;
    transport?: string;
    api_style?: string;
    http_retries?: number;
    retry_max_tokens_cap?: number;
    use_env_proxy?: boolean;
    auto_bypass_proxy_on_error?: boolean;
  }>;
}

export const settingsApi = {
  // 获取设置
  get: () => request<Settings>('/api/settings'),

  // 更新设置
  update: (data: {
    current_provider?: string;
    api_key?: string;
    base_url?: string;
    model?: string;
    max_tokens?: number;
    temperature?: number;
    transport?: string;
    api_style?: string;
    http_retries?: number;
    retry_max_tokens_cap?: number;
    use_env_proxy?: boolean;
    auto_bypass_proxy_on_error?: boolean;
  }) =>
    request<{ message: string }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
};

// ==================== 健康检查 ====================

export const healthApi = {
  check: () => request<{ status: string; version: string }>('/api/health'),
};

// ==================== 账号管理 API ====================

export interface Account {
  id: string;
  username: string;
  description: string;
  created_at: string;
}

export interface AccountListResponse {
  accounts: Account[];
  total: number;
}

export const accountApi = {
  // 获取所有账号
  list: () => request<AccountListResponse>('/api/accounts'),

  // 创建账号
  create: (data: { username: string; password: string; description?: string }) =>
    request<Account>('/api/accounts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 更新账号
  update: (id: string, data: { username?: string; password?: string; description?: string }) =>
    request<Account>(`/api/accounts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // 删除账号
  delete: (id: string) =>
    request<{ message: string }>(`/api/accounts/${id}`, { method: 'DELETE' }),
};

// ==================== 提交队列 API ====================

export interface SubmitQueueItem {
  id: string;
  project_id: string;
  project_name: string;
  status: 'pending' | 'submitting' | 'completed' | 'failed';
  added_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface SubmitQueueResponse {
  items: SubmitQueueItem[];
  total: number;
  is_running: boolean;
}

export interface SubmitQueueStartBlockedItem {
  item_id: string;
  project_name: string;
  score: number;
  report_path: string;
  auto_fix_attempted?: boolean;
  auto_fix_fixed?: boolean;
  auto_fixed_actions?: string[];
  remaining_blockers?: string[];
}

export interface SubmitQueueStartResponse {
  message: string;
  eligible: number;
  blocked: number;
  eligible_items?: Array<{
    item_id: string;
    project_name: string;
    report_path?: string;
  }>;
  blocked_items: SubmitQueueStartBlockedItem[];
}

export const submitQueueApi = {
  // 获取队列
  getQueue: () => request<SubmitQueueResponse>('/api/submit-queue'),

  // 添加到队列
  addToQueue: (project_ids: string[]) =>
    request<{ message: string; items: SubmitQueueItem[] }>('/api/submit-queue/add', {
      method: 'POST',
      body: JSON.stringify({ project_ids }),
    }),

  // 从队列移除
  removeFromQueue: (item_id: string) =>
    request<{ message: string }>(`/api/submit-queue/${item_id}`, { method: 'DELETE' }),

  // 清除已完成
  clearCompleted: () =>
    request<{ message: string }>('/api/submit-queue/clear-completed', { method: 'POST' }),

  // 重置运行状态
  reset: () =>
    request<{ message: string }>('/api/submit-queue/reset', { method: 'POST' }),

  // 启动提交
  startSubmit: (account_id?: string) =>
    request<SubmitQueueStartResponse>('/api/submit-queue/start', {
      method: 'POST',
      body: JSON.stringify({ account_id }),
    }),
};

// ==================== 签章流程 API ====================

export interface SignatureStatus {
  step: 'idle' | 'downloading' | 'signing' | 'scanning' | 'uploading' | 'completed';
  progress: number;
  total_files: number;
  processed_files: number;
  current_file?: string;
  message?: string;
  logs: string[];
}

export interface SignatureStats {
  pending_download: number;
  downloaded: number;
  signed: number;
  scan_effected: number;
}

export const signatureApi = {
  // 获取状态
  getStatus: () => request<SignatureStatus>('/api/signature/status'),

  // 获取统计
  getStats: () => request<SignatureStats>('/api/signature/stats'),

  // 批量下载签章页
  download: (account_id?: string) =>
    request<{ message: string }>('/api/signature/download', {
      method: 'POST',
      body: JSON.stringify({ account_id }),
    }),

  // 批量签名
  sign: () =>
    request<{ message: string }>('/api/signature/sign', { method: 'POST' }),

  // 批量扫描生效
  scan: () =>
    request<{ message: string }>('/api/signature/scan', { method: 'POST' }),

  // 批量上传
  upload: (account_id?: string) =>
    request<{ message: string }>('/api/signature/upload', {
      method: 'POST',
      body: JSON.stringify({ account_id }),
    }),

  // 重置状态
  reset: () =>
    request<{ message: string }>('/api/signature/reset', { method: 'POST' }),
};

// ==================== 输出目录扫描 API ====================

export interface ScanOutputResponse {
  found: number;
  imported: number;
  projects: string[];
}

export const scanApi = {
  // 扫描输出目录
  scanOutput: (import_projects: boolean = true) =>
    request<ScanOutputResponse>('/api/scan-output', {
      method: 'POST',
      body: JSON.stringify({ import_projects }),
    }),
};

// ==================== 通用设置 API ====================

export interface GeneralSettings {
  captcha_wait_seconds: number;
  output_directory: string;
  ui_skill_enabled: boolean;
  ui_skill_mode: 'narrative_tool_hybrid' | 'tool_first' | 'narrative_first' | string;
  ui_token_policy: 'economy' | 'balanced' | 'quality_first' | string;
}

export const generalSettingsApi = {
  // 获取设置
  get: () => request<GeneralSettings>('/api/general-settings'),

  // 更新设置
  update: (data: {
    captcha_wait_seconds?: number;
    output_directory?: string;
    ui_skill_enabled?: boolean;
    ui_skill_mode?: string;
    ui_token_policy?: string;
  }) =>
    request<{ message: string }>('/api/general-settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
};

export interface UiSkillPlanResponse {
  project_id: string;
  project_name: string;
  profile_path: string;
  blueprint_path: string;
  contract_path: string;
  runtime_skill_path?: string;
  runtime_rule_graph_path?: string;
  skill_compliance_report_path?: string;
  skill_autorepair_report_path?: string;
  skill_policy_report_path?: string;
  report_path: string;
  profile: Record<string, any>;
  blueprint_summary: Record<string, any>;
  report: Record<string, any>;
}

export interface UiSkillStudioResponse {
  project_id: string;
  project_name: string;
  studio_plan_path: string;
  runtime_skill_override_path: string;
  actions: string[];
  decisions: Record<string, any>;
  ui_skill_artifacts: Record<string, any>;
  spec_path?: string;
  spec_digest?: string;
  spec_review_status?: string;
  override_validation?: Record<string, any>;
}

export interface UiSkillPolicyAutofixResponse {
  project_id: string;
  project_name: string;
  attempted: boolean;
  fixed: boolean;
  policy_actions: string[];
  remaining_blockers: string[];
  skill_autorepair_report_path: string;
  submission_risk_report_path: string;
  final_report: Record<string, any>;
}
