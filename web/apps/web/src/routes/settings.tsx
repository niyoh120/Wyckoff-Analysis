import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { ExternalLink, User, ShieldCheck, Database, Brain, Bell, ChevronDown, Eye, EyeOff } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { PROVIDERS, PROVIDER_LABELS, PROVIDER_BASE_URLS, PROVIDER_DEFAULT_MODELS } from '@wyckoff/shared'
import type { Provider } from '@wyckoff/shared'
import { usePreferences } from '@/lib/preferences'
import { buildSettingsCapabilityRows, summarizeSettingsCapabilities } from '@/lib/settings-capabilities'

interface ProviderConfig {
  api_key: string
  model: string
  base_url: string
}

export function SettingsPage() {
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [chatProvider, setChatProvider] = useState<Provider>('1route')
  const [configs, setConfigs] = useState<Record<string, ProviderConfig>>(() => buildDefaultProviderConfigs())
  const [tickflowKey, setTickflowKey] = useState('')
  const [feishuWebhook, setFeishuWebhook] = useState('')
  const [wecomWebhook, setWecomWebhook] = useState('')
  const [dingtalkWebhook, setDingtalkWebhook] = useState('')
  const [tgBotToken, setTgBotToken] = useState('')
  const [tgChatId, setTgChatId] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState('')
  const [activeTab, setActiveTab] = useState<'capability' | 'sources' | 'model' | 'notifications' | 'account'>('capability')
  const [toastKind, setToastKind] = useState<'success' | 'error'>('success')
  const toastTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const activeModelConfig = configs[chatProvider]
  const settingsCapabilities = useMemo(
    () => buildSettingsCapabilityRows({
      tickflow: tickflowKey,
      modelProviderLabel: PROVIDER_LABELS[chatProvider],
      modelConfig: activeModelConfig,
    }),
    [tickflowKey, chatProvider, activeModelConfig],
  )
  const settingsCapabilitySummary = useMemo(
    () => summarizeSettingsCapabilities(settingsCapabilities),
    [settingsCapabilities],
  )

  useEffect(() => () => clearTimeout(toastTimerRef.current), [])

  const loadSettings = useCallback(async (userId: string) => {
    const { data } = await supabase
      .from('user_settings')
      .select('*')
      .eq('user_id', userId)
      .single()

    if (!data) return

    const savedProvider = data.chat_provider as Provider
    setChatProvider(PROVIDERS.includes(savedProvider) ? savedProvider : '1route')
    setTickflowKey(data.tickflow_api_key || '')
    setFeishuWebhook(data.feishu_webhook || '')
    setWecomWebhook(data.wecom_webhook || '')
    setDingtalkWebhook(data.dingtalk_webhook || '')
    setTgBotToken(data.tg_bot_token || '')
    setTgChatId(data.tg_chat_id || '')

    const custom = typeof data.custom_providers === 'string'
      ? JSON.parse(data.custom_providers || '{}')
      : (data.custom_providers || {})

    const cfgs: Record<string, ProviderConfig> = buildDefaultProviderConfigs()
    for (const p of PROVIDERS) {
      if (p === 'gemini') {
        cfgs[p] = {
          api_key: data.gemini_api_key || '',
          model: data.gemini_model || PROVIDER_DEFAULT_MODELS.gemini,
          base_url: data.gemini_base_url || PROVIDER_BASE_URLS.gemini,
        }
      } else if (p === 'openai') {
        cfgs[p] = {
          api_key: data.openai_api_key || '',
          model: data.openai_model || PROVIDER_DEFAULT_MODELS.openai,
          base_url: data.openai_base_url || PROVIDER_BASE_URLS.openai,
        }
      } else if (p === 'deepseek') {
        cfgs[p] = {
          api_key: data.deepseek_api_key || '',
          model: data.deepseek_model || PROVIDER_DEFAULT_MODELS.deepseek,
          base_url: data.deepseek_base_url || PROVIDER_BASE_URLS.deepseek,
        }
      } else if (p === 'anthropic') {
        cfgs[p] = {
          api_key: data.anthropic_api_key || '',
          model: data.anthropic_model || PROVIDER_DEFAULT_MODELS.anthropic,
          base_url: data.anthropic_base_url || PROVIDER_BASE_URLS.anthropic,
        }
      } else {
        const info = custom[p] || {}
        cfgs[p] = {
          api_key: info.apikey || info.api_key || '',
          model: info.model || PROVIDER_DEFAULT_MODELS[p],
          base_url: info.baseurl || info.base_url || PROVIDER_BASE_URLS[p] || '',
        }
      }
    }
    setConfigs(cfgs)
  }, [])

  useEffect(() => {
    if (user?.id) void loadSettings(user.id)
  }, [user?.id, loadSettings])

  function updateConfig(provider: string, field: keyof ProviderConfig, value: string) {
    setConfigs((prev) => {
      const current = prev[provider] || { api_key: '', model: '', base_url: '' }
      return { ...prev, [provider]: { ...current, [field]: value } }
    })
  }

  async function handleSave() {
    if (!user) return
    setSaving(true)
    setToast('')

    const custom_providers: Record<string, object> = {}
    for (const p of ['1route'] as const) {
      const c = configs[p]
      if (c) {
        custom_providers[p] = {
          apikey: c.api_key,
          model: c.model || PROVIDER_DEFAULT_MODELS[p],
          baseurl: c.base_url || PROVIDER_BASE_URLS[p],
        }
      }
    }

    const settings = {
      user_id: user.id,
      chat_provider: chatProvider,
      gemini_api_key: configs.gemini?.api_key || '',
      gemini_model: configs.gemini?.model || PROVIDER_DEFAULT_MODELS.gemini,
      gemini_base_url: configs.gemini?.base_url || PROVIDER_BASE_URLS.gemini,
      openai_api_key: configs.openai?.api_key || '',
      openai_model: configs.openai?.model || PROVIDER_DEFAULT_MODELS.openai,
      openai_base_url: configs.openai?.base_url || PROVIDER_BASE_URLS.openai,
      deepseek_api_key: configs.deepseek?.api_key || '',
      deepseek_model: configs.deepseek?.model || PROVIDER_DEFAULT_MODELS.deepseek,
      deepseek_base_url: configs.deepseek?.base_url || PROVIDER_BASE_URLS.deepseek,
      anthropic_api_key: configs.anthropic?.api_key || '',
      anthropic_model: configs.anthropic?.model || PROVIDER_DEFAULT_MODELS.anthropic,
      anthropic_base_url: configs.anthropic?.base_url || PROVIDER_BASE_URLS.anthropic,
      custom_providers,
      tickflow_api_key: tickflowKey,
      feishu_webhook: feishuWebhook,
      wecom_webhook: wecomWebhook,
      dingtalk_webhook: dingtalkWebhook,
      tg_bot_token: tgBotToken,
      tg_chat_id: tgChatId,
    }

    const { error } = await supabase.from('user_settings').upsert(settings)
    setSaving(false)
    setToastKind(error ? 'error' : 'success')
    setToast(error ? t('settings.saveFailed', { message: error.message }) : t('settings.saved'))
    clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(''), 3000)
  }

  const tabs = [
    { id: 'capability', label: t('settings.capabilityCenter'), icon: ShieldCheck },
    { id: 'sources', label: t('settings.dataSources'), icon: Database },
    { id: 'model', label: t('settings.modelConfig'), icon: Brain },
    { id: 'notifications', label: t('settings.notifications'), icon: Bell },
    { id: 'account', label: t('settings.account'), icon: User },
  ] as const
  const canSaveActiveTab = activeTab === 'sources' || activeTab === 'model' || activeTab === 'notifications'

  return (
    <div className="h-full overflow-auto p-4 sm:p-6 bg-background/50">
      <div className="mx-auto max-w-5xl">
        <h1 className="mb-6 bg-gradient-to-r from-primary to-indigo-500 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
          {t('settings.title')}
        </h1>

        {toast && (
          <div className={`mb-6 rounded-xl px-4 py-3 text-sm shadow-sm transition-all border ${
            toastKind === 'error'
              ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-200 dark:border-red-500/20'
              : 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-200 dark:border-indigo-500/20'
          }`}>
            {toast}
          </div>
        )}

        <div className="flex flex-col md:flex-row gap-6 items-start">
          {/* Side tabs */}
          <div className="flex w-full shrink-0 flex-row gap-1 overflow-auto border-b border-border pb-3 md:w-56 md:flex-col md:border-b-0 md:border-r md:pb-0 md:pr-4" role="tablist" aria-label={t('settings.title')}>
            {tabs.map((tab) => {
              const Icon = tab.icon
              const active = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2.5 px-3.5 py-2.5 text-xs font-semibold rounded-xl transition-all whitespace-nowrap ${
                    active
                      ? 'bg-primary/10 text-primary shadow-sm'
                      : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'
                  }`}
                >
                  <Icon size={15} />
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Configuration Form Panel */}
          <div className="flex-1 min-w-0 w-full animate-fade-in-up">
            {activeTab === 'account' && user && (
              <section className="glass-panel rounded-2xl p-5">
                <h2 className="mb-4 text-sm font-semibold text-foreground flex items-center gap-2 border-b border-border/60 pb-2">
                  <User size={16} className="text-primary" />
                  {t('settings.account')}
                </h2>
                <div className="space-y-4 text-sm">
                  <div className="flex items-center justify-between border-b border-border/30 pb-2">
                    <span className="text-muted-foreground">Email</span>
                    <span className="font-medium">{user.email}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">User ID</span>
                    <span className="font-mono text-xs select-all bg-muted px-2 py-1 rounded-md border border-border/40">{user.id}</span>
                  </div>
                </div>
              </section>
            )}

            {activeTab === 'capability' && (
              <section className="space-y-4">
                <div className="rounded-2xl border border-border bg-card/65 p-5 shadow-sm">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-bold">{t('settings.capabilityCenter')}</h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t('settings.capabilitySummary', {
                          ready: settingsCapabilitySummary.readyCount,
                          total: settingsCapabilitySummary.totalCount,
                        })}
                      </p>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
                      settingsCapabilitySummary.missingCount === 0
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300'
                        : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300'
                    }`}>
                      {settingsCapabilitySummary.readyCount}/{settingsCapabilitySummary.totalCount}
                    </span>
                  </div>
                  <div className="mt-4 h-2 w-full rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-primary to-indigo-500 transition-all duration-500 rounded-full"
                      style={{ width: `${(settingsCapabilitySummary.readyCount / settingsCapabilitySummary.totalCount) * 100}%` }}
                    />
                  </div>
                </div>

                <div className="space-y-3">
                  {settingsCapabilities.map((row) => (
                    <div key={row.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-border bg-card/40 p-4 hover:bg-card/75 transition-all">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-semibold text-foreground">{row.name}</span>
                          {row.badgeLabelKeys.map((key) => (
                            <span key={key} className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                              {t(key)}
                            </span>
                          ))}
                          {row.badgeLabels?.map((label) => (
                            <span key={label} className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                              {label}
                            </span>
                          ))}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground font-medium">
                          {row.capabilityLabelKeys.map((key) => t(key)).join(' · ')}
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground/80 leading-relaxed">{t(row.noteKey)}</div>
                      </div>
                      <div className="flex items-center gap-2 self-start sm:self-center shrink-0">
                        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${
                          row.isReady
                            ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300'
                            : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300'
                        }`}>
                          <span className={`pulse-dot ${row.isReady ? 'text-emerald-500 bg-emerald-500' : 'text-amber-500 bg-amber-500'}`} />
                          <span>{t(row.statusLabelKey)}</span>
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {activeTab === 'sources' && (
              <section className="space-y-4">
                <div className="rounded-2xl border border-emerald-200/50 bg-gradient-to-br from-emerald-50/70 to-emerald-50/30 dark:from-emerald-500/10 dark:to-transparent p-5 shadow-sm">
                  <h3 className="text-sm font-bold text-emerald-950 dark:text-emerald-200 flex items-center gap-1.5">
                    <Database size={15} />
                    {t('settings.dataSources')}
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-emerald-800 dark:text-emerald-300/95">
                    {t('settings.tickflowPromo')}
                    <a
                      href="https://tickflow.org/auth/register?ref=5N4NKTCPL4"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-1 inline-flex items-center gap-0.5 font-semibold underline underline-offset-2 hover:opacity-80"
                    >
                      {t('settings.purchaseLink')}
                      <ExternalLink size={11} />
                    </a>
                  </p>
                </div>
                <div className="glass-panel rounded-2xl p-5 space-y-4 shadow-sm">
                  <Input label={t('settings.tickflowApiKey')} type="password" value={tickflowKey} onChange={setTickflowKey} placeholder="tf-..." />
                </div>
              </section>
            )}

            {activeTab === 'model' && (
              <section className="space-y-5">
                <div className="rounded-2xl border border-indigo-200/50 bg-gradient-to-br from-indigo-50/70 to-indigo-50/30 dark:from-indigo-500/10 dark:to-transparent p-5 shadow-sm">
                  <h3 className="text-sm font-bold text-indigo-950 dark:text-indigo-200 flex items-center gap-1.5">
                    <Brain size={15} />
                    {t('settings.modelConfig')}
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-indigo-800 dark:text-indigo-300/95">
                    {t('settings.oneRoutePromo')}
                    <a
                      href="https://www.1route.dev/register?aff=359904261"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-1 inline-flex items-center gap-0.5 font-semibold underline underline-offset-2 hover:opacity-80"
                    >
                      {t('settings.purchaseLink')}
                      <ExternalLink size={11} />
                    </a>
                  </p>
                </div>

                <div className="glass-panel rounded-2xl p-5 shadow-sm space-y-4">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">{t('settings.provider')}</label>
                    <select
                      value={chatProvider}
                      onChange={(e) => setChatProvider(e.target.value as Provider)}
                      className="w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-primary/20 focus:border-primary font-medium"
                    >
                      {PROVIDERS.map((p) => (
                        <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="space-y-3">
                  {PROVIDERS.map((p) => {
                    const hasKey = configs[p]?.api_key
                    return (
                      <details key={p} className="group rounded-2xl border border-border bg-card/45 overflow-hidden [&_summary::-webkit-details-marker]:hidden">
                        <summary className="flex items-center justify-between cursor-pointer p-4 text-xs font-bold select-none hover:bg-muted/30 transition-colors">
                          <div className="flex items-center gap-2">
                            <span>{PROVIDER_LABELS[p]}</span>
                            {hasKey && <span className="flex h-1.5 w-1.5 rounded-full bg-indigo-500 pulse-dot" />}
                          </div>
                          <span className="text-muted-foreground transition-transform duration-200 group-open:rotate-180">
                            <ChevronDown size={14} />
                          </span>
                        </summary>
                        <div className="space-y-4 border-t border-border/50 p-4 bg-muted/10">
                          {p === '1route' && (
                            <div className="rounded-xl bg-indigo-50/50 dark:bg-indigo-500/5 px-3 py-2 text-xs text-indigo-700 dark:text-indigo-300 border border-indigo-100/50 dark:border-indigo-500/10 leading-relaxed">
                              {t('settings.oneRouteNoAccount')}
                              <a
                                href="https://www.1route.dev/register?aff=359904261"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="ml-1 inline-flex items-center gap-0.5 font-semibold underline hover:opacity-80"
                              >
                                {t('settings.oneRouteInvite')}
                                <ExternalLink size={11} />
                              </a>
                            </div>
                          )}
                          <Input
                            label={t('settings.apiKey')}
                            type="password"
                            value={configs[p]?.api_key || ''}
                            onChange={(v) => updateConfig(p, 'api_key', v)}
                            placeholder="sk-..."
                          />
                          <Input
                            label={t('settings.model')}
                            value={configs[p]?.model || ''}
                            onChange={(v) => updateConfig(p, 'model', v)}
                            placeholder={PROVIDER_DEFAULT_MODELS[p]}
                          />
                          <Input
                            label={t('settings.baseUrl')}
                            value={configs[p]?.base_url || ''}
                            onChange={(v) => updateConfig(p, 'base_url', v)}
                            placeholder={PROVIDER_BASE_URLS[p]}
                          />
                        </div>
                      </details>
                    )
                  })}
                </div>
              </section>
            )}

            {activeTab === 'notifications' && (
              <section className="glass-panel rounded-2xl p-5 space-y-4 shadow-sm">
                <h2 className="mb-2 text-sm font-semibold text-foreground flex items-center gap-2 border-b border-border/60 pb-2">
                  <Bell size={16} className="text-primary" />
                  {t('settings.notifications')}
                </h2>
                <div className="space-y-4">
                  <Input label={t('settings.feishuWebhook')} type="password" value={feishuWebhook} onChange={setFeishuWebhook} />
                  <Input label={t('settings.wecomWebhook')} type="password" value={wecomWebhook} onChange={setWecomWebhook} />
                  <Input label={t('settings.dingtalkWebhook')} type="password" value={dingtalkWebhook} onChange={setDingtalkWebhook} />
                  <Input label="Telegram Bot Token" type="password" value={tgBotToken} onChange={setTgBotToken} />
                  <Input label="Telegram Chat ID" value={tgChatId} onChange={setTgChatId} />
                </div>
              </section>
            )}

            {canSaveActiveTab && (
              <div className="mt-6 border-t border-border/60 pt-4">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="w-full rounded-xl bg-gradient-to-r from-primary to-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-primary/10 hover:shadow-lg hover:shadow-primary/20 transition-all disabled:opacity-50 cursor-pointer"
                >
                  {saving ? t('settings.saving') : t('settings.saveConfig')}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Input({ label, value, onChange, type = 'text', placeholder = '' }: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
}) {
  const [showPassword, setShowPassword] = useState(false)
  const isPassword = type === 'password'
  const inputType = isPassword ? (showPassword ? 'text' : 'password') : type

  return (
    <div>
      <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">{label}</label>
      <div className="relative flex items-center">
        <input
          type={inputType}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded-xl border border-border bg-background/50 pl-3.5 pr-10 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-primary/20 focus:border-primary"
        />
        {isPassword && value && (
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? '隐藏密码' : '显示密码'}
            className="absolute right-3 text-muted-foreground hover:text-foreground cursor-pointer"
          >
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        )}
      </div>
    </div>
  )
}

function buildDefaultProviderConfigs(): Record<string, ProviderConfig> {
  return Object.fromEntries(PROVIDERS.map((provider) => [provider, {
    api_key: '',
    model: PROVIDER_DEFAULT_MODELS[provider],
    base_url: PROVIDER_BASE_URLS[provider] || '',
  }]))
}
