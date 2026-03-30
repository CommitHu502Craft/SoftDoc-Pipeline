import React, { useState, useEffect } from 'react';
import { signatureApi, accountApi, SignatureStatus, SignatureStats, Account } from '../api';
import '../styles/SignaturePage.css';

export const SignaturePage: React.FC = () => {
  const [status, setStatus] = useState<SignatureStatus>({
    step: 'idle',
    progress: 0,
    total_files: 0,
    processed_files: 0,
    logs: [],
  });
  const [stats, setStats] = useState<SignatureStats>({
    pending_download: 0,
    downloaded: 0,
    signed: 0,
    scan_effected: 0,
  });
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>('');
  const [loading, setLoading] = useState(false);

  // 加载数据
  const loadData = async () => {
    try {
      const [statusData, statsData, accountsData] = await Promise.all([
        signatureApi.getStatus(),
        signatureApi.getStats(),
        accountApi.list(),
      ]);

      setStatus(statusData);
      setStats(statsData);
      setAccounts(accountsData.accounts);
    } catch (error) {
      console.error('加载数据失败:', error);
    }
  };

  useEffect(() => {
    loadData();
    // 定时刷新状态
    const interval = setInterval(loadData, 2000);
    return () => clearInterval(interval);
  }, []);

  // 批量下载
  const handleDownload = async () => {
    if (!selectedAccount) {
      alert('请选择一个账号');
      return;
    }

    setLoading(true);
    try {
      await signatureApi.download(selectedAccount);
      alert('下载任务已启动');
    } catch (error) {
      console.error('启动下载失败:', error);
      alert('启动下载失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 批量签名
  const handleSign = async () => {
    if (stats.downloaded === 0) {
      alert('没有待签名的文件');
      return;
    }

    setLoading(true);
    try {
      await signatureApi.sign();
      alert('签名任务已启动');
    } catch (error) {
      console.error('启动签名失败:', error);
      alert('启动签名失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 批量扫描生效
  const handleScan = async () => {
    if (stats.signed === 0) {
      alert('没有待扫描的文件');
      return;
    }

    setLoading(true);
    try {
      await signatureApi.scan();
      alert('扫描任务已启动');
    } catch (error) {
      console.error('启动扫描失败:', error);
      alert('启动扫描失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 批量上传
  const handleUpload = async () => {
    if (!selectedAccount) {
      alert('请选择一个账号');
      return;
    }

    if (stats.scan_effected === 0) {
      alert('没有待上传的文件');
      return;
    }

    setLoading(true);
    try {
      await signatureApi.upload(selectedAccount);
      alert('上传任务已启动');
    } catch (error) {
      console.error('启动上传失败:', error);
      alert('启动上传失败: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // 重置状态
  const handleReset = async () => {
    if (status.step !== 'idle' && status.step !== 'completed') {
      alert('任务正在运行中，无法重置');
      return;
    }

    try {
      await signatureApi.reset();
      loadData();
    } catch (error) {
      console.error('重置失败:', error);
      alert('重置失败: ' + (error as Error).message);
    }
  };

  // 步骤文本映射
  const getStepText = (step: string) => {
    switch (step) {
      case 'idle': return '空闲';
      case 'downloading': return '下载中';
      case 'signing': return '签名中';
      case 'scanning': return '扫描中';
      case 'uploading': return '上传中';
      case 'completed': return '已完成';
      default: return step;
    }
  };

  const isRunning = status.step !== 'idle' && status.step !== 'completed';

  return (
    <div className="signature-page">
      <div className="page-header">
        <h1>签章流程管理</h1>
        <button
          className="btn btn-secondary"
          onClick={handleReset}
          disabled={isRunning}
        >
          重置状态
        </button>
      </div>

      {/* 统计面板 */}
      <div className="stats-panel">
        <div className="stat-card">
          <div className="stat-value">{stats.downloaded}</div>
          <div className="stat-label">已下载</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.signed}</div>
          <div className="stat-label">已签名</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.scan_effected}</div>
          <div className="stat-label">已扫描生效</div>
        </div>
      </div>

      {/* 当前状态 */}
      <div className="current-status">
        <h2>当前状态</h2>
        <div className="status-info">
          <div className="status-item">
            <span className="label">步骤:</span>
            <span className={`value ${isRunning ? 'running' : ''}`}>
              {getStepText(status.step)}
            </span>
          </div>
          {status.progress > 0 && (
            <div className="status-item">
              <span className="label">进度:</span>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${status.progress}%` }}>
                  {status.progress}%
                </div>
              </div>
            </div>
          )}
          {status.current_file && (
            <div className="status-item">
              <span className="label">当前文件:</span>
              <span className="value">{status.current_file}</span>
            </div>
          )}
          {status.message && (
            <div className="status-item">
              <span className="label">消息:</span>
              <span className="value">{status.message}</span>
            </div>
          )}
        </div>
      </div>

      {/* 账号选择 */}
      <div className="account-selection">
        <label>选择账号 (下载和上传需要):</label>
        <select
          value={selectedAccount}
          onChange={(e) => setSelectedAccount(e.target.value)}
          disabled={isRunning}
        >
          <option value="">请选择账号</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.username} {account.description && `(${account.description})`}
            </option>
          ))}
        </select>
      </div>

      {/* 操作按钮 */}
      <div className="action-buttons">
        <div className="action-step">
          <h3>1. 批量下载签章页</h3>
          <p>从网站下载待签名的PDF文件</p>
          <button
            className="btn btn-primary"
            onClick={handleDownload}
            disabled={loading || isRunning || !selectedAccount}
          >
            下载签章页
          </button>
        </div>

        <div className="action-step">
          <h3>2. 批量签名</h3>
          <p>对下载的PDF文件进行签名</p>
          <button
            className="btn btn-primary"
            onClick={handleSign}
            disabled={loading || isRunning || stats.downloaded === 0}
          >
            批量签名
          </button>
        </div>

        <div className="action-step">
          <h3>3. 批量扫描生效</h3>
          <p>扫描签名后的文件以验证生效</p>
          <button
            className="btn btn-primary"
            onClick={handleScan}
            disabled={loading || isRunning || stats.signed === 0}
          >
            扫描生效
          </button>
        </div>

        <div className="action-step">
          <h3>4. 批量上传</h3>
          <p>将签名后的文件上传回网站</p>
          <button
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={loading || isRunning || !selectedAccount || stats.scan_effected === 0}
          >
            上传签章
          </button>
        </div>
      </div>

      {/* 日志面板 */}
      {status.logs.length > 0 && (
        <div className="logs-panel">
          <h2>操作日志</h2>
          <div className="logs-content">
            {status.logs.map((log, index) => (
              <div key={index} className="log-entry">
                {log}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
