import React from 'react';
import { Loader2 } from 'lucide-react';

export const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost', isLoading?: boolean }> = ({ 
  children, variant = 'primary', className = '', isLoading, ...props 
}) => {
  const baseStyles = "px-5 py-2.5 rounded-xl font-medium transition-all duration-300 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed active:scale-95 border border-transparent";
  
  const variants = {
    primary: "bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-500 hover:to-blue-500 text-white shadow-lg shadow-indigo-500/30 hover:shadow-indigo-500/50",
    secondary: "bg-white/50 dark:bg-zinc-800/50 hover:bg-white/80 dark:hover:bg-zinc-700/80 text-zinc-700 dark:text-zinc-200 border-zinc-200/50 dark:border-zinc-700/50 backdrop-blur-sm",
    danger: "bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white shadow-lg shadow-red-500/30",
    ghost: "bg-transparent hover:bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
  };

  return (
    <button className={`${baseStyles} ${variants[variant]} ${className}`} disabled={isLoading || props.disabled} {...props}>
      {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
      {children}
    </button>
  );
};

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement> & { noPadding?: boolean }> = ({ children, className = '', noPadding = false, ...props }) => (
  <div className={`glass-panel rounded-2xl shadow-xl shadow-black/5 ${noPadding ? '' : 'p-6'} ${className}`} {...props}>
    {children}
  </div>
);

export const Badge: React.FC<{ status: 'success' | 'warning' | 'error' | 'info' | 'neutral', children: React.ReactNode }> = ({ status, children }) => {
  const styles = {
    success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
    warning: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    error: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20",
    info: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20",
    neutral: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20"
  };
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold border ${styles[status]} backdrop-blur-md`}>
      {children}
    </span>
  );
};

export const Modal: React.FC<{ isOpen: boolean; onClose: () => void; title: string; children: React.ReactNode }> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-in fade-in duration-300">
      <div className="w-full max-w-md glass-panel bg-white/90 dark:bg-[#141416]/90 rounded-2xl shadow-2xl p-6 m-4 animate-in zoom-in-95 duration-300 border border-white/20">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-zinc-900 to-zinc-600 dark:from-white dark:to-zinc-400">{title}</h3>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 transition-colors">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
};

export const ProgressBar: React.FC<{ progress: number }> = ({ progress }) => (
  <div className="w-full h-2.5 bg-zinc-200/50 dark:bg-zinc-700/50 rounded-full overflow-hidden backdrop-blur-sm">
    <div 
      className="h-full bg-gradient-to-r from-blue-500 to-indigo-600 shadow-[0_0_10px_rgba(59,130,246,0.5)] transition-all duration-700 ease-out relative"
      style={{ width: `${progress}%` }}
    >
      <div className="absolute inset-0 bg-white/20 animate-[shimmer_2s_infinite]"></div>
    </div>
  </div>
);
