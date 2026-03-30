import React, { useEffect, useRef } from 'react';
import { LogEntry } from '../types';
import { Terminal } from 'lucide-react';

export const LogViewer: React.FC<{ logs: LogEntry[] }> = ({ logs }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'INFO': return 'text-blue-400';
      case 'SUCCESS': return 'text-emerald-400';
      case 'WARNING': return 'text-amber-400';
      case 'ERROR': return 'text-rose-400';
      default: return 'text-zinc-400';
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#1e1e24] dark:bg-[#0d1117] rounded-2xl border border-zinc-700/50 dark:border-zinc-800 overflow-hidden shadow-2xl font-mono text-sm relative">
      {/* Glossy Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/50 dark:border-zinc-800 bg-white/5 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <Terminal className="w-4 h-4 text-zinc-400" />
          <span className="text-xs font-bold text-zinc-300 tracking-wider">TERMINAL OUTPUT</span>
        </div>
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-rose-500/80"></div>
          <div className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></div>
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></div>
        </div>
      </div>
      
      <div className="flex-1 p-5 overflow-y-auto custom-scrollbar space-y-2 bg-gradient-to-b from-transparent to-black/20">
        {logs.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-2 opacity-50">
             <div className="w-2 h-2 bg-zinc-500 rounded-full animate-ping"></div>
             <div className="italic">$ 等待任务初始化...</div>
          </div>
        )}
        {logs.map((log) => (
          <div key={log.id} className="flex gap-3 font-mono group hover:bg-white/5 p-0.5 rounded -mx-1 px-1 transition-colors">
            <span className="text-zinc-600 shrink-0 select-none text-xs pt-0.5">[{log.timestamp}]</span>
            <span className={`${getLevelColor(log.level)} font-bold shrink-0 w-16 text-xs pt-0.5`}>{log.level}</span>
            <span className="text-zinc-300 break-all leading-relaxed group-hover:text-white transition-colors">{log.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};