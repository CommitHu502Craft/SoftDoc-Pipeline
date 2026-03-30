import React, { useEffect, useMemo, useState } from 'react';
import { BarChart3, Loader2, RefreshCw } from 'lucide-react';
import { Card, Button } from '../components/UI';
import { usageApi, LlmUsageSnapshot } from '../api';

export const LlmUsagePage: React.FC = () => {
  const [snapshot, setSnapshot] = useState<LlmUsageSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadUsage = async (silent: boolean = false) => {
    try {
      if (!silent) {
        setLoading(true);
      }
      const data = await usageApi.getLlmUsage(30);
      setSnapshot(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    void loadUsage();
    const timer = setInterval(() => {
      void loadUsage(true);
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  const providerRows = useMemo(() => {
    const rows = Object.entries(snapshot?.provider_summary || {}).map(([provider, value]) => ({
      provider,
      ...value,
    }));
    rows.sort((a, b) => Number(b.total_tokens || 0) - Number(a.total_tokens || 0));
    return rows;
  }, [snapshot]);

  const stageRows = useMemo(() => {
    const stageCalls = snapshot?.summary?.stage_calls || {};
    const stageInput = snapshot?.summary?.stage_input_tokens || {};
    const stageOutput = snapshot?.summary?.stage_output_tokens || {};
    const stageTotal = snapshot?.summary?.stage_total_tokens || {};
    const stageFailures = snapshot?.summary?.stage_failures || {};

    const stages = Array.from(
      new Set([
        ...Object.keys(stageCalls),
        ...Object.keys(stageInput),
        ...Object.keys(stageOutput),
        ...Object.keys(stageTotal),
        ...Object.keys(stageFailures),
      ])
    );
    return stages
      .map((stage) => ({
        stage,
        calls: Number(stageCalls[stage] || 0),
        failures: Number(stageFailures[stage] || 0),
        input_tokens: Number(stageInput[stage] || 0),
        output_tokens: Number(stageOutput[stage] || 0),
        total_tokens: Number(stageTotal[stage] || 0),
      }))
      .sort((a, b) => b.total_tokens - a.total_tokens);
  }, [snapshot]);

  const summary = snapshot?.summary;
  const totalCalls = Number(summary?.total_calls || 0);
  const totalFailures = Number(summary?.total_failures || 0);
  const inputTokens = Number(summary?.input_tokens || 0);
  const outputTokens = Number(summary?.output_tokens || 0);
  const totalTokens = Number(summary?.total_tokens || 0);
  const callsLimit = Number(snapshot?.config?.total_calls || 1);
  const usagePercent = Math.min(100, Math.round((totalCalls / Math.max(1, callsLimit)) * 100));

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold dark:text-white flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-indigo-500" />
            LLM 使用量监控
          </h2>
          <p className="text-sm text-zinc-500 mt-1">总 tokens、输入/输出 tokens、按 API 提供商与阶段消耗</p>
        </div>
        <Button variant="secondary" onClick={() => loadUsage()} disabled={loading}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          刷新
        </Button>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <Card>
        <div className="h-2 w-full bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden mb-4">
          <div className="h-full bg-gradient-to-r from-indigo-500 to-blue-500" style={{ width: `${usagePercent}%` }} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-sm">
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
            <p className="text-zinc-500">总调用</p>
            <p className="font-semibold">{totalCalls} / {callsLimit}</p>
          </div>
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
            <p className="text-zinc-500">总失败</p>
            <p className="font-semibold">{totalFailures}</p>
          </div>
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
            <p className="text-zinc-500">输入 Tokens</p>
            <p className="font-semibold">{inputTokens}</p>
          </div>
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
            <p className="text-zinc-500">输出 Tokens</p>
            <p className="font-semibold">{outputTokens}</p>
          </div>
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
            <p className="text-zinc-500">总 Tokens</p>
            <p className="font-semibold">{totalTokens}</p>
          </div>
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
            <p className="text-zinc-500">活跃 Run</p>
            <p className="font-semibold">{Number(summary?.active_runs || 0)}</p>
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="text-lg font-semibold dark:text-zinc-100 mb-4">按 API 提供商消耗</h3>
        {providerRows.length === 0 ? (
          <p className="text-sm text-zinc-500">暂无提供商统计</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-zinc-500 border-b border-zinc-100 dark:border-zinc-800">
                  <th className="py-2 font-medium">Provider</th>
                  <th className="py-2 font-medium">调用</th>
                  <th className="py-2 font-medium">失败</th>
                  <th className="py-2 font-medium">输入 tokens</th>
                  <th className="py-2 font-medium">输出 tokens</th>
                  <th className="py-2 font-medium">总 tokens</th>
                  <th className="py-2 font-medium">模型/协议</th>
                </tr>
              </thead>
              <tbody>
                {providerRows.map((row) => (
                  <tr key={row.provider} className="border-b border-zinc-100 dark:border-zinc-900">
                    <td className="py-2 font-mono">{row.provider}</td>
                    <td className="py-2">{row.calls}</td>
                    <td className="py-2">{row.failures}</td>
                    <td className="py-2">{row.input_tokens}</td>
                    <td className="py-2">{row.output_tokens}</td>
                    <td className="py-2 font-semibold">{row.total_tokens}</td>
                    <td className="py-2 text-xs text-zinc-500">
                      model: {Object.keys(row.models || {}).join(', ') || '-'}
                      <br />
                      style: {Object.keys(row.api_styles || {}).join(', ') || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <h3 className="text-lg font-semibold dark:text-zinc-100 mb-4">按阶段消耗</h3>
          {stageRows.length === 0 ? (
            <p className="text-sm text-zinc-500">暂无阶段统计</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-zinc-500 border-b border-zinc-100 dark:border-zinc-800">
                    <th className="py-2 font-medium">阶段</th>
                    <th className="py-2 font-medium">调用</th>
                    <th className="py-2 font-medium">失败</th>
                    <th className="py-2 font-medium">总 tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {stageRows.map((row) => (
                    <tr key={row.stage} className="border-b border-zinc-100 dark:border-zinc-900">
                      <td className="py-2 font-mono">{row.stage}</td>
                      <td className="py-2">{row.calls}</td>
                      <td className="py-2">{row.failures}</td>
                      <td className="py-2">{row.total_tokens}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <h3 className="text-lg font-semibold dark:text-zinc-100 mb-4">最近运行</h3>
          {!snapshot?.runs?.length ? (
            <p className="text-sm text-zinc-500">暂无运行记录</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="text-zinc-500 border-b border-zinc-100 dark:border-zinc-800">
                    <th className="py-2 font-medium">Run ID</th>
                    <th className="py-2 font-medium">调用</th>
                    <th className="py-2 font-medium">失败</th>
                    <th className="py-2 font-medium">总 tokens</th>
                    <th className="py-2 font-medium">开始时间</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.runs.slice(0, 12).map((run) => (
                    <tr key={run.run_id} className="border-b border-zinc-100 dark:border-zinc-900">
                      <td className="py-2 font-mono">{run.run_id}</td>
                      <td className="py-2">{run.total_calls}</td>
                      <td className="py-2">{run.total_failures}</td>
                      <td className="py-2">{Number(run.total_tokens || 0)}</td>
                      <td className="py-2 text-zinc-500">{new Date(run.started_at * 1000).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
