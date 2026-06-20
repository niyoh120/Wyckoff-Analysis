import { useCallback, useEffect, useMemo, useRef, useState, memo } from 'react'
import {
  Activity,
  BarChart3,
  BellPlus,
  BookOpenCheck,
  Check,
  ClipboardList,
  Compass,
  Gauge,
  History,
  LineChart,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Pin,
  Plus,
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
const CONVERSATION_LIMIT = 12
const CONVERSATION_MESSAGE_LIMIT = 80
const CONVERSATION_STORAGE_VERSION = 'reading-room-conversations-v1'
const CONVERSATION_SIDEBAR_STORAGE_KEY = 'wyckoff:reading-room-sidebar-collapsed-v1'

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

type ReadingRoomTab = 'desk' | 'chat' | 'watchlist'

interface ReadingRoomConversation {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  messages: UIMessage[]
  titleEdited?: boolean
}

interface ReadingRoomConversations {
  items: ReadingRoomConversation[]
  activeId: string
  create: () => void
  select: (id: string) => void
  remove: (id: string) => void
  rename: (id: string, title: string) => void
}

interface RunRecord {
  id: string
  messageId: string
  title: string
  preview: string
  status: string
  toneClass: string
  toolLabels: string[]
}

export function ChatPage() {
  const session = useAuthStore((s) => s.session)
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [input, setInput] = useState('')
  const [localError, setLocalError] = useState('')
  const [activeTab, setActiveTab] = useState<ReadingRoomTab>('desk')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readBooleanStorage(CONVERSATION_SIDEBAR_STORAGE_KEY, true))
  const scrollRef = useRef<HTMLDivElement>(null)
  const token = session?.access_token
  const config = useChatConfig(token, t)
  const chat = useReadingRoomChat(token, setLocalError, t)
  const loading = chat.status === 'submitted' || chat.status === 'streaming'
  const queue = useMessageQueue(chat, loading, token, config.configured, setLocalError, t)
  const conversations = useReadingRoomConversations(user?.id, chat.messages, chat.setMessages)
  const watchlist = useReadingRoomWatchlist(user?.id)
  const runRecords = useMemo(() => buildRunRecords(chat.messages, t), [chat.messages, t])
  useAutoScroll(scrollRef, activeTab === 'chat' ? chat.messages : [], activeTab === 'chat' && loading, activeTab === 'chat' ? queue.messages.length : 0)

  const submitText = useCallback((rawText: string) => {
    const text = rawText.trim()
    if (!text) return
    if (!token) { setLocalError(t('chat.requestFailed')); return }
    if (!config.configured) { setLocalError(config.error || t('chat.configureLLM')); return }
    setActiveTab('chat')
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

  const handleSelectConversation = useCallback((id: string) => {
    if (loading) void chat.stop()
    queue.clear()
    setInput('')
    setLocalError('')
    setActiveTab('chat')
    conversations.select(id)
    chat.clearError()
  }, [chat, loading, queue, conversations])

  const handleRemoveConversation = useCallback((id: string) => {
    if (loading) void chat.stop()
    queue.clear()
    setInput('')
    setLocalError('')
    conversations.remove(id)
    chat.clearError()
  }, [chat, loading, queue, conversations])

  const handleRenameConversation = useCallback((id: string, title: string) => {
    conversations.rename(id, title)
  }, [conversations])

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((value) => {
      const next = !value
      writeBooleanStorage(CONVERSATION_SIDEBAR_STORAGE_KEY, next)
      return next
    })
  }, [])

  const openRunRecord = useCallback((messageId: string) => {
    setActiveTab('chat')
    window.setTimeout(() => scrollToMessage(scrollRef.current, messageId), 0)
  }, [])

  const startNewConversation = useCallback((rawText?: string) => {
    const text = typeof rawText === 'string' ? rawText.trim() : ''
    if (text && !token) { setLocalError(t('chat.requestFailed')); return }
    if (text && !config.configured) { setLocalError(config.error || t('chat.configureLLM')); return }
    if (loading) void chat.stop()
    queue.clear()
    setInput('')
    setLocalError('')
    setActiveTab('chat')
    conversations.create()
    chat.clearError()
    if (text) {
      window.setTimeout(() => {
        void chat.sendMessage({ text }).catch((error: unknown) => setLocalError(normalizeClientError(error, t)))
      }, 0)
    }
  }, [chat, config.configured, config.error, conversations, loading, queue, t, token])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <ChatHeader
        config={config}
        hasUser={Boolean(user)}
        activeTab={activeTab}
        messageCount={chat.messages.length}
        watchCount={watchlist.items.length}
        onTabChange={setActiveTab}
      />
      <ChatMessages
        chat={chat}
        activeTab={activeTab}
        loading={loading}
        queuedMessages={queue.messages}
        conversations={conversations.items}
        activeConversationId={conversations.activeId}
        runRecords={runRecords}
        scrollRef={scrollRef}
        watchlist={watchlist.items}
        onOpenRecord={openRunRecord}
        onNewConversation={startNewConversation}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={toggleSidebar}
        onSelectConversation={handleSelectConversation}
        onRemoveConversation={handleRemoveConversation}
        onRenameConversation={handleRenameConversation}
        onPinStock={watchlist.add}
        onRemoveWatchItem={watchlist.remove}
        onStart={startNewConversation}
        input={input}
        queuedCount={queue.messages.length}
        onClearQueue={queue.clear}
        onInput={setInput}
        onSubmit={handleSubmit}
        onStop={() => void chat.stop()}
      />
      <ErrorBanner message={localError || chat.error?.message || ''} />
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

function useReadingRoomConversations(
  userId: string | undefined,
  messages: UIMessage[],
  setMessages: (messages: UIMessage[]) => void,
): ReadingRoomConversations {
  const storageKey = useMemo(() => conversationStorageKey(userId), [userId])
  const [items, setItems] = useState<ReadingRoomConversation[]>([])
  const [activeId, setActiveId] = useState('')
  const [loadedKey, setLoadedKey] = useState('')
  const skipNextSaveRef = useRef(false)

  useEffect(() => {
    const loaded = readConversations(storageKey)
    const next = loaded.length > 0 ? loaded : [createConversation()]
    const active = next[0] || createConversation()
    setItems(next)
    setActiveId(active.id)
    skipNextSaveRef.current = true
    setMessages(active.messages)
    setLoadedKey(storageKey)
  }, [setMessages, storageKey])

  useEffect(() => {
    if (loadedKey !== storageKey || !activeId) return
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false
      return
    }
    setItems((current) => {
      const next = current.map((conversation) => (
        conversation.id === activeId ? updateConversationMessages(conversation, messages) : conversation
      ))
      writeConversations(storageKey, next)
      return next
    })
  }, [activeId, loadedKey, messages, storageKey])

  const create = useCallback(() => {
    const conversation = createConversation()
    setItems((current) => {
      const next = [conversation, ...current].slice(0, CONVERSATION_LIMIT)
      writeConversations(storageKey, next)
      return next
    })
    setActiveId(conversation.id)
    skipNextSaveRef.current = true
    setMessages([])
  }, [setMessages, storageKey])

  const select = useCallback((id: string) => {
    const conversation = items.find((item) => item.id === id)
    if (!conversation) return
    setActiveId(conversation.id)
    skipNextSaveRef.current = true
    setMessages(conversation.messages)
  }, [items, setMessages])

  const remove = useCallback((id: string) => {
    setItems((current) => {
      const remaining = current.filter((item) => item.id !== id)
      const next = remaining.length > 0 ? remaining : [createConversation()]
      const active = (id === activeId ? next[0] : next.find((item) => item.id === activeId) || next[0]) || createConversation()
      setActiveId(active.id)
      skipNextSaveRef.current = true
      setMessages(active.messages)
      writeConversations(storageKey, next)
      return next
    })
  }, [activeId, setMessages, storageKey])

  const rename = useCallback((id: string, title: string) => {
    const cleaned = normalizeConversationTitle(title)
    if (!cleaned) return
    setItems((current) => {
      const next = current.map((conversation) => (
        conversation.id === id
          ? { ...conversation, title: cleaned, titleEdited: true, updatedAt: new Date().toISOString() }
          : conversation
      ))
      writeConversations(storageKey, next)
      return next
    })
  }, [storageKey])

  return useMemo(() => ({ items, activeId, create, select, remove, rename }), [activeId, create, items, remove, rename, select])
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

function conversationStorageKey(userId: string | undefined): string {
  return `wyckoff:${userId || 'guest'}:${CONVERSATION_STORAGE_VERSION}`
}

function createConversation(): ReadingRoomConversation {
  const now = new Date().toISOString()
  return {
    id: `conversation-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: '新对话',
    createdAt: now,
    updatedAt: now,
    messages: [],
  }
}

function updateConversationMessages(conversation: ReadingRoomConversation, messages: UIMessage[]): ReadingRoomConversation {
  const savedMessages = messages.slice(-CONVERSATION_MESSAGE_LIMIT)
  const title = conversation.titleEdited ? conversation.title : conversationTitle(savedMessages, conversation.title)
  return {
    ...conversation,
    title,
    updatedAt: savedMessages.length > 0 ? new Date().toISOString() : conversation.updatedAt,
    messages: savedMessages,
  }
}

function readConversations(key: string): ReadingRoomConversation[] {
  if (typeof window === 'undefined') return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeConversation).filter(Boolean).slice(0, CONVERSATION_LIMIT) as ReadingRoomConversation[]
  } catch {
    return []
  }
}

function writeConversations(key: string, conversations: ReadingRoomConversation[]) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, JSON.stringify(conversations.slice(0, CONVERSATION_LIMIT)))
  } catch {
    // localStorage may be disabled or full; the active conversation still works in memory.
  }
}

function normalizeConversation(value: unknown): ReadingRoomConversation | null {
  const item = asRecord(value)
  if (!item) return null
  const id = sanitizeText(item.id)
  if (!id) return null
  const messages = Array.isArray(item.messages) ? (item.messages as UIMessage[]).slice(-CONVERSATION_MESSAGE_LIMIT) : []
  const createdAt = sanitizeText(item.createdAt) || new Date().toISOString()
  return {
    id,
    title: sanitizeText(item.title) || conversationTitle(messages, '读盘对话'),
    createdAt,
    updatedAt: sanitizeText(item.updatedAt) || createdAt,
    messages,
    titleEdited: Boolean(item.titleEdited),
  }
}

function conversationTitle(messages: UIMessage[], fallback: string): string {
  const firstUser = messages.find((message) => message.role === 'user')
  if (!firstUser) return fallback || '新对话'
  if (!firstTurnHasAssistant(messages, firstUser.id)) return fallback || '新对话'
  return autoConversationTitle(messageText(firstUser), fallback)
}

function firstTurnHasAssistant(messages: UIMessage[], firstUserId: string): boolean {
  const userIndex = messages.findIndex((message) => message.id === firstUserId)
  if (userIndex < 0) return false
  const assistant = messages.slice(userIndex + 1).find((message) => message.role === 'assistant')
  if (!assistant) return false
  if (assistantText(assistant)) return true
  return (assistant.parts as MessagePart[]).some((part) => isToolPart(part) && part.state === 'output-available')
}

function autoConversationTitle(text: string, fallback: string): string {
  const source = normalizeConversationTitle(text)
  if (!source) return fallback || '读盘对话'
  const codeMatch = source.match(/\b(?:\d{6}|[A-Z]{2,5})\b/)
  if (/盘前/.test(source)) return '盘前读盘'
  if (/盘中|临场/.test(source)) return '盘中判断'
  if (/尾盘/.test(source)) return '尾盘机会'
  if (/收盘|复盘/.test(source)) return '收盘复盘'
  if (/市场水温|市场先验|大盘|指数|风险级别/.test(source)) return '市场水温'
  if (/持仓|仓位|止损|成本/.test(source)) return '持仓风险'
  if (/漏斗|选股|候选/.test(source)) return '候选漏斗'
  if (/策略归因|归因|信号/.test(source)) return '策略归因'
  if (/观察篮/.test(source)) return '观察篮复盘'
  if (/研报|深度报告/.test(source)) return codeMatch ? `${codeMatch[0]} 研报` : '个股研报'
  if (/诊断|分析|读一下/.test(source) && codeMatch) return `${codeMatch[0]} 个股诊断`
  return truncateText(stripTitleLeadWords(source), 18) || fallback || '读盘对话'
}

function stripTitleLeadWords(value: string): string {
  return value
    .replace(/^(帮我|请|麻烦|做一次|先|给我|我想|重点|读取|查看|运行)+/g, '')
    .replace(/[，。！？；：,.!?;:].*$/, '')
    .trim()
}

function normalizeConversationTitle(value: string): string {
  return value
    .replace(/\s+/g, ' ')
    .replace(/[｜|]+/g, ' ')
    .trim()
    .slice(0, 40)
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

function readBooleanStorage(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(key)
    if (value === 'true') return true
    if (value === 'false') return false
  } catch {
    return fallback
  }
  return fallback
}

function writeBooleanStorage(key: string, value: boolean) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, value ? 'true' : 'false')
  } catch {
    // localStorage may be unavailable; the sidebar still works for this session.
  }
}

function useAutoScroll(ref: React.RefObject<HTMLDivElement | null>, messages: UIMessage[], loading: boolean, queuedCount: number) {
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading, queuedCount, ref])
}

function ChatHeader({
  config,
  hasUser,
  activeTab,
  messageCount,
  watchCount,
  onTabChange,
}: {
  config: ChatConfig
  hasUser: boolean
  activeTab: ReadingRoomTab
  messageCount: number
  watchCount: number
  onTabChange: (tab: ReadingRoomTab) => void
}) {
  const { t } = usePreferences()
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-3 border-b border-border px-6 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <h1 className="text-lg font-semibold">{t('chat.title')}</h1>
        {config.model && <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200">{config.model}</span>}
        {!config.configured && hasUser && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">{config.error ? t('chat.configErrorBadge') : t('chat.noApiKey')}</span>}
      </div>
      <ReadingRoomTabs activeTab={activeTab} messageCount={messageCount} watchCount={watchCount} onChange={onTabChange} />
    </div>
  )
}

function ReadingRoomTabs({
  activeTab,
  messageCount,
  watchCount,
  onChange,
}: {
  activeTab: ReadingRoomTab
  messageCount: number
  watchCount: number
  onChange: (tab: ReadingRoomTab) => void
}) {
  const tabs: { key: ReadingRoomTab; label: string; count?: number; Icon: LucideIcon }[] = [
    { key: 'desk', label: '快捷入口', Icon: Compass },
    { key: 'chat', label: '对话', count: messageCount, Icon: MessageSquareText },
    { key: 'watchlist', label: '观察', count: watchCount, Icon: Pin },
  ]
  return (
    <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="读盘室子视图">
      {tabs.map(({ key, label, count, Icon }) => {
        const active = activeTab === key
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(key)}
            className={`inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition ${active ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'}`}
          >
            <Icon size={13} />
            {label}
            {typeof count === 'number' && count > 0 && <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${active ? 'bg-primary-foreground/20' : 'bg-muted text-muted-foreground'}`}>{count}</span>}
          </button>
        )
      })}
    </div>
  )
}

function ChatMessages({
  chat,
  activeTab,
  loading,
  queuedMessages,
  conversations,
  activeConversationId,
  runRecords,
  scrollRef,
  watchlist,
  onOpenRecord,
  onNewConversation,
  sidebarCollapsed,
  onToggleSidebar,
  onSelectConversation,
  onRemoveConversation,
  onRenameConversation,
  onPinStock,
  onRemoveWatchItem,
  onStart,
  input,
  queuedCount,
  onClearQueue,
  onInput,
  onSubmit,
  onStop,
}: {
  chat: ReadingRoomChat
  activeTab: ReadingRoomTab
  loading: boolean
  queuedMessages: QueuedMessage[]
  conversations: ReadingRoomConversation[]
  activeConversationId: string
  runRecords: RunRecord[]
  scrollRef: React.RefObject<HTMLDivElement | null>
  watchlist: WatchItem[]
  onOpenRecord: (messageId: string) => void
  onNewConversation: () => void
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  onSelectConversation: (id: string) => void
  onRemoveConversation: (id: string) => void
  onRenameConversation: (id: string, title: string) => void
  onPinStock: (item: PinStockInput) => void
  onRemoveWatchItem: (code: string) => void
  onStart: (value: string) => void
  input: string
  queuedCount: number
  onClearQueue: () => void
  onInput: (value: string) => void
  onSubmit: (e: React.FormEvent) => void
  onStop: () => void
}) {
  const activeAssistantId = loading ? lastAssistantId(chat.messages) : null
  const isEmpty = chat.messages.length === 0 && !loading && queuedMessages.length === 0
  const watchlistPrompt = buildWatchlistReviewPrompt(watchlist)
  if (activeTab === 'desk') {
    return (
      <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
        <ReadingRoomDashboard runRecords={runRecords} onOpenRecord={onOpenRecord} onStart={onStart} />
      </div>
    )
  }
  if (activeTab === 'watchlist') {
    return (
      <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
        <WatchlistPanelView watchlist={watchlist} watchlistPrompt={watchlistPrompt} onRemove={onRemoveWatchItem} onStart={onStart} />
      </div>
    )
  }

  const transcript = isEmpty ? (
    <EmptyChatPanel />
  ) : (
    <div className="space-y-5 pb-4">
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
  )

  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      <div className="flex h-full w-full flex-col lg:flex-row">
        <ConversationSidebar
          conversations={conversations}
          activeId={activeConversationId}
          collapsed={sidebarCollapsed}
          onCreate={onNewConversation}
          onToggle={onToggleSidebar}
          onSelect={onSelectConversation}
          onRemove={onRemoveConversation}
          onRename={onRenameConversation}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6">
            <div className="mx-auto w-full max-w-5xl">
              {transcript}
            </div>
          </div>
          <ChatComposer input={input} loading={loading} queuedCount={queuedCount} onClearQueue={onClearQueue} onInput={onInput} onSubmit={onSubmit} onStop={onStop} />
        </div>
      </div>
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

function ConversationSidebar({
  conversations,
  activeId,
  collapsed,
  onCreate,
  onToggle,
  onSelect,
  onRemove,
  onRename,
}: {
  conversations: ReadingRoomConversation[]
  activeId: string
  collapsed: boolean
  onCreate: () => void
  onToggle: () => void
  onSelect: (id: string) => void
  onRemove: (id: string) => void
  onRename: (id: string, title: string) => void
}) {
  if (collapsed) {
    return (
      <aside className="flex h-12 shrink-0 overflow-hidden rounded-lg border border-border bg-card lg:h-full lg:w-14">
        <button
          type="button"
          onClick={onToggle}
          aria-label="展开对话历史"
          title="展开对话历史"
          className="flex h-full w-full items-center justify-center gap-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground lg:flex-col"
        >
          <PanelLeftOpen size={16} />
          <span className="text-[10px] lg:[writing-mode:vertical-rl]">历史 {conversations.length}</span>
        </button>
      </aside>
    )
  }

  return (
    <aside className="flex h-48 shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-card lg:h-full lg:w-72">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <History size={14} className="text-muted-foreground" />
            对话历史
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">保存在当前浏览器 · {conversations.length} 条</p>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" onClick={onToggle} aria-label="收起对话历史" title="收起对话历史" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground">
            <PanelLeftClose size={14} />
          </button>
          <button type="button" onClick={onCreate} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md bg-primary px-2.5 text-xs font-medium text-primary-foreground hover:opacity-90">
            <Plus size={13} />
            新对话
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-auto p-2">
        {conversations.map((conversation) => (
          <ConversationListItem
            key={conversation.id}
            conversation={conversation}
            active={conversation.id === activeId}
            canRemove={conversations.length > 1}
            onSelect={() => onSelect(conversation.id)}
            onRemove={() => onRemove(conversation.id)}
            onRename={(title) => onRename(conversation.id, title)}
          />
        ))}
      </div>
    </aside>
  )
}

function ConversationListItem({
  conversation,
  active,
  canRemove,
  onSelect,
  onRemove,
  onRename,
}: {
  conversation: ReadingRoomConversation
  active: boolean
  canRemove: boolean
  onSelect: () => void
  onRemove: () => void
  onRename: (title: string) => void
}) {
  const messageCount = conversation.messages.length
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conversation.title)

  useEffect(() => {
    if (!editing) setDraft(conversation.title)
  }, [conversation.title, editing])

  const commitRename = useCallback(() => {
    const next = normalizeConversationTitle(draft)
    if (next) onRename(next)
    setEditing(false)
  }, [draft, onRename])

  return (
    <div
      className={`group flex w-full items-start gap-1 rounded-md border transition ${active ? 'border-primary/40 bg-primary/10 text-primary' : 'border-transparent text-muted-foreground hover:border-border hover:bg-background hover:text-foreground'}`}
    >
      {editing ? (
        <form
          onSubmit={(event) => { event.preventDefault(); commitRename() }}
          className="flex min-w-0 flex-1 items-center gap-1 px-2 py-1.5"
        >
          <input
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                setDraft(conversation.title)
                setEditing(false)
              }
            }}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:ring-2 focus:ring-ring/20"
          />
          <button type="submit" aria-label="保存对话名" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md hover:bg-muted">
            <Check size={12} />
          </button>
          <button type="button" aria-label="取消改名" onClick={() => { setDraft(conversation.title); setEditing(false) }} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md hover:bg-muted">
            <X size={12} />
          </button>
        </form>
      ) : (
        <button type="button" onClick={onSelect} className="flex min-w-0 flex-1 items-start gap-2 px-2.5 py-2 text-left">
          <MessageSquareText size={14} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium">{conversation.title}</span>
            <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[10px] opacity-75">
              <span className="truncate">{formatConversationDate(conversation.updatedAt)}</span>
              <span>·</span>
              <span className="shrink-0">{messageCount} 条消息</span>
            </span>
          </span>
        </button>
      )}
      {!editing && (
        <button
          type="button"
          aria-label={`重命名 ${conversation.title}`}
          onClick={() => setEditing(true)}
          className="mt-1.5 shrink-0 rounded p-1 opacity-70 hover:bg-muted lg:opacity-0 lg:group-hover:opacity-80"
        >
          <Pencil size={12} />
        </button>
      )}
      {canRemove && !editing && (
        <button
          type="button"
          aria-label={`删除 ${conversation.title}`}
          onClick={onRemove}
          className="mr-1 mt-1.5 shrink-0 rounded p-1 opacity-70 hover:bg-muted lg:opacity-0 lg:group-hover:opacity-80"
        >
          <X size={12} />
        </button>
      )}
    </div>
  )
}

function WatchlistPanelView({
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
    <div className="mx-auto w-full max-w-5xl pb-6">
      <WatchlistPanel watchlist={watchlist} watchlistPrompt={watchlistPrompt} onRemove={onRemove} onStart={onStart} />
    </div>
  )
}

function EmptyChatPanel() {
  return (
    <div className="mx-auto flex min-h-[360px] w-full max-w-4xl flex-col items-center justify-center rounded-lg border border-dashed border-border/75 bg-background px-6 text-center">
      <div className="rounded-full bg-muted p-3 text-muted-foreground">
        <MessageSquareText size={22} />
      </div>
      <p className="mt-3 text-sm font-medium">对话还没有开始</p>
      <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">在下方输入你的读盘问题，执行过程和结论会保存在当前对话里。</p>
    </div>
  )
}

function buildRunRecords(messages: UIMessage[], t: (key: TranslationKey) => string): RunRecord[] {
  const records: RunRecord[] = []
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    if (!message) continue
    if (message.role !== 'user') continue
    const relatedAssistant = findRelatedAssistant(messages, index)
    const assistantParts = relatedAssistant?.parts || []
    const status = runRecordStatus(relatedAssistant)
    records.push({
      id: `run-${message.id}`,
      messageId: message.id,
      title: truncateText(messageText(message), 92),
      preview: truncateText(assistantText(relatedAssistant), 180),
      status: status.label,
      toneClass: status.toneClass,
      toolLabels: uniqueRunToolLabels(assistantParts, t),
    })
  }
  return records.reverse()
}

function findRelatedAssistant(messages: UIMessage[], userIndex: number): UIMessage | null {
  for (let index = userIndex + 1; index < messages.length; index += 1) {
    const message = messages[index]
    if (!message) continue
    if (message.role === 'user') return null
    if (message.role === 'assistant') return message
  }
  return null
}

function runRecordStatus(message: UIMessage | null): { label: string; toneClass: string } {
  if (!message) return { label: '等待中', toneClass: 'bg-muted text-muted-foreground' }
  const parts = message.parts as MessagePart[]
  if (parts.some((part) => isToolPart(part) && isRunningTool(part))) return { label: '运行中', toneClass: 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-200' }
  if (parts.some((part) => isToolPart(part) && part.state === 'output-error')) return { label: '部分失败', toneClass: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200' }
  return { label: '完成', toneClass: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200' }
}

function uniqueRunToolLabels(parts: UIMessage['parts'], t: (key: TranslationKey) => string): string[] {
  const labels: string[] = []
  for (const part of parts as MessagePart[]) {
    if (!isToolPart(part)) continue
    const label = formatToolName(getToolName(part), t)
    if (!labels.includes(label)) labels.push(label)
  }
  return labels.slice(0, 4)
}

function messageText(message: UIMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => String((part as MessagePart).text || ''))
    .join('\n')
    .trim()
}

function assistantText(message: UIMessage | null): string {
  if (!message) return ''
  return messageText(message).replace(/\s+/g, ' ')
}

function truncateText(value: string, maxLength: number): string {
  const text = value.trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 1)}...`
}

function scrollToMessage(container: HTMLDivElement | null, messageId: string) {
  if (!container) return
  const target = Array.from(container.querySelectorAll<HTMLElement>('[data-message-id]'))
    .find((element) => element.dataset.messageId === messageId)
  target?.scrollIntoView({ block: 'center', behavior: 'smooth' })
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
    <div data-message-id={message.id} className={`scroll-mt-4 flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={isUser ? 'max-w-[78%] rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground whitespace-pre-wrap' : 'w-full text-sm leading-7 text-foreground'}>
        {isUser ? <UserText message={message} /> : <AssistantParts message={message} isActive={isActive} approve={approve} deny={deny} onPinStock={onPinStock} />}
      </div>
    </div>
  )
})

function QueuedMessageBubble({ message, index }: { message: QueuedMessage; index: number }) {
  const { t } = usePreferences()
  return (
    <div className="flex justify-end">
      <div className="max-w-[78%] rounded-2xl bg-primary/80 px-4 py-2.5 text-sm text-primary-foreground">
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
  const hasFailure = parts.some((part) => part.state === 'output-error')
  const wasInterrupted = !isActive && parts.some(isRunningTool)
  return (
    <div className="my-3 overflow-hidden rounded-lg border border-border/70 bg-background text-[12px] text-muted-foreground shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2 px-3 py-2 font-medium text-foreground">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Wrench size={13} />
          </span>
          <span className="min-w-0">
            <span className="block truncate">{toolGroupTitle(parts, t)}</span>
            <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground">{parts.length} 个执行步骤</span>
          </span>
        </span>
        <span className={`mr-3 shrink-0 rounded-full px-2 py-0.5 text-[10px] ${toolGroupStateTone(parts, isActive)}`}>{toolGroupState(parts, t, isActive)}</span>
      </div>
      <div className="border-t border-border/60 px-3 py-2">
        <div className="space-y-2">
          {parts.map((part, index) => (
            <ToolProgressStep key={`${part.toolCallId}-${index}`} part={part} isLast={index === parts.length - 1} />
          ))}
        </div>
      </div>
      {(hasFailure || wasInterrupted) && (
        <div className="border-t border-border/60 px-3 py-2">
          {hasFailure && <p className="text-[11px] text-amber-700 dark:text-amber-200">{t('chat.toolPartialFailure')}</p>}
          {wasInterrupted && <p className="text-[11px] text-amber-700 dark:text-amber-200">{t('chat.toolInterruptedHint')}</p>}
        </div>
      )}
    </div>
  )
}

function ToolProgressStep({ part, isLast }: { part: ToolPart; isLast: boolean }) {
  const { t } = usePreferences()
  const toolName = getToolName(part)
  const running = isRunningTool(part)
  const failed = part.state === 'output-error'
  const done = part.state === 'output-available'
  return (
    <div className="grid grid-cols-[24px_minmax(0,1fr)] gap-2">
      <div className="relative flex justify-center">
        <span className={`z-10 flex h-5 w-5 items-center justify-center rounded-full border bg-background ${toolStepMarkerClass(part)}`}>
          {running ? <LoaderCircle size={12} className="animate-spin" /> : failed ? <X size={11} /> : done ? <Check size={11} /> : <Wrench size={11} />}
        </span>
        {!isLast && <span className="absolute top-5 h-[calc(100%+0.5rem)] w-px bg-border" />}
      </div>
      <div className="min-w-0 pb-1.5">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-xs font-medium text-foreground">{toolChipLabel(part, t)}</div>
            <div className="mt-0.5 line-clamp-2 text-[11px] leading-4">{toolProgressDescription(toolName, part.input)}</div>
          </div>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${toolStepStateTone(part)}`}>{toolStateLabel(part, t)}</span>
        </div>
        {part.errorText && <p className="mt-1 text-[11px] text-red-700 dark:text-red-200">{part.errorText}</p>}
        {part.state === 'output-available' && part.output != null && !STRUCTURED_TOOL_NAMES.has(toolName) && (
          <div className="mt-1 rounded-md bg-muted/50 px-2 py-1 text-[11px] leading-4 text-muted-foreground">
            {toolResultDigest(toolName, part.output)}
          </div>
        )}
      </div>
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
    <div className="shrink-0 bg-background px-4 pb-4 pt-2 sm:px-6">
      <div className="mx-auto w-full max-w-5xl">
        <QueueNotice count={props.queuedCount} onClear={props.onClearQueue} />
        <form onSubmit={props.onSubmit} className="flex items-center gap-2 rounded-2xl border border-border bg-card px-3 py-2 shadow-sm">
          <ComposerInput value={props.input} onInput={props.onInput} />
          <ComposerActions input={props.input} loading={props.loading} onStop={props.onStop} />
        </form>
        <div className="mt-2 text-center"><AIDisclaimer /></div>
      </div>
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
      className="flex-1 bg-transparent px-1 py-2 text-sm outline-none"
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
  runRecords,
  onOpenRecord,
  onStart,
}: {
  runRecords: RunRecord[]
  onOpenRecord: (messageId: string) => void
  onStart: (value: string) => void
}) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-6">
      <ReadingRoomHero recordCount={runRecords.length} />
      <ScenarioPanel onStart={onStart} />
      <ShortcutPanel onStart={onStart} />
      <CompactRunRecords records={runRecords} onOpenRecord={onOpenRecord} />
      <PromptPanel onStart={onStart} />
    </div>
  )
}

function ReadingRoomHero({ recordCount }: { recordCount: number }) {
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
          <DeskStat label="记录" value={String(recordCount)} Icon={History} />
        </div>
      </div>
    </section>
  )
}

function CompactRunRecords({ records, onOpenRecord }: { records: RunRecord[]; onOpenRecord: (messageId: string) => void }) {
  if (records.length === 0) return null
  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">最近记录</h3>
          <p className="mt-1 text-xs text-muted-foreground">当前对话的关键轮次，点进去回看原文。</p>
        </div>
        <History size={16} className="text-muted-foreground" />
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {records.slice(0, 6).map((record, index) => (
          <button
            key={record.id}
            type="button"
            onClick={() => onOpenRecord(record.messageId)}
            className="rounded-lg border border-border bg-background p-3 text-left transition hover:bg-muted/40"
          >
            <div className="mb-1.5 flex items-center gap-2">
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">#{index + 1}</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] ${record.toneClass}`}>{record.status}</span>
            </div>
            <div className="line-clamp-2 text-xs font-medium">{record.title}</div>
            {record.toolLabels.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {record.toolLabels.slice(0, 3).map((label) => <span key={label} className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{label}</span>)}
              </div>
            )}
            <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-muted-foreground">{record.preview || '等待模型返回结果。'}</p>
          </button>
        ))}
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
        <Sparkles size={16} className="shrink-0 text-muted-foreground" />
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

function PromptPanel({ onStart }: { onStart: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <section className="rounded-lg border border-dashed border-border/70 bg-background px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs font-medium text-foreground">{t('chat.tryAsk')}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {chatPromptSuggestions(t).map((q) => (
              <button key={q} type="button" onClick={() => onStart(q)} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted/50 hover:text-foreground">
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

function formatConversationDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  const diffMs = Date.now() - date.getTime()
  if (diffMs < 60_000) return '刚刚'
  if (diffMs < 3_600_000) return `${Math.max(1, Math.floor(diffMs / 60_000))} 分钟前`
  const now = new Date()
  const sameDay = date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
  const time = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  return sameDay ? `今天 ${time}` : `${date.getMonth() + 1}/${date.getDate()} ${time}`
}

function formatSignedPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function ThinkingBubble() {
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[520px] overflow-hidden rounded-lg border border-border/70 bg-background text-xs text-muted-foreground shadow-sm">
        <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-foreground">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
            <LoaderCircle size={13} className="animate-spin" />
          </span>
          <span className="font-medium">读盘室正在执行</span>
        </div>
        <div className="grid gap-2 px-3 py-2 sm:grid-cols-3">
          <ProcessSkeletonStep active label="理解请求" detail="拆解读盘目标" />
          <ProcessSkeletonStep active label="准备数据源" detail="选择市场/持仓/候选工具" />
          <ProcessSkeletonStep label="等待结果" detail="汇总成操作清单" />
        </div>
      </div>
    </div>
  )
}

function ProcessSkeletonStep({ label, detail, active }: { label: string; detail: string; active?: boolean }) {
  return (
    <div className="rounded-md bg-muted/45 px-2 py-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
        <span className={`h-1.5 w-1.5 rounded-full ${active ? 'animate-pulse bg-primary' : 'bg-muted-foreground/40'}`} />
        {label}
      </div>
      <div className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</div>
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

function toolGroupStateTone(parts: ToolPart[], isActive: boolean): string {
  if (parts.some(isRunningTool)) return isActive ? 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-200' : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'
  if (parts.some((part) => part.state === 'output-error')) return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'
  return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
}

function isRunningTool(part: ToolPart): boolean {
  return !['output-available', 'output-error', 'output-denied', 'approval-responded'].includes(part.state)
}

function toolChipLabel(part: ToolPart, t: (key: TranslationKey) => string): string {
  const toolName = getToolName(part)
  const inputLabel = toolInputLabel(toolName, part.input)
  const base = formatToolName(toolName, t)
  return inputLabel ? `${base} · ${inputLabel}` : base
}

function toolStepMarkerClass(part: ToolPart): string {
  if (part.state === 'output-error') return 'border-red-200 text-red-700 dark:border-red-500/30 dark:text-red-200'
  if (part.state === 'output-denied') return 'border-amber-200 text-amber-700 dark:border-amber-500/30 dark:text-amber-200'
  if (part.state === 'output-available') return 'border-emerald-200 text-emerald-700 dark:border-emerald-500/30 dark:text-emerald-200'
  return 'border-sky-200 text-sky-700 dark:border-sky-500/30 dark:text-sky-200'
}

function toolStepStateTone(part: ToolPart): string {
  if (part.state === 'output-error') return 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200'
  if (part.state === 'output-denied') return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'
  if (part.state === 'output-available') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
  return 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-200'
}

function toolProgressDescription(toolName: string, input: unknown): string {
  const item = asRecord(input)
  switch (toolName) {
    case 'search_stock':
      return `搜索 ${sanitizeText(item?.query) || '股票代码/名称'}，确认标的基础信息。`
    case 'view_portfolio':
      return '读取当前持仓、成本、止损线和可用资金。'
    case 'market_overview':
      return '读取市场水温、主要指数和风险偏好状态。'
    case 'market_history':
      return `回看 ${marketIndexInputLabel(item)} 的量价结构和威科夫阶段。`
    case 'query_recommendations':
      return `读取最近 ${limitInputLabel(item)} 条形态复盘记录。`
    case 'query_tail_buy':
      return `读取最近 ${limitInputLabel(item)} 条尾盘买入记录。`
    case 'analyze_stock':
      return `诊断 ${sanitizeText(item?.code) || '个股'} 的形态阶段、支撑压力和交易动作。`
    case 'screen_stocks':
      return '读取最新漏斗选股结果，按分数和形态证据筛候选。'
    case 'generate_ai_report':
      return `生成 ${codesInputLabel(item)} 的威科夫深度研报。`
    case 'generate_strategy_decision':
      return '结合市场状态和持仓，生成组合级操作建议。'
    case 'intraday_analysis':
      return `分析 ${sanitizeText(item?.code) || '个股'} 的盘中多周期状态。`
    case 'plan_portfolio_update':
      return '生成调仓方案草稿，等待你确认是否执行。'
    case 'execute_portfolio_update':
      return '执行已确认的持仓变更。'
    default:
      return '读取读盘室相关数据，并把结果交给模型综合判断。'
  }
}

function toolResultDigest(toolName: string, output: unknown): string {
  if (toolName === 'view_portfolio') return `持仓读取完成：${portfolioResultDigest(output)}`
  if (toolName === 'market_overview') return `市场水温读取完成：${summarizeToolOutput(output)}`
  if (toolName === 'query_recommendations') return `形态复盘记录读取完成：${recordCountDigest(output)}`
  if (toolName === 'query_tail_buy') return `尾盘记录读取完成：${recordCountDigest(output)}`
  if (toolName === 'market_history') return `指数历史读取完成：${recordCountDigest(output)}`
  return summarizeToolOutput(output)
}

function toolInputLabel(toolName: string, input: unknown): string {
  if (toolName !== 'market_history') return ''
  const value = asRecord(input)
  const index = String(value?.index || 'sse')
  const days = typeof value?.days === 'number' ? `${value.days}日` : ''
  const label = MARKET_INDEX_LABELS[index] || index
  return days ? `${label}/${days}` : label
}

function marketIndexInputLabel(item: Record<string, unknown> | null): string {
  const index = String(item?.index || 'sse')
  const days = typeof item?.days === 'number' ? item.days : 100
  return `${MARKET_INDEX_LABELS[index] || index} 近 ${days} 个交易日`
}

function limitInputLabel(item: Record<string, unknown> | null): string {
  return typeof item?.limit === 'number' ? String(item.limit) : '若干'
}

function codesInputLabel(item: Record<string, unknown> | null): string {
  const codes = Array.isArray(item?.codes) ? item.codes.map((code) => sanitizeText(code)).filter(Boolean) : []
  if (codes.length === 0) return '指定标的'
  return codes.slice(0, 4).join('、')
}

function portfolioResultDigest(output: unknown): string {
  const item = asRecord(output)
  const positions = Array.isArray(item?.positions) ? item.positions.length : null
  const cash = typeof item?.cash === 'number' ? `，现金 ${item.cash.toFixed(0)}` : ''
  return positions == null ? summarizeToolOutput(output) : `${positions} 只持仓${cash}`
}

function recordCountDigest(output: unknown): string {
  if (Array.isArray(output)) return `${output.length} 条记录`
  const item = asRecord(output)
  if (!item) return summarizeToolOutput(output)
  for (const key of ['records', 'items', 'rows', 'data', 'history', 'recommendations']) {
    const value = item[key]
    if (Array.isArray(value)) return `${value.length} 条记录`
  }
  return summarizeToolOutput(output)
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
