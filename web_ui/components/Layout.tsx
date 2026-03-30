import React, { useContext, useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { 
  LayoutGrid, 
  UploadCloud, 
  PenTool, 
  Settings, 
  BarChart3,
  Moon, 
  Sun, 
  Bot 
} from 'lucide-react';
import { ThemeContext } from '../App';
import { usageApi } from '../api';

export const Layout: React.FC = () => {
  const { isDark, toggleTheme } = useContext(ThemeContext);
  const location = useLocation();
  const [usagePercent, setUsagePercent] = useState(0);
  const [usageText, setUsageText] = useState('--');

  const navItems = [
    { to: "/", icon: LayoutGrid, label: "项目管理" },
    { to: "/llm-usage", icon: BarChart3, label: "LLM监控" },
    { to: "/submit", icon: UploadCloud, label: "自动提交" },
    { to: "/signatures", icon: PenTool, label: "签章管理" },
    { to: "/settings", icon: Settings, label: "系统设置" },
  ];

  useEffect(() => {
    let cancelled = false;
    const loadUsage = async () => {
      try {
        const data = await usageApi.getLlmUsage(10);
        if (cancelled) return;
        const limit = Math.max(1, Number(data.config.total_calls || 1));
        const used = Math.max(0, Number(data.summary.total_calls || 0));
        const ratio = Math.min(100, Math.round((used / limit) * 100));
        setUsagePercent(ratio);
        setUsageText(`${used}/${limit}`);
      } catch {
        if (!cancelled) {
          setUsageText('不可用');
        }
      }
    };
    void loadUsage();
    const timer = setInterval(() => {
      void loadUsage();
    }, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="flex h-screen overflow-hidden text-zinc-900 dark:text-zinc-100 font-sans transition-colors duration-300">
      {/* Glass Sidebar */}
      <aside className="w-72 flex flex-col p-6 z-20 relative">
        {/* Sidebar Background Panel */}
        <div className="absolute inset-4 rounded-3xl glass-panel -z-10 shadow-2xl shadow-indigo-500/5"></div>

        <div className="flex items-center gap-3 px-2 py-2 mb-8">
          <div className="p-2.5 bg-gradient-to-br from-indigo-500 to-blue-600 rounded-xl shadow-lg shadow-indigo-500/30">
            <Bot className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-lg tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-violet-600 dark:from-indigo-400 dark:to-violet-400">
              软著AI系统
            </h1>
            <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Pro Edition</span>
          </div>
        </div>

        <nav className="flex-1 space-y-2">
          {navItems.map((item) => {
            const isActive = location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(item.to));
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive: linkActive }) => `
                  flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition-all duration-300 relative group
                  ${linkActive 
                    ? 'text-white shadow-lg shadow-indigo-500/20' 
                    : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100'}
                `}
              >
                {({ isActive: linkActive }) => (
                  <>
                    {/* Active Background with Gradient */}
                    {linkActive && (
                      <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-blue-600 rounded-xl -z-10 animate-in fade-in zoom-in-95 duration-200"></div>
                    )}
                    {/* Hover Background */}
                    {!linkActive && (
                      <div className="absolute inset-0 bg-zinc-100/50 dark:bg-white/5 rounded-xl -z-10 opacity-0 group-hover:opacity-100 transition-opacity duration-200"></div>
                    )}
                    
                    <item.icon className={`w-5 h-5 ${linkActive ? 'text-white' : 'text-zinc-400 group-hover:text-indigo-500 dark:group-hover:text-indigo-400 transition-colors'}`} />
                    {item.label}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        <div className="pt-6 mt-auto">
          <div className="p-4 rounded-2xl bg-gradient-to-br from-indigo-500/5 to-purple-500/5 border border-indigo-500/10 mb-4">
            <div className="flex justify-between items-center mb-2">
               <span className="text-xs font-bold text-indigo-500 dark:text-indigo-400">API 使用量</span>
               <span className="text-xs text-zinc-500">{usagePercent}%</span>
            </div>
            <div className="h-1.5 w-full bg-zinc-200 dark:bg-zinc-700/50 rounded-full overflow-hidden">
               <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500" style={{ width: `${usagePercent}%` }}></div>
            </div>
            <p className="text-[11px] text-zinc-500 mt-2">调用: {usageText}</p>
          </div>

          <button
            onClick={toggleTheme}
            className="w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium text-zinc-600 dark:text-zinc-400 bg-white/50 dark:bg-black/20 hover:bg-white/80 dark:hover:bg-black/40 border border-zinc-200/50 dark:border-white/5 transition-all shadow-sm"
          >
            <span className="flex items-center gap-2">
              {isDark ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
              {isDark ? '深色模式' : '浅色模式'}
            </span>
            <div className={`w-9 h-5 rounded-full relative transition-colors duration-300 ${isDark ? 'bg-indigo-600' : 'bg-zinc-300'}`}>
              <div className={`absolute top-1 w-3 h-3 bg-white rounded-full shadow-sm transition-all duration-300 ${isDark ? 'left-5' : 'left-1'}`} />
            </div>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto h-full scrollbar-hide p-4 md:p-8 relative">
        <div className="max-w-7xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500 pb-10">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
