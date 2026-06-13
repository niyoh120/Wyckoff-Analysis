import { useState, useEffect, useMemo, useRef } from 'react'
import { CheckCircle2, CircleAlert, ExternalLink } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { PROVIDERS, PROVIDER_LABELS, PROVIDER_BASE_URLS } from '@wyckoff/shared'
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
  const [configs, setConfigs] = useState<Record<string, ProviderConfig>>({})
  const [tickflowKey, setTickflowKey] = useState('')
  const [feishuWebhook, setFeishuWebhook] = useState('')
  const [wecomWebhook, setWecomWebhook] = useState('')
  const [dingtalkWebhook, setDingtalkWebhook] = useState('')
  const [tgBotToken, setTgBotToken] = useState('')
  const [tgChatId, setTgChatId] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState('')
  const [toastKind, setToastKind] = useState<'success' | 'error'>('success')
  const toastTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const activeModelConfig = configs[chatProvider]
  const settingsCapabilities = useMemo(
    () => buildSettingsCapabilityRows({
      tickflow: tickflowKey,
      modelProviderLabel: PROVIDER_LABELS[chatProvider],
      modelConfig: activeModelConfig,
    }),
    [tickflowKey, chatProvider, activeModelConfig?.api_key, activeModelConfig?.model],
  )
  const settingsCapabilitySummary = useMemo(
    () => summarizeSettingsCapabilities(settingsCapabilities),
    [settingsCapabilities],
  )

  useEffect(() => {
    if (!user) return
    loadSettings()
  }, [user])

  useEffect(() => () => clearTimeout(toastTimerRef.current), [])

  async function loadSettings() {
    const { data } = await supabase
      .from('user_settings')
      .select('*')
      .eq('user_id', user!.id)
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

    const cfgs: Record<string, ProviderConfig> = {}
    for (const p of PROVIDERS) {
      if (p === 'gemini') {
        cfgs[p] = {
          api_key: data.gemini_api_key || '',
          model: data.gemini_model || '',
          base_url: data.gemini_base_url || '',
        }
      } else if (p === 'openai') {
        cfgs[p] = {
          api_key: data.openai_api_key || '',
          model: data.openai_model || '',
          base_url: data.openai_base_url || PROVIDER_BASE_URLS.openai,
        }
      } else if (p === 'deepseek') {
        cfgs[p] = {
          api_key: data.deepseek_api_key || '',
          model: data.deepseek_model || '',
          base_url: data.deepseek_base_url || PROVIDER_BASE_URLS.deepseek,
        }
      } else if (p === 'anthropic') {
        cfgs[p] = {
          api_key: data.anthropic_api_key || '',
          model: data.anthropic_model || '',
          base_url: data.anthropic_base_url || '',
        }
      } else {
        const info = custom[p] || {}
        cfgs[p] = {
          api_key: info.apikey || info.api_key || '',
          model: info.model || '',
          base_url: info.baseurl || info.base_url || PROVIDER_BASE_URLS[p] || '',
        }
      }
    }
    setConfigs(cfgs)
  }

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
        custom_providers[p] = { apikey: c.api_key, model: c.model, baseurl: c.base_url }
      }
    }

    const settings = {
      user_id: user.id,
      chat_provider: chatProvider,
      gemini_api_key: configs.gemini?.api_key || '',
      gemini_model: configs.gemini?.model || '',
      gemini_base_url: configs.gemini?.base_url || '',
      openai_api_key: configs.openai?.api_key || '',
      openai_model: configs.openai?.model || '',
      openai_base_url: configs.openai?.base_url || '',
      deepseek_api_key: configs.deepseek?.api_key || '',
      deepseek_model: configs.deepseek?.model || '',
      deepseek_base_url: configs.deepseek?.base_url || '',
      anthropic_api_key: configs.anthropic?.api_key || '',
      anthropic_model: configs.anthropic?.model || '',
      anthropic_base_url: configs.anthropic?.base_url || '',
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

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-xl font-semibold">{t('settings.title')}</h1>

      {toast && (
        <div className={`mb-4 rounded-lg px-4 py-2 text-sm ${toastKind === 'error' ? 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200' : 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200'}`}>
          {toast}
        </div>
      )}

      {user && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t('settings.account')}</h2>
          <div className="space-y-2 rounded-lg border border-border px-4 py-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Email</span>
              <span>{user.email}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">User ID</span>
              <span className="font-mono text-xs select-all">{user.id}</span>
            </div>
          </div>
        </section>
      )}

      <section className="mb-8">
        <div className="rounded-lg border border-border">
          <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2.5">
            <div>
              <div className="text-sm font-medium">{t('settings.capabilityCenter')}</div>
              <div className="text-xs text-muted-foreground">
                {t('settings.capabilitySummary', {
                  ready: settingsCapabilitySummary.readyCount,
                  total: settingsCapabilitySummary.totalCount,
                })}
              </div>
            </div>
            <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${
              settingsCapabilitySummary.missingCount === 0
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
                : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'
            }`}>
              {settingsCapabilitySummary.readyCount}/{settingsCapabilitySummary.totalCount}
            </span>
          </div>
          <div className="divide-y divide-border">
            {settingsCapabilities.map((row) => {
              const StatusIcon = row.isReady ? CheckCircle2 : CircleAlert
              return (
                <div key={row.id} className="grid gap-3 px-3 py-3 sm:grid-cols-[9rem_1fr_auto]">
                  <div>
                    <div className="text-sm font-medium">{row.name}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{t(row.priorityLabelKey)}</div>
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap gap-1">
                      {row.badgeLabelKeys.map((key) => (
                        <span key={key} className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                          {t(key)}
                        </span>
                      ))}
                      {row.badgeLabels?.map((label) => (
                        <span key={label} className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                          {label}
                        </span>
                      ))}
                    </div>
                    <div className="mt-1.5 text-xs text-foreground">
                      {row.capabilityLabelKeys.map((key) => t(key)).join(' · ')}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{t(row.noteKey)}</div>
                  </div>
                  <div className={`flex h-7 items-center gap-1.5 self-start rounded-full border px-2 text-xs font-medium ${
                    row.isReady
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
                      : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'
                  }`}>
                    <StatusIcon size={14} />
                    <span>{t(row.statusLabelKey)}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t('settings.dataSources')}</h2>
        <div className="space-y-3">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
            {t('settings.tickflowPromo')}
            <a
              href="https://tickflow.org/auth/register?ref=5N4NKTCPL4"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1 inline-flex items-center gap-1 font-medium text-emerald-900 hover:underline dark:text-emerald-100"
            >
              {t('settings.purchaseLink')}
              <ExternalLink size={12} />
            </a>
          </div>
          <Input label={t('settings.tickflowApiKey')} type="password" value={tickflowKey} onChange={setTickflowKey} placeholder="tf-..." />
        </div>
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t('settings.modelConfig')}</h2>
        <div className="mb-4 rounded-lg border border-indigo-200 bg-indigo-50/60 px-3 py-2 text-xs text-indigo-800 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200">
          {t('settings.oneRoutePromo')}
          <a
            href="https://www.1route.dev/register?aff=359904261"
            target="_blank"
            rel="noopener noreferrer"
            className="ml-1 inline-flex items-center gap-1 font-medium text-indigo-900 hover:underline dark:text-indigo-100"
          >
            {t('settings.purchaseLink')}
            <ExternalLink size={12} />
          </a>
        </div>
        <div className="mb-4">
          <label className="mb-1.5 block text-sm font-medium">{t('settings.provider')}</label>
          <select
            value={chatProvider}
            onChange={(e) => setChatProvider(e.target.value as Provider)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>
            ))}
          </select>
        </div>
        <div className="space-y-4">
          {PROVIDERS.map((p) => (
            <details key={p} className="rounded-lg border border-border">
              <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium">
                {PROVIDER_LABELS[p]}
                {configs[p]?.api_key && <span className="ml-2 text-indigo-600">●</span>}
              </summary>
              <div className="space-y-3 border-t border-border px-4 py-3">
                {p === '1route' && (
                  <div className="rounded-md bg-indigo-50 px-2.5 py-2 text-xs text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200">
                    {t('settings.oneRouteNoAccount')}
                    <a
                      href="https://www.1route.dev/register?aff=359904261"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-1 inline-flex items-center gap-1 font-medium text-indigo-900 hover:underline dark:text-indigo-100"
                    >
                      {t('settings.oneRouteInvite')}
                      <ExternalLink size={12} />
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
                  placeholder={p === '1route' ? 'gpt-5.5' : ''}
                />
                <Input
                  label={t('settings.baseUrl')}
                  value={configs[p]?.base_url || ''}
                  onChange={(v) => updateConfig(p, 'base_url', v)}
                  placeholder={PROVIDER_BASE_URLS[p]}
                />
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t('settings.notifications')}</h2>
        <div className="space-y-3">
          <Input label={t('settings.feishuWebhook')} type="password" value={feishuWebhook} onChange={setFeishuWebhook} />
          <Input label={t('settings.wecomWebhook')} type="password" value={wecomWebhook} onChange={setWecomWebhook} />
          <Input label={t('settings.dingtalkWebhook')} type="password" value={dingtalkWebhook} onChange={setDingtalkWebhook} />
          <Input label="Telegram Bot Token" type="password" value={tgBotToken} onChange={setTgBotToken} />
          <Input label="Telegram Chat ID" value={tgChatId} onChange={setTgChatId} />
        </div>
      </section>

      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        {saving ? t('settings.saving') : t('settings.saveConfig')}
      </button>
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
  return (
    <div>
      <label className="mb-1 block text-xs text-muted-foreground">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/20"
      />
    </div>
  )
}
