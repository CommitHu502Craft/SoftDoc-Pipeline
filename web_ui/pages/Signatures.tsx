import React, { useState, useEffect, useRef } from 'react';
import { Download, PenTool, ScanLine, Upload, ArrowRight, Zap, Folder, Check, RotateCcw } from 'lucide-react';
import { Button, Card } from '../components/UI';
import { signatureApi, accountApi, SignatureStatus, SignatureStats, Account } from '../api';

export const SignaturesPage: React.FC = () => {
  // 状态管理
  const [status, setStatus] = useState<SignatureStatus>({
    step: 'idle',
    progress: 0,
    total_files: 0,
    processed_files: 0,
    logs: []
  });
  const [stats, setStats] = useState<SignatureStats>({
    pending_download: 0,
    downloaded: 0,
    signed: 0,
    scan_effected: 0
  });
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // 初始化和轮询
  useEffect(() => {
    loadAccounts();
    fetchStatus();
    fetchStats();

    const interval = setInterval(() => {
      fetchStatus();
      fetchStats();
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  // 自动滚动日志
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [status.logs]);

  const loadAccounts = async () => {
    try {
      const res = await accountApi.list();
      setAccounts(res.accounts);
      if (res.accounts.length > 0) {
        setSelectedAccount(res.accounts[0].id);
      }
    } catch (err) {
      console.error('加载账号失败', err);
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await signatureApi.getStatus();
      setStatus(res);
    } catch (err) {
      console.error('获取状态失败', err);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await signatureApi.getStats();
      setStats(res);
    } catch (err) {
      console.error('获取统计失败', err);
    }
  };

  // 操作处理函数
  const handleDownload = async () => {
    if (!selectedAccount) return alert('请选择账号');
    try {
      await signatureApi.download(selectedAccount);
    } catch (err) {
      alert('启动下载失败');
    }
  };

  const handleSign = async () => {
    try {
      await signatureApi.sign();
    } catch (err) {
      alert('启动签名失败');
    }
  };

  const handleScan = async () => {
    try {
      await signatureApi.scan();
    } catch (err) {
      alert('启动扫描特效失败');
    }
  };

  const handleUpload = async () => {
    if (!selectedAccount) return alert('请选择账号');
    try {
      await signatureApi.upload(selectedAccount);
    } catch (err) {
      alert('启动上传失败');
    }
  };

  const handleReset = async () => {
    if (!confirm('确定要重置所有状态吗？这将清空当前进度。')) return;
    try {
      await signatureApi.reset();
      fetchStatus();
    } catch (err) {
      alert('重置失败');
    }
  };

  // 步骤配置
  const steps = [
    {
      id: 'downloading',
      icon: Download,
      title: "获取文件",
      desc: "自动下载待签PDF",
      color: "text-blue-500",
      bg: "bg-blue-500/10",
      action: handleDownload,
      count: stats.pending_download,
      countLabel: "待下载"
    },
    {
      id: 'signing',
      icon: PenTool,
      title: "电子签名",
      desc: "AI定位签名区域",
      color: "text-purple-500",
      bg: "bg-purple-500/10",
      action: handleSign,
      count: stats.downloaded,
      countLabel: "待签名"
    },
    {
      id: 'scanning',
      icon: ScanLine,
      title: "仿真扫描",
      desc: "添加噪点与倾斜",
      color: "text-orange-500",
      bg: "bg-orange-500/10",
      action: handleScan,
      count: stats.signed,
      countLabel: "待扫描"
    },
    {
      id: 'uploading',
      icon: Upload,
      title: "自动回传",
      desc: "提交至版权中心",
      color: "text-emerald-500",
      bg: "bg-emerald-500/10",
      action: handleUpload,
      count: stats.scan_effected,
      countLabel: "待上传"
    }
  ];

  const isActive = status.step !== 'idle' && status.step !== 'completed';

  return (
    <div className="space-y-10">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-zinc-900 to-zinc-500 dark:from-white dark:to-zinc-400">签章管理</h2>
          <p className="text-zinc-500 mt-1">智能自动化处理电子签章流程</p>
        </div>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={handleReset} disabled={isActive}>
            <RotateCcw className="w-4 h-4 mr-2" /> 重置状态
          </Button>
        </div>
      </div>

      {/* Hero Action - Glassmorphism Gradient */}
      <div className="relative overflow-hidden rounded-3xl p-10 shadow-2xl group">
        <div className={`absolute inset-0 bg-gradient-to-br from-indigo-600 to-violet-700 transition-opacity duration-1000 ${isActive ? 'opacity-100' : 'opacity-90'}`}></div>
        {/* Animated background shapes */}
        <div className={`absolute top-0 right-0 w-96 h-96 bg-white/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 transition-transform duration-1000 ${isActive ? 'scale-125 animate-pulse' : 'group-hover:scale-110'}`}></div>
        <div className="absolute bottom-0 left-0 w-64 h-64 bg-blue-500/20 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2"></div>

        <div className="relative z-10 flex flex-col md:flex-row items-center justify-between gap-8">
          <div className="text-white space-y-4 max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 backdrop-blur-md border border-white/20 text-sm font-medium text-indigo-100">
               <Zap className={`w-4 h-4 text-yellow-300 fill-current ${isActive ? 'animate-bounce' : ''}`} />
               {isActive ? '正在处理任务...' : '智能流水线就绪'}
            </div>
            <h3 className="text-3xl font-bold">
              {status.step === 'idle' ? '一键全自动处理' :
               status.step === 'completed' ? '处理完成' :
               `正在${steps.find(s => s.id === status.step)?.title.replace('获取文件', '下载文件') || '处理'}...`}
            </h3>
            <p className="text-indigo-100 text-lg leading-relaxed">
              {status.message || '系统将自动连接版权中心，批量下载待签文件，精准定位并施加电子签名，随后应用高保真扫描滤镜，最后自动回传提交。'}
            </p>

            {isActive && (
              <div className="w-full bg-white/20 rounded-full h-2 mt-4 overflow-hidden">
                <div
                  className="bg-white h-2 rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${Math.max(5, status.progress)}%` }}
                ></div>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-3 min-w-[200px]">
            {!isActive && status.step !== 'completed' && (
              <button
                onClick={handleDownload}
                className="bg-white text-indigo-600 px-8 py-4 rounded-2xl font-bold text-lg hover:bg-indigo-50 hover:shadow-xl hover:shadow-white/20 transition-all active:scale-95 flex items-center justify-center gap-2"
              >
                🚀 开始流程
              </button>
            )}

            <div className="bg-white/10 backdrop-blur rounded-xl p-4 text-white text-sm">
              <div className="flex justify-between mb-1">
                <span className="opacity-70">处理进度</span>
                <span className="font-bold">{status.processed_files} / {status.total_files}</span>
              </div>
              <div className="text-xs opacity-50 truncate">
                {status.current_file || '等待开始...'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Visual Workflow Steps */}
      <div className="relative py-4">
         {/* Connector Line */}
         <div className="absolute top-1/2 left-0 w-full h-1 bg-gradient-to-r from-zinc-200 via-zinc-300 to-zinc-200 dark:from-zinc-800 dark:via-zinc-700 dark:to-zinc-800 -translate-y-1/2 hidden md:block rounded-full z-0"></div>

         <div className="grid grid-cols-1 md:grid-cols-4 gap-6 relative z-10">
            {steps.map((step, idx) => (
              <div
                key={idx}
                className={`group glass-panel rounded-2xl p-6 text-center transition-all duration-300 border-t-4 relative overflow-hidden ${
                  status.step === step.id
                    ? `border-${step.color.split('-')[1]}-500 shadow-xl scale-105 bg-white dark:bg-zinc-800`
                    : 'border-transparent hover:-translate-y-2 hover:shadow-lg'
                }`}
              >
                 <div className={`absolute inset-0 bg-gradient-to-b from-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity`}></div>

                 <div className={`w-20 h-20 mx-auto rounded-2xl ${step.bg} flex items-center justify-center mb-4 transition-transform duration-300 shadow-inner relative`}>
                    <step.icon className={`w-10 h-10 ${step.color} ${status.step === step.id ? 'animate-pulse' : ''}`} />
                    {step.count > 0 && (
                      <div className="absolute -top-2 -right-2 bg-red-500 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center border-2 border-white dark:border-zinc-900">
                        {step.count}
                      </div>
                    )}
                 </div>

                 <h4 className="font-bold text-lg dark:text-zinc-100">{step.title}</h4>
                 <p className="text-sm text-zinc-500 mt-2 leading-relaxed">{step.desc}</p>
                 <div className="mt-2 text-xs font-medium text-zinc-400">{step.countLabel}: {step.count}</div>

                 <div className={`mt-4 pt-4 border-t border-dashed border-zinc-200 dark:border-zinc-700 transition-opacity transform ${isActive ? 'opacity-50 pointer-events-none' : 'opacity-0 group-hover:opacity-100 translate-y-2 group-hover:translate-y-0'}`}>
                    <button
                      onClick={step.action}
                      className="text-xs font-semibold text-indigo-500 hover:text-indigo-600 flex items-center justify-center gap-1 mx-auto w-full py-2 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
                    >
                       仅运行此步 <ArrowRight className="w-3 h-3" />
                    </button>
                 </div>
              </div>
            ))}
         </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Settings */}
        <Card className="lg:col-span-2" noPadding>
           <div className="p-6 border-b border-zinc-100 dark:border-white/5">
              <h3 className="font-bold text-lg dark:text-zinc-100">配置参数</h3>
           </div>
           <div className="p-8 grid grid-cols-1 md:grid-cols-2 gap-8">
              <div className="space-y-3">
                 <label className="text-sm font-semibold dark:text-zinc-300">版权中心账号</label>
                 <div className="relative">
                    <select
                      value={selectedAccount}
                      onChange={(e) => setSelectedAccount(e.target.value)}
                      className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-zinc-700 rounded-xl dark:text-white appearance-none focus:ring-2 focus:ring-indigo-500/50 outline-none"
                    >
                      <option value="" disabled>选择账号</option>
                      {accounts.map(acc => (
                        <option key={acc.id} value={acc.id}>{acc.description ? `${acc.description} (${acc.username})` : acc.username}</option>
                      ))}
                    </select>
                    <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-zinc-500">▼</div>
                 </div>
              </div>
              <div className="space-y-3">
                 <label className="text-sm font-semibold dark:text-zinc-300">签名素材库</label>
                 <div className="flex gap-2">
                    <input className="flex-1 px-4 py-3 bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-zinc-700 rounded-xl dark:text-zinc-400" value="系统默认路径" readOnly />
                    <Button variant="secondary" className="px-4"><Folder className="w-5 h-5" /></Button>
                 </div>
              </div>
              <div className="md:col-span-2 p-4 rounded-xl bg-blue-50/50 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-900/30 flex gap-4">
                  <div className="p-2 bg-blue-100 dark:bg-blue-800 rounded-lg h-fit">
                     <Check className="w-4 h-4 text-blue-600 dark:text-blue-300" />
                  </div>
                  <div>
                     <h5 className="font-semibold text-sm text-blue-900 dark:text-blue-200">准备就绪</h5>
                     <p className="text-xs text-blue-700 dark:text-blue-400 mt-1">
                       {status.step === 'idle'
                         ? `当前有 ${stats.pending_download} 个项目等待下载，${stats.downloaded} 个待签名，${stats.signed} 个待扫描。`
                         : status.message || '正在处理任务...'}
                     </p>
                  </div>
              </div>
           </div>
        </Card>

        {/* Logs */}
        <div className="glass-panel rounded-2xl overflow-hidden flex flex-col h-full bg-[#0d1117] border-zinc-800 shadow-inner min-h-[400px]">
           <div className="px-5 py-3 border-b border-zinc-800/50 bg-white/5 flex justify-between items-center">
              <span className="text-xs font-mono text-zinc-400 font-bold uppercase tracking-wider">System Terminal</span>
              <div className="flex gap-1.5">
                 <div className={`w-2.5 h-2.5 rounded-full ${isActive ? 'bg-green-500 animate-pulse' : 'bg-zinc-700'}`}></div>
                 <div className="w-2.5 h-2.5 rounded-full bg-zinc-700"></div>
              </div>
           </div>
           <div className="flex-1 p-5 font-mono text-xs space-y-3 overflow-y-auto">
              {status.logs.length === 0 ? (
                <div className="text-zinc-600 italic">&gt; 等待指令...</div>
              ) : (
                status.logs.map((log, i) => (
                  <div key={i} className="flex gap-2">
                     <span className="text-zinc-500">[{new Date().toLocaleTimeString()}]</span>
                     <span className="text-zinc-300">{log}</span>
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
           </div>
        </div>
      </div>
    </div>
  );
};
