import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { PROVIDERS, PROVIDER_LABELS, PROVIDER_BASE_URLS } from '@wyckoff/shared'
import type { Provider } from '@wyckoff/shared'

interface ProviderConfig {
  api_key: string
  model: string
  base_url: string
}

export function SettingsPage() {
  const user = useAuthStore((s) => s.user)
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

  useEffect(() => {
    if (!user) return
    loadSettings()
  }, [user])

  async function loadSettings() {
    const { data } = await supabase
      .from('user_settings')
      .select('*')
      .eq('user_id', user!.id)
      .single()

    if (!data) return

    setChatProvider((data.chat_provider as Provider) || '1route')
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
    for (const p of ['1route', 'zhipu', 'minimax', 'qwen', 'volcengine'] as const) {
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
    setToast(error ? `保存失败: ${error.message}` : '已保存')
    setTimeout(() => setToast(''), 3000)
  }

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-xl font-semibold">设置</h1>

      {toast && (
        <div className={`mb-4 rounded-lg px-4 py-2 text-sm ${toast.includes('失败') ? 'bg-red-50 text-red-700' : 'bg-indigo-50 text-indigo-700'}`}>
          {toast}
        </div>
      )}

      {/* Chat Provider */}
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">读盘室供应商</h2>
        <select
          value={chatProvider}
          onChange={(e) => setChatProvider(e.target.value as Provider)}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>
          ))}
        </select>
      </section>

      {/* LLM Providers */}
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">模型配置</h2>
        <div className="space-y-4">
          {PROVIDERS.map((p) => (
            <details key={p} className="rounded-lg border border-border">
              <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium">
                {PROVIDER_LABELS[p]}
                {configs[p]?.api_key && <span className="ml-2 text-indigo-600">●</span>}
              </summary>
              <div className="space-y-3 border-t border-border px-4 py-3">
                <Input
                  label="API Key"
                  type="password"
                  value={configs[p]?.api_key || ''}
                  onChange={(v) => updateConfig(p, 'api_key', v)}
                  placeholder="sk-..."
                />
                <Input
                  label="模型"
                  value={configs[p]?.model || ''}
                  onChange={(v) => updateConfig(p, 'model', v)}
                  placeholder={p === '1route' ? 'gpt-5.5' : ''}
                />
                <Input
                  label="Base URL"
                  value={configs[p]?.base_url || ''}
                  onChange={(v) => updateConfig(p, 'base_url', v)}
                  placeholder={PROVIDER_BASE_URLS[p]}
                />
              </div>
            </details>
          ))}
        </div>
      </section>

      {/* Data Sources */}
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">数据源</h2>
        <div className="space-y-3">
          <Input label="TickFlow API Key" type="password" value={tickflowKey} onChange={setTickflowKey} placeholder="tf-..." />
        </div>
      </section>

      {/* Notifications */}
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">通知推送</h2>
        <div className="space-y-3">
          <Input label="飞书 Webhook" type="password" value={feishuWebhook} onChange={setFeishuWebhook} />
          <Input label="企业微信 Webhook" type="password" value={wecomWebhook} onChange={setWecomWebhook} />
          <Input label="钉钉 Webhook" type="password" value={dingtalkWebhook} onChange={setDingtalkWebhook} />
          <Input label="Telegram Bot Token" type="password" value={tgBotToken} onChange={setTgBotToken} />
          <Input label="Telegram Chat ID" value={tgChatId} onChange={setTgChatId} />
        </div>
      </section>

      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        {saving ? '保存中...' : '保存配置'}
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
