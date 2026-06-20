import { useCallback, useEffect, useMemo, useRef, useState, memo } from 'react'
import {
  Activity,
  BarChart3,
  BellPlus,
  BookOpenCheck,
  Check,
  ClipboardList,
  Compass,
  Eye,
  Gauge,
  LineChart,
  ListChecks,
  Pin,
  Plus,
  RotateCcw,
  Send,
  ShieldAlert,
  Sparkles,
  Square,
  Target,
  Trash2,
  WalletCards,
  Wrench,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'
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
import type { AnalyzeStockResult, ScreenResult, ScreenStockItem, StrategyDecisionResult } from '@wyckoff/shared'

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
const MAX_QUEUED_MESSAGES = 5
const WATCHLIST_LIMIT = 18
const WATCHLIST_STORAGE_VERSION = 'reading-room-watchlist-v1'

const READING_ROOM_SCENARIOS: DeskScenario[] = [
  {
    id: 'premarket',
    title: '盘前',
    eyebrow: '市场先验',
    description: '水温、持仓、候选池先排队。',
    prompt: '做一次盘前读盘：先看市场水温和风险状态，再结合我的持仓、最新漏斗候选和威科夫形态复盘，给出今天只需要盯的 3 件事。',
    Icon: Gauge,
    toneClass: 'border-sky-200 bg-sky-50/75 text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100',
  },
  {
    id: 'intraday',
    title: '盘中',
    eyebrow: '临场判断',
    description: '先判断该进攻、等待还是防守。',
    prompt: '做一次盘中读盘：先读取市场水温，再判断当前更适合进攻、等待还是防守；如果需要我补股票代码，请直接问我。',
    Icon: Activity,
    toneClass: 'border-emerald-200 bg-emerald-50/75 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100',
  },
  {
    id: 'tail',
    title: '尾盘',
    eyebrow: '明日线索',
    description: '把尾盘机会和漏斗候选合并看。',
    prompt: '做一次尾盘机会筛选：读取尾盘记录和漏斗选股，按证据强弱列出明天值得观察的股票，并给出触发条件和失效条件。',
    Icon: Zap,
    toneClass: 'border-amber-200 bg-amber-50/80 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100',
  },
  {
    id: 'review',
    title: '复盘',
    eyebrow: '信号归因',
    description: '看哪些信号有效，哪些要降权。',
    prompt: '做一次收盘复盘：回看最近威科夫形态复盘、策略归因和尾盘记录，告诉我哪些信号有效、哪些是噪音，明天应该降权或加权什么。',
    Icon: BookOpenCheck,
    toneClass: 'border-rose-200 bg-rose-50/75 text-rose-900 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100',
  },
]

const INTELLIGENCE_SHORTCUTS: DeskShortcut[] = [
  {
    title: '市场水温',
    description: '大盘、A50、VIX 和风险状态。',
    prompt: '先读取市场水温，告诉我今天的市场先验、风险级别和仓位倾向。',
    Icon: BarChart3,
    metric: '先验',
  },
  {
    title: '持仓风险',
    description: '把我的持仓按处理优先级排序。',
    prompt: '查看我的持仓，并按“需要处理、继续观察、暂不操作”分组，给出每只票的风险点和下一步。',
    Icon: WalletCards,
    metric: '持仓',
  },
  {
    title: '候选漏斗',
    description: '高分候选先给交易条件。',
    prompt: '运行漏斗选股，把结果按分数、形态阶段和证据强弱排序，并告诉我最值得盯的前 5 只。',
    Icon: ListChecks,
    metric: '候选',
  },
  {
    title: '尾盘记录',
    description: '只看尾盘确认和隔日线索。',
    prompt: '读取尾盘记录，筛出有尾盘确认、次日仍值得观察的标的，并说明为什么。',
    Icon: LineChart,
    metric: '尾盘',
  },
  {
    title: '策略归因',
    description: '用近期结果校准信号权重。',
    prompt: '读取策略归因报告，告诉我最近哪些信号贡献最好、哪些信号需要降权，并把结论用于今天读盘。',
    Icon: ClipboardList,
    metric: '归因',
  },
]

type MessagePart = UIMessage['parts'][number] & Record<string, unknown>
type ReadingRoomChat = ReturnType<typeof useChat<UIMessage>>
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
  error?: string
}

interface QueuedMessage {
  id: string
  text: string
}

interface MessageQueue {
  messages: QueuedMessage[]
  enqueue: (text: string) => void
  clear: () => void
}

interface DeskScenario {
  id: string
  title: string
  eyebrow: string
  description: string
  prompt: string
  Icon: LucideIcon
  toneClass: string
}

interface DeskShortcut {
  title: string
  description: string
  prompt: string
  Icon: LucideIcon
  metric: string
}

interface WatchItem {
  id: string
  code: string
  name: string
  reason: string
  source: string
  trigger: string
  invalidation: string
  addedAt: string
  updatedAt: string
  score?: number | null
  changePct?: number | null
  phase?: string | null
  action?: string | null
}

interface PinStockInput {
  code: string
  name?: string | null
  reason: string
  source: string
  trigger?: string | null
  invalidation?: string | null
  score?: number | null
  changePct?: number | null
  phase?: string | null
  action?: string | null
}

interface ReadingRoomWatchlist {
  items: WatchItem[]
  add: (item: PinStockInput) => void
  remove: (code: string) => void
}

export function ChatPage() {
  const session = useAuthStore((s) => s.session)
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [input, setInput] = useState('')
  const [localError, setLocalError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const token = session?.access_token
  const config = useChatConfig(token, t)
  const chat = useReadingRoomChat(token, setLocalError, t)
  const loading = chat.status === 'submitted' || chat.status === 'streaming'
  const queue = useMessageQueue(chat, loading, token, config.configured, setLocalError, t)
  const watchlist = useReadingRoomWatchlist(user?.id)
  useAutoScroll(scrollRef, chat.messages, loading, queue.messages.length)

  const submitText = useCallback((rawText: string) => {
    const text = rawText.trim()
    if (!text) return
    if (!token) { setLocalError(t('chat.requestFailed')); return }
    if (!config.configured) { setLocalError(config.error || t('chat.configureLLM')); return }
    setInput('')
    setLocalError('')
    chat.clearError()
    if (loading) {
      queue.enqueue(text)
      return
    }
    void chat.sendMessage({ text })
  }, [chat, config.configured, config.error, loading, queue, t, token])

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    submitText(input)
  }, [input, submitText])

  const handleNewChat = useCallback(() => {
    if (loading) void chat.stop()
    queue.clear()
    chat.setMessages([])
    setInput('')
    setLocalError('')
    chat.clearError()
  }, [chat, loading, queue])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <ChatHeader config={config} hasUser={Boolean(user)} watchCount={watchlist.items.length} onNewChat={handleNewChat} />
      <ChatMessages
        chat={chat}
        loading={loading}
        queuedMessages={queue.messages}
        scrollRef={scrollRef}
        watchlist={watchlist.items}
        onPick={setInput}
        onPinStock={watchlist.add}
        onRemoveWatchItem={watchlist.remove}
        onStart={submitText}
      />
      <ErrorBanner message={localError || chat.error?.message || ''} />
      <ChatComposer input={input} loading={loading} queuedCount={queue.messages.length} onClearQueue={queue.clear} onInput={setInput} onSubmit={handleSubmit} onStop={() => void chat.stop()} />
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

function useChatConfig(token: string | undefined, t: (key: TranslationKey, vars?: Record<string, string>) => string): ChatConfig {
  const [config, setConfig] = useState<ChatConfig>({ configured: false, model: null })
  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetchChatConfig(token, t)
      .then((next) => { if (!cancelled) setConfig(next) })
      .catch(() => {
        if (!cancelled) setConfig({ configured: false, model: null, error: t('chat.configUnreachable') })
      })
    return () => { cancelled = true }
  }, [t, token])
  return config
}

function useMessageQueue(
  chat: ReadingRoomChat,
  loading: boolean,
  token: string | undefined,
  configured: boolean,
  setLocalError: (value: string) => void,
  t: (key: TranslationKey) => string,
): MessageQueue {
  const [messages, setMessages] = useState<QueuedMessage[]>([])
  const dispatchingRef = useRef('')
  const enqueue = useCallback((text: string) => {
    setMessages((items) => {
      if (items.length >= MAX_QUEUED_MESSAGES) {
        setLocalError(t('chat.queueFull'))
        return items
      }
      return [...items, { id: createQueuedMessageId(), text }]
    })
  }, [setLocalError, t])
  const clear = useCallback(() => setMessages([]), [])

  useEffect(() => {
    const next = messages[0]
    if (!next || loading || !token || !configured || dispatchingRef.current) return
    dispatchingRef.current = next.id
    setMessages((items) => items[0]?.id === next.id ? items.slice(1) : items.filter((item) => item.id !== next.id))
    setLocalError('')
    chat.clearError()
    void chat.sendMessage({ text: next.text })
      .catch((error: unknown) => setLocalError(normalizeClientError(error, t)))
      .finally(() => { dispatchingRef.current = '' })
  }, [chat, configured, loading, messages, setLocalError, t, token])

  return useMemo(() => ({ messages, enqueue, clear }), [clear, enqueue, messages])
}

function useReadingRoomWatchlist(userId: string | undefined): ReadingRoomWatchlist {
  const storageKey = useMemo(() => watchlistStorageKey(userId), [userId])
  const [items, setItems] = useState<WatchItem[]>([])
  const [loadedKey, setLoadedKey] = useState('')

  useEffect(() => {
    setItems(readWatchlist(storageKey))
    setLoadedKey(storageKey)
  }, [storageKey])

  useEffect(() => {
    if (loadedKey !== storageKey) return
    writeWatchlist(storageKey, items)
  }, [items, loadedKey, storageKey])

  const add = useCallback((item: PinStockInput) => {
    const code = normalizeStockCode(item.code)
    if (!code) return
    const now = new Date().toISOString()
    setItems((current) => {
      const existing = current.find((entry) => entry.code === code)
      const nextItem: WatchItem = {
        id: existing?.id || `watch-${code}`,
        code,
        name: sanitizeText(item.name) || existing?.name || '',
        reason: item.reason || existing?.reason || '读盘室观察',
        source: item.source || existing?.source || '读盘室',
        trigger: sanitizeText(item.trigger) || existing?.trigger || '等放量突破或回踩确认',
        invalidation: sanitizeText(item.invalidation) || existing?.invalidation || '跌破关键支撑或证据消失',
        addedAt: existing?.addedAt || now,
        updatedAt: now,
        score: item.score ?? existing?.score ?? null,
        changePct: item.changePct ?? existing?.changePct ?? null,
        phase: sanitizeText(item.phase) || existing?.phase || null,
        action: sanitizeText(item.action) || existing?.action || null,
      }
      return [nextItem, ...current.filter((entry) => entry.code !== code)].slice(0, WATCHLIST_LIMIT)
    })
  }, [])

  const remove = useCallback((code: string) => {
    const normalized = normalizeStockCode(code)
    setItems((current) => current.filter((item) => item.code !== normalized))
  }, [])

  return useMemo(() => ({ items, add, remove }), [add, items, remove])
}

function watchlistStorageKey(userId: string | undefined): string {
  return `wyckoff:${userId || 'guest'}:${WATCHLIST_STORAGE_VERSION}`
}

function readWatchlist(key: string): WatchItem[] {
  if (typeof window === 'undefined') return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeWatchItem).filter(Boolean).slice(0, WATCHLIST_LIMIT) as WatchItem[]
  } catch {
    return []
  }
}

function writeWatchlist(key: string, items: WatchItem[]) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, JSON.stringify(items.slice(0, WATCHLIST_LIMIT)))
  } catch {
    // localStorage may be disabled; the in-memory basket still works for this session.
  }
}

function normalizeWatchItem(value: unknown): WatchItem | null {
  const item = asRecord(value)
  const code = normalizeStockCode(item?.code)
  if (!item || !code) return null
  return {
    id: sanitizeText(item.id) || `watch-${code}`,
    code,
    name: sanitizeText(item.name),
    reason: sanitizeText(item.reason) || '读盘室观察',
    source: sanitizeText(item.source) || '读盘室',
    trigger: sanitizeText(item.trigger) || '等放量突破或回踩确认',
    invalidation: sanitizeText(item.invalidation) || '跌破关键支撑或证据消失',
    addedAt: sanitizeText(item.addedAt) || new Date().toISOString(),
    updatedAt: sanitizeText(item.updatedAt) || new Date().toISOString(),
    score: nullableNumber(item.score),
    changePct: nullableNumber(item.changePct),
    phase: sanitizeText(item.phase) || null,
    action: sanitizeText(item.action) || null,
  }
}

function sanitizeText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function normalizeStockCode(value: unknown): string {
  return sanitizeText(value).toUpperCase()
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function createQueuedMessageId(): string {
  return `queued-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function normalizeClientError(error: unknown, t: (key: TranslationKey) => string): string {
  return error instanceof Error ? error.message : t('chat.requestFailed')
}

function useAutoScroll(ref: React.RefObject<HTMLDivElement | null>, messages: UIMessage[], loading: boolean, queuedCount: number) {
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading, queuedCount, ref])
}

function ChatHeader({ config, hasUser, watchCount, onNewChat }: { config: ChatConfig; hasUser: boolean; watchCount: number; onNewChat: () => void }) {
  const { t } = usePreferences()
  return (
    <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-3">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">{t('chat.title')}</h1>
        {config.model && <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200">{config.model}</span>}
        {watchCount > 0 && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200"><Pin size={11} />观察 {watchCount}</span>}
        {!config.configured && hasUser && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">{config.error ? t('chat.configErrorBadge') : t('chat.noApiKey')}</span>}
      </div>
      <button onClick={onNewChat} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-muted/50">
        <RotateCcw size={14} />
        {t('chat.newChat')}
      </button>
    </div>
  )
}

function ChatMessages({
  chat,
  loading,
  queuedMessages,
  scrollRef,
  watchlist,
  onPick,
  onPinStock,
  onRemoveWatchItem,
  onStart,
}: {
  chat: ReadingRoomChat
  loading: boolean
  queuedMessages: QueuedMessage[]
  scrollRef: React.RefObject<HTMLDivElement | null>
  watchlist: WatchItem[]
  onPick: (value: string) => void
  onPinStock: (item: PinStockInput) => void
  onRemoveWatchItem: (code: string) => void
  onStart: (value: string) => void
}) {
  const activeAssistantId = loading ? lastAssistantId(chat.messages) : null
  const isEmpty = chat.messages.length === 0 && !loading && queuedMessages.length === 0
  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto px-6 py-4">
      {isEmpty ? (
        <ReadingRoomDashboard watchlist={watchlist} onPick={onPick} onRemoveWatchItem={onRemoveWatchItem} onStart={onStart} />
      ) : (
        <div className="space-y-4 pb-2">
          {chat.messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              isActive={message.id === activeAssistantId}
              approve={(id) => void chat.addToolApprovalResponse({ id, approved: true })}
              deny={(id) => void chat.addToolApprovalResponse({ id, approved: false })}
              onPinStock={onPinStock}
            />
          ))}
          {queuedMessages.map((message, index) => <QueuedMessageBubble key={message.id} message={message} index={index + 1} />)}
          {loading && <ThinkingBubble />}
        </div>
      )}
    </div>
  )
}

function lastAssistantId(messages: UIMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant') return message.id
  }
  return null
}

function ErrorBanner({ message }: { message: string }) {
  if (!message) return null
  return <div className="mx-6 mb-2 shrink-0 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-200">{message}</div>
}

const MessageBubble = memo(function MessageBubble({
  message,
  isActive,
  approve,
  deny,
  onPinStock,
}: {
  message: UIMessage
  isActive: boolean
  approve: (approvalId: string) => void
  deny: (approvalId: string) => void
  onPinStock: (item: PinStockInput) => void
}) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-sm ${isUser ? 'bg-primary text-primary-foreground whitespace-pre-wrap' : 'bg-muted text-foreground'}`}>
        {isUser ? <UserText message={message} /> : <AssistantParts message={message} isActive={isActive} approve={approve} deny={deny} onPinStock={onPinStock} />}
      </div>
    </div>
  )
})

function QueuedMessageBubble({ message, index }: { message: QueuedMessage; index: number }) {
  const { t } = usePreferences()
  return (
    <div className="flex justify-end">
      <div className="max-w-[82%] rounded-2xl bg-primary/80 px-4 py-2.5 text-sm text-primary-foreground">
        <div className="whitespace-pre-wrap">{message.text}</div>
        <div className="mt-1 text-right text-[10px] opacity-80">
          {t('chat.queued').replace('{index}', String(index))}
        </div>
      </div>
    </div>
  )
}

function AssistantParts({
  message,
  isActive,
  approve,
  deny,
  onPinStock,
}: {
  message: UIMessage
  isActive: boolean
  approve: (id: string) => void
  deny: (id: string) => void
  onPinStock: (item: PinStockInput) => void
}) {
  const items = buildAssistantRenderItems(message.parts)
  return (
    <>
      {items.map((item) => {
        if (item.type === 'text') return <MarkdownContent key={item.key} content={item.content} />
        if (item.type === 'tool-group') return <ToolRunSummary key={item.key} parts={item.parts} isActive={isActive} />
        if (item.type === 'tool') return <ToolPartCard key={item.key} part={item.part} approve={approve} deny={deny} onPinStock={onPinStock} />
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

function ToolPartCard({
  part,
  approve,
  deny,
  onPinStock,
}: {
  part: ToolPart
  approve: (id: string) => void
  deny: (id: string) => void
  onPinStock: (item: PinStockInput) => void
}) {
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
      <ToolStructuredOutput toolName={toolName} input={part.input} output={part.output} onPinStock={onPinStock} />
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

function ToolRunSummary({ parts, isActive }: { parts: ToolPart[]; isActive: boolean }) {
  const { t } = usePreferences()
  const labels = uniqueToolLabels(parts, t)
  const hasFailure = parts.some((part) => part.state === 'output-error')
  const wasInterrupted = !isActive && parts.some(isRunningTool)
  return (
    <div className="my-2 rounded-md border border-border/70 bg-background/70 px-3 py-2 text-[12px] text-muted-foreground">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-1.5 font-medium text-foreground">
          <Wrench size={12} className="shrink-0 text-primary" />
          <span className="truncate">{toolGroupTitle(parts, t)}</span>
        </span>
        <span className="shrink-0 text-[10px]">{toolGroupState(parts, t, isActive)}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {labels.map((label) => <span key={label} className="rounded-full bg-muted px-2 py-0.5 text-[11px]">{label}</span>)}
      </div>
      {hasFailure && <p className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-200">{t('chat.toolPartialFailure')}</p>}
      {wasInterrupted && <p className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-200">{t('chat.toolInterruptedHint')}</p>}
    </div>
  )
}

function ToolStructuredOutput({
  toolName,
  input,
  output,
  onPinStock,
}: {
  toolName: string
  input: unknown
  output: unknown
  onPinStock: (item: PinStockInput) => void
}) {
  if (toolName === 'screen_stocks' && isScreenResult(output)) {
    return <ScreenResultCard data={output} onPinStock={(stock) => onPinStock(pinFromScreenStock(stock))} />
  }
  if (toolName === 'analyze_stock' && isAnalyzeResult(output)) return <AnalyzeResultCard data={output} input={input} onPinStock={onPinStock} />
  if (toolName === 'generate_strategy_decision' && isStrategyResult(output)) return <StrategyResultCard data={output} onPinStock={onPinStock} />
  if (output == null) return null
  return <p className="mt-1 line-clamp-2 text-[11px] opacity-80">{summarizeToolOutput(output)}</p>
}

function pinFromScreenStock(stock: ScreenStockItem): PinStockInput {
  return {
    code: stock.code,
    name: stock.name,
    reason: stock.funnel_score != null ? `漏斗分 ${stock.funnel_score.toFixed(2)} 的候选股` : '漏斗选股候选',
    source: '漏斗选股',
    trigger: '等待放量突破、缩量回踩或尾盘确认',
    invalidation: '跌破形态关键支撑或后续证据转弱',
    score: stock.funnel_score,
    changePct: stock.change_pct,
  }
}

function AnalyzeResultCard({
  data,
  input,
  onPinStock,
}: {
  data: AnalyzeStockResult
  input: unknown
  onPinStock: (item: PinStockInput) => void
}) {
  const inputRecord = asRecord(input)
  const code = normalizeStockCode(inputRecord?.code || inputRecord?.symbol || inputRecord?.ts_code)
  const name = sanitizeText(inputRecord?.name)

  return (
    <div className="mt-2 space-y-2 rounded-lg border border-border/50 bg-background/50 p-3">
      <AnalyzeResultHeader data={data} code={code} name={name} onPinStock={onPinStock} />
      <div className="grid gap-2 text-[11px] sm:grid-cols-3">
        <DecisionMetric label="阶段" value={data.phase} />
        <DecisionMetric label="动作" value={data.action} />
        <DecisionMetric label="置信" value={data.confidence != null ? data.confidence.toFixed(0) : '--'} />
      </div>
      <AnalyzeLevelBadges data={data} />
      <MarkdownContent content={data.markdown || data.summary} className="text-xs" />
    </div>
  )
}

function AnalyzeResultHeader({
  data,
  code,
  name,
  onPinStock,
}: {
  data: AnalyzeStockResult
  code: string
  name: string
  onPinStock: (item: PinStockInput) => void
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <div className="text-[11px] text-muted-foreground">个股决策卡</div>
        <p className="text-sm font-semibold">{code ? `${code}${name ? ` ${name}` : ''}` : data.summary}</p>
      </div>
      {code && <PinAnalyzeButton data={data} code={code} name={name} onPinStock={onPinStock} />}
    </div>
  )
}

function PinAnalyzeButton({ data, code, name, onPinStock }: {
  data: AnalyzeStockResult
  code: string
  name: string
  onPinStock: (item: PinStockInput) => void
}) {
  return (
    <button type="button" onClick={() => onPinStock(pinFromAnalyze(data, code, name))} className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/70 hover:text-foreground">
      <BellPlus size={12} />
      观察
    </button>
  )
}

function pinFromAnalyze(data: AnalyzeStockResult, code: string, name: string): PinStockInput {
  return {
    code,
    name,
    reason: data.action || data.summary,
    source: '个股诊断',
    trigger: data.resistance ? `突破或站稳 ${data.resistance}` : '等待关键位确认',
    invalidation: data.support ? `跌破 ${data.support}` : data.risk,
    phase: data.phase,
    action: data.action,
  }
}

function AnalyzeLevelBadges({ data }: { data: AnalyzeStockResult }) {
  return (
    <div className="flex flex-wrap gap-2 text-[11px]">
      {data.support && <span className="rounded-full bg-down/10 px-2 py-0.5 text-down">支撑 {data.support}</span>}
      {data.resistance && <span className="rounded-full bg-up/10 px-2 py-0.5 text-up">压力 {data.resistance}</span>}
      {data.risk && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">风险 {data.risk}</span>}
    </div>
  )
}

function DecisionMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-background/60 px-2 py-1.5">
      <div className="text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate font-medium text-foreground">{value || '--'}</div>
    </div>
  )
}

function StrategyResultCard({
  data,
  onPinStock,
}: {
  data: StrategyDecisionResult
  onPinStock: (item: PinStockInput) => void
}) {
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-border/50 bg-background/50 p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[11px] text-muted-foreground">组合策略卡</div>
          <p className="font-semibold">{data.summary}</p>
        </div>
        <ShieldAlert size={16} className="shrink-0 text-amber-600" />
      </div>
      <div className="grid gap-2 text-[11px] sm:grid-cols-2">
        <DecisionMetric label="市场环境" value={data.market_regime} />
        <DecisionMetric label="总仓位" value={data.overall_position} />
      </div>
      <StrategyActionList actions={data.position_actions} onPinStock={onPinStock} />
      <p className="text-muted-foreground">组合风险：{data.risk}</p>
    </div>
  )
}

function StrategyActionList({ actions, onPinStock }: {
  actions: StrategyDecisionResult['position_actions']
  onPinStock: (item: PinStockInput) => void
}) {
  if (actions.length === 0) return null
  return (
    <div className="space-y-1.5">
      {actions.map((item) => <StrategyActionCard key={`${item.code}-${item.action}`} item={item} onPinStock={onPinStock} />)}
    </div>
  )
}

function StrategyActionCard({ item, onPinStock }: {
  item: StrategyDecisionResult['position_actions'][number]
  onPinStock: (item: PinStockInput) => void
}) {
  return (
    <div className="rounded-md border border-border/50 bg-background/60 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 font-medium">
          <span className="font-mono">{item.code}</span> {item.name || ''} · {item.action}
        </div>
        <button type="button" onClick={() => onPinStock(pinFromStrategy(item))} className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/70 hover:text-foreground">
          <Plus size={12} />
          观察
        </button>
      </div>
      <div className="mt-0.5 text-muted-foreground">{item.reason}</div>
      {item.risk && <div className="mt-0.5 text-amber-700 dark:text-amber-200">风险：{item.risk}</div>}
    </div>
  )
}

function pinFromStrategy(item: StrategyDecisionResult['position_actions'][number]): PinStockInput {
  return {
    code: item.code,
    name: item.name,
    reason: item.reason,
    source: '策略建议',
    trigger: item.action,
    invalidation: item.risk,
    action: item.action,
  }
}

function ChatComposer(props: {
  input: string
  loading: boolean
  queuedCount: number
  onClearQueue: () => void
  onInput: (value: string) => void
  onSubmit: (e: React.FormEvent) => void
  onStop: () => void
}) {
  return (
    <div className="shrink-0 border-t border-border bg-background px-6 py-3">
      <QueueNotice count={props.queuedCount} onClear={props.onClearQueue} />
      <form onSubmit={props.onSubmit} className="flex items-center gap-2">
        <ComposerInput value={props.input} onInput={props.onInput} />
        <ComposerActions input={props.input} loading={props.loading} onStop={props.onStop} />
      </form>
      <div className="mt-2 text-center"><AIDisclaimer /></div>
    </div>
  )
}

function QueueNotice({ count, onClear }: { count: number; onClear: () => void }) {
  const { t } = usePreferences()
  if (count === 0) return null
  return (
    <div className="mb-2 flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/45 px-3 py-1.5 text-xs text-muted-foreground">
      <span>{t('chat.queueCount').replace('{count}', String(count))}</span>
      <button type="button" onClick={onClear} className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 hover:bg-background hover:text-foreground">
        <X size={12} />
        {t('chat.clearQueue')}
      </button>
    </div>
  )
}

function ComposerInput({ value, onInput }: { value: string; onInput: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onInput(e.target.value)}
      placeholder={t('chat.placeholder')}
      aria-label={t('chat.placeholder')}
      className="flex-1 rounded-xl border border-border bg-background px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring/20"
    />
  )
}

function ComposerActions({ input, loading, onStop }: { input: string; loading: boolean; onStop: () => void }) {
  const { t } = usePreferences()
  if (!loading) return <SendButton disabled={!input.trim()} label={t('chat.placeholder')} />
  return (
    <>
      <SendButton disabled={!input.trim()} label={t('chat.queueMessage')} />
      <button type="button" onClick={onStop} aria-label={t('chat.stop')} className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-600 text-white hover:bg-rose-700">
        <Square size={15} />
      </button>
    </>
  )
}

function SendButton({ disabled, label }: { disabled: boolean; label: string }) {
  return (
    <button type="submit" disabled={disabled} aria-label={label} className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground disabled:opacity-40">
      <Send size={16} />
    </button>
  )
}

function ReadingRoomDashboard({
  watchlist,
  onPick,
  onRemoveWatchItem,
  onStart,
}: {
  watchlist: WatchItem[]
  onPick: (value: string) => void
  onRemoveWatchItem: (code: string) => void
  onStart: (value: string) => void
}) {
  const watchlistPrompt = buildWatchlistReviewPrompt(watchlist)

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-6">
      <ReadingRoomHero watchCount={watchlist.length} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.85fr)]">
        <ScenarioPanel onStart={onStart} />
        <WatchlistPanel watchlist={watchlist} watchlistPrompt={watchlistPrompt} onRemove={onRemoveWatchItem} onStart={onStart} />
      </div>
      <ShortcutPanel onStart={onStart} />
      <PromptPanel onPick={onPick} />
    </div>
  )
}

function ReadingRoomHero({ watchCount }: { watchCount: number }) {
  const { t } = usePreferences()
  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-2xl">
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
            <Compass size={12} />
            READING DESK
          </div>
          <h2 className="text-2xl font-semibold text-foreground">{t('chat.title')}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {t('chat.emptyTitle')}。先定市场先验，再把持仓、候选、尾盘和归因串成一张当日操作清单。
          </p>
        </div>
        <div className="grid min-w-[260px] grid-cols-3 gap-2 rounded-lg border border-border bg-background p-2 text-center">
          <DeskStat label="场景" value="4" Icon={Sparkles} />
          <DeskStat label="情报" value="5" Icon={Target} />
          <DeskStat label="观察" value={String(watchCount)} Icon={Eye} />
        </div>
      </div>
    </section>
  )
}

function ScenarioPanel({ onStart }: { onStart: (value: string) => void }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">今日读盘场景</h3>
          <p className="mt-1 text-xs text-muted-foreground">盘前、盘中、尾盘、复盘都能一键开局。</p>
        </div>
        <button type="button" onClick={() => onStart('帮我从市场水温、持仓风险、漏斗候选和尾盘记录四个角度，生成今天的读盘清单。')} className="inline-flex shrink-0 items-center gap-1 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:opacity-90">
          <Zap size={13} />
          全量读盘
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {READING_ROOM_SCENARIOS.map((scenario) => <ScenarioButton key={scenario.id} scenario={scenario} onStart={onStart} />)}
      </div>
    </section>
  )
}

function ShortcutPanel({ onStart }: { onStart: (value: string) => void }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">情报入口</h3>
          <p className="mt-1 text-xs text-muted-foreground">这些入口会直接调用读盘室工具，不只是一句静态提示。</p>
        </div>
        <Gauge size={16} className="text-muted-foreground" />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {INTELLIGENCE_SHORTCUTS.map((shortcut) => <ShortcutButton key={shortcut.title} shortcut={shortcut} onStart={onStart} />)}
      </div>
    </section>
  )
}

function PromptPanel({ onPick }: { onPick: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <section className="rounded-lg border border-dashed border-border/70 bg-background px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs font-medium text-foreground">{t('chat.tryAsk')}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {chatPromptSuggestions(t).map((q) => (
              <button key={q} type="button" onClick={() => onPick(q)} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted/50 hover:text-foreground">
                {q}
              </button>
            ))}
          </div>
        </div>
        <p className="max-w-xl text-[11px] leading-5 text-muted-foreground/75">
          {t('chat.fullVersionPrefix')} · <code className="rounded bg-muted px-1 py-0.5 text-[10px]">curl -fsSL https://raw.githubusercontent.com/YoungCan-Wang/Wyckoff-Analysis/main/install.sh | bash</code> {t('chat.unlockFull')}
        </p>
      </div>
    </section>
  )
}

function chatPromptSuggestions(t: (key: TranslationKey) => string): string[] {
  return [
    t('chat.prompt.portfolio'),
    t('chat.prompt.market'),
    t('chat.prompt.recent'),
    t('chat.prompt.search'),
    t('chat.prompt.screen'),
    t('chat.prompt.strategy'),
  ]
}

function DeskStat({ label, value, Icon }: { label: string; value: string; Icon: LucideIcon }) {
  return (
    <div className="rounded-md bg-muted/50 px-2 py-2">
      <Icon size={14} className="mx-auto text-muted-foreground" />
      <div className="mt-1 text-base font-semibold">{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </div>
  )
}

function ScenarioButton({ scenario, onStart }: { scenario: DeskScenario; onStart: (value: string) => void }) {
  const { Icon } = scenario
  return (
    <button
      type="button"
      onClick={() => onStart(scenario.prompt)}
      className={`group flex min-h-[132px] flex-col justify-between rounded-lg border p-3 text-left transition hover:-translate-y-0.5 hover:shadow-md ${scenario.toneClass}`}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2">
          <span className="rounded-md bg-background/75 p-1.5">
            <Icon size={16} />
          </span>
          <span className="text-[11px] font-medium opacity-75">{scenario.eyebrow}</span>
        </span>
        <Send size={13} className="opacity-45 transition group-hover:translate-x-0.5 group-hover:opacity-90" />
      </span>
      <span>
        <span className="block text-lg font-semibold">{scenario.title}</span>
        <span className="mt-1 block text-xs leading-5 opacity-75">{scenario.description}</span>
      </span>
    </button>
  )
}

function ShortcutButton({ shortcut, onStart }: { shortcut: DeskShortcut; onStart: (value: string) => void }) {
  const { Icon } = shortcut
  return (
    <button
      type="button"
      onClick={() => onStart(shortcut.prompt)}
      className="flex min-h-[118px] flex-col justify-between rounded-lg border border-border bg-background p-3 text-left transition hover:border-muted-foreground/35 hover:bg-muted/35"
    >
      <span className="flex items-center justify-between gap-2">
        <Icon size={16} className="text-primary" />
        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{shortcut.metric}</span>
      </span>
      <span>
        <span className="block text-sm font-semibold">{shortcut.title}</span>
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">{shortcut.description}</span>
      </span>
    </button>
  )
}

function WatchlistPanel({
  watchlist,
  watchlistPrompt,
  onRemove,
  onStart,
}: {
  watchlist: WatchItem[]
  watchlistPrompt: string
  onRemove: (code: string) => void
  onStart: (value: string) => void
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">观察篮</h3>
          <p className="mt-1 text-xs text-muted-foreground">从候选、诊断和策略卡里沉淀标的。</p>
        </div>
        <button
          type="button"
          onClick={() => onStart(watchlistPrompt)}
          disabled={watchlist.length === 0}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Pin size={13} />
          复盘观察篮
        </button>
      </div>

      {watchlist.length === 0 ? (
        <div className="flex min-h-[260px] flex-col items-center justify-center rounded-lg border border-dashed border-border/75 bg-background px-4 text-center">
          <div className="rounded-full bg-muted p-3 text-muted-foreground">
            <BellPlus size={22} />
          </div>
          <p className="mt-3 text-sm font-medium">还没有观察标的</p>
          <p className="mt-1 max-w-[260px] text-xs leading-5 text-muted-foreground">漏斗选股、个股诊断和策略建议会提供“观察”按钮。</p>
        </div>
      ) : (
        <div className="max-h-[360px] space-y-2 overflow-auto pr-1">
          {watchlist.map((item) => (
            <WatchItemCard key={item.id} item={item} onRemove={onRemove} onStart={onStart} />
          ))}
        </div>
      )}
    </section>
  )
}

function WatchItemCard({ item, onRemove, onStart }: { item: WatchItem; onRemove: (code: string) => void; onStart: (value: string) => void }) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={() => onStart(buildStockReviewPrompt(item))} className="min-w-0 text-left">
          <div className="flex min-w-0 items-center gap-2">
            <span className="font-mono text-sm font-semibold">{item.code}</span>
            {item.name && <span className="truncate text-sm font-medium">{item.name}</span>}
          </div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.reason}</p>
        </button>
        <button
          type="button"
          onClick={() => onRemove(item.code)}
          aria-label={`移除 ${item.code}`}
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Trash2 size={13} />
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
        <span className="rounded-full bg-muted px-2 py-0.5">{item.source}</span>
        {item.phase && <span className="rounded-full bg-muted px-2 py-0.5">{item.phase}</span>}
        {item.score != null && <span className="rounded-full bg-muted px-2 py-0.5">分数 {item.score.toFixed(2)}</span>}
        {item.changePct != null && <span className={`rounded-full px-2 py-0.5 ${item.changePct >= 0 ? 'bg-up/10 text-up' : 'bg-down/10 text-down'}`}>{formatSignedPct(item.changePct)}</span>}
        <span className="rounded-full bg-muted px-2 py-0.5">{formatWatchDate(item.updatedAt)}</span>
      </div>
      <div className="mt-2 grid gap-1.5 text-[11px] sm:grid-cols-2">
        <div className="rounded-md bg-muted/45 px-2 py-1">
          <div className="text-muted-foreground">触发</div>
          <div className="mt-0.5 line-clamp-2 text-foreground">{item.trigger}</div>
        </div>
        <div className="rounded-md bg-muted/45 px-2 py-1">
          <div className="text-muted-foreground">失效</div>
          <div className="mt-0.5 line-clamp-2 text-foreground">{item.invalidation}</div>
        </div>
      </div>
    </div>
  )
}

function buildWatchlistReviewPrompt(items: WatchItem[]): string {
  if (items.length === 0) return '帮我先运行漏斗选股，生成一个值得观察的股票清单。'
  const lines = items.slice(0, 10).map((item) => `${item.code}${item.name ? ` ${item.name}` : ''}：${item.reason}；触发=${item.trigger}；失效=${item.invalidation}`)
  return `复盘我的读盘室观察篮，按优先级排序并给出今天怎么盯：\n${lines.join('\n')}`
}

function buildStockReviewPrompt(item: WatchItem): string {
  return `重点读一下 ${item.code}${item.name ? ` ${item.name}` : ''}：来源=${item.source}，观察理由=${item.reason}，触发条件=${item.trigger}，失效条件=${item.invalidation}。请结合最新市场水温和个股数据判断现在是继续观察、等待确认、试仓还是回避。`
}

function formatWatchDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚更新'
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function formatSignedPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
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

async function fetchChatConfig(token: string, t: (key: TranslationKey, vars?: Record<string, string>) => string): Promise<ChatConfig> {
  let response: Response
  try {
    response = await fetch(apiUrl('/api/chat/config'), {
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    return { configured: false, model: null, error: t('chat.configUnreachable') }
  }
  if (!response.ok) return { configured: false, model: null, error: t('chat.configHttpError', { status: String(response.status) }) }
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

function toolGroupState(parts: ToolPart[], t: (key: TranslationKey) => string, isActive: boolean): string {
  if (parts.some(isRunningTool)) return isActive ? t('chat.toolRunning') : t('chat.toolInterrupted')
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
