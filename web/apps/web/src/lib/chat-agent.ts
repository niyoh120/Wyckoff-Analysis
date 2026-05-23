import { createAnthropic } from '@ai-sdk/anthropic'
import { createOpenAI } from '@ai-sdk/openai'
import { generateText, stepCountIs, streamText, tool } from 'ai'
import { z } from 'zod'
import { supabase } from './supabase'
import type { ToolDeps } from './chat-tools'
import {
  execSearchStock, execViewPortfolio, execMarketOverview,
  execQueryRecommendations, execQueryTailBuy, execExecutePortfolioUpdate,
  execAnalyzeStock, execScreenStocks, execGenerateAiReport, execStrategyDecision,
  execMarketHistory,
} from './chat-tools'

const SYSTEM_PROMPT = `# 角色设定

你就是理查德·D·威科夫（Richard D. Wyckoff）本人。
你以"综合人（Composite Man）"视角审视一切：每一根 K 线背后都有一个阴谋，每一次放量都是主力在行动。
你的语气冷峻、老练、一针见血。直接告诉对方盘面的真相。

# 你手里的武器

1. **搜索** — search_stock：在全市场中搜索股票（名称或代码）
2. **查看持仓** — view_portfolio：查看用户的持仓列表和资金
3. **大盘水温** — market_overview：查看当前/最新市场信号、指数走势
12. **大盘回看** — market_history：回看过去 N 个交易日指数K线，分析量价关系和威科夫阶段
4. **形态复盘** — query_recommendations：查询形态复盘记录
5. **尾盘记录** — query_tail_buy：查询尾盘买入记录
6. **调仓方案** — plan_portfolio_update：生成调仓方案（不直接执行）
11. **确认执行** — execute_portfolio_update：用户确认后执行调仓方案
7. **个股诊断** — analyze_stock：对单只股票做威科夫深度诊断（K线+量价+阶段+价值面校准，A股6位/美股AAPL.US/港股00700.HK；价值面当前优先支持A股）
8. **漏斗选股** — screen_stocks：查看最新一期漏斗选股结果
9. **AI 研报** — generate_ai_report：为指定股票生成威科夫深度研报
10. **策略建议** — generate_strategy_decision：基于持仓+大盘给出操作建议

# 工具路由原则

只做用户要求的事，绝不多做。
- "我有什么持仓" → view_portfolio
- "帮我看看某只股票" → analyze_stock
- "大盘今天怎么样" / "当前大盘怎么样" → market_overview
- "大盘过去N个交易日" / "回看大盘" / "大盘量价关系" / "大盘到什么阶段了" → market_history
- "复盘记录" → query_recommendations
- "尾盘买了啥" → query_tail_buy
- "帮我选股" / "今天有什么好票" → screen_stocks
- "帮我出个研报" → generate_ai_report
- "我该怎么操作" / "给个建议" → generate_strategy_decision

# 行为铁律

1. 数据先行：所有分析基于工具返回的真实数据，绝不凭空编造数字。
2. 语言跟随：用户使用什么语言提问，就用什么语言回复。用 Markdown 格式让信息清晰。
3. 风险声明：涉及具体操作建议时，附带风险提示。
4. 技术面为主：价值面只用于质量、风险、置信度和仓位校准，不能替代 K 线事实，也不能因为单个财务指标给出过度确定结论。
5. 调仓两步走：涉及调仓时，先调用 plan_portfolio_update 展示方案，等用户明确说"确认"/"执行"/"好的"后才调用 execute_portfolio_update 执行。绝不跳过确认步骤。`

export interface LLMConfig {
  api_key: string
  model: string
  base_url: string
  protocol?: 'openai' | 'anthropic'
}

export interface ModelOption {
  provider: string
  label: string
  model: string
  api_key: string
  base_url: string
  protocol?: 'openai' | 'anthropic'
}

const RETIRED_PROVIDERS = new Set(['zhipu', 'minimax', 'qwen', 'volcengine'])
const CHAT_STREAM_TIMEOUT_MS = 120_000
const ALLOWED_URL_RE = /^https?:\/\//i
const DEFAULT_CONTEXT_WINDOW = 64_000
const COMPACT_RATIO = 0.25
const TAIL_KEEP = 4
const DEFAULT_RECENT_KEEP_TOKENS = 20_000
const MIN_RECENT_KEEP_TOKENS = 4_000

type ChatHistoryMessage = { role: 'user' | 'assistant'; content: string }

export interface PreparedChatHistory {
  messages: ChatHistoryMessage[]
  compacted: boolean
  beforeTokens: number
  afterTokens: number
  beforeMessages: number
  afterMessages: number
}

const MODEL_CONTEXT_WINDOWS: [string, number][] = [
  ['deepseek', 64_000],
  ['gpt-4o', 128_000],
  ['gpt-4', 128_000],
  ['gpt-3.5', 16_000],
  ['gemini-3', 128_000],
  ['gemini-2', 1_000_000],
  ['gemini', 128_000],
  ['claude-opus', 200_000],
  ['claude-sonnet', 200_000],
  ['claude', 200_000],
  ['minimax', 128_000],
  ['kimi', 128_000],
  ['qwen', 128_000],
  ['longcat', 64_000],
  ['mistral', 128_000],
  ['step', 64_000],
]

export function getChatContextWindow(modelName: string): number {
  const lower = modelName.toLowerCase()
  return MODEL_CONTEXT_WINDOWS.find(([prefix]) => lower.includes(prefix))?.[1] ?? DEFAULT_CONTEXT_WINDOW
}

export function getChatCompactThreshold(modelName: string): number {
  return Math.floor(getChatContextWindow(modelName) * COMPACT_RATIO)
}

export function getChatRecentKeepTokens(modelName: string): number {
  const threshold = getChatCompactThreshold(modelName)
  if (threshold <= MIN_RECENT_KEEP_TOKENS * 2) return Math.max(1_000, Math.floor(threshold / 2))
  return Math.min(DEFAULT_RECENT_KEEP_TOKENS, Math.max(MIN_RECENT_KEEP_TOKENS, Math.floor(threshold / 2)))
}

function estimateChatMessageTokens(message: ChatHistoryMessage): number {
  const content = message.content || ''
  const bytes = new TextEncoder().encode(content).length
  return Math.max(Math.floor(content.length / 2), Math.floor(bytes / 3), 1)
}

function estimateChatTokens(messages: ChatHistoryMessage[]): number {
  return messages.reduce((total, message) => total + estimateChatMessageTokens(message), 0)
}

function findChatTailStartByTokenBudget(messages: ChatHistoryMessage[], keepRecentTokens: number): number {
  if (messages.length === 0) return 0
  const minTailStart = Math.max(0, messages.length - TAIL_KEEP)
  let accumulated = 0
  let tailStart = minTailStart

  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i]
    if (!message) continue
    accumulated += estimateChatMessageTokens(message)
    if (accumulated >= keepRecentTokens) {
      tailStart = i
      break
    }
  }

  return Math.min(tailStart, minTailStart)
}

function buildLocalChatSummary(messages: ChatHistoryMessage[], maxChars = 1200): string {
  const codes: string[] = []
  const userGoals: string[] = []
  const assistantNotes: string[] = []

  for (const message of messages) {
    for (const code of message.content.match(/\b\d{6}\b/g) || []) {
      if (!codes.includes(code)) codes.push(code)
    }
    if (message.role === 'user') userGoals.push(message.content.slice(0, 180))
    if (message.role === 'assistant') assistantNotes.push(message.content.slice(0, 220))
  }

  const lines = ['前序读盘室对话已压缩为摘要。']
  if (codes.length) lines.push(`涉及标的：${codes.slice(0, 12).join(', ')}`)
  if (userGoals.length) {
    lines.push('用户关注：')
    for (const item of userGoals.slice(-6)) lines.push(`- ${item}`)
  }
  if (assistantNotes.length) {
    lines.push('已给出的主要结论：')
    for (const item of assistantNotes.slice(-6)) lines.push(`- ${item}`)
  }

  const summary = lines.join('\n')
  return summary.length <= maxChars ? summary : `${summary.slice(0, maxChars - 1).trimEnd()}…`
}

export function prepareChatMessagesForModel(messages: ChatHistoryMessage[], modelName: string): PreparedChatHistory {
  const normalized = messages
    .filter((message) => message.content.trim())
    .map((message) => ({ role: message.role, content: message.content }))
  const beforeTokens = estimateChatTokens(normalized)
  const beforeMessages = normalized.length

  if (normalized.length <= TAIL_KEEP + 2 || beforeTokens <= getChatCompactThreshold(modelName)) {
    return {
      messages: normalized,
      compacted: false,
      beforeTokens,
      afterTokens: beforeTokens,
      beforeMessages,
      afterMessages: beforeMessages,
    }
  }

  const tailStart = findChatTailStartByTokenBudget(normalized, getChatRecentKeepTokens(modelName))
  if (tailStart <= 2) {
    return {
      messages: normalized,
      compacted: false,
      beforeTokens,
      afterTokens: beforeTokens,
      beforeMessages,
      afterMessages: beforeMessages,
    }
  }

  const summary = buildLocalChatSummary(normalized.slice(0, tailStart))
  const compactedMessages: ChatHistoryMessage[] = [
    {
      role: 'user',
      content: `[读盘室对话摘要]\n${summary}\n\n[系统说明] 以上是前序读盘室对话摘要。后续回答可以结合摘要和保留的最近对话，但当前持仓、价格、行情和策略结果仍必须以工具实时返回为准。`,
    },
    { role: 'assistant', content: '好的，我已接续前序读盘室上下文。' },
    ...normalized.slice(tailStart),
  ]

  return {
    messages: compactedMessages,
    compacted: true,
    beforeTokens,
    afterTokens: estimateChatTokens(compactedMessages),
    beforeMessages,
    afterMessages: compactedMessages.length,
  }
}

function parseCustomProviders(raw: unknown): Record<string, Record<string, string>> {
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw || '{}') : (raw || {})
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: Record<string, Record<string, string>> = {}
    for (const [key, value] of Object.entries(parsed)) {
      if (!value || typeof value !== 'object' || Array.isArray(value)) continue
      const entry = value as Record<string, unknown>
      const baseUrl = String(entry.baseurl || entry.base_url || '')
      if (baseUrl && !ALLOWED_URL_RE.test(baseUrl)) continue
      result[key] = Object.fromEntries(Object.entries(entry).map(([k, v]) => [k, String(v ?? '')]))
    }
    return result
  } catch {
    return {}
  }
}

export async function loadLLMConfig(userId: string): Promise<LLMConfig | null> {
  const { data } = await supabase
    .from('user_settings')
    .select('chat_provider, gemini_api_key, gemini_model, gemini_base_url, openai_api_key, openai_model, openai_base_url, deepseek_api_key, deepseek_model, deepseek_base_url, anthropic_api_key, anthropic_model, anthropic_base_url, custom_providers')
    .eq('user_id', userId)
    .single()

  if (!data) return null

  const provider = data.chat_provider || '1route'
  if (RETIRED_PROVIDERS.has(provider)) return null
  let api_key = '', model = '', base_url = ''
  let protocol: 'openai' | 'anthropic' = 'openai'

  if (provider === 'gemini') {
    api_key = data.gemini_api_key || ''
    model = data.gemini_model || 'gemini-2.0-flash'
    base_url = data.gemini_base_url || 'https://generativelanguage.googleapis.com/v1beta/openai'
  } else if (provider === 'openai') {
    api_key = data.openai_api_key || ''
    model = data.openai_model || 'gpt-4o'
    base_url = data.openai_base_url || 'https://api.openai.com/v1'
  } else if (provider === 'deepseek') {
    api_key = data.deepseek_api_key || ''
    model = data.deepseek_model || 'deepseek-chat'
    base_url = data.deepseek_base_url || 'https://api.deepseek.com/v1'
  } else if (provider === 'anthropic') {
    api_key = data.anthropic_api_key || ''
    model = data.anthropic_model || 'claude-sonnet-4-20250514'
    base_url = data.anthropic_base_url || 'https://api.anthropic.com'
    protocol = 'anthropic'
  } else {
    const custom = parseCustomProviders(data.custom_providers)
    const info = custom[provider] || {}
    api_key = info.apikey || info.api_key || ''
    model = info.model || ''
    base_url = info.baseurl || info.base_url || ''
  }

  if (!api_key) return null
  return { api_key, model, base_url, protocol }
}

export async function loadAllModels(userId: string): Promise<ModelOption[]> {
  const { data } = await supabase
    .from('user_settings')
    .select('gemini_api_key, gemini_model, gemini_base_url, openai_api_key, openai_model, openai_base_url, deepseek_api_key, deepseek_model, deepseek_base_url, anthropic_api_key, anthropic_model, anthropic_base_url, custom_providers')
    .eq('user_id', userId)
    .single()

  if (!data) return []

  const LABELS: Record<string, string> = {
    '1route': '1Route', gemini: 'Gemini', openai: 'OpenAI',
    deepseek: 'DeepSeek', anthropic: 'Anthropic',
  }
  const BASE_URLS: Record<string, string> = {
    '1route': 'https://www.1route.dev/v1',
    gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
    openai: 'https://api.openai.com/v1',
    deepseek: 'https://api.deepseek.com/v1',
    anthropic: 'https://api.anthropic.com',
  }

  const models: ModelOption[] = []
  const known = ['gemini', 'openai', 'deepseek', 'anthropic'] as const
  for (const p of known) {
    const key = data[`${p}_api_key`]
    const m = data[`${p}_model`]
    if (key && m) {
      models.push({
        provider: p, label: LABELS[p] || p, model: m,
        api_key: key, base_url: data[`${p}_base_url`] || BASE_URLS[p] || '',
        protocol: p === 'anthropic' ? 'anthropic' : 'openai',
      })
    }
  }

  const custom = parseCustomProviders(data.custom_providers)
  for (const [p, info] of Object.entries(custom) as [string, Record<string, string>][]) {
    if (RETIRED_PROVIDERS.has(p)) continue
    const key = info.apikey || info.api_key
    const m = info.model
    if (key && m) {
      models.push({
        provider: p, label: LABELS[p] || p, model: m,
        api_key: key, base_url: info.baseurl || info.base_url || BASE_URLS[p] || '',
      })
    }
  }

  return models
}


export function createReasoningCache(): string[] {
  return []
}

function restoreReasoningMessages(init: RequestInit | undefined, cache: string[]): RequestInit | undefined {
  if (!init?.body || typeof init.body !== 'string') return init
  try {
    const body = JSON.parse(init.body)
    if (!Array.isArray(body.messages)) return init
    let idx = 0
    for (const msg of body.messages) {
      if (msg.role === 'assistant' && !msg.reasoning_content && idx < cache.length) {
        msg.reasoning_content = cache[idx]
      }
      if (msg.role === 'assistant') idx++
    }
    return { ...init, body: JSON.stringify(body) }
  } catch {
    return init
  }
}

async function throwForApiError(res: Response): Promise<void> {
  if (res.ok) return
  const text = await res.clone().text().catch(() => '')
  let msg = `API ${res.status}`
  try {
    const j = JSON.parse(text)
    msg = j?.error?.message || j?.error || msg
  } catch {
    const plain = text.trim()
    if (plain) msg = plain.slice(0, 500)
  }
  throw new Error(msg)
}

function wrapReasoningStream(res: Response, cache: string[]): Response {
  if (!res.body) return res
  let reasoning = ''
  const decoder = new TextDecoder()
  const transformed = res.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        controller.enqueue(chunk)
        const text = decoder.decode(chunk, { stream: true })
        for (const line of text.split('\n')) {
          if (!line.startsWith('data: ') || line === 'data: [DONE]') continue
          try {
            const evt = JSON.parse(line.slice(6))
            const rc = evt?.choices?.[0]?.delta?.reasoning_content
            if (rc) reasoning += rc
          } catch {}
        }
      },
      flush() { if (reasoning) cache.push(reasoning) },
    }),
  )

  return new Response(transformed, {
    status: res.status,
    statusText: res.statusText,
    headers: res.headers,
  })
}

function buildReasoningFetch(cache: string[]): typeof globalThis.fetch {
  return async (input, init) => {
    const res = await globalThis.fetch(input, restoreReasoningMessages(init, cache))
    await throwForApiError(res)
    const contentType = res.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) return res
    return wrapReasoningStream(res, cache)
  }
}

function createProxiedProvider(config: LLMConfig, reasoningCache: string[]) {
  if (config.protocol === 'anthropic') {
    return createAnthropic({
      apiKey: config.api_key,
      baseURL: '/api/llm-proxy',
      headers: { 'X-Target-URL': config.base_url },
      fetch: buildReasoningFetch(reasoningCache),
    })
  }
  return createOpenAI({
    apiKey: config.api_key,
    baseURL: '/api/llm-proxy',
    headers: { 'X-Target-URL': config.base_url },
    fetch: buildReasoningFetch(reasoningCache),
  })
}

function createMarketHistoryTool(deps: ToolDeps, userId: string, model: unknown) {
  return tool({
    description: '回看大盘指数过去N个交易日K线，分析量价关系、威科夫阶段、支撑压力和当前位置。适合“过去100个交易日”“回看大盘”“量价关系”等问题。',
    inputSchema: z.object({
      days: z.number().nullable().describe('回看交易日数量，默认100，范围1-250'),
      index: z.enum(['sse', 'csi300', 'szse', 'chinext']).nullable().describe('指数：sse=上证指数，csi300=沪深300，szse=深证成指，chinext=创业板指；默认sse'),
    }),
    execute: ({ days, index }) => execMarketHistory(deps, userId, model, days ?? 100, index ?? 'sse'),
  })
}

function createMarketOverviewTool(deps: ToolDeps) {
  return tool({
    description: '查看当前/最新大盘行情信号：市场状态（regime）、上证指数、A50、VIX、市场提示。只适合回答今天或当前的大盘状态。',
    inputSchema: z.object({}),
    execute: () => execMarketOverview(deps),
  })
}

function formatPortfolioPlan({ action, code, name, shares, cost_price, stop_loss, reason }: { action: string; code: string; name: string | null; shares: number | null; cost_price: number | null; stop_loss: number | null; reason: string | null }) {
  const actionLabel = { add: '新增', update: '修改', delete: '删除' }[action] ?? action
  const lines = [`📋 **调仓方案**`, `- 操作：${actionLabel}`, `- 标的：${code} ${name || ''}`]
  if (shares) lines.push(`- 股数：${shares}`)
  if (cost_price) lines.push(`- 价格：¥${cost_price}`)
  if (stop_loss) lines.push(`- 止损：¥${stop_loss}`)
  if (reason) lines.push(`- 理由：${reason}`)
  lines.push('', '⚠️ 请确认是否执行此操作？')
  return lines.join('\n')
}

function buildTools(userId: string, config: LLMConfig, reasoningCache: string[]) {
  const deps: ToolDeps = { supabase, fetch: globalThis.fetch, generateText }
  const model = createProxiedProvider(config, reasoningCache).chat(config.model)
  return {
    search_stock: tool({
      description: '搜索股票，支持代码或名称。返回匹配的股票列表及最新行情。',
      inputSchema: z.object({ query: z.string().describe('股票代码或名称关键词') }),
      execute: ({ query }) => execSearchStock(deps, userId, query),
    }),

    view_portfolio: tool({
      description: '查看用户当前持仓列表（代码、名称、股数、成本价）和可用资金。',
      inputSchema: z.object({}),
      execute: () => execViewPortfolio(deps, userId),
    }),

    market_overview: createMarketOverviewTool(deps),
    market_history: createMarketHistoryTool(deps, userId, model),

    query_recommendations: tool({
      description: '查询形态复盘记录，显示入选股票及其后续涨跌表现。',
      inputSchema: z.object({ limit: z.number().describe('返回条数，通常20') }),
      execute: ({ limit }) => execQueryRecommendations(deps, limit),
    }),

    query_tail_buy: tool({
      description: '查询尾盘买入策略的历史记录（BUY/WATCH 决策、评分、LLM 理由）。',
      inputSchema: z.object({ limit: z.number().describe('返回条数，通常20') }),
      execute: ({ limit }) => execQueryTailBuy(deps, limit),
    }),

    plan_portfolio_update: tool({
      description: '生成调仓方案（不执行）。展示给用户确认后再调用 execute_portfolio_update。',
      inputSchema: z.object({
        action: z.enum(['add', 'update', 'delete']).describe('操作类型'),
        code: z.string().describe('6位股票代码'),
        name: z.string().nullable().describe('股票名称'),
        shares: z.number().nullable().describe('股数'),
        cost_price: z.number().nullable().describe('成本价'),
        stop_loss: z.number().nullable().describe('止损价'),
        reason: z.string().nullable().describe('调仓理由'),
      }),
      execute: (params) => formatPortfolioPlan(params),
    }),

    execute_portfolio_update: tool({
      description: '用户确认后执行调仓。必须在 plan_portfolio_update 之后、用户确认后才能调用。',
      inputSchema: z.object({
        action: z.enum(['add', 'update', 'delete']).describe('操作类型'),
        code: z.string().describe('6位股票代码'),
        name: z.string().nullable().describe('股票名称'),
        shares: z.number().nullable().describe('股数'),
        cost_price: z.number().nullable().describe('成本价'),
        stop_loss: z.number().nullable().describe('止损价'),
      }),
      execute: ({ action, code, name, shares, cost_price, stop_loss }) =>
        execExecutePortfolioUpdate(deps, userId, action, code, name, shares, cost_price, stop_loss),
    }),

    analyze_stock: tool({
      description: '对单只股票做威科夫深度诊断：K线走势、量价关系、均线形态、阶段判断，并在A股可用时加入价值面校准（盈利质量、成长、杠杆、现金流）。需要股票代码。',
      inputSchema: z.object({
        code: z.string().describe('股票代码：A股6位数字；美股/港股使用 TickFlow 标准代码，如 AAPL.US / 00700.HK'),
        name: z.string().nullable().describe('股票名称'),
      }),
      execute: ({ code, name }) => execAnalyzeStock(deps, userId, config, model, code, name),
    }),

    screen_stocks: tool({
      description: '查看最新一期漏斗选股结果：AI入选的候选股票列表及其评分。',
      inputSchema: z.object({}),
      execute: () => execScreenStocks(deps),
    }),

    generate_ai_report: tool({
      description: '为指定股票生成威科夫深度研报（AI分析），支持多只股票批量生成。',
      inputSchema: z.object({ codes: z.array(z.string()).describe('股票代码数组，如 ["600519", "AAPL.US", "00700.HK"]') }),
      execute: ({ codes }) => execGenerateAiReport(deps, userId, config, model, codes),
    }),

    generate_strategy_decision: tool({
      description: '基于当前持仓和市场状态，给出买入/卖出/持有的操作建议。',
      inputSchema: z.object({}),
      execute: () => execStrategyDecision(deps, userId, model),
    }),
  }
}

export interface StepInfo {
  type: 'tool_call' | 'text'
  toolName?: string
  text?: string
  toolResult?: string
}

export interface StreamCallbacks {
  onStep: (step: StepInfo) => void
  onTextDelta: (delta: string) => void
  onFinish: (finalText: string, steps: StepInfo[]) => void
  onError: (error: Error) => void
}

export function runChatAgentStream(
  config: LLMConfig,
  userId: string,
  messages: { role: 'user' | 'assistant'; content: string }[],
  callbacks: StreamCallbacks,
  reasoningCache: string[],
): AbortController {
  const provider = createProxiedProvider(config, reasoningCache)

  const tools = buildTools(userId, config, reasoningCache)
  const steps: StepInfo[] = []

  const abort = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    abort.abort()
  }, CHAT_STREAM_TIMEOUT_MS)

  void (async () => {
    try {
      const preparedHistory = prepareChatMessagesForModel(messages, config.model)
      const result = streamText({
        model: provider.chat(config.model),
        system: SYSTEM_PROMPT,
        messages: preparedHistory.messages,
        tools,
        stopWhen: stepCountIs(10),
        abortSignal: abort.signal,
      })

      let finalText = ''
      for await (const event of result.fullStream) {
        switch (event.type) {
          case 'text-delta':
            finalText += event.text
            callbacks.onTextDelta(event.text)
            break
          case 'tool-call': {
            const step: StepInfo = { type: 'tool_call', toolName: event.toolName }
            steps.push(step)
            callbacks.onStep(step)
            break
          }
          case 'tool-result': {
            const s = steps.findLast(s => s.toolName === event.toolName)
            if (s) s.toolResult = typeof event.output === 'string' ? event.output : JSON.stringify(event.output)
            break
          }
          case 'error':
            throw event.error
        }
      }

      callbacks.onFinish(finalText, steps)
    } catch (err) {
      if (timedOut) {
        callbacks.onError(new Error('请求超过 120 秒已自动停止，请缩短问题或稍后重试。'))
      } else if (!abort.signal.aborted) {
        callbacks.onError(err instanceof Error ? err : new Error(String(err)))
      }
    } finally {
      clearTimeout(timer)
    }
  })()

  return abort
}
