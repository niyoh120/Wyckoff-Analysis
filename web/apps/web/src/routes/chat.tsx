import { useCallback, useEffect, useMemo, useRef, useState, memo } from 'react'
import { Activity, Check, RotateCcw, Send, Square, X, Wrench } from 'lucide-react'
import {
  DefaultChatTransport,
  lastAssistantMessageIsCompleteWithApprovalResponses,
  type UIMessage,
} from 'ai'
import { useChat } from '@ai-sdk/react'
import { useAuthStore } from '@/stores/auth'
import { MarkdownContent } from '@/components/markdown'
import { ScreenResultCard } from '@/components/screen-result-card'
import { AIDisclaimer } from '@/components/ai-disclaimer'
import { usePreferences, type TranslationKey } from '@/lib/preferences'
import type { AnalyzeStockResult, ScreenResult, StrategyDecisionResult } from '@wyckoff/shared'

const TOOL_LABEL_KEYS: Record<string, TranslationKey> = {
  search_stock: 'tool.search_stock',
  view_portfolio: 'tool.view_portfolio',
  market_overview: 'tool.market_overview',
  market_history: 'tool.market_history',
  query_recommendations: 'tool.query_recommendations',
  query_tail_buy: 'tool.query_tail_buy',
  plan_portfolio_update: 'tool.plan_portfolio_update',
  execute_portfolio_update: 'tool.execute_portfolio_update',
  analyze_stock: 'tool.analyze_stock',
  screen_stocks: 'tool.screen_stocks',
  generate_ai_report: 'tool.generate_ai_report',
  generate_strategy_decision: 'tool.generate_strategy_decision',
  intraday_analysis: 'tool.intraday_analysis',
}

const TOOL_TONES: Record<string, string> = {
  market_overview: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100',
  market_history: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100',
  analyze_stock: 'border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-100',
  screen_stocks: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100',
  generate_strategy_decision: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100',
  plan_portfolio_update: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100',
  execute_portfolio_update: 'border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-100',
}

const STRUCTURED_TOOL_NAMES = new Set(['screen_stocks', 'analyze_stock', 'generate_strategy_decision'])
const ACTION_TOOL_NAMES = new Set(['plan_portfolio_update', 'execute_portfolio_update'])
const MARKET_INDEX_LABELS: Record<string, string> = {
  sse: '上证',
  csi300: '沪深300',
  szse: '深成指',
  chinext: '创业板',
}

type MessagePart = UIMessage['parts'][number] & Record<string, unknown>
type ToolPart = MessagePart & {
  type: `tool-${string}` | 'dynamic-tool'
  state: string
  toolCallId: string
  input?: unknown
  output?: unknown
  errorText?: string
  approval?: { id: string; approved?: boolean; reason?: string }
}

type AssistantRenderItem =
  | { type: 'text'; content: string; key: string }
  | { type: 'tool'; part: ToolPart; key: string }
  | { type: 'tool-group'; parts: ToolPart[]; key: string }

interface ChatConfig {
  configured: boolean
  model: string | null
}

export function ChatPage() {
  const session = useAuthStore((s) => s.session)
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [input, setInput] = useState('')
  const [localError, setLocalError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const token = session?.access_token
  const config = useChatConfig(token)
  const chat = useReadingRoomChat(token, setLocalError, t)
  const loading = chat.status === 'submitted' || chat.status === 'streaming'
  useAutoScroll(scrollRef, chat.messages, loading)

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading) return
    if (!token) { setLocalError(t('chat.requestFailed')); return }
    if (!config.configured) { setLocalError(t('chat.configureLLM')); return }
    setInput('')
    setLocalError('')
    chat.clearError()
    void chat.sendMessage({ text })
  }, [chat, config.configured, input, loading, t, token])

  const handleNewChat = useCallback(() => {
    if (loading) void chat.stop()
    chat.setMessages([])
    setInput('')
    setLocalError('')
    chat.clearError()
  }, [chat, loading])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <ChatHeader config={config} hasUser={Boolean(user)} onNewChat={handleNewChat} />
      <ChatMessages chat={chat} loading={loading} scrollRef={scrollRef} onPick={setInput} />
      <ErrorBanner message={localError || chat.error?.message || ''} />
      <ChatComposer input={input} loading={loading} onInput={setInput} onSubmit={handleSubmit} onStop={() => void chat.stop()} />
    </div>
  )
}

function useReadingRoomChat(token: string | undefined, setLocalError: (value: string) => void, t: (key: TranslationKey) => string) {
  const transport = useMemo(() => buildChatTransport(token), [token])
  return useChat({
    transport,
    experimental_throttle: 50,
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
    onError: (err) => setLocalError(err.message || t('chat.requestFailed')),
  })
}

function useChatConfig(token: string | undefined): ChatConfig {
  const [config, setConfig] = useState<ChatConfig>({ configured: false, model: null })
  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetchChatConfig(token)
      .then((next) => { if (!cancelled) setConfig(next) })
      .catch(() => { if (!cancelled) setConfig({ configured: false, model: null }) })
    return () => { cancelled = true }
  }, [token])
  return config
}

function useAutoScroll(ref: React.RefObject<HTMLDivElement | null>, messages: UIMessage[], loading: boolean) {
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading, ref])
}

function ChatHeader({ config, hasUser, onNewChat }: { config: ChatConfig; hasUser: boolean; onNewChat: () => void }) {
  const { t } = usePreferences()
  return (
    <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-3">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">{t('chat.title')}</h1>
        {config.model && <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200">{config.model}</span>}
        {!config.configured && hasUser && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">{t('chat.noApiKey')}</span>}
      </div>
      <button onClick={onNewChat} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-muted/50">
        <RotateCcw size={14} />
        {t('chat.newChat')}
      </button>
    </div>
  )
}

function ChatMessages({ chat, loading, scrollRef, onPick }: {
  chat: ReturnType<typeof useChat<UIMessage>>
  loading: boolean
  scrollRef: React.RefObject<HTMLDivElement | null>
  onPick: (value: string) => void
}) {
  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto px-6 py-4">
      {chat.messages.length === 0 && !loading ? (
        <EmptyChat onPick={onPick} />
      ) : (
        <div className="space-y-4 pb-2">
          {chat.messages.map((message) => <MessageBubble key={message.id} message={message} approve={(id) => void chat.addToolApprovalResponse({ id, approved: true })} deny={(id) => void chat.addToolApprovalResponse({ id, approved: false })} />)}
          {loading && <ThinkingBubble />}
        </div>
      )}
    </div>
  )
}

function ErrorBanner({ message }: { message: string }) {
  if (!message) return null
  return <div className="mx-6 mb-2 shrink-0 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-200">{message}</div>
}

const MessageBubble = memo(function MessageBubble({
  message,
  approve,
  deny,
}: {
  message: UIMessage
  approve: (approvalId: string) => void
  deny: (approvalId: string) => void
}) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-sm ${isUser ? 'bg-primary text-primary-foreground whitespace-pre-wrap' : 'bg-muted text-foreground'}`}>
        {isUser ? <UserText message={message} /> : <AssistantParts message={message} approve={approve} deny={deny} />}
      </div>
    </div>
  )
})

function AssistantParts({ message, approve, deny }: { message: UIMessage; approve: (id: string) => void; deny: (id: string) => void }) {
  const items = buildAssistantRenderItems(message.parts)
  return (
    <>
      {items.map((item) => {
        if (item.type === 'text') return <MarkdownContent key={item.key} content={item.content} />
        if (item.type === 'tool-group') return <ToolRunSummary key={item.key} parts={item.parts} />
        if (item.type === 'tool') return <ToolPartCard key={item.key} part={item.part} approve={approve} deny={deny} />
        return null
      })}
    </>
  )
}

function buildAssistantRenderItems(parts: UIMessage['parts']): AssistantRenderItem[] {
  const items: AssistantRenderItem[] = []
  let pending: ToolPart[] = []
  const flush = () => {
    if (!pending.length) return
    items.push({ type: 'tool-group', parts: pending, key: `tools-${items.length}` })
    pending = []
  }
  parts.forEach((part, index) => appendAssistantPart(items, pending, flush, part as MessagePart, index))
  flush()
  return items
}

function appendAssistantPart(items: AssistantRenderItem[], pending: ToolPart[], flush: () => void, item: MessagePart, index: number) {
  if (item.type === 'text') {
    flush()
    items.push({ type: 'text', content: String(item.text || ''), key: `text-${index}` })
  } else if (isToolPart(item) && shouldRenderStandaloneTool(item)) {
    flush()
    items.push({ type: 'tool', part: item, key: `${item.toolCallId}-${index}` })
  } else if (isToolPart(item)) {
    pending.push(item)
  }
}

function UserText({ message }: { message: UIMessage }) {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => String((part as MessagePart).text || ''))
    .join('\n')
}

function ToolPartCard({ part, approve, deny }: { part: ToolPart; approve: (id: string) => void; deny: (id: string) => void }) {
  const { t } = usePreferences()
  const toolName = getToolName(part)
  const stateLabel = toolStateLabel(part, t)
  return (
    <div className={`my-2 rounded-md border px-3 py-2 ${toolToneClass(toolName)}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-1.5">
          <Wrench size={12} className="shrink-0" />
          <span className="truncate text-[12px] font-medium">{formatToolName(toolName, t)}</span>
        </span>
        <span className="shrink-0 text-[10px] opacity-75">{stateLabel}</span>
      </div>
      <ToolStructuredOutput toolName={toolName} output={part.output} />
      {part.errorText && <p className="mt-2 text-xs text-red-700 dark:text-red-200">{part.errorText}</p>}
      {part.state === 'approval-requested' && part.approval?.id && (
        <div className="mt-3 flex items-center gap-2">
          <button type="button" onClick={() => approve(part.approval!.id)} className="inline-flex items-center gap-1 rounded-md bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700">
            <Check size={12} />
            {t('chat.approve')}
          </button>
          <button type="button" onClick={() => deny(part.approval!.id)} className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted/60">
            <X size={12} />
            {t('chat.deny')}
          </button>
        </div>
      )}
    </div>
  )
}

function ToolRunSummary({ parts }: { parts: ToolPart[] }) {
  const { t } = usePreferences()
  const labels = uniqueToolLabels(parts, t)
  const hasFailure = parts.some((part) => part.state === 'output-error')
  return (
    <div className="my-2 rounded-md border border-border/70 bg-background/70 px-3 py-2 text-[12px] text-muted-foreground">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-1.5 font-medium text-foreground">
          <Wrench size={12} className="shrink-0 text-primary" />
          <span className="truncate">{toolGroupTitle(parts, t)}</span>
        </span>
        <span className="shrink-0 text-[10px]">{toolGroupState(parts, t)}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {labels.map((label) => <span key={label} className="rounded-full bg-muted px-2 py-0.5 text-[11px]">{label}</span>)}
      </div>
      {hasFailure && <p className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-200">{t('chat.toolPartialFailure')}</p>}
    </div>
  )
}

function ToolStructuredOutput({ toolName, output }: { toolName: string; output: unknown }) {
  if (toolName === 'screen_stocks' && isScreenResult(output)) return <ScreenResultCard data={output} />
  if (toolName === 'analyze_stock' && isAnalyzeResult(output)) return <AnalyzeResultCard data={output} />
  if (toolName === 'generate_strategy_decision' && isStrategyResult(output)) return <StrategyResultCard data={output} />
  if (output == null) return null
  return <p className="mt-1 line-clamp-2 text-[11px] opacity-80">{summarizeToolOutput(output)}</p>
}

function AnalyzeResultCard({ data }: { data: AnalyzeStockResult }) {
  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-2 text-[11px]">
        <span className="rounded-full bg-background/70 px-2 py-0.5">阶段 {data.phase}</span>
        {data.confidence != null && <span className="rounded-full bg-background/70 px-2 py-0.5">置信 {data.confidence.toFixed(0)}</span>}
        {data.support && <span className="rounded-full bg-background/70 px-2 py-0.5">支撑 {data.support}</span>}
        {data.resistance && <span className="rounded-full bg-background/70 px-2 py-0.5">压力 {data.resistance}</span>}
      </div>
      <p className="text-xs font-medium">{data.action}</p>
      <MarkdownContent content={data.markdown || data.summary} className="text-xs" />
    </div>
  )
}

function StrategyResultCard({ data }: { data: StrategyDecisionResult }) {
  return (
    <div className="mt-2 space-y-2 text-xs">
      <p className="font-medium">{data.summary}</p>
      <div className="flex flex-wrap gap-2 text-[11px]">
        <span className="rounded-full bg-background/70 px-2 py-0.5">环境 {data.market_regime}</span>
        <span className="rounded-full bg-background/70 px-2 py-0.5">仓位 {data.overall_position}</span>
      </div>
      {data.position_actions.length > 0 && (
        <div className="space-y-1">
          {data.position_actions.map((item) => (
            <div key={`${item.code}-${item.action}`} className="rounded border border-border/50 bg-background/40 px-2 py-1">
              <div className="font-medium">{item.code} {item.name || ''} · {item.action}</div>
              <div className="mt-0.5 opacity-80">{item.reason}</div>
            </div>
          ))}
        </div>
      )}
      <p className="opacity-80">{data.risk}</p>
    </div>
  )
}

function ChatComposer(props: {
  input: string
  loading: boolean
  onInput: (value: string) => void
  onSubmit: (e: React.FormEvent) => void
  onStop: () => void
}) {
  const { t } = usePreferences()
  return (
    <div className="shrink-0 border-t border-border bg-background px-6 py-3">
      <form onSubmit={props.onSubmit} className="flex items-center gap-2">
        <input
          type="text"
          value={props.input}
          onChange={(e) => props.onInput(e.target.value)}
          placeholder={t('chat.placeholder')}
          aria-label={t('chat.placeholder')}
          className="flex-1 rounded-xl border border-border bg-background px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring/20"
        />
        <button
          type={props.loading ? 'button' : 'submit'}
          onClick={props.loading ? props.onStop : undefined}
          disabled={!props.loading && !props.input.trim()}
          aria-label={props.loading ? t('chat.stop') : t('chat.placeholder')}
          className={`flex h-10 w-10 items-center justify-center rounded-xl text-primary-foreground disabled:opacity-40 ${props.loading ? 'bg-rose-600 hover:bg-rose-700' : 'bg-primary'}`}
        >
          {props.loading ? <Square size={15} /> : <Send size={16} />}
        </button>
      </form>
      <div className="mt-2 text-center"><AIDisclaimer /></div>
    </div>
  )
}

function EmptyChat({ onPick }: { onPick: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <div className="flex min-h-full flex-col items-center justify-center text-muted-foreground">
      <div className="mb-4 rounded-full border border-border bg-muted/40 p-3 text-primary">
        <Activity size={28} />
      </div>
      <p className="text-sm font-medium">{t('chat.emptyTitle')}</p>
      <p className="mt-2 text-xs text-muted-foreground">{t('chat.tryAsk')}</p>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {[t('chat.prompt.portfolio'), t('chat.prompt.market'), t('chat.prompt.recent'), t('chat.prompt.search'), t('chat.prompt.screen'), t('chat.prompt.strategy')].map((q) => (
          <button key={q} onClick={() => onPick(q)} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted/50">
            {q}
          </button>
        ))}
      </div>
      <div className="mt-8 rounded-lg border border-dashed border-border/60 px-4 py-2.5 text-center">
        <p className="text-[11px] text-muted-foreground/70">
          {t('chat.fullVersionPrefix')} · <code className="rounded bg-muted px-1 py-0.5 text-[10px]">curl -fsSL https://raw.githubusercontent.com/YoungCan-Wang/Wyckoff-Analysis/main/install.sh | bash</code> {t('chat.unlockFull')}
        </p>
      </div>
    </div>
  )
}

function ThinkingBubble() {
  const { t } = usePreferences()
  return (
    <div className="flex justify-start">
      <div className="max-w-[82%] rounded-2xl bg-muted px-4 py-2.5 text-sm text-foreground">
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          <span>{t('chat.thinking')}</span>
        </div>
      </div>
    </div>
  )
}

function buildChatTransport(token: string | undefined) {
  return new DefaultChatTransport({
    api: apiUrl('/api/chat'),
    headers: (): Record<string, string> => token ? { Authorization: `Bearer ${token}` } : {},
  })
}

async function fetchChatConfig(token: string): Promise<ChatConfig> {
  const response = await fetch(apiUrl('/api/chat/config'), {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) return { configured: false, model: null }
  return await response.json() as ChatConfig
}

function apiUrl(path: string): string {
  const base = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://127.0.0.1:8787' : '')
  return `${base.replace(/\/$/, '')}${path}`
}

function isToolPart(part: MessagePart): part is ToolPart {
  return typeof part.type === 'string' && (part.type.startsWith('tool-') || part.type === 'dynamic-tool')
}

function getToolName(part: ToolPart): string {
  if (part.type === 'dynamic-tool') return String(part.toolName || '')
  return part.type.slice(5)
}

function formatToolName(toolName: string, t: (key: TranslationKey) => string): string {
  const labelKey = TOOL_LABEL_KEYS[toolName]
  return labelKey ? t(labelKey) : toolName
}

function toolToneClass(toolName: string): string {
  return TOOL_TONES[toolName] || 'border-border bg-background text-foreground'
}

function toolStateLabel(part: ToolPart, t: (key: TranslationKey) => string): string {
  if (part.state === 'approval-requested') return t('chat.awaitingApproval')
  if (part.state === 'output-denied') return t('chat.denied')
  if (part.state === 'output-available') return t('chat.toolDone')
  if (part.state === 'output-error') return t('chat.requestFailed')
  return t('chat.toolRunning')
}

function shouldRenderStandaloneTool(part: ToolPart): boolean {
  const toolName = getToolName(part)
  if (ACTION_TOOL_NAMES.has(toolName)) return true
  if (part.state === 'approval-requested' || part.state === 'output-denied') return true
  return STRUCTURED_TOOL_NAMES.has(toolName) && part.state === 'output-available'
}

function toolGroupTitle(parts: ToolPart[], t: (key: TranslationKey) => string): string {
  const names = new Set(parts.map(getToolName))
  if (names.has('market_overview') || names.has('market_history')) return t('chat.toolGroupMarketData')
  return t('chat.toolGroupDataLookup')
}

function toolGroupState(parts: ToolPart[], t: (key: TranslationKey) => string): string {
  if (parts.some(isRunningTool)) return t('chat.toolRunning')
  if (parts.some((part) => part.state === 'output-error')) return t('chat.toolGroupPartial')
  return t('chat.toolDone')
}

function isRunningTool(part: ToolPart): boolean {
  return !['output-available', 'output-error', 'output-denied', 'approval-responded'].includes(part.state)
}

function uniqueToolLabels(parts: ToolPart[], t: (key: TranslationKey) => string): string[] {
  const labels: string[] = []
  for (const part of parts) {
    const label = toolChipLabel(part, t)
    if (!labels.includes(label)) labels.push(label)
  }
  return labels.slice(0, 5)
}

function toolChipLabel(part: ToolPart, t: (key: TranslationKey) => string): string {
  const toolName = getToolName(part)
  const inputLabel = toolInputLabel(toolName, part.input)
  const base = formatToolName(toolName, t)
  return inputLabel ? `${base} · ${inputLabel}` : base
}

function toolInputLabel(toolName: string, input: unknown): string {
  if (toolName !== 'market_history') return ''
  const value = asRecord(input)
  const index = String(value?.index || 'sse')
  const days = typeof value?.days === 'number' ? `${value.days}日` : ''
  const label = MARKET_INDEX_LABELS[index] || index
  return days ? `${label}/${days}` : label
}

function isScreenResult(value: unknown): value is ScreenResult {
  const item = asRecord(value)
  return Boolean(item && typeof item.date === 'string' && Array.isArray(item.stocks) && asRecord(item.meta))
}

function isAnalyzeResult(value: unknown): value is AnalyzeStockResult {
  const item = asRecord(value)
  return Boolean(item && typeof item.summary === 'string' && typeof item.phase === 'string' && typeof item.markdown === 'string')
}

function isStrategyResult(value: unknown): value is StrategyDecisionResult {
  const item = asRecord(value)
  return Boolean(item && typeof item.summary === 'string' && Array.isArray(item.position_actions))
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function summarizeToolOutput(value: unknown): string {
  if (typeof value === 'string') return value.replace(/\s+/g, ' ').slice(0, 160)
  if (Array.isArray(value)) return `${value.length} rows`
  const item = asRecord(value)
  if (!item) return String(value ?? '-')
  return Object.keys(item).slice(0, 4).map((key) => `${key}: ${formatPreviewValue(item[key])}`).join(' · ')
}

function formatPreviewValue(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} rows`
  if (value && typeof value === 'object') return 'object'
  return String(value ?? '-').slice(0, 40)
}
