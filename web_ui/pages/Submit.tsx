import React, { useState, useEffect, useRef } from 'react';
import { UploadCloud, Trash, CheckSquare, Square, Plus, Loader2, X, RefreshCw } from 'lucide-react';
import { Button, Card, Badge, Modal } from '../components/UI';
import { submitQueueApi, accountApi, projectApi, SubmitQueueItem, Account, Project, SubmitQueueStartBlockedItem } from '../api';
import { buildSubmitStartAlert, formatBlockedItem } from './submitShared';

// 日志类型定义
interface LogEntry {
  id: string;
  time: string;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
}

export const SubmitPage: React.FC = () => {
  // 状态管理
  const [queue, setQueue] = useState<SubmitQueueItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());

  // 添加项目模态框状态
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [availableProjects, setAvailableProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [projectsToAdd, setProjectsToAdd] = useState<Set<string>>(new Set());

  // 日志状态 (模拟日志，实际应从后端获取或通过WS)
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // 初始化加载
  useEffect(() => {
    loadAccounts();
    refreshQueue();

    // 轮询队列状态
    const interval = setInterval(refreshQueue, 3000);
    return () => clearInterval(interval);
  }, []);

  // 自动滚动日志
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // 加载账号
  const loadAccounts = async () => {
    try {
      const response = await accountApi.list();
      setAccounts(response.accounts);
      if (response.accounts.length > 0 && !selectedAccount) {
        setSelectedAccount(response.accounts[0].id);
      }
    } catch (err) {
      addLog('加载账号列表失败', 'error');
    }
  };

  // 刷新队列
  const refreshQueue = async () => {
    try {
      const response = await submitQueueApi.getQueue();
      setQueue(response.items);
      setIsRunning(response.is_running);
      setLoading(false);

      // 如果正在运行，添加模拟日志 (实际项目中应从后端获取实时日志)
      if (response.is_running) {
        // 这里仅作演示，实际应连接WebSocket或轮询日志接口
        // 简单模拟: 查找正在运行的项目
        const runningItem = response.items.find(i => i.status === 'submitting');
        if (runningItem) {
          // 在实际应用中，这里不应重复添加日志，除非有新内容
        }
      }
    } catch (err) {
      console.error('刷新队列失败:', err);
    }
  };

  // 添加日志辅助函数
  const addLog = (message: string, type: LogEntry['type'] = 'info') => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false });
    setLogs(prev => {
      // 防止重复日志
      if (prev.length > 0 && prev[prev.length - 1].message === message) {
        return prev;
      }
      return [...prev, {
        id: Math.random().toString(36).substring(7),
        time: timeStr,
        message,
        type
      }];
    });
  };

  // 处理全选/取消全选
  const handleSelectAll = () => {
    if (selectedItems.size === queue.length) {
      setSelectedItems(new Set());
    } else {
      setSelectedItems(new Set(queue.map(item => item.id)));
    }
  };

  // 处理单个选择
  const toggleSelection = (id: string) => {
    const newSelection = new Set(selectedItems);
    if (newSelection.has(id)) {
      newSelection.delete(id);
    } else {
      newSelection.add(id);
    }
    setSelectedItems(newSelection);
  };

  // 批量移除
  const handleRemoveSelected = async () => {
    if (selectedItems.size === 0) return;

    try {
      // 逐个移除 (API目前只支持单个移除，实际可优化为批量接口)
      for (const id of selectedItems) {
        await submitQueueApi.removeFromQueue(id);
      }
      setSelectedItems(new Set());
      await refreshQueue();
      addLog(`已移除 ${selectedItems.size} 个项目`, 'info');
    } catch (err) {
      addLog('移除项目失败', 'error');
    }
  };

  // 清除已完成
  const handleClearCompleted = async () => {
    try {
      await submitQueueApi.clearCompleted();
      await refreshQueue();
      addLog('已清除所有已完成项目', 'success');
    } catch (err) {
      addLog('清除失败', 'error');
    }
  };

  // 重置运行状态
  const handleResetStatus = async () => {
    try {
      await submitQueueApi.reset();
      setIsRunning(false);
      await refreshQueue();
      addLog('运行状态已重置', 'success');
    } catch (err) {
      addLog('重置失败', 'error');
    }
  };

  // 开始提交
  const handleStartSubmit = async () => {
    if (!selectedAccount) {
      alert('请先选择提交账号');
      return;
    }

    try {
      setIsRunning(true);
      const result = await submitQueueApi.startSubmit(selectedAccount);
      addLog(`提交队列启动: 可提交 ${result.eligible}，拦截 ${result.blocked}`, 'info');
      for (const blocked of result.blocked_items || []) {
        const item = blocked as SubmitQueueStartBlockedItem;
        addLog(formatBlockedItem(item), 'warning');
      }
      if (result.blocked > 0) {
        alert(buildSubmitStartAlert(result, 3));
      }
      await refreshQueue();
    } catch (err) {
      setIsRunning(false);
      addLog(`启动失败: ${err instanceof Error ? err.message : '未知错误'}`, 'error');
    }
  };

  // 打开添加项目模态框
  const openAddModal = async () => {
    setIsAddModalOpen(true);
    setLoadingProjects(true);
    try {
      const response = await projectApi.list();
      // 过滤掉已经在队列中的项目
      const queueProjectIds = new Set(queue.map(item => item.project_id));
      const available = response.projects.filter(p => !queueProjectIds.has(p.id));
      setAvailableProjects(available);
    } catch (err) {
      addLog('加载项目列表失败', 'error');
    } finally {
      setLoadingProjects(false);
    }
  };

  // 在模态框中选择项目
  const toggleProjectToAdd = (id: string) => {
    const newSet = new Set(projectsToAdd);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    setProjectsToAdd(newSet);
  };

  // 确认添加项目
  const handleAddProjects = async () => {
    if (projectsToAdd.size === 0) return;

    try {
      await submitQueueApi.addToQueue(Array.from(projectsToAdd));
      setProjectsToAdd(new Set());
      setIsAddModalOpen(false);
      await refreshQueue();
      addLog(`已添加 ${projectsToAdd.size} 个项目到队列`, 'success');
    } catch (err) {
      addLog('添加项目失败', 'error');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold dark:text-white">自动提交</h2>
        <div className="flex items-center gap-2">
           {isRunning && <span className="flex items-center text-sm text-green-500 gap-2 mr-4"><Loader2 className="w-4 h-4 animate-spin" /> 任务运行中</span>}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[calc(100vh-12rem)]">
        {/* Main Queue List */}
        <Card className="lg:col-span-2 flex flex-col p-0 overflow-hidden">
          <div className="p-4 border-b border-zinc-200 dark:border-zinc-800 flex justify-between items-center bg-zinc-50/50 dark:bg-zinc-900/50">
             <div className="flex items-center gap-3">
                <select
                  value={selectedAccount}
                  onChange={(e) => setSelectedAccount(e.target.value)}
                  className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-md px-3 py-1.5 text-sm focus:outline-none dark:text-white min-w-[200px]"
                >
                  <option value="" disabled>选择提交账号</option>
                  {accounts.map(acc => (
                    <option key={acc.id} value={acc.id}>{acc.description ? `${acc.description} (${acc.username})` : acc.username}</option>
                  ))}
                </select>
                <Button variant="ghost" className="text-xs h-8" onClick={openAddModal}>
                  <Plus className="w-3 h-3" /> 添加项目
                </Button>
             </div>
             <div className="flex gap-2">
               <Button
                 variant="ghost"
                 className="text-xs h-8"
                 onClick={handleSelectAll}
               >
                 {selectedItems.size === queue.length && queue.length > 0 ? '取消全选' : '全选'}
               </Button>
               <Button
                 variant="secondary"
                 className="text-xs h-8 text-red-500 hover:text-red-600"
                 onClick={handleRemoveSelected}
                 disabled={selectedItems.size === 0}
               >
                 <Trash className="w-3 h-3" /> 移除
               </Button>
             </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex justify-center items-center h-full text-zinc-400">
                <Loader2 className="w-6 h-6 animate-spin mr-2" /> 加载中...
              </div>
            ) : queue.length === 0 ? (
              <div className="flex flex-col justify-center items-center h-full text-zinc-400 gap-2">
                <p>队列为空</p>
                <Button variant="outline" size="sm" onClick={openAddModal}>添加项目到队列</Button>
              </div>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 border-b border-zinc-200 dark:border-zinc-800">
                  <tr>
                    <th className="px-6 py-3 font-medium w-12">
                      <div
                        className="cursor-pointer"
                        onClick={handleSelectAll}
                      >
                        {selectedItems.size === queue.length && queue.length > 0 ?
                          <CheckSquare className="w-4 h-4 text-blue-500" /> :
                          <Square className="w-4 h-4" />
                        }
                      </div>
                    </th>
                    <th className="px-6 py-3 font-medium">项目名称</th>
                    <th className="px-6 py-3 font-medium">状态</th>
                    <th className="px-6 py-3 font-medium">添加时间</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {queue.map((item) => (
                    <tr
                      key={item.id}
                      className={`hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors ${selectedItems.has(item.id) ? 'bg-blue-50/50 dark:bg-blue-900/10' : ''}`}
                      onClick={() => toggleSelection(item.id)}
                    >
                      <td className="px-6 py-4 text-zinc-400 cursor-pointer">
                        {selectedItems.has(item.id) ?
                          <CheckSquare className="w-4 h-4 text-blue-500" /> :
                          <Square className="w-4 h-4" />
                        }
                      </td>
                      <td className="px-6 py-4 font-medium dark:text-zinc-200">{item.project_name}</td>
                      <td className="px-6 py-4">
                        {item.status === 'pending' && <Badge status="neutral">等待中</Badge>}
                        {item.status === 'submitting' && <Badge status="warning">提交中...</Badge>}
                        {item.status === 'completed' && <Badge status="success">已完成</Badge>}
                        {item.status === 'failed' && <Badge status="error">失败</Badge>}
                      </td>
                      <td className="px-6 py-4 text-zinc-500">{new Date(item.added_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="p-4 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 flex justify-between gap-3">
             <div className="flex gap-3">
               <Button variant="secondary" onClick={handleClearCompleted}>清除已完成</Button>
               {isRunning && (
                 <Button variant="secondary" onClick={handleResetStatus} className="text-orange-500 hover:text-orange-600">
                   <RefreshCw className="w-4 h-4" /> 重置状态
                 </Button>
               )}
             </div>
             <Button onClick={handleStartSubmit} disabled={isRunning || queue.length === 0}>
               {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
               {isRunning ? '提交中...' : '开始批量提交'}
             </Button>
          </div>
        </Card>

        {/* Side Log Panel */}
        <div className="flex flex-col gap-4">
          <Card className="flex-1 flex flex-col bg-zinc-900 border-zinc-800 p-0 overflow-hidden">
             <div className="px-4 py-3 border-b border-zinc-800 font-mono text-xs text-zinc-400 flex justify-between items-center">
               <span>提交日志</span>
               <button onClick={() => setLogs([])} className="hover:text-white"><Trash className="w-3 h-3" /></button>
             </div>
             <div className="flex-1 p-4 font-mono text-xs space-y-2 overflow-y-auto">
               {logs.length === 0 ? (
                 <div className="text-zinc-600 italic">暂无日志...</div>
               ) : (
                 logs.map(log => (
                   <div key={log.id} className={`${
                     log.type === 'error' ? 'text-red-400' :
                     log.type === 'success' ? 'text-green-400' :
                     log.type === 'warning' ? 'text-yellow-400' : 'text-zinc-300'
                   }`}>
                     <span className="text-zinc-500">[{log.time}]</span> {log.message}
                   </div>
                 ))
               )}
               <div ref={logsEndRef} />
             </div>
          </Card>
        </div>
      </div>

      {/* Add Project Modal */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="添加项目到提交队列"
      >
        <div className="h-96 flex flex-col">
          {loadingProjects ? (
             <div className="flex-1 flex justify-center items-center">
               <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
             </div>
          ) : availableProjects.length === 0 ? (
             <div className="flex-1 flex justify-center items-center text-zinc-500">
               没有可添加的项目
             </div>
          ) : (
            <div className="flex-1 overflow-y-auto border border-zinc-200 dark:border-zinc-700 rounded-md mb-4">
              {availableProjects.map(project => (
                <div
                  key={project.id}
                  className={`p-3 border-b border-zinc-100 dark:border-zinc-800 cursor-pointer flex items-center justify-between hover:bg-zinc-50 dark:hover:bg-zinc-800 ${projectsToAdd.has(project.id) ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                  onClick={() => toggleProjectToAdd(project.id)}
                >
                  <span className="dark:text-zinc-200">{project.name}</span>
                  {projectsToAdd.has(project.id) ? <CheckSquare className="w-4 h-4 text-blue-500" /> : <Square className="w-4 h-4 text-zinc-300" />}
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-between items-center pt-2">
            <span className="text-sm text-zinc-500">已选择 {projectsToAdd.size} 个项目</span>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setIsAddModalOpen(false)}>取消</Button>
              <Button onClick={handleAddProjects} disabled={projectsToAdd.size === 0}>确定添加</Button>
            </div>
          </div>
        </div>
      </Modal>
    </div>
  );
};
