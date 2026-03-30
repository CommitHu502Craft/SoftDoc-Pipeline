import React, { useState, useEffect } from 'react';
import { Save, Eye, EyeOff, Plus, Edit2, Trash2, Loader2 } from 'lucide-react';
import { Button, Card, Modal } from '../components/UI';
import { settingsApi, accountApi, generalSettingsApi, usageApi, Account, Settings, GeneralSettings, LlmUsageSnapshot } from '../api';

export const SettingsPage: React.FC = () => {
  // AI配置状态
  const [aiSettings, setAiSettings] = useState<Settings | null>(null);
  const [currentProvider, setCurrentProvider] = useState('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [loadedApiKeyMask, setLoadedApiKeyMask] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [maxTokens, setMaxTokens] = useState('');
  const [temperature, setTemperature] = useState('');
  const [transport, setTransport] = useState('');
  const [apiStyle, setApiStyle] = useState('');
  const [httpRetries, setHttpRetries] = useState('');
  const [retryMaxTokensCap, setRetryMaxTokensCap] = useState('');
  const [useEnvProxy, setUseEnvProxy] = useState(false);
  const [autoBypassProxyOnError, setAutoBypassProxyOnError] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [savingAI, setSavingAI] = useState(false);

  // 账号管理状态
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [isAccountModalOpen, setIsAccountModalOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [accountForm, setAccountForm] = useState({ username: '', password: '', description: '' });
  const [savingAccount, setSavingAccount] = useState(false);

  // 通用设置状态
  const [generalSettings, setGeneralSettings] = useState<GeneralSettings | null>(null);
  const [captchaWait, setCaptchaWait] = useState(60);
  const [outputDir, setOutputDir] = useState('');
  const [uiSkillEnabled, setUiSkillEnabled] = useState(true);
  const [uiSkillMode, setUiSkillMode] = useState('narrative_tool_hybrid');
  const [uiTokenPolicy, setUiTokenPolicy] = useState('balanced');
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [llmUsage, setLlmUsage] = useState<LlmUsageSnapshot | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(false);
  const [usageError, setUsageError] = useState('');
  const [isProviderModalOpen, setIsProviderModalOpen] = useState(false);
  const [newProviderName, setNewProviderName] = useState('');
  const [creatingProvider, setCreatingProvider] = useState(false);

  // 加载AI配置
  const loadAISettings = async () => {
    try {
      const settings = await settingsApi.get();
      setAiSettings(settings);
      setCurrentProvider(settings.current_provider);
      const provider = settings.providers[settings.current_provider];
      if (provider) {
        setApiKey(provider.api_key);
        setLoadedApiKeyMask(provider.api_key || '');
        setBaseUrl(provider.base_url);
        setModel(provider.model);
        setMaxTokens(provider.max_tokens != null ? String(provider.max_tokens) : '');
        setTemperature(provider.temperature != null ? String(provider.temperature) : '');
        setTransport(provider.transport || '');
        setApiStyle(provider.api_style || '');
        setHttpRetries(provider.http_retries != null ? String(provider.http_retries) : '');
        setRetryMaxTokensCap(provider.retry_max_tokens_cap != null ? String(provider.retry_max_tokens_cap) : '');
        setUseEnvProxy(Boolean(provider.use_env_proxy));
        setAutoBypassProxyOnError(Boolean(provider.auto_bypass_proxy_on_error));
      }
    } catch (err) {
      console.error('加载AI配置失败:', err);
    }
  };

  // 加载账号列表
  const loadAccounts = async () => {
    try {
      setLoadingAccounts(true);
      const response = await accountApi.list();
      setAccounts(response.accounts);
    } catch (err) {
      console.error('加载账号列表失败:', err);
    } finally {
      setLoadingAccounts(false);
    }
  };

  // 加载通用设置
  const loadGeneralSettings = async () => {
    try {
      const settings = await generalSettingsApi.get();
      setGeneralSettings(settings);
      setCaptchaWait(settings.captcha_wait_seconds);
      setOutputDir(settings.output_directory);
      setUiSkillEnabled(Boolean(settings.ui_skill_enabled));
      setUiSkillMode(settings.ui_skill_mode || 'narrative_tool_hybrid');
      setUiTokenPolicy(settings.ui_token_policy || 'balanced');
    } catch (err) {
      console.error('加载通用设置失败:', err);
    }
  };

  const loadLlmUsage = async (silent: boolean = false) => {
    try {
      if (!silent) {
        setLoadingUsage(true);
      }
      const snapshot = await usageApi.getLlmUsage(10);
      setLlmUsage(snapshot);
      setUsageError('');
    } catch (err) {
      console.error('加载 LLM 使用量失败:', err);
      setUsageError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (!silent) {
        setLoadingUsage(false);
      }
    }
  };

  useEffect(() => {
    loadAISettings();
    loadAccounts();
    loadGeneralSettings();
    loadLlmUsage();
    const timer = setInterval(() => {
      void loadLlmUsage(true);
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!aiSettings) return;
    const provider = aiSettings.providers[currentProvider];
    if (!provider) return;
    setApiKey(provider.api_key || '');
    setLoadedApiKeyMask(provider.api_key || '');
    setBaseUrl(provider.base_url || '');
    setModel(provider.model || '');
    setMaxTokens(provider.max_tokens != null ? String(provider.max_tokens) : '');
    setTemperature(provider.temperature != null ? String(provider.temperature) : '');
    setTransport(provider.transport || '');
    setApiStyle(provider.api_style || '');
    setHttpRetries(provider.http_retries != null ? String(provider.http_retries) : '');
    setRetryMaxTokensCap(provider.retry_max_tokens_cap != null ? String(provider.retry_max_tokens_cap) : '');
    setUseEnvProxy(Boolean(provider.use_env_proxy));
    setAutoBypassProxyOnError(Boolean(provider.auto_bypass_proxy_on_error));
  }, [aiSettings, currentProvider]);

  const buildProviderPayload = (providerName: string) => {
    const payload: {
      current_provider: string;
      api_key?: string;
      base_url: string;
      model: string;
      max_tokens?: number;
      temperature?: number;
      transport?: string;
      api_style?: string;
      http_retries?: number;
      retry_max_tokens_cap?: number;
      use_env_proxy?: boolean;
      auto_bypass_proxy_on_error?: boolean;
    } = {
      current_provider: providerName,
      base_url: baseUrl.trim() || 'https://api.deepseek.com',
      model: model.trim() || 'deepseek-chat',
    };

    const normalizedKey = apiKey.trim();
    if (
      normalizedKey &&
      normalizedKey !== loadedApiKeyMask &&
      !normalizedKey.endsWith('...')
    ) {
      payload.api_key = normalizedKey;
    }

    const parsedMaxTokens = Number(maxTokens);
    if (maxTokens.trim() && Number.isFinite(parsedMaxTokens)) {
      payload.max_tokens = parsedMaxTokens;
    }

    const parsedTemperature = Number(temperature);
    if (temperature.trim() && Number.isFinite(parsedTemperature)) {
      payload.temperature = parsedTemperature;
    }

    const parsedRetries = Number(httpRetries);
    if (httpRetries.trim() && Number.isFinite(parsedRetries)) {
      payload.http_retries = parsedRetries;
    }

    const parsedRetryCap = Number(retryMaxTokensCap);
    if (retryMaxTokensCap.trim() && Number.isFinite(parsedRetryCap)) {
      payload.retry_max_tokens_cap = parsedRetryCap;
    }

    if (transport.trim()) {
      payload.transport = transport.trim();
    }
    if (apiStyle.trim()) {
      payload.api_style = apiStyle.trim();
    }
    payload.use_env_proxy = useEnvProxy;
    payload.auto_bypass_proxy_on_error = autoBypassProxyOnError;
    return payload;
  };

  // 保存AI配置
  const handleSaveAI = async () => {
    try {
      setSavingAI(true);
      await settingsApi.update(buildProviderPayload(currentProvider));
      alert('AI配置保存成功！');
      await loadAISettings();
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSavingAI(false);
    }
  };

  const handleCreateProvider = async () => {
    const providerName = newProviderName.trim();
    if (!providerName) {
      alert('请输入 Provider 名称');
      return;
    }
    if (!/^[a-zA-Z0-9_-]{2,32}$/.test(providerName)) {
      alert('Provider 名称仅支持 2-32 位字母、数字、下划线或中划线');
      return;
    }
    const exists = Boolean(aiSettings?.providers?.[providerName]);
    if (exists) {
      alert('该 Provider 已存在，请直接切换使用');
      return;
    }

    try {
      setCreatingProvider(true);
      await settingsApi.update(buildProviderPayload(providerName));
      await loadAISettings();
      setCurrentProvider(providerName);
      setNewProviderName('');
      setIsProviderModalOpen(false);
      alert(`已创建并切换到 Provider: ${providerName}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : '创建 Provider 失败');
    } finally {
      setCreatingProvider(false);
    }
  };

  // 打开账号模态框
  const openAccountModal = (account?: Account) => {
    if (account) {
      setEditingAccount(account);
      setAccountForm({
        username: account.username,
        password: '', // 不显示密码
        description: account.description,
      });
    } else {
      setEditingAccount(null);
      setAccountForm({ username: '', password: '', description: '' });
    }
    setIsAccountModalOpen(true);
  };

  // 保存账号
  const handleSaveAccount = async () => {
    if (!accountForm.username.trim()) {
      alert('请输入用户名');
      return;
    }
    if (!editingAccount && !accountForm.password.trim()) {
      alert('请输入密码');
      return;
    }

    try {
      setSavingAccount(true);
      if (editingAccount) {
        // 更新账号
        const updateData: any = {
          username: accountForm.username,
          description: accountForm.description,
        };
        if (accountForm.password) {
          updateData.password = accountForm.password;
        }
        await accountApi.update(editingAccount.id, updateData);
      } else {
        // 创建账号
        await accountApi.create({
          username: accountForm.username,
          password: accountForm.password,
          description: accountForm.description,
        });
      }
      setIsAccountModalOpen(false);
      await loadAccounts();
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSavingAccount(false);
    }
  };

  // 删除账号
  const handleDeleteAccount = async (id: string) => {
    if (!confirm('确定要删除这个账号吗？')) return;

    try {
      await accountApi.delete(id);
      await loadAccounts();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  // 保存通用设置
  const handleSaveGeneral = async () => {
    try {
      setSavingGeneral(true);
      await generalSettingsApi.update({
        captcha_wait_seconds: captchaWait,
        output_directory: outputDir,
        ui_skill_enabled: uiSkillEnabled,
        ui_skill_mode: uiSkillMode,
        ui_token_policy: uiTokenPolicy,
      });
      alert('通用设置保存成功！');
      await loadGeneralSettings();
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSavingGeneral(false);
    }
  };

  const usagePercent = llmUsage
    ? Math.min(
        100,
        Math.round(
          (Number(llmUsage.summary.total_calls || 0) /
            Math.max(1, Number(llmUsage.config.total_calls || 1))) * 100
        )
      )
    : 0;
  const providerOptions = Object.keys(aiSettings?.providers || {});

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <h2 className="text-2xl font-bold dark:text-white">系统设置</h2>

      <Card>
        <div className="flex items-center justify-between mb-4 border-b border-zinc-100 dark:border-zinc-800 pb-2">
          <h3 className="text-lg font-semibold dark:text-zinc-100">LLM API 使用量</h3>
          <Button variant="ghost" className="text-sm" onClick={() => loadLlmUsage()} disabled={loadingUsage}>
            {loadingUsage ? <Loader2 className="w-4 h-4 animate-spin" /> : '刷新'}
          </Button>
        </div>
        {!llmUsage ? (
          <p className="text-sm text-zinc-500">{usageError || (loadingUsage ? '正在加载使用量...' : '暂无数据')}</p>
        ) : (
          <div className="space-y-4">
            <div className="h-2 w-full bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-indigo-500 to-blue-500" style={{ width: `${usagePercent}%` }} />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
                <p className="text-zinc-500">总调用</p>
                <p className="font-semibold">{llmUsage.summary.total_calls} / {llmUsage.config.total_calls}</p>
              </div>
              <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
                <p className="text-zinc-500">总失败</p>
                <p className="font-semibold">{llmUsage.summary.total_failures} / {llmUsage.config.total_failures}</p>
              </div>
              <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
                <p className="text-zinc-500">活跃 Run</p>
                <p className="font-semibold">{llmUsage.summary.active_runs}</p>
              </div>
              <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/40 p-3">
                <p className="text-zinc-500">缓存</p>
                <p className="font-semibold">{llmUsage.cache.entries} / {llmUsage.cache.max_entries}</p>
              </div>
            </div>
            {llmUsage.runs.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="text-zinc-500 border-b border-zinc-100 dark:border-zinc-800">
                      <th className="py-2 font-medium">Run ID</th>
                      <th className="py-2 font-medium">调用</th>
                      <th className="py-2 font-medium">失败</th>
                      <th className="py-2 font-medium">开始时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {llmUsage.runs.slice(0, 5).map((run) => (
                      <tr key={run.run_id} className="border-b border-zinc-100 dark:border-zinc-900">
                        <td className="py-2 font-mono">{run.run_id}</td>
                        <td className="py-2">{run.total_calls}</td>
                        <td className="py-2">{run.total_failures}</td>
                        <td className="py-2 text-zinc-500">{new Date(run.started_at * 1000).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {usageError && <p className="text-xs text-orange-500">{usageError}</p>}
          </div>
        )}
      </Card>

      {/* API Configuration */}
      <Card>
        <h3 className="text-lg font-semibold mb-6 dark:text-zinc-100 border-b border-zinc-100 dark:border-zinc-800 pb-2">LLM API 配置</h3>
        <div className="space-y-4 max-w-2xl">
          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">服务商 (Provider)</label>
            <div className="col-span-2 flex gap-2">
              <select
                value={currentProvider}
                onChange={(e) => setCurrentProvider(e.target.value)}
                className="flex-1 px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              >
                {providerOptions.length === 0 && (
                  <option value={currentProvider}>{currentProvider || 'default'}</option>
                )}
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
              <Button variant="secondary" onClick={() => setIsProviderModalOpen(true)}>
                <Plus className="w-4 h-4" /> 新建
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">API 密钥 (API Key)</label>
            <div className="col-span-2 relative">
              <input
                type={showApiKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="请输入API密钥"
                className="w-full pl-3 pr-10 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
              <button
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
              >
                {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">API 地址 (Base URL)</label>
            <div className="col-span-2">
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.deepseek.com"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">模型名称 (Model)</label>
            <div className="col-span-2">
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="deepseek-chat"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">max_tokens</label>
            <div className="col-span-2">
              <input
                type="number"
                value={maxTokens}
                onChange={(e) => setMaxTokens(e.target.value)}
                placeholder="4096"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">temperature</label>
            <div className="col-span-2">
              <input
                type="number"
                step="0.1"
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                placeholder="0.7"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">transport</label>
            <div className="col-span-2">
              <input
                type="text"
                value={transport}
                onChange={(e) => setTransport(e.target.value)}
                placeholder="openai_chat / openai_responses / gemini"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">api_style</label>
            <div className="col-span-2">
              <input
                type="text"
                value={apiStyle}
                onChange={(e) => setApiStyle(e.target.value)}
                placeholder="chat / responses / generateContent"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">http_retries</label>
            <div className="col-span-2">
              <input
                type="number"
                value={httpRetries}
                onChange={(e) => setHttpRetries(e.target.value)}
                placeholder="2"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">retry_max_tokens_cap</label>
            <div className="col-span-2">
              <input
                type="number"
                value={retryMaxTokensCap}
                onChange={(e) => setRetryMaxTokensCap(e.target.value)}
                placeholder="30000"
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">代理策略</label>
            <div className="col-span-2 flex items-center gap-6 text-sm text-zinc-600 dark:text-zinc-300">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={useEnvProxy}
                  onChange={(e) => setUseEnvProxy(e.target.checked)}
                />
                use_env_proxy
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={autoBypassProxyOnError}
                  onChange={(e) => setAutoBypassProxyOnError(e.target.checked)}
                />
                auto_bypass_proxy_on_error
              </label>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary">测试连接</Button>
            <Button onClick={handleSaveAI} disabled={savingAI}>
              {savingAI ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {savingAI ? '保存中...' : '保存配置'}
            </Button>
          </div>
        </div>
      </Card>

      {/* Account Management */}
      <Card>
        <div className="flex justify-between items-center mb-6 border-b border-zinc-100 dark:border-zinc-800 pb-2">
          <h3 className="text-lg font-semibold dark:text-zinc-100">提交账号管理</h3>
          <Button variant="ghost" className="text-sm" onClick={() => openAccountModal()}>
            <Plus className="w-4 h-4" /> 添加账号
          </Button>
        </div>

        {loadingAccounts ? (
          <div className="flex justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-zinc-500">
                <th className="pb-3 font-medium">用户名</th>
                <th className="pb-3 font-medium">描述</th>
                <th className="pb-3 font-medium">创建时间</th>
                <th className="pb-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {accounts.map((acc) => (
                <tr key={acc.id} className="group">
                  <td className="py-3 font-medium dark:text-zinc-200">{acc.username}</td>
                  <td className="py-3 text-zinc-500">{acc.description || '-'}</td>
                  <td className="py-3 text-zinc-500 text-xs">{acc.created_at}</td>
                  <td className="py-3 flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      className="p-1 hover:text-blue-500"
                      onClick={() => openAccountModal(acc)}
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      className="p-1 hover:text-red-500"
                      onClick={() => handleDeleteAccount(acc.id)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {accounts.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-zinc-400">
                    暂无账号，请点击上方"添加账号"按钮
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      {/* General Settings */}
      <Card>
        <h3 className="text-lg font-semibold mb-6 dark:text-zinc-100 border-b border-zinc-100 dark:border-zinc-800 pb-2">通用设置</h3>
        <div className="space-y-4 max-w-2xl">
          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">验证码等待 (秒)</label>
            <div className="col-span-2">
              <input
                type="number"
                value={captchaWait}
                onChange={(e) => setCaptchaWait(parseInt(e.target.value) || 60)}
                className="w-24 px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">输出目录</label>
            <div className="col-span-2 flex gap-2">
              <input
                type="text"
                value={outputDir}
                onChange={(e) => setOutputDir(e.target.value)}
                className="flex-1 px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              />
              <Button variant="secondary">浏览</Button>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">UI Skill 编排</label>
            <div className="col-span-2 flex items-center gap-3 text-sm text-zinc-600 dark:text-zinc-300">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={uiSkillEnabled}
                  onChange={(e) => setUiSkillEnabled(e.target.checked)}
                />
                启用
              </label>
              <span className="text-xs text-zinc-400">启用后将输出 ui_blueprint/screenshot_contract</span>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">UI 模式</label>
            <div className="col-span-2">
              <select
                value={uiSkillMode}
                onChange={(e) => setUiSkillMode(e.target.value)}
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              >
                <option value="narrative_tool_hybrid">narrative_tool_hybrid</option>
                <option value="tool_first">tool_first</option>
                <option value="narrative_first">narrative_first</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4 items-center">
            <label className="text-sm font-medium text-zinc-600 dark:text-zinc-400">Token 策略</label>
            <div className="col-span-2">
              <select
                value={uiTokenPolicy}
                onChange={(e) => setUiTokenPolicy(e.target.value)}
                className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
              >
                <option value="economy">economy</option>
                <option value="balanced">balanced</option>
                <option value="quality_first">quality_first</option>
              </select>
            </div>
          </div>
          <div className="flex justify-end pt-4">
            <Button onClick={handleSaveGeneral} disabled={savingGeneral}>
              {savingGeneral ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {savingGeneral ? '保存中...' : '保存设置'}
            </Button>
          </div>
        </div>
      </Card>

      {/* Account Modal */}
      <Modal
        isOpen={isAccountModalOpen}
        onClose={() => setIsAccountModalOpen(false)}
        title={editingAccount ? '编辑账号' : '添加账号'}
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-2">用户名</label>
            <input
              type="text"
              value={accountForm.username}
              onChange={(e) => setAccountForm({ ...accountForm, username: e.target.value })}
              placeholder="例如：138****1234"
              className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-2">
              密码 {editingAccount && <span className="text-xs text-zinc-400">(留空则不修改)</span>}
            </label>
            <input
              type="password"
              value={accountForm.password}
              onChange={(e) => setAccountForm({ ...accountForm, password: e.target.value })}
              placeholder={editingAccount ? "留空则不修改" : "请输入密码"}
              className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-2">描述（可选）</label>
            <input
              type="text"
              value={accountForm.description}
              onChange={(e) => setAccountForm({ ...accountForm, description: e.target.value })}
              placeholder="例如：主账号 - 生产环境"
              className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setIsAccountModalOpen(false)} disabled={savingAccount}>
              取消
            </Button>
            <Button onClick={handleSaveAccount} disabled={savingAccount}>
              {savingAccount ? <><Loader2 className="w-4 h-4 animate-spin" /> 保存中...</> : '保存'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={isProviderModalOpen}
        onClose={() => setIsProviderModalOpen(false)}
        title="新建 Provider"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-2">Provider 名称</label>
            <input
              type="text"
              value={newProviderName}
              onChange={(e) => setNewProviderName(e.target.value)}
              placeholder="例如：openai_proxy_a"
              className="w-full px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-white focus:ring-2 focus:ring-blue-500 outline-none"
            />
            <p className="text-xs text-zinc-500 mt-2">
              会按当前表单参数创建 Provider，可立即切换使用。
            </p>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setIsProviderModalOpen(false)} disabled={creatingProvider}>
              取消
            </Button>
            <Button onClick={handleCreateProvider} disabled={creatingProvider}>
              {creatingProvider ? <><Loader2 className="w-4 h-4 animate-spin" /> 创建中...</> : '创建并切换'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
