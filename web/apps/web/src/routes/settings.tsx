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

type SettingsTab = 'capability' | 'sources' | 'model' | 'notifications' | 'account'
type Translate = ReturnType<typeof usePreferences>['t']
type SettingsRow = Record<string, any>

const SETTINGS_TABS = [
  { id: 'capability', labelKey: 'settings.capabilityCenter', Icon: ShieldCheck },
  { id: 'sources', labelKey: 'settings.dataSources', Icon: Database },
  { id: 'model', labelKey: 'settings.modelConfig', Icon: Brain },
  { id: 'notifications', labelKey: 'settings.notifications', Icon: Bell },
  { id: 'account', labelKey: 'settings.account', Icon: User },
] as const

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
  const [activeTab, setActiveTab] = useState<SettingsTab>('capability')
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
    const { data } = await supabase.from('user_settings').select('*').eq('user_id', userId).single()
    if (!data) return
    setChatProvider(resolveProvider(data.chat_provider))
    setTickflowKey(data.tickflow_api_key || '')
    setFeishuWebhook(data.feishu_webhook || '')
    setWecomWebhook(data.wecom_webhook || '')
    setDingtalkWebhook(data.dingtalk_webhook || '')
    setTgBotToken(data.tg_bot_token || '')
    setTgChatId(data.tg_chat_id || '')
    setConfigs(buildProviderConfigsFromSettings(data))
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
    const { error } = await supabase.from('user_settings').upsert(buildSettingsPayload({
      userId: user.id,
      chatProvider,
      configs,
      tickflowKey,
      feishuWebhook,
      wecomWebhook,
      dingtalkWebhook,
      tgBotToken,
      tgChatId,
    }))
    setSaving(false)
    setToastKind(error ? 'error' : 'success')
    setToast(error ? t('settings.saveFailed', { message: error.message }) : t('settings.saved'))
    clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(''), 3000)
  }

  const canSaveActiveTab = activeTab === 'sources' || activeTab === 'model' || activeTab === 'notifications'

  return (
    <div className="h-full overflow-auto p-4 sm:p-6 bg-background/50">
      <div className="mx-auto max-w-5xl">
        <h1 className="mb-6 bg-gradient-to-r from-primary to-indigo-500 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
          {t('settings.title')}
        </h1>
        <SettingsToast toast={toast} kind={toastKind} />
        <div className="flex flex-col md:flex-row gap-6 items-start">
          <SettingsTabs activeTab={activeTab} onChange={setActiveTab} t={t} />
          <div className="flex-1 min-w-0 w-full animate-fade-in-up">
            {activeTab === 'account' && user && <AccountPanel email={user.email || ''} id={user.id} t={t} />}
            {activeTab === 'capability' && (
              <CapabilityPanel rows={settingsCapabilities} summary={settingsCapabilitySummary} t={t} />
            )}
            {activeTab === 'sources' && <SourcesPanel tickflowKey={tickflowKey} setTickflowKey={setTickflowKey} t={t} />}
            {activeTab === 'model' && (
              <ModelPanel chatProvider={chatProvider} configs={configs} setChatProvider={setChatProvider} updateConfig={updateConfig} t={t} />
            )}
            {activeTab === 'notifications' && (
              <NotificationsPanel
                feishuWebhook={feishuWebhook}
                setFeishuWebhook={setFeishuWebhook}
                wecomWebhook={wecomWebhook}
                setWecomWebhook={setWecomWebhook}
                dingtalkWebhook={dingtalkWebhook}
                setDingtalkWebhook={setDingtalkWebhook}
                tgBotToken={tgBotToken}
                setTgBotToken={setTgBotToken}
                tgChatId={tgChatId}
                setTgChatId={setTgChatId}
                t={t}
              />
            )}
            {canSaveActiveTab && <SaveBar saving={saving} onSave={handleSave} t={t} />}
          </div>
        </div>
      </div>
    </div>
  )
}

function SettingsToast({ toast, kind }: { toast: string; kind: 'success' | 'error' }) {
  if (!toast) return null
  const toneClass = kind === 'error'
    ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-200 dark:border-red-500/20'
    : 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-200 dark:border-indigo-500/20'
  return <div className={`mb-6 rounded-xl px-4 py-3 text-sm shadow-sm transition-all border ${toneClass}`}>{toast}</div>
}

function SettingsTabs({ activeTab, onChange, t }: { activeTab: SettingsTab; onChange: (tab: SettingsTab) => void; t: Translate }) {
  return (
    <div className="flex w-full shrink-0 flex-row gap-1 overflow-auto border-b border-border pb-3 md:w-56 md:flex-col md:border-b-0 md:border-r md:pb-0 md:pr-4" role="tablist" aria-label={t('settings.title')}>
      {SETTINGS_TABS.map(({ id, labelKey, Icon }) => {
        const active = activeTab === id
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(id)}
            className={`flex items-center gap-2.5 px-3.5 py-2.5 text-xs font-semibold rounded-xl transition-all whitespace-nowrap ${
              active ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'
            }`}
          >
            <Icon size={15} />
            {t(labelKey)}
          </button>
        )
      })}
    </div>
  )
}

function AccountPanel({ email, id, t }: { email: string; id: string; t: Translate }) {
  return (
    <section className="glass-panel rounded-2xl p-5">
      <h2 className="mb-4 text-sm font-semibold text-foreground flex items-center gap-2 border-b border-border/60 pb-2">
        <User size={16} className="text-primary" />
        {t('settings.account')}
      </h2>
      <div className="space-y-4 text-sm">
        <div className="flex items-center justify-between border-b border-border/30 pb-2">
          <span className="text-muted-foreground">Email</span>
          <span className="font-medium">{email}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">User ID</span>
          <span className="font-mono text-xs select-all bg-muted px-2 py-1 rounded-md border border-border/40">{id}</span>
        </div>
      </div>
    </section>
  )
}

function CapabilityPanel({ rows, summary, t }: {
  rows: ReturnType<typeof buildSettingsCapabilityRows>
  summary: ReturnType<typeof summarizeSettingsCapabilities>
  t: Translate
}) {
  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-border bg-card/65 p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold">{t('settings.capabilityCenter')}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('settings.capabilitySummary', { ready: summary.readyCount, total: summary.totalCount })}
            </p>
          </div>
          <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${summaryPillClass(summary.missingCount)}`}>
            {summary.readyCount}/{summary.totalCount}
          </span>
        </div>
        <div className="mt-4 h-2 w-full rounded-full bg-muted overflow-hidden">
          <div className="h-full bg-gradient-to-r from-primary to-indigo-500 transition-all duration-500 rounded-full" style={{ width: `${(summary.readyCount / summary.totalCount) * 100}%` }} />
        </div>
      </div>
      <div className="space-y-3">
        {rows.map((row) => <CapabilityRow key={row.id} row={row} t={t} />)}
      </div>
    </section>
  )
}

function CapabilityRow({ row, t }: { row: ReturnType<typeof buildSettingsCapabilityRows>[number]; t: Translate }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-border bg-card/40 p-4 hover:bg-card/75 transition-all">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-foreground">{row.name}</span>
          {row.badgeLabelKeys.map((key) => <Badge key={key}>{t(key)}</Badge>)}
          {row.badgeLabels?.map((label) => <Badge key={label}>{label}</Badge>)}
        </div>
        <div className="mt-1 text-xs text-muted-foreground font-medium">{row.capabilityLabelKeys.map((key) => t(key)).join(' · ')}</div>
        <div className="mt-1 text-[11px] text-muted-foreground/80 leading-relaxed">{t(row.noteKey)}</div>
      </div>
      <div className="flex items-center gap-2 self-start sm:self-center shrink-0">
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${statusPillClass(row.isReady)}`}>
          <span className={`pulse-dot ${row.isReady ? 'text-emerald-500 bg-emerald-500' : 'text-amber-500 bg-amber-500'}`} />
          <span>{t(row.statusLabelKey)}</span>
        </span>
      </div>
    </div>
  )
}

function SourcesPanel({ tickflowKey, setTickflowKey, t }: { tickflowKey: string; setTickflowKey: (value: string) => void; t: Translate }) {
  return (
    <section className="space-y-4">
      <PromoPanel icon={<Database size={15} />} title={t('settings.dataSources')} body={t('settings.tickflowPromo')} href="https://tickflow.org/auth/register?ref=5N4NKTCPL4" tone="emerald" t={t} />
      <div className="glass-panel rounded-2xl p-5 space-y-4 shadow-sm">
        <Input label={t('settings.tickflowApiKey')} type="password" value={tickflowKey} onChange={setTickflowKey} placeholder="tf-..." />
      </div>
    </section>
  )
}

function ModelPanel({ chatProvider, configs, setChatProvider, updateConfig, t }: {
  chatProvider: Provider
  configs: Record<string, ProviderConfig>
  setChatProvider: (provider: Provider) => void
  updateConfig: (provider: string, field: keyof ProviderConfig, value: string) => void
  t: Translate
}) {
  return (
    <section className="space-y-5">
      <PromoPanel icon={<Brain size={15} />} title={t('settings.modelConfig')} body={t('settings.oneRoutePromo')} href="https://www.1route.dev/register?aff=359904261" tone="indigo" t={t} />
      <div className="glass-panel rounded-2xl p-5 shadow-sm space-y-4">
        <div>
          <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">{t('settings.provider')}</label>
          <select
            value={chatProvider}
            onChange={(e) => setChatProvider(e.target.value as Provider)}
            className="w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-primary/20 focus:border-primary font-medium"
          >
            {PROVIDERS.map((provider) => <option key={provider} value={provider}>{PROVIDER_LABELS[provider]}</option>)}
          </select>
        </div>
      </div>
      <div className="space-y-3">
        {PROVIDERS.map((provider) => (
          <ProviderDetails key={provider} provider={provider} config={configs[provider]} updateConfig={updateConfig} t={t} />
        ))}
      </div>
    </section>
  )
}

function ProviderDetails({ provider, config, updateConfig, t }: {
  provider: Provider
  config?: ProviderConfig
  updateConfig: (provider: string, field: keyof ProviderConfig, value: string) => void
  t: Translate
}) {
  const hasKey = config?.api_key
  return (
    <details className="group rounded-2xl border border-border bg-card/45 overflow-hidden [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex items-center justify-between cursor-pointer p-4 text-xs font-bold select-none hover:bg-muted/30 transition-colors">
        <div className="flex items-center gap-2">
          <span>{PROVIDER_LABELS[provider]}</span>
          {hasKey && <span className="flex h-1.5 w-1.5 rounded-full bg-indigo-500 pulse-dot" />}
        </div>
        <span className="text-muted-foreground transition-transform duration-200 group-open:rotate-180">
          <ChevronDown size={14} />
        </span>
      </summary>
      <div className="space-y-4 border-t border-border/50 p-4 bg-muted/10">
        {provider === '1route' && <OneRouteInvite t={t} />}
        <Input label={t('settings.apiKey')} type="password" value={config?.api_key || ''} onChange={(value) => updateConfig(provider, 'api_key', value)} placeholder="sk-..." />
        <Input label={t('settings.model')} value={config?.model || ''} onChange={(value) => updateConfig(provider, 'model', value)} placeholder={PROVIDER_DEFAULT_MODELS[provider]} />
        <Input label={t('settings.baseUrl')} value={config?.base_url || ''} onChange={(value) => updateConfig(provider, 'base_url', value)} placeholder={PROVIDER_BASE_URLS[provider]} />
      </div>
    </details>
  )
}

function NotificationsPanel(props: {
  feishuWebhook: string
  setFeishuWebhook: (value: string) => void
  wecomWebhook: string
  setWecomWebhook: (value: string) => void
  dingtalkWebhook: string
  setDingtalkWebhook: (value: string) => void
  tgBotToken: string
  setTgBotToken: (value: string) => void
  tgChatId: string
  setTgChatId: (value: string) => void
  t: Translate
}) {
  return (
    <section className="glass-panel rounded-2xl p-5 space-y-4 shadow-sm">
      <h2 className="mb-2 text-sm font-semibold text-foreground flex items-center gap-2 border-b border-border/60 pb-2">
        <Bell size={16} className="text-primary" />
        {props.t('settings.notifications')}
      </h2>
      <div className="space-y-4">
        <Input label={props.t('settings.feishuWebhook')} type="password" value={props.feishuWebhook} onChange={props.setFeishuWebhook} />
        <Input label={props.t('settings.wecomWebhook')} type="password" value={props.wecomWebhook} onChange={props.setWecomWebhook} />
        <Input label={props.t('settings.dingtalkWebhook')} type="password" value={props.dingtalkWebhook} onChange={props.setDingtalkWebhook} />
        <Input label="Telegram Bot Token" type="password" value={props.tgBotToken} onChange={props.setTgBotToken} />
        <Input label="Telegram Chat ID" value={props.tgChatId} onChange={props.setTgChatId} />
      </div>
    </section>
  )
}

function PromoPanel({ icon, title, body, href, tone, t }: {
  icon: React.ReactNode
  title: string
  body: string
  href: string
  tone: 'emerald' | 'indigo'
  t: Translate
}) {
  const toneClass = tone === 'emerald'
    ? 'border-emerald-200/50 bg-gradient-to-br from-emerald-50/70 to-emerald-50/30 dark:from-emerald-500/10 dark:to-transparent text-emerald-950 dark:text-emerald-200'
    : 'border-indigo-200/50 bg-gradient-to-br from-indigo-50/70 to-indigo-50/30 dark:from-indigo-500/10 dark:to-transparent text-indigo-950 dark:text-indigo-200'
  const bodyClass = tone === 'emerald'
    ? 'text-emerald-800 dark:text-emerald-300/95'
    : 'text-indigo-800 dark:text-indigo-300/95'
  return (
    <div className={`rounded-2xl border p-5 shadow-sm ${toneClass}`}>
      <h3 className="text-sm font-bold flex items-center gap-1.5">
        {icon}
        {title}
      </h3>
      <p className={`mt-2 text-xs leading-relaxed ${bodyClass}`}>
        {body}
        <a href={href} target="_blank" rel="noopener noreferrer" className="ml-1 inline-flex items-center gap-0.5 font-semibold underline underline-offset-2 hover:opacity-80">
          {t('settings.purchaseLink')}
          <ExternalLink size={11} />
        </a>
      </p>
    </div>
  )
}

function OneRouteInvite({ t }: { t: Translate }) {
  return (
    <div className="rounded-xl bg-indigo-50/50 dark:bg-indigo-500/5 px-3 py-2 text-xs text-indigo-700 dark:text-indigo-300 border border-indigo-100/50 dark:border-indigo-500/10 leading-relaxed">
      {t('settings.oneRouteNoAccount')}
      <a href="https://www.1route.dev/register?aff=359904261" target="_blank" rel="noopener noreferrer" className="ml-1 inline-flex items-center gap-0.5 font-semibold underline hover:opacity-80">
        {t('settings.oneRouteInvite')}
        <ExternalLink size={11} />
      </a>
    </div>
  )
}

function SaveBar({ saving, onSave, t }: { saving: boolean; onSave: () => void; t: Translate }) {
  return (
    <div className="mt-6 border-t border-border/60 pt-4">
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="w-full rounded-xl bg-gradient-to-r from-primary to-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-primary/10 hover:shadow-lg hover:shadow-primary/20 transition-all disabled:opacity-50 cursor-pointer"
      >
        {saving ? t('settings.saving') : t('settings.saveConfig')}
      </button>
    </div>
  )
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">{children}</span>
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

function buildProviderConfigsFromSettings(data: SettingsRow): Record<string, ProviderConfig> {
  const custom = parseCustomProviders(data.custom_providers)
  const cfgs = buildDefaultProviderConfigs()
  for (const provider of PROVIDERS) {
    if (provider === 'gemini' || provider === 'openai' || provider === 'deepseek' || provider === 'anthropic') {
      cfgs[provider] = {
        api_key: data[`${provider}_api_key`] || '',
        model: data[`${provider}_model`] || PROVIDER_DEFAULT_MODELS[provider],
        base_url: data[`${provider}_base_url`] || PROVIDER_BASE_URLS[provider],
      }
      continue
    }
    const info = custom[provider] || {}
    cfgs[provider] = {
      api_key: info.apikey || info.api_key || '',
      model: info.model || PROVIDER_DEFAULT_MODELS[provider],
      base_url: info.baseurl || info.base_url || PROVIDER_BASE_URLS[provider] || '',
    }
  }
  return cfgs
}

function buildSettingsPayload(args: {
  userId: string
  chatProvider: Provider
  configs: Record<string, ProviderConfig>
  tickflowKey: string
  feishuWebhook: string
  wecomWebhook: string
  dingtalkWebhook: string
  tgBotToken: string
  tgChatId: string
}) {
  return {
    user_id: args.userId,
    chat_provider: args.chatProvider,
    gemini_api_key: args.configs.gemini?.api_key || '',
    gemini_model: args.configs.gemini?.model || PROVIDER_DEFAULT_MODELS.gemini,
    gemini_base_url: args.configs.gemini?.base_url || PROVIDER_BASE_URLS.gemini,
    openai_api_key: args.configs.openai?.api_key || '',
    openai_model: args.configs.openai?.model || PROVIDER_DEFAULT_MODELS.openai,
    openai_base_url: args.configs.openai?.base_url || PROVIDER_BASE_URLS.openai,
    deepseek_api_key: args.configs.deepseek?.api_key || '',
    deepseek_model: args.configs.deepseek?.model || PROVIDER_DEFAULT_MODELS.deepseek,
    deepseek_base_url: args.configs.deepseek?.base_url || PROVIDER_BASE_URLS.deepseek,
    anthropic_api_key: args.configs.anthropic?.api_key || '',
    anthropic_model: args.configs.anthropic?.model || PROVIDER_DEFAULT_MODELS.anthropic,
    anthropic_base_url: args.configs.anthropic?.base_url || PROVIDER_BASE_URLS.anthropic,
    custom_providers: buildCustomProviders(args.configs),
    tickflow_api_key: args.tickflowKey,
    feishu_webhook: args.feishuWebhook,
    wecom_webhook: args.wecomWebhook,
    dingtalk_webhook: args.dingtalkWebhook,
    tg_bot_token: args.tgBotToken,
    tg_chat_id: args.tgChatId,
  }
}

function buildCustomProviders(configs: Record<string, ProviderConfig>): Record<string, object> {
  const oneRoute = configs['1route']
  if (!oneRoute) return {}
  return {
    '1route': {
      apikey: oneRoute.api_key,
      model: oneRoute.model || PROVIDER_DEFAULT_MODELS['1route'],
      baseurl: oneRoute.base_url || PROVIDER_BASE_URLS['1route'],
    },
  }
}

function parseCustomProviders(raw: unknown): Record<string, any> {
  if (typeof raw === 'string') return JSON.parse(raw || '{}')
  return (raw || {}) as Record<string, any>
}

function resolveProvider(raw: unknown): Provider {
  return PROVIDERS.includes(raw as Provider) ? raw as Provider : '1route'
}

function summaryPillClass(missingCount: number): string {
  return missingCount === 0
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300'
    : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300'
}

function statusPillClass(isReady: boolean): string {
  return isReady
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300'
    : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300'
}
