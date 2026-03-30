import React, { useState, useEffect } from 'react';
import {
  submitQueueApi,
  accountApi,
  projectApi,
  SubmitQueueItem,
  Account,
  Project,
} from '../api';
import { buildSubmitStartAlert } from './submitShared';
import '../styles/SubmitQueuePage.css';

export const SubmitQueuePage: React.FC = () => {
  const [queueItems, setQueueItems] = useState<SubmitQueueItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedAccount, setSelectedAccount] = useState<string>('');
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]);
  const [showAddModal, setShowAddModal] = useState(false);

  // 加载数据
  const loadData = async () => {
    setLoading(true);
    try {
      const [queueResponse, accountsResponse, projectsResponse] = await Promise.all([
        submitQueueApi.getQueue(),
        accountApi.list(),
        projectApi.list(),
      ]);

      setQueueItems(queueResponse.items);
      setIsRunning(queueResponse.is_running);
      setAccounts(accountsResponse.accounts);
      setProjects(projectsResponse.projects);
    } catch (error) {
      console.error('加载数据失败:', error);
      alert('加载数据失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // 定时刷新队列状态
    const interval = setInterval(loadData, 3000);
    return () => clearInterval(interval);
  }, []);

  // 添加到队列
  const handleAddToQueue = async () => {
    if (selectedProjects.length === 0) {
      alert('请至少选择一个项目');
      return;
    }

    setLoading(true);
    try {
      await submitQueueApi.addToQueue(selectedProjects);
      alert('已添加到队列');
      setShowAddModal(false);
      setSelectedProjects([]);
      loadData();
    } catch (error) {
      console.error('添加到队列失败:', error);
      alert('添加到队列失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 从队列移除
  const handleRemove = async (itemId: string) => {
    if (!confirm('确定要从队列中移除此项吗？')) return;

    setLoading(true);
    try {
      await submitQueueApi.removeFromQueue(itemId);
      loadData();
    } catch (error) {
      console.error('移除失败:', error);
      alert('移除失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 清除已完成
  const handleClearCompleted = async () => {
    if (!confirm('确定要清除所有已完成和失败的项吗？')) return;

    setLoading(true);
    try {
      await submitQueueApi.clearCompleted();
      alert('已清除完成项');
      loadData();
    } catch (error) {
      console.error('清除失败:', error);
      alert('清除失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 启动提交
  const handleStartSubmit = async () => {
    if (!selectedAccount) {
      alert('请选择一个账号');
      return;
    }

    if (!confirm('确定要开始提交吗？')) return;

    setLoading(true);
    try {
      const result = await submitQueueApi.startSubmit(selectedAccount);
      alert(buildSubmitStartAlert(result, 3));
      loadData();
    } catch (error) {
      console.error('启动提交失败:', error);
      alert('启动提交失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 状态颜色映射
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'status-pending';
      case 'submitting': return 'status-running';
      case 'completed': return 'status-completed';
      case 'failed': return 'status-error';
      default: return '';
    }
  };

  // 状态文本映射
  const getStatusText = (status: string) => {
    switch (status) {
      case 'pending': return '等待中';
      case 'submitting': return '提交中';
      case 'completed': return '已完成';
      case 'failed': return '失败';
      default: return status;
    }
  };

  return (
    <div className="submit-queue-page">
      <div className="page-header">
        <h1>提交队列</h1>
        <div className="header-actions">
          <button
            className="btn btn-secondary"
            onClick={handleClearCompleted}
            disabled={loading || isRunning}
          >
            清除已完成
          </button>
          <button
            className="btn btn-primary"
            onClick={() => setShowAddModal(true)}
            disabled={loading || isRunning}
          >
            + 添加项目
          </button>
        </div>
      </div>

      {/* 控制面板 */}
      <div className="control-panel">
        <div className="form-group">
          <label>选择账号:</label>
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            disabled={loading || isRunning}
          >
            <option value="">请选择账号</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.username} {account.description && `(${account.description})`}
              </option>
            ))}
          </select>
        </div>

        <button
          className="btn btn-success"
          onClick={handleStartSubmit}
          disabled={loading || isRunning || !selectedAccount || queueItems.length === 0}
        >
          {isRunning ? '提交中...' : '开始提交'}
        </button>

        {isRunning && <span className="running-indicator">● 正在运行</span>}
      </div>

      {/* 队列列表 */}
      <div className="queue-list">
        {loading && queueItems.length === 0 ? (
          <div className="loading">加载中...</div>
        ) : queueItems.length === 0 ? (
          <div className="empty-state">
            <p>队列为空，点击"添加项目"按钮添加项目到队列</p>
          </div>
        ) : (
          <table className="queue-table">
            <thead>
              <tr>
                <th>项目名称</th>
                <th>状态</th>
                <th>添加时间</th>
                <th>开始时间</th>
                <th>完成时间</th>
                <th>错误信息</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {queueItems.map((item) => (
                <tr key={item.id}>
                  <td>{item.project_name}</td>
                  <td>
                    <span className={`status-badge ${getStatusColor(item.status)}`}>
                      {getStatusText(item.status)}
                    </span>
                  </td>
                  <td>{item.added_at}</td>
                  <td>{item.started_at || '-'}</td>
                  <td>{item.completed_at || '-'}</td>
                  <td className="error-cell">{item.error || '-'}</td>
                  <td>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => handleRemove(item.id)}
                      disabled={loading || isRunning || item.status === 'submitting'}
                    >
                      移除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 添加项目模态框 */}
      {showAddModal && (
        <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>添加项目到队列</h2>
            <div className="projects-selection">
              {projects
                .filter((p) => p.status === 'completed')
                .map((project) => (
                  <label key={project.id} className="project-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedProjects.includes(project.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedProjects([...selectedProjects, project.id]);
                        } else {
                          setSelectedProjects(selectedProjects.filter((id) => id !== project.id));
                        }
                      }}
                    />
                    <span>{project.name}</span>
                    <span className="project-date">{project.created_at}</span>
                  </label>
                ))}
              {projects.filter((p) => p.status === 'completed').length === 0 && (
                <div className="empty-state">暂无已完成的项目</div>
              )}
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setShowAddModal(false);
                  setSelectedProjects([]);
                }}
                disabled={loading}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleAddToQueue}
                disabled={loading || selectedProjects.length === 0}
              >
                添加 ({selectedProjects.length})
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
