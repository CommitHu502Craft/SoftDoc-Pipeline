import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Search, Play, Trash2, MoreHorizontal, Loader2, RefreshCw, FolderSearch, CheckSquare, Square, StopCircle, Sparkles, Wand2 } from 'lucide-react';
import { Button, Card, Modal } from '../components/UI';
import { projectApi, scanApi, Project, ProjectCharter, DEFAULT_PIPELINE_STEPS } from '../api';

export const ProjectsPage: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [businessScope, setBusinessScope] = useState('');
  const [creating, setCreating] = useState(false);

  // 扫描状态
  const [scanning, setScanning] = useState(false);

  // 批量选择状态
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBatchModalOpen, setIsBatchModalOpen] = useState(false);
  const [maxParallel, setMaxParallel] = useState(2);
  const [batchRunning, setBatchRunning] = useState(false);
  const [charterDrafting, setCharterDrafting] = useState(false);
  const [selfHealing, setSelfHealing] = useState(false);
  const [batchStatus, setBatchStatus] = useState<{
    is_running: boolean;
    total: number;
    completed: number;
    failed: number;
  } | null>(null);

  // 加载项目列表
  const loadProjects = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await projectApi.list();
      setProjects(response.projects);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
      setProjects([]);
    } finally {
      setLoading(false);
    }
  };

  // 轮询批量状态
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null;

    if (batchRunning) {
      interval = setInterval(async () => {
        try {
          const status = await projectApi.getBatchStatus();
          setBatchStatus(status);

          if (!status.is_running) {
            setBatchRunning(false);
            await loadProjects();
          }
        } catch (e) {
          console.error('获取批量状态失败', e);
        }
      }, 2000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [batchRunning]);

  useEffect(() => {
    loadProjects();
  }, []);

  const filteredProjects = projects.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  // 切换选择
  const toggleSelect = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    setSelectedIds(newSet);
  };

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedIds.size === filteredProjects.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredProjects.map(p => p.id)));
    }
  };

  // 批量执行
  const handleBatchRun = async () => {
    if (selectedIds.size === 0) return;
    const selectedProjects = projects.filter(p => selectedIds.has(p.id));
    const missingCharter = selectedProjects.filter(p => !p.charter_completed);
    if (missingCharter.length > 0) {
      alert(`有 ${missingCharter.length} 个项目章程未完成，无法批量执行。请先补全章程后再运行。`);
      return;
    }

    try {
      setBatchRunning(true);
      setIsBatchModalOpen(false);
      await projectApi.batchRun(Array.from(selectedIds), maxParallel, DEFAULT_PIPELINE_STEPS);
      setSelectedIds(new Set());
      await loadProjects();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量执行失败');
      setBatchRunning(false);
    }
  };

  // 批量AI补全章程（默认补全选中项；未选中则补全全部缺失项）
  const handleBatchDraftCharter = async () => {
    const targetIds = selectedIds.size > 0
      ? Array.from(selectedIds)
      : projects.filter(p => !p.charter_completed).map(p => p.id);
    if (targetIds.length === 0) {
      alert('当前没有需要补全章程的项目。');
      return;
    }
    try {
      setCharterDrafting(true);
      const res = await projectApi.batchDraftCharter(targetIds, '', true);
      alert(`章程补全完成：更新 ${res.updated}，跳过 ${res.skipped}，失败 ${res.failed}`);
      await loadProjects();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量补全章程失败');
    } finally {
      setCharterDrafting(false);
    }
  };

  // 批量自动修复并执行
  const handleBatchSelfHeal = async () => {
    if (selectedIds.size === 0) {
      alert('请先选择项目。');
      return;
    }
    try {
      setSelfHealing(true);
      setBatchRunning(true);
      setIsBatchModalOpen(false);
      await projectApi.batchSelfHealRun(Array.from(selectedIds), maxParallel, {
        steps: DEFAULT_PIPELINE_STEPS,
        auto_confirm_spec: true,
      });
      setSelectedIds(new Set());
      await loadProjects();
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量自动修复失败');
      setBatchRunning(false);
    } finally {
      setSelfHealing(false);
    }
  };

  // 停止批量执行
  const handleStopBatch = async () => {
    try {
      await projectApi.stopBatch();
      setBatchRunning(false);
      await loadProjects();
    } catch (err) {
      alert('停止失败');
    }
  };

  const handleCreate = async () => {
    if (!newProjectName.trim()) return;

    const buildCharter = (name: string): ProjectCharter => ({
      project_name: name,
      business_scope: businessScope.trim() || `${name}的业务边界为：围绕核心业务数据的录入、审核、查询与导出，不扩展到无关行业场景。`,
      user_roles: [
        { name: '系统管理员', responsibility: '系统配置、权限分配与审计' },
        { name: '业务操作员', responsibility: '执行业务录入、提交、查询与导出' },
      ],
      core_flows: [
        {
          name: '主业务流程',
          steps: ['录入业务数据', '提交审核', '查询与导出结果'],
          success_criteria: '业务记录可追溯，审核状态清晰，结果可导出',
        },
      ],
      non_functional_constraints: ['关键页面响应时间不超过2秒', '关键操作全量审计并可追溯'],
      acceptance_criteria: ['可端到端完成主业务流程', '核心数据可查询并导出'],
    });

    try {
      setCreating(true);
      const names = newProjectName.split('\n').map(n => n.trim()).filter(n => n);

      if (names.length === 1) {
        const newProject = await projectApi.create(names[0], buildCharter(names[0]));
        setProjects(prev => [newProject, ...prev]);
        setIsModalOpen(false);
        setNewProjectName('');
        setBusinessScope('');
        navigate(`/projects/${newProject.id}`);
      } else {
        const created = await Promise.all(
          names.map(name => projectApi.create(name, buildCharter(name)))
        );
        alert(`成功创建 ${created.length} 个项目（已写入章程）`);
        setIsModalOpen(false);
        setNewProjectName('');
        setBusinessScope('');
        await loadProjects();
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : '创建失败');
    } finally {
      setCreating(false);
    }
  };

  const handleScan = async () => {
    try {
      setScanning(true);
      const res = await scanApi.scanOutput(true);
      alert(`扫描完成！\n发现项目: ${res.found}\n成功导入: ${res.imported}`);
      await loadProjects();
    } catch (err) {
      alert('扫描失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setScanning(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, projectId: string) => {
    e.stopPropagation();
    if (!confirm('确定要删除这个项目吗？')) return;

    try {
      await projectApi.delete(projectId);
      setProjects(prev => prev.filter(p => p.id !== projectId));
      selectedIds.delete(projectId);
      setSelectedIds(new Set(selectedIds));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const getStatusBadge = (status: Project['status']) => {
    const styles: Record<string, string> = {
      idle: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500',
      running: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400',
      completed: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400',
      error: 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400',
      submitted: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400',
    };
    const labels: Record<string, string> = { idle: '待处理', running: '运行中', completed: '已完成', error: '出错', submitted: '已提交' };
    return (
      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${styles[status] || styles.idle}`}>
        {labels[status] || status}
      </span>
    );
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
           <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-zinc-900 to-zinc-500 dark:from-white dark:to-zinc-400">项目概览</h2>
           <p className="text-zinc-500 dark:text-zinc-400 mt-1">管理并监控您的软著生成进度</p>
        </div>
        <div className="flex gap-4">
          <div className="relative group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 group-focus-within:text-indigo-500 transition-colors" />
            <input
              type="text"
              placeholder="搜索项目..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 pr-4 py-2.5 bg-white/50 dark:bg-black/20 border border-zinc-200 dark:border-white/10 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 dark:text-white w-64 transition-all backdrop-blur-sm shadow-sm"
            />
          </div>
          <Button
            variant="secondary"
            onClick={handleScan}
            disabled={scanning}
            className="shadow-sm"
          >
            {scanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderSearch className="w-4 h-4" />}
            {scanning ? '扫描中...' : '扫描本地'}
          </Button>
          <Button
            variant="secondary"
            onClick={handleBatchDraftCharter}
            disabled={charterDrafting}
            className="shadow-sm"
          >
            {charterDrafting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {charterDrafting ? '补全中...' : '批量补章程'}
          </Button>
          <Button onClick={() => setIsModalOpen(true)} className="shadow-lg shadow-indigo-500/20">
            <Plus className="w-4 h-4" /> 新建项目
          </Button>
        </div>
      </div>

      {/* 批量操作栏 */}
      {filteredProjects.length > 0 && !loading && !error && (
        <div className="flex items-center justify-between glass-panel rounded-xl px-4 py-3">
          <div className="flex items-center gap-4">
            <button
              onClick={toggleSelectAll}
              className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300 hover:text-indigo-500 transition-colors"
            >
              {selectedIds.size === filteredProjects.length ? (
                <CheckSquare className="w-5 h-5 text-indigo-500" />
              ) : (
                <Square className="w-5 h-5" />
              )}
              {selectedIds.size === filteredProjects.length ? '取消全选' : '全选'}
            </button>
            {selectedIds.size > 0 && (
              <span className="text-sm text-zinc-500">
                已选择 <span className="text-indigo-500 font-semibold">{selectedIds.size}</span> 个项目
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {batchRunning ? (
              <>
                <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
                  <span>
                    批量执行中: {batchStatus?.completed || 0}/{batchStatus?.total || 0}
                    {batchStatus?.failed ? <span className="text-red-500 ml-1">(失败: {batchStatus.failed})</span> : null}
                  </span>
                </div>
                <Button
                  variant="secondary"
                  onClick={handleStopBatch}
                  className="text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                >
                  <StopCircle className="w-4 h-4" /> 停止
                </Button>
              </>
            ) : (
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={handleBatchSelfHeal}
                  disabled={selectedIds.size === 0 || selfHealing}
                  className="shadow-md"
                >
                  {selfHealing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
                  自动修复并执行
                </Button>
                <Button
                  onClick={() => setIsBatchModalOpen(true)}
                  disabled={selectedIds.size === 0}
                  className="shadow-md"
                >
                  <Play className="w-4 h-4" /> 批量执行 ({selectedIds.size})
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
          <span className="ml-3 text-zinc-500">加载中...</span>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div className="text-center py-20">
          <p className="text-red-500 mb-4">{error}</p>
          <Button onClick={loadProjects}>重试</Button>
        </div>
      )}

      {/* Projects Grid */}
      {!loading && !error && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredProjects.map((project) => (
            <div
              key={project.id}
              onClick={() => navigate(`/projects/${project.id}`)}
              className={`group relative glass-panel rounded-2xl p-6 hover:-translate-y-1 hover:shadow-2xl hover:shadow-indigo-500/10 hover:border-indigo-500/30 transition-all duration-500 cursor-pointer flex flex-col h-[260px] overflow-hidden ${selectedIds.has(project.id) ? 'ring-2 ring-indigo-500 border-indigo-500/50' : ''}`}
            >
              {/* 选择复选框 */}
              <button
                onClick={(e) => toggleSelect(e, project.id)}
                className="absolute top-3 left-3 z-20 p-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors"
              >
                {selectedIds.has(project.id) ? (
                  <CheckSquare className="w-5 h-5 text-indigo-500" />
                ) : (
                  <Square className="w-5 h-5 text-zinc-400 group-hover:text-zinc-600 dark:group-hover:text-zinc-300" />
                )}
              </button>

              {/* Background Gradient Blob */}
              <div className="absolute -top-10 -right-10 w-32 h-32 bg-indigo-500/10 rounded-full blur-2xl group-hover:bg-indigo-500/20 transition-colors duration-500"></div>

              <div className="flex justify-between items-start mb-6 z-10 pl-6">
                 {/* Custom SVG Ring Progress */}
                 <div className="relative w-16 h-16">
                   <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                      <path
                        className="text-zinc-200 dark:text-zinc-800"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="3"
                      />
                      <path
                        className={project.progress === 100 ? "text-emerald-500 drop-shadow-[0_0_3px_rgba(16,185,129,0.5)]" : "text-indigo-500 drop-shadow-[0_0_3px_rgba(99,102,241,0.5)]"}
                        strokeDasharray={`${project.progress}, 100`}
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="3"
                        strokeLinecap="round"
                      />
                   </svg>
                   <div className="absolute inset-0 flex items-center justify-center text-xs font-bold dark:text-white">
                     {project.progress}%
                   </div>
                 </div>

                 <div className="flex items-center gap-2">
                   {getStatusBadge(project.status)}
                   <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                     <button className="p-2 hover:bg-zinc-100 dark:hover:bg-white/10 rounded-full transition-colors">
                        <MoreHorizontal className="w-5 h-5 text-zinc-400" />
                     </button>
                   </div>
                 </div>
              </div>

              <h3 className="text-xl font-bold mb-auto line-clamp-2 dark:text-zinc-100 group-hover:text-indigo-500 transition-colors z-10 leading-snug">
                {project.name}
              </h3>

              {project.charter_completed === false && (
                <p className="text-xs text-amber-600 dark:text-amber-400 mt-1 z-10">
                  章程未完成，计划阶段将被阻断
                </p>
              )}

              {project.current_step && (
                <p className="text-xs text-indigo-500 mb-2 truncate z-10">
                  {project.current_step}
                </p>
              )}

              <div className="pt-4 border-t border-zinc-100 dark:border-white/5 flex items-center justify-between text-zinc-400 z-10">
                <span className="text-xs font-medium bg-zinc-100 dark:bg-white/5 px-2 py-1 rounded-md">{project.created_at}</span>
                <div className="flex gap-2">
                  <button title="运行" className="p-2 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-500 rounded-xl hover:bg-indigo-500 hover:text-white transition-all duration-300" onClick={(e) => { e.stopPropagation(); navigate(`/projects/${project.id}`); }}>
                    <Play className="w-4 h-4 fill-current" />
                  </button>
                  <button title="删除" className="p-2 hover:bg-red-50 dark:hover:bg-red-500/10 hover:text-red-500 rounded-xl transition-colors duration-300" onClick={(e) => handleDelete(e, project.id)}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}

          {/* Create Card */}
          <div
            onClick={() => setIsModalOpen(true)}
            className="group border-2 border-dashed border-zinc-300 dark:border-zinc-700 hover:border-indigo-500 dark:hover:border-indigo-500/50 rounded-2xl p-6 flex flex-col items-center justify-center text-zinc-400 hover:text-indigo-500 hover:bg-indigo-50/50 dark:hover:bg-indigo-900/10 transition-all duration-300 cursor-pointer h-[260px]"
          >
            <div className="w-16 h-16 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mb-4 group-hover:scale-110 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-500/20 transition-all duration-300">
              <Plus className="w-8 h-8" />
            </div>
            <span className="font-semibold text-lg">新建项目</span>
          </div>
        </div>
      )}

      {/* 批量执行设置 Modal */}
      <Modal isOpen={isBatchModalOpen} onClose={() => setIsBatchModalOpen(false)} title="批量执行设置">
        <div className="space-y-6">
          <div>
            <label className="block text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              并行数量
              <span className="font-normal text-zinc-500 ml-2">（同时执行的项目数）</span>
            </label>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min={1}
                max={5}
                value={maxParallel}
                onChange={(e) => setMaxParallel(Number(e.target.value))}
                className="flex-1 h-2 bg-zinc-200 dark:bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
              <span className="text-2xl font-bold text-indigo-500 w-8 text-center">{maxParallel}</span>
            </div>
            <div className="flex justify-between text-xs text-zinc-400 mt-1 px-1">
              <span>1（稳定）</span>
              <span>5（快速）</span>
            </div>
          </div>

          <div className="bg-zinc-50 dark:bg-zinc-800/50 rounded-xl p-4">
            <h4 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-2">即将执行</h4>
            <div className="text-sm text-zinc-500 space-y-1">
              <p>• 已选择 <span className="text-indigo-500 font-semibold">{selectedIds.size}</span> 个项目</p>
              <p>• 并行执行 <span className="text-indigo-500 font-semibold">{maxParallel}</span> 个任务</p>
              <p>• 执行步骤：规划 → 规格 → HTML → 截图 → 代码 → 验证 → 说明书 → PDF → 冻结</p>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setIsBatchModalOpen(false)}>取消</Button>
            <Button onClick={handleBatchRun} className="shadow-lg shadow-indigo-500/20">
              <Play className="w-4 h-4" /> 开始执行
            </Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title="新建项目">
        <div className="space-y-6">
          <div>
            <label className="block text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              项目名称
              <span className="font-normal text-zinc-500 ml-2">（支持批量录入，每行一个）</span>
            </label>
            <textarea
              autoFocus
              rows={6}
              className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 dark:text-white transition-all resize-none font-mono text-sm"
              placeholder={`智慧林业综合管理系统\n智慧农业监控平台\n智慧水利调度系统\n...\n\n（每行一个项目名称，可直接粘贴多行）`}
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              disabled={creating}
            />
            <div className="mt-2 flex justify-between items-center text-xs text-zinc-500">
              <span className="flex items-center gap-1">
                <span className="inline-block w-1 h-1 rounded-full bg-indigo-500"></span>
                提示：项目名称将作为软著申请的"软件全称"
              </span>
              <span className="text-indigo-500 font-medium">
                {newProjectName.split('\n').filter(n => n.trim()).length} 个项目
              </span>
            </div>
          </div>
          <div>
            <label className="block text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              业务边界（章程）
              <span className="font-normal text-zinc-500 ml-2">（可选，不填将自动生成）</span>
            </label>
            <textarea
              rows={3}
              className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 dark:text-white transition-all resize-none text-sm"
              placeholder="例如：面向企业合同审批，覆盖申请、审批、归档、查询全流程。"
              value={businessScope}
              onChange={(e) => setBusinessScope(e.target.value)}
              disabled={creating}
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setIsModalOpen(false)} disabled={creating}>取消</Button>
            <Button onClick={handleCreate} disabled={creating || !newProjectName.trim()}>
              {creating ? <><Loader2 className="w-4 h-4 animate-spin" /> 创建中...</> : '创建项目'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
