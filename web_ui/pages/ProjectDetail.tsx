import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Square, RotateCw, CheckCircle2, Circle, Loader2, Download, AlertCircle, TestTube2, Wand2, Save, ShieldCheck, Sparkles } from 'lucide-react';
import { Button, Card, ProgressBar, Badge, Modal } from '../components/UI';
import { LogViewer } from '../components/LogViewer';
import { LogEntry } from '../types';
import { projectApi, pipelineApi, fileApi, specReviewApi, Project, TaskProgress, PipelineStep, SpecReviewStatus, SubmissionRiskResponse, UiSkillPlanResponse, UiSkillStudioResponse } from '../api';

const STEPS = [
  { id: 'plan' as PipelineStep, label: '生成规划', key: 'plan' },
  { id: 'spec' as PipelineStep, label: '生成规格', key: 'spec' },
  { id: 'html' as PipelineStep, label: '生成HTML', key: 'html' },
  { id: 'screenshot' as PipelineStep, label: '截取屏幕', key: 'screenshots' },
  { id: 'code' as PipelineStep, label: '处理代码', key: 'code' },
  { id: 'verify' as PipelineStep, label: '运行验证', key: 'verify' },
  { id: 'document' as PipelineStep, label: '生成文档', key: 'document' },
  { id: 'pdf' as PipelineStep, label: '生成PDF', key: 'pdf' },
  { id: 'freeze' as PipelineStep, label: '冻结提交包', key: 'freeze' },
];

const IMPLEMENTATION_STEPS: PipelineStep[] = ['code', 'verify', 'document', 'pdf', 'freeze'];
const POST_SPEC_PIPELINE_STEPS: PipelineStep[] = ['html', 'screenshot', 'code', 'verify', 'document', 'pdf', 'freeze'];
const PLAN_SPEC_STEPS: PipelineStep[] = ['plan', 'spec'];
const FULL_PIPELINE_STEPS: PipelineStep[] = [...PLAN_SPEC_STEPS, ...POST_SPEC_PIPELINE_STEPS];
const STUDIO_PRESETS = ['IDE风格', '运营监控', '知识检索', '管理系统'];
const STUDIO_FEATURES = ['工单流转', '搜索筛选', '状态变更', '多图表', '批量操作', '回放留痕'];

export const ProjectDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskProgress, setTaskProgress] = useState<TaskProgress | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [runningStep, setRunningStep] = useState<PipelineStep | null>(null); // 正在运行的单步
  const [specReview, setSpecReview] = useState<SpecReviewStatus | null>(null);
  const [approvingSpec, setApprovingSpec] = useState(false);
  const [charterText, setCharterText] = useState('');
  const [savingCharter, setSavingCharter] = useState(false);
  const [draftingCharter, setDraftingCharter] = useState(false);
  const [selfHealing, setSelfHealing] = useState(false);
  const [riskChecking, setRiskChecking] = useState(false);
  const [riskReport, setRiskReport] = useState<SubmissionRiskResponse | null>(null);
  const [uiSkillPlan, setUiSkillPlan] = useState<UiSkillPlanResponse | null>(null);
  const [uiSkillLoading, setUiSkillLoading] = useState(false);
  const [uiSkillRebuilding, setUiSkillRebuilding] = useState(false);
  const [uiSkillStudioResult, setUiSkillStudioResult] = useState<UiSkillStudioResponse | null>(null);
  const [uiSkillStudioRunning, setUiSkillStudioRunning] = useState(false);
  const [uiPolicyFixing, setUiPolicyFixing] = useState(false);
  const [studioModalOpen, setStudioModalOpen] = useState(false);
  const [studioForm, setStudioForm] = useState({
    intent_text: '',
    domain: 'workflow',
    ui_mode: 'narrative_tool_hybrid',
    token_policy: 'balanced',
    page_count: 6,
    preset_template: 'IDE风格',
    feature_preferences: ['工单流转', '搜索筛选', '状态变更'],
  });

  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshProjectAndSpec = async (projectId: string) => {
    const [projectData, specStatus] = await Promise.all([
      projectApi.get(projectId),
      specReviewApi.getStatus(projectId).catch(() => null),
    ]);
    setProject(projectData);
    if (specStatus) {
      setSpecReview(specStatus);
    }
    setIsRunning(projectData.status === 'running');
  };

  // 加载项目详情
  const closeTaskSocket = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  useEffect(() => {
    if (!id) return;

    const loadProject = async () => {
      try {
        setLoading(true);
        await refreshProjectAndSpec(id);
        try {
          const charterRes = await projectApi.getCharter(id);
          setCharterText(JSON.stringify(charterRes.charter, null, 2));
        } catch (e) {
          console.warn('load charter failed', e);
        }
        try {
          const risk = await projectApi.getSubmissionRisk(id);
          setRiskReport(risk);
        } catch (e) {
          console.warn('load risk report failed', e);
        }
        try {
          setUiSkillLoading(true);
          const plan = await projectApi.getUiSkillPlan(id);
          setUiSkillPlan(plan);
        } catch (e) {
          console.warn('load ui skill plan failed', e);
        } finally {
          setUiSkillLoading(false);
        }
        try {
          const studio = await projectApi.getUiSkillStudio(id);
          setUiSkillStudioResult(studio);
        } catch (e) {
          console.warn('load ui skill studio failed', e);
        }

        // 加载历史日志
        try {
          const logsData = await projectApi.getLogs(id);
          if (logsData.logs && logsData.logs.length > 0) {
            setLogs(logsData.logs);
          }
        } catch (e) {
          console.log('No previous logs');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载失败');
      } finally {
        setLoading(false);
      }
    };

    loadProject();

    return () => {
      closeTaskSocket();
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [id]);

  const stopTaskPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startTaskPolling = (runningTaskId: string, projectId: string) => {
    stopTaskPolling();
    pollRef.current = setInterval(async () => {
      try {
        const data = await pipelineApi.getTask(runningTaskId);
        setTaskProgress(data);
        if (data.logs && data.logs.length > 0) {
          setLogs(data.logs);
        }
        if (data.status === 'completed' || data.status === 'error') {
          stopTaskPolling();
          setIsRunning(false);
          setRunningStep(null);
          await refreshProjectAndSpec(projectId);
        }
      } catch (err) {
        console.warn('任务轮询失败:', err);
      }
    }, 1500);
  };

  const bindTaskRealtime = (runningTaskId: string, projectId: string) => {
    closeTaskSocket();
    startTaskPolling(runningTaskId, projectId);

    let terminal = false;
    const markTerminal = (data?: TaskProgress) => {
      if (terminal) return;
      terminal = true;
      stopTaskPolling();
      setIsRunning(false);
      setRunningStep(null);
      if (data) {
        setTaskProgress(data);
      }
      refreshProjectAndSpec(projectId).catch(() => undefined);
    };

    const ws = pipelineApi.connectWebSocket(runningTaskId, (data) => {
      setTaskProgress(data);
      if (data.logs && data.logs.length > 0) {
        setLogs(data.logs);
      }
      if (data.status === 'completed' || data.status === 'error') {
        markTerminal(data);
      }
    });
    wsRef.current = ws;

    ws.addEventListener('open', () => {
      if (wsRef.current !== ws) return;
      stopTaskPolling();
    });

    const resumePolling = () => {
      if (wsRef.current !== ws) return;
      if (!terminal) {
        startTaskPolling(runningTaskId, projectId);
      }
    };

    ws.addEventListener('error', resumePolling);
    ws.addEventListener('close', resumePolling);
  };

  const runPipeline = async (steps: PipelineStep[]) => {
    const projectId = id;
    if (!projectId) return;
    setIsRunning(true);
    setLogs([]);
    setTaskProgress(null);
    const result = await pipelineApi.run(projectId, { steps });
    setTaskId(result.task_id);
    bindTaskRealtime(result.task_id, projectId);
  };

  // 启动流水线
  const handleStart = async () => {
    if (!id || isRunning) return;
    if (project?.charter_completed === false) {
      alert('项目章程未完成。请先点击“AI补全章程/保存章程”，或使用“自动修复并继续”。');
      return;
    }

    try {
      const status = await specReviewApi.getStatus(id);
      setSpecReview(status);
      if (status.review_status === 'missing_spec') {
        await runPipeline(FULL_PIPELINE_STEPS);
        return;
      }

      if (!status.approved) {
        try {
          const approved = await specReviewApi.approve(id, 'web-auto');
          setSpecReview(approved);
        } catch (e) {
          console.warn('自动确认规格失败，继续由后端门禁兜底:', e);
        }
      }

      await runPipeline(POST_SPEC_PIPELINE_STEPS);
    } catch (err) {
      setIsRunning(false);
      alert(err instanceof Error ? err.message : '启动失败');
    }
  };

  // 停止任务
  const handleStop = async () => {
    if (taskId) {
      try {
        await pipelineApi.cancelTask(taskId);
      } catch (err) {
        console.warn('取消任务失败:', err);
      }
    }
    closeTaskSocket();
    stopTaskPolling();
    setIsRunning(false);
    setTaskId(null);
    setRunningStep(null);
  };

  // 重启任务
  const handleRestart = () => {
    void handleStop();
    setTimeout(handleStart, 500);
  };

  const handleApproveSpec = async () => {
    if (!id || isRunning || approvingSpec) return;
    try {
      setApprovingSpec(true);
      const status = await specReviewApi.approve(id);
      setSpecReview(status);
      alert('规格确认成功，现可执行实现阶段。');
    } catch (err) {
      alert(err instanceof Error ? err.message : '规格确认失败');
    } finally {
      setApprovingSpec(false);
    }
  };

  const handleSaveCharter = async () => {
    if (!id || savingCharter) return;
    try {
      setSavingCharter(true);
      const parsed = JSON.parse(charterText || '{}');
      const res = await projectApi.updateCharter(id, parsed);
      setCharterText(JSON.stringify(res.charter, null, 2));
      await refreshProjectAndSpec(id);
      alert(res.charter_completed ? '章程已保存并通过校验。' : `章程已保存，但仍有缺项：${res.validation_errors.join('；')}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : '章程保存失败');
    } finally {
      setSavingCharter(false);
    }
  };

  const handleDraftCharter = async () => {
    if (!id || draftingCharter) return;
    try {
      setDraftingCharter(true);
      const res = await projectApi.draftCharter(id);
      setCharterText(JSON.stringify(res.charter, null, 2));
      await refreshProjectAndSpec(id);
      alert('已完成 AI 章程补全。');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'AI补全章程失败');
    } finally {
      setDraftingCharter(false);
    }
  };

  const handleSelfHealRun = async () => {
    if (!id || isRunning || selfHealing) return;
    try {
      setSelfHealing(true);
      setIsRunning(true);
      setLogs([]);
      const result = await projectApi.selfHealRun(id, {
        steps: FULL_PIPELINE_STEPS,
        auto_confirm_spec: true,
      });
      setTaskId(result.task_id);
      if (result.actions?.length) {
        setLogs([
          {
            id: `self-heal-${Date.now()}`,
            timestamp: new Date().toLocaleTimeString(),
            level: 'INFO',
            message: `自愈动作: ${result.actions.join(', ')}`,
          },
        ]);
      }
      setTaskProgress(null);
      bindTaskRealtime(result.task_id, id);
    } catch (err) {
      setIsRunning(false);
      alert(err instanceof Error ? err.message : '自动修复并继续失败');
    } finally {
      setSelfHealing(false);
    }
  };

  const handleRiskCheck = async () => {
    if (!id || riskChecking) return;
    try {
      setRiskChecking(true);
      const report = await projectApi.checkSubmissionRisk(id, {
        block_threshold: 75,
        enable_auto_fix: true,
        max_fix_rounds: 2,
      });
      setRiskReport(report);
      if (report.report.should_block_submission) {
        alert(`风险预检未通过（score=${report.report.score}），请先按提示补齐证据链。`);
      } else {
        alert(`风险预检通过（score=${report.report.score}）。`);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : '风险预检失败');
    } finally {
      setRiskChecking(false);
    }
  };

  const handleRebuildUiSkillPlan = async () => {
    if (!id || uiSkillRebuilding) return;
    try {
      setUiSkillRebuilding(true);
      await projectApi.rebuildUiSkillPlan(id);
      const plan = await projectApi.getUiSkillPlan(id);
      setUiSkillPlan(plan);
      alert('UI Skill 规划已重建。');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'UI Skill 规划重建失败');
    } finally {
      setUiSkillRebuilding(false);
    }
  };

  const handleRunUiSkillStudio = async () => {
    if (!id || uiSkillStudioRunning || isRunning) return;
    setStudioModalOpen(true);
  };

  const handleSubmitUiSkillStudio = async () => {
    if (!id || uiSkillStudioRunning || isRunning) return;
    const intentText = String(studioForm.intent_text || '').trim();
    if (!intentText) {
      alert('请先填写目标描述');
      return;
    }
    try {
      setUiSkillStudioRunning(true);
      const result = await projectApi.runUiSkillStudio(id, {
        intent_text: intentText,
        domain: studioForm.domain,
        ui_mode: studioForm.ui_mode,
        token_policy: studioForm.token_policy,
        page_count: Number(studioForm.page_count || 6),
        preset_template: studioForm.preset_template,
        feature_preferences: studioForm.feature_preferences,
        apply_to_plan: true,
        rebuild_ui_skill: true,
      });
      setUiSkillStudioResult(result);
      const plan = await projectApi.getUiSkillPlan(id);
      setUiSkillPlan(plan);
      const specStatus = await specReviewApi.getStatus(id).catch(() => null);
      if (specStatus) {
        setSpecReview(specStatus);
      }
      setStudioModalOpen(false);
      alert(`Skill Studio 已完成：${(result.actions || []).join('、') || '已更新'}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Skill Studio 执行失败');
    } finally {
      setUiSkillStudioRunning(false);
    }
  };

  const handleRunUiPolicyAutofix = async () => {
    if (!id || uiPolicyFixing || isRunning) return;
    try {
      setUiPolicyFixing(true);
      const result = await projectApi.runUiSkillPolicyAutofix(id, {
        max_rounds: 2,
        block_threshold: 75,
      });
      setRiskReport({
        project_id: result.project_id,
        project_name: result.project_name,
        report_path: result.submission_risk_report_path,
        report: result.final_report as any,
      });
      if (result.fixed) {
        alert(`策略修复完成，门禁已通过。执行动作: ${(result.policy_actions || []).join('、') || '无'}`);
      } else {
        alert(`策略修复完成但仍有阻断项: ${(result.remaining_blockers || []).slice(0, 4).join('；') || '无'}`);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : '策略自动修复失败');
    } finally {
      setUiPolicyFixing(false);
    }
  };

  // 单步测试
  const handleSingleStep = async (step: PipelineStep) => {
    if (!id || isRunning) return;

    try {
      if (IMPLEMENTATION_STEPS.includes(step)) {
        const status = await specReviewApi.getStatus(id);
        setSpecReview(status);
        if (status.review_status === 'missing_spec') {
          alert('尚未生成可执行规格，请先执行 plan/spec。');
          return;
        }
        if (!status.approved) {
          try {
            const approved = await specReviewApi.approve(id, 'web-auto');
            setSpecReview(approved);
          } catch (e) {
            alert('规格自动确认失败，请手动确认后重试。');
            return;
          }
        }
      }

      setIsRunning(true);
      setRunningStep(step);
      setLogs([]);
      setTaskProgress(null);
      const result = await projectApi.runSingleStep(id, step);
      setTaskId(result.task_id);
      bindTaskRealtime(result.task_id, id);
    } catch (err) {
      setIsRunning(false);
      setRunningStep(null);
      alert(err instanceof Error ? err.message : '启动失败');
    }
  };

  // 下载文件
  const handleDownload = (fileType: 'plan' | 'document' | 'pdf') => {
    if (!id) return;
    fileApi.download(id, fileType);
  };

  // 计算当前步骤索引
  const getCurrentStepIndex = (): number => {
    if (!taskProgress?.current_step) {
      if (project?.status === 'completed') return STEPS.length;
      return -1;
    }

    const stepNameMap: Record<string, number> = {
      '生成项目规划': 0,
      '生成可执行规格': 1,
      '生成HTML页面': 2,
      '截图生成': 3,
      '代码生成': 4,
      '运行验证': 5,
      '说明书生成': 6,
      '源码PDF生成': 7,
      '冻结提交包': 8,
    };

    return stepNameMap[taskProgress.current_step] ?? -1;
  };

  const currentStepIndex = getCurrentStepIndex();
  const progress = taskProgress?.progress ?? project?.progress ?? 0;
  const riskFailedChecks =
    riskReport?.report?.hard_gate?.failed_checks || riskReport?.report?.failed_checks || [];
  const riskAutoFixRounds = riskReport?.report?.auto_fix?.rounds || [];
  const riskAutoFixedActions = Array.from(
    new Set(
      riskAutoFixRounds.flatMap((round) =>
        (round?.action_results || [])
          .filter((item: any) => item?.ok && item?.action)
          .map((item: any) => String(item.action))
      )
    )
  );
  const runtimeSkillCompliance = (riskReport?.report?.checks?.runtime_skill_compliance || {}) as Record<string, any>;
  const runtimePolicyPassRatio = Number((runtimeSkillCompliance.summary || {}).rule_pass_ratio || 0);
  const runtimePolicyCriticalFailed = (runtimeSkillCompliance.critical_failed_rules || []) as string[];
  const runtimePolicyAutoFix = (runtimeSkillCompliance.policy_auto_fix_actions || []) as string[];
  const runtimePolicyActionResolution = (runtimeSkillCompliance.policy_action_resolution || []) as Array<Record<string, any>>;
  const runtimePolicyEvidencePreview = (runtimeSkillCompliance.evidence_preview || []) as Array<Record<string, any>>;

  // 获取状态徽章
  const getStatusBadge = () => {
    if (isRunning) return <Badge status="info">运行中</Badge>;
    if (project?.status === 'completed') return <Badge status="success">已完成</Badge>;
    if (project?.status === 'error') return <Badge status="error">出错</Badge>;
    return <Badge status="neutral">待处理</Badge>;
  };

  const specBadgeStatus = specReview?.approved ? 'success' : (specReview?.review_status === 'missing_spec' ? 'warning' : 'error');
  const specBadgeText = specReview?.approved
    ? '规格已确认'
    : (specReview?.review_status === 'missing_spec' ? '缺少规格' : '规格待确认');

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
        <span className="ml-3 text-zinc-500">加载中...</span>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh]">
        <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
        <p className="text-red-500 mb-4">{error || '项目不存在'}</p>
        <Button onClick={() => navigate('/')}>返回首页</Button>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-8 shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/')} className="p-3 bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700 rounded-xl shadow-sm transition-colors text-zinc-500 dark:text-zinc-400">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h2 className="text-2xl font-bold dark:text-white flex items-center gap-3">
              {project.name}
              {getStatusBadge()}
            </h2>
            <div className="flex items-center gap-3 mt-1 text-sm text-zinc-500">
               <span>项目ID: {id}</span>
               <span className="w-1 h-1 rounded-full bg-zinc-300"></span>
               <span>创建于 {project.created_at}</span>
            </div>
          </div>
        </div>

        <div className="flex gap-3">
          <Button
            variant="secondary"
            onClick={handleDraftCharter}
            isLoading={draftingCharter}
            disabled={isRunning}
          >
            <Sparkles className="w-4 h-4" /> AI补全章程
          </Button>
          <Button
            variant="secondary"
            onClick={handleSaveCharter}
            isLoading={savingCharter}
            disabled={isRunning}
          >
            <Save className="w-4 h-4" /> 保存章程
          </Button>
          <Button
            variant="secondary"
            onClick={handleRiskCheck}
            isLoading={riskChecking}
            disabled={isRunning}
          >
            <ShieldCheck className="w-4 h-4" /> 风险预检
          </Button>
          <Button
            variant="secondary"
            onClick={handleSelfHealRun}
            isLoading={selfHealing}
            disabled={isRunning}
          >
            <Wand2 className="w-4 h-4" /> 自动修复并继续
          </Button>
          <Button
            variant="secondary"
            onClick={handleApproveSpec}
            isLoading={approvingSpec}
            disabled={isRunning || !specReview || specReview.review_status === 'missing_spec' || specReview.approved}
          >
            确认规格
          </Button>
          {!isRunning ? (
            <Button variant="primary" onClick={handleStart}>
              <Play className="w-4 h-4" /> 开始生成
            </Button>
          ) : (
            <Button variant="danger" onClick={handleStop}>
              <Square className="w-4 h-4 fill-current" /> 停止
            </Button>
          )}
          <Button variant="ghost" onClick={handleRestart} disabled={!isRunning}>
            <RotateCw className="w-4 h-4" /> 重启
          </Button>
        </div>
      </div>

      <Card className="mb-6 bg-white/60 dark:bg-black/30 border-white/20">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-zinc-500">规格评审状态</p>
            <div className="mt-1 flex items-center gap-2">
              <Badge status={specBadgeStatus as 'success' | 'warning' | 'error'}>{specBadgeText}</Badge>
              {specReview?.spec_digest ? (
                <span className="text-xs text-zinc-500">digest: {specReview.spec_digest.slice(0, 12)}</span>
              ) : null}
              {specReview?.reviewer ? (
                <span className="text-xs text-zinc-500">reviewer: {specReview.reviewer}</span>
              ) : null}
            </div>
          </div>
          <p className="text-xs text-zinc-500">
            规则：code/verify/document/pdf/freeze 前必须规格已确认
          </p>
        </div>
      </Card>

      <Card className="mb-6 bg-white/60 dark:bg-black/30 border-white/20">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm text-zinc-500">策略裁决</p>
            <div className="mt-1 flex items-center gap-2">
              <Badge status={runtimePolicyCriticalFailed.length ? 'error' : 'success'}>
                {runtimePolicyCriticalFailed.length ? '关键规则失败' : '关键规则通过'}
              </Badge>
              <span className="text-xs text-zinc-500">rule pass ratio: {(runtimePolicyPassRatio * 100).toFixed(1)}%</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <p className="text-xs text-zinc-500">展示 critical_failed_rules / policy_auto_fix_actions</p>
            <Button
              variant="secondary"
              onClick={handleRunUiPolicyAutofix}
              isLoading={uiPolicyFixing}
              disabled={isRunning}
            >
              <Wand2 className="w-4 h-4" /> 执行策略修复
            </Button>
          </div>
        </div>
        {runtimePolicyCriticalFailed.length ? (
          <div className="mt-3 text-xs text-red-500 space-y-1">
            <p>关键失败规则: {runtimePolicyCriticalFailed.join('、')}</p>
          </div>
        ) : null}
        {runtimePolicyAutoFix.length ? (
          <div className="mt-2 text-xs text-emerald-600 space-y-1">
            <p>建议自动修复动作: {runtimePolicyAutoFix.join('、')}</p>
          </div>
        ) : null}
        {runtimePolicyActionResolution.length ? (
          <div className="mt-2 text-xs text-zinc-600 dark:text-zinc-300 space-y-1">
            <p>动作裁决顺序:</p>
            {runtimePolicyActionResolution.slice(0, 6).map((item, idx) => (
              <p key={`resolution-${idx}`}>
                {idx + 1}. {String(item.action || '-')} | priority={Number(item.priority_index ?? 99)} | critical={Number(item.critical_rule_count ?? 0)} | rules={Number(item.rule_count ?? 0)}
              </p>
            ))}
          </div>
        ) : null}
        {runtimePolicyEvidencePreview.length ? (
          <div className="mt-3 text-xs text-zinc-600 dark:text-zinc-300 space-y-1">
            <p>证据锚点预览:</p>
            {runtimePolicyEvidencePreview.slice(0, 6).map((item, idx) => (
              <p key={`evidence-${idx}`}>
                [{String(item.rule_id || '-')}] {String(item.jump_anchor || item.file_rel || '-')}: {String(item.message || '')}
              </p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card className="mb-6 bg-white/60 dark:bg-black/30 border-white/20">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm text-zinc-500">申报前风险预检</p>
            {riskReport ? (
              <div className="mt-1 flex items-center gap-2">
                <Badge status={riskReport.report.should_block_submission ? 'error' : 'success'}>
                  {riskReport.report.should_block_submission ? '需拦截' : '可提交'}
                </Badge>
                <Badge status={riskReport.report.hard_gate?.passed ? 'success' : 'warning'}>
                  {riskReport.report.hard_gate?.passed ? '硬门禁通过' : '硬门禁未通过'}
                </Badge>
                <span className="text-xs text-zinc-500">score: {riskReport.report.score}</span>
                <span className="text-xs text-zinc-500">level: {riskReport.report.risk_level}</span>
              </div>
            ) : (
              <p className="text-xs text-zinc-500 mt-1">暂无风险报告</p>
            )}
          </div>
          <p className="text-xs text-zinc-500">
            章程完整性 / 规格一致性 / 文档截图一致性 / 运行证据链
          </p>
        </div>
        {riskAutoFixedActions.length ? (
          <div className="mt-3 text-xs text-emerald-600 space-y-1">
            <p>已自动修复: {riskAutoFixedActions.join('、')}</p>
          </div>
        ) : null}
        {riskFailedChecks.length ? (
          <div className="mt-3 text-xs text-amber-600 space-y-1">
            <p>剩余未通过门禁: {riskFailedChecks.join('、')}</p>
          </div>
        ) : null}
        {riskReport?.report?.blocking_issues?.length ? (
          <div className="mt-2 text-xs text-red-500 space-y-1">
            {riskReport.report.blocking_issues.slice(0, 6).map((item, idx) => (
              <p key={`${idx}-${item}`}>- {item}</p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card className="mb-6 bg-white/60 dark:bg-black/30 border-white/20">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm text-zinc-500">UI Skill 规划</p>
            {uiSkillLoading ? (
              <p className="text-xs text-zinc-500 mt-1">加载中...</p>
            ) : uiSkillPlan ? (
              <div className="mt-1 flex items-center gap-2">
                <Badge status={(uiSkillPlan.report?.passed ?? false) ? 'success' : 'warning'}>
                  {(uiSkillPlan.report?.passed ?? false) ? '规划通过' : '规划待完善'}
                </Badge>
                <span className="text-xs text-zinc-500">
                  mode: {String(uiSkillPlan.profile?.mode || '-')}
                </span>
                <span className="text-xs text-zinc-500">
                  token: {String(uiSkillPlan.profile?.token_policy || '-')}
                </span>
                <span className="text-xs text-zinc-500">
                  pages: {Number(uiSkillPlan.blueprint_summary?.page_count || 0)}
                </span>
                <span className="text-xs text-zinc-500">
                  blocks: {Number(uiSkillPlan.blueprint_summary?.block_count || 0)}
                </span>
                {uiSkillStudioResult?.decisions?.domain ? (
                  <span className="text-xs text-zinc-500">
                    domain: {String(uiSkillStudioResult.decisions.domain)}
                  </span>
                ) : null}
              </div>
            ) : (
              <p className="text-xs text-zinc-500 mt-1">暂无 UI Skill 规划</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleRebuildUiSkillPlan}
              isLoading={uiSkillRebuilding}
              disabled={isRunning}
            >
              <RotateCw className="w-4 h-4" /> 重建 UI 规划
            </Button>
            <Button
              variant="secondary"
              onClick={handleRunUiSkillStudio}
              isLoading={uiSkillStudioRunning}
              disabled={isRunning}
            >
              <Sparkles className="w-4 h-4" /> Skill Studio 接管
            </Button>
          </div>
        </div>
        {uiSkillStudioResult?.actions?.length ? (
          <div className="mt-3 text-xs text-zinc-500">
            最近一次 Studio 动作: {uiSkillStudioResult.actions.join('、')}
          </div>
        ) : null}
      </Card>

      <Card className="mb-6 bg-white/60 dark:bg-black/30 border-white/20">
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm text-zinc-500">项目章程 JSON（可编辑）</p>
          {project.charter_completed === false ? <Badge status="warning">章程未完成</Badge> : <Badge status="success">章程已完成</Badge>}
        </div>
        <textarea
          value={charterText}
          onChange={(e) => setCharterText(e.target.value)}
          rows={10}
          className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
          placeholder="项目章程 JSON"
          disabled={isRunning}
        />
      </Card>

      <div className="flex-1 flex gap-8 min-h-0">
        {/* Left: Workflow */}
        <Card className="w-80 flex flex-col shrink-0 overflow-hidden bg-white/60 dark:bg-black/40 backdrop-blur-xl border-white/20" noPadding>
          <div className="p-6 border-b border-zinc-100 dark:border-white/5 bg-white/30 dark:bg-white/5">
             <h3 className="font-bold dark:text-zinc-100">任务进度</h3>
          </div>

          <div className="flex-1 overflow-y-auto p-6 space-y-0 relative">
            {/* Timeline Line */}
            <div className="absolute left-[2.2rem] top-8 bottom-8 w-0.5 bg-zinc-200 dark:bg-zinc-800 -z-10"></div>

            {STEPS.map((step, index) => {
              let stepState: 'completed' | 'current' | 'pending' = 'pending';

              // 根据项目文件状态或任务进度判断
              if (project.files[step.key as keyof typeof project.files]) {
                stepState = 'completed';
              }
              if (isRunning && index === currentStepIndex) {
                stepState = 'current';
              }
              if (isRunning && index < currentStepIndex) {
                stepState = 'completed';
              }

              const isStepRunning = runningStep === step.id;

              return (
                <div key={step.id} className="group relative flex items-start gap-4 pb-8 last:pb-0">
                  <div className={`
                    w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border-2 transition-all duration-300 shadow-sm z-10
                    ${stepState === 'completed' ? 'bg-emerald-500 border-emerald-500 text-white shadow-emerald-500/30' : ''}
                    ${stepState === 'current' ? 'bg-white dark:bg-zinc-900 border-indigo-500 text-indigo-500 shadow-indigo-500/20 scale-110' : ''}
                    ${stepState === 'pending' ? 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 text-zinc-300' : ''}
                  `}>
                    {stepState === 'completed' && <CheckCircle2 className="w-5 h-5" />}
                    {stepState === 'current' && <Loader2 className="w-5 h-5 animate-spin" />}
                    {stepState === 'pending' && <Circle className="w-5 h-5" />}
                  </div>
                  <div className="pt-1.5 flex-1">
                    <div className="flex items-center justify-between">
                      <p className={`font-bold text-base transition-colors ${stepState === 'current' ? 'text-indigo-600 dark:text-indigo-400' : 'text-zinc-700 dark:text-zinc-300'} ${stepState === 'pending' ? 'opacity-50' : ''}`}>
                        {step.label}
                      </p>
                      {/* 单步测试按钮 */}
                      {!isRunning && (
                        <button
                          onClick={() => handleSingleStep(step.id)}
                          className="opacity-0 group-hover:opacity-100 p-1.5 text-xs bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 rounded-lg hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-all flex items-center gap-1"
                          title={`单独测试: ${step.label}`}
                        >
                          <TestTube2 className="w-3 h-3" />
                          测试
                        </button>
                      )}
                      {isStepRunning && (
                        <span className="text-xs text-indigo-500 flex items-center gap-1">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          测试中
                        </span>
                      )}
                    </div>
                    <p className="text-xs font-medium text-zinc-500 mt-1">
                      {stepState === 'completed' ? '已完成' : stepState === 'current' ? taskProgress?.current_step || '处理中...' : '等待执行'}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="p-6 border-t border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-white/5">
             <div className="flex justify-between text-sm font-semibold mb-3 dark:text-zinc-300">
               <span>总进度</span>
               <span className="text-indigo-500">{progress}%</span>
             </div>
             <ProgressBar progress={progress} />

             {/* 下载按钮 */}
             {project.status === 'completed' && (
               <div className="mt-4 space-y-2">
                 <p className="text-xs text-zinc-500 mb-2">下载文件:</p>
                 <div className="flex flex-wrap gap-2">
                   {project.files.plan && (
                     <button
                       onClick={() => handleDownload('plan')}
                       className="flex items-center gap-1 text-xs px-2 py-1 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 rounded-lg hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
                     >
                       <Download className="w-3 h-3" /> 规划JSON
                     </button>
                   )}
                   {project.files.document && (
                     <button
                       onClick={() => handleDownload('document')}
                       className="flex items-center gap-1 text-xs px-2 py-1 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 rounded-lg hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors"
                     >
                       <Download className="w-3 h-3" /> 说明书
                     </button>
                   )}
                   {project.files.pdf && (
                     <button
                       onClick={() => handleDownload('pdf')}
                       className="flex items-center gap-1 text-xs px-2 py-1 bg-orange-50 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 rounded-lg hover:bg-orange-100 dark:hover:bg-orange-900/50 transition-colors"
                     >
                       <Download className="w-3 h-3" /> 源码PDF
                     </button>
                   )}
                 </div>
               </div>
             )}
          </div>
        </Card>

        {/* Right: Logs */}
        <div className="flex-1 flex flex-col min-w-0 h-full">
           <LogViewer logs={logs} />
        </div>
      </div>

      <Modal isOpen={studioModalOpen} onClose={() => setStudioModalOpen(false)} title="Skill Studio 接管配置">
        <div className="space-y-3">
          <div>
            <p className="text-xs text-zinc-500 mb-1">目标描述</p>
            <textarea
              rows={3}
              value={studioForm.intent_text}
              onChange={(e) => setStudioForm((prev) => ({ ...prev, intent_text: e.target.value }))}
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-sm"
              placeholder="例如：做一个工单系统，界面像IDE，页面精美且可审查"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-zinc-500">
              行业
              <select
                value={studioForm.domain}
                onChange={(e) => setStudioForm((prev) => ({ ...prev, domain: e.target.value }))}
                className="mt-1 w-full px-2 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-sm"
              >
                <option value="workflow">workflow</option>
                <option value="knowledge">knowledge</option>
                <option value="operations">operations</option>
                <option value="generic">generic</option>
              </select>
            </label>
            <label className="text-xs text-zinc-500">
              UI模式
              <select
                value={studioForm.ui_mode}
                onChange={(e) => setStudioForm((prev) => ({ ...prev, ui_mode: e.target.value }))}
                className="mt-1 w-full px-2 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-sm"
              >
                <option value="narrative_tool_hybrid">narrative_tool_hybrid</option>
                <option value="tool_first">tool_first</option>
                <option value="narrative_first">narrative_first</option>
              </select>
            </label>
            <label className="text-xs text-zinc-500">
              token策略
              <select
                value={studioForm.token_policy}
                onChange={(e) => setStudioForm((prev) => ({ ...prev, token_policy: e.target.value }))}
                className="mt-1 w-full px-2 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-sm"
              >
                <option value="economy">economy</option>
                <option value="balanced">balanced</option>
                <option value="quality_first">quality_first</option>
              </select>
            </label>
            <label className="text-xs text-zinc-500">
              页面数量
              <input
                type="number"
                min={6}
                max={8}
                value={studioForm.page_count}
                onChange={(e) => setStudioForm((prev) => ({ ...prev, page_count: Number(e.target.value || 6) }))}
                className="mt-1 w-full px-2 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-sm"
              />
            </label>
          </div>
          <label className="text-xs text-zinc-500 block">
            模板
            <select
              value={studioForm.preset_template}
              onChange={(e) => setStudioForm((prev) => ({ ...prev, preset_template: e.target.value }))}
              className="mt-1 w-full px-2 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/60 text-sm"
            >
              {STUDIO_PRESETS.map((x) => (
                <option key={x} value={x}>{x}</option>
              ))}
            </select>
          </label>
          <div>
            <p className="text-xs text-zinc-500 mb-1">功能偏好</p>
            <div className="grid grid-cols-2 gap-2">
              {STUDIO_FEATURES.map((feature) => {
                const checked = studioForm.feature_preferences.includes(feature);
                return (
                  <label key={feature} className="text-xs text-zinc-600 dark:text-zinc-300 flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        setStudioForm((prev) => ({
                          ...prev,
                          feature_preferences: e.target.checked
                            ? [...prev.feature_preferences, feature]
                            : prev.feature_preferences.filter((x) => x !== feature),
                        }));
                      }}
                    />
                    {feature}
                  </label>
                );
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setStudioModalOpen(false)} disabled={uiSkillStudioRunning}>取消</Button>
            <Button variant="secondary" onClick={handleSubmitUiSkillStudio} isLoading={uiSkillStudioRunning}>执行接管</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
