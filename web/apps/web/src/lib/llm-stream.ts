import type { LLMConfig } from './chat-agent'

interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

type StreamProtocol = 'openai' | 'anthropic'

interface StreamRequest {
  url: string
  headers: Record<string, string>
  body: string
}

export interface LLMStreamStatus {
  phase: 'retrying' | 'fallback'
  model: string
  attempt: number
  nextModel?: string
}

export async function streamLLMResponse(
  config: LLMConfig,
  messages: ChatMessage[],
  opts: { temperature?: number; maxTokens?: number; signal?: AbortSignal; onDelta?: (chunk: string) => void } = {},
): Promise<string> {
  const protocol = config.protocol ?? 'openai'
  const request = buildStreamRequest(config, messages, opts, protocol)
  const response = await fetch(request.url, {
    method: 'POST',
    signal: opts.signal,
    headers: request.headers,
    body: request.body,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.error?.message || `模型请求失败 (${response.status})`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('响应无可读流')

  const decoder = new TextDecoder()
  let result = ''
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()!
    for (const line of lines) {
      const delta = extractDataLineDelta(line, protocol)
      if (delta) { opts.onDelta?.(delta); result += delta }
    }
  }
  buffer += decoder.decode()
  for (const line of buffer.split('\n')) {
    const delta = extractDataLineDelta(line, protocol)
    if (delta) { opts.onDelta?.(delta); result += delta }
  }
  return result
}

export async function streamLLMResponseWithFallback(
  configs: LLMConfig[],
  messages: ChatMessage[],
  opts: { temperature?: number; maxTokens?: number; signal?: AbortSignal; onDelta?: (chunk: string) => void; onStatus?: (status: LLMStreamStatus) => void } = {},
): Promise<string> {
  let lastError: unknown = new Error('没有可用的模型配置')
  for (let index = 0; index < configs.length; index += 1) {
    const config = configs[index]
    if (!config) continue
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      let emitted = false
      try {
        return await streamLLMResponse(config, messages, {
          ...opts,
          onDelta: (chunk) => { emitted = true; opts.onDelta?.(chunk) },
        })
      } catch (error) {
        lastError = error
        if (opts.signal?.aborted || emitted || !isRetryableModelError(error)) throw error
        const nextConfig = configs[index + 1]
        const canRetry = attempt < 2
        opts.onStatus?.({
          phase: canRetry ? 'retrying' : 'fallback',
          model: config.model,
          attempt,
          ...(canRetry ? {} : nextConfig ? { nextModel: nextConfig.model } : {}),
        })
        if (!canRetry && !nextConfig) throw error
        await waitForRetry(attempt, opts.signal)
        if (!canRetry) break
      }
    }
  }
  throw lastError
}

function isRetryableModelError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  const match = message.match(/\((\d{3})\)/)
  const status = match ? Number(match[1]) : null
  if (status == null) return true
  return status === 408 || status === 409 || status === 429 || status >= 500
}

async function waitForRetry(attempt: number, signal?: AbortSignal): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const timer = globalThis.setTimeout(resolve, attempt * 350)
    signal?.addEventListener('abort', () => { globalThis.clearTimeout(timer); reject(signal.reason) }, { once: true })
  })
}

function buildStreamRequest(
  config: LLMConfig,
  messages: ChatMessage[],
  opts: { temperature?: number; maxTokens?: number },
  protocol: StreamProtocol,
): StreamRequest {
  if (protocol === 'anthropic') {
    const system = messages.filter(item => item.role === 'system').map(item => item.content).join('\n\n')
    const chatMessages = messages.filter(item => item.role !== 'system')
    return {
      url: '/api/llm-proxy/v1/messages',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': config.api_key,
        'anthropic-version': '2023-06-01',
        'X-Target-URL': config.base_url,
      },
      body: JSON.stringify({
        model: config.model,
        messages: chatMessages,
        ...(system ? { system } : {}),
        temperature: opts.temperature ?? 0.5,
        max_tokens: opts.maxTokens ?? 4096,
        stream: true,
      }),
    }
  }

  return {
    url: '/api/llm-proxy/chat/completions',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${config.api_key}`,
      'X-Target-URL': config.base_url,
    },
    body: JSON.stringify({
      model: config.model,
      messages,
      temperature: opts.temperature ?? 0.5,
      max_tokens: opts.maxTokens ?? 4096,
      stream: true,
    }),
  }
}

function extractDataLineDelta(line: string, protocol: StreamProtocol): string | undefined {
  const trimmed = line.trim()
  if (!trimmed.startsWith('data: ')) return undefined
  const payload = trimmed.slice(6)
  if (payload === '[DONE]') return undefined
  try {
    return extractStreamDelta(JSON.parse(payload), protocol)
  } catch {
    return undefined
  }
}

function extractStreamDelta(json: unknown, protocol: StreamProtocol): string | undefined {
  if (!json || typeof json !== 'object') return undefined
  if (protocol === 'anthropic') return extractAnthropicDelta(json as Record<string, unknown>)
  const choices = (json as Record<string, unknown>).choices
  if (!Array.isArray(choices)) return undefined
  const first = choices[0]
  if (!first || typeof first !== 'object') return undefined
  const delta = (first as Record<string, unknown>).delta
  if (!delta || typeof delta !== 'object') return undefined
  const content = (delta as Record<string, unknown>).content
  return typeof content === 'string' ? content : undefined
}

function extractAnthropicDelta(json: Record<string, unknown>): string | undefined {
  if (json.type !== 'content_block_delta') return undefined
  const delta = json.delta
  if (!delta || typeof delta !== 'object') return undefined
  const text = (delta as Record<string, unknown>).text
  return typeof text === 'string' ? text : undefined
}
