const HIGH_RISK_MOMENTUM_SIGNALS = new Set(['rec_momentum_continuation'])

export interface TailBuyExecutionInput {
  finalDecision?: unknown
  signalType?: unknown
  features?: Record<string, unknown> | null
}

export interface TailBuyExecutionSemantics {
  rawDecision: string
  label: string
  status: string
  orderable: boolean
  nextStep: string
  display: string
  tone: 'buy' | 'watch' | 'skip' | 'unknown'
}

export function tailBuyExecutionSemantics(input: TailBuyExecutionInput): TailBuyExecutionSemantics {
  const rawDecision = String(input.finalDecision || '').trim().toUpperCase()
  const features = input.features || {}
  const explicitLabel = String(features.execution_label || '').trim()
  const explicitStatus = String(features.execution_status || '').trim()
  const explicitNextStep = String(features.execution_next_step || '').trim()
  const explicitOrderable = typeof features.orderable === 'boolean' ? features.orderable : undefined
  const fallback = fallbackTailBuyExecution(rawDecision, String(input.signalType || '').trim())
  const label = explicitLabel || fallback.label
  const status = explicitStatus || fallback.status
  const orderable = explicitOrderable ?? fallback.orderable
  const nextStep = explicitNextStep || fallback.nextStep
  return {
    rawDecision: rawDecision || '-',
    label,
    status,
    orderable,
    nextStep,
    display: rawDecision ? `${rawDecision}（${label}）` : label,
    tone: toneFromStatus(status, rawDecision),
  }
}

function fallbackTailBuyExecution(decision: string, signalType: string) {
  if (decision === 'BUY' && HIGH_RISK_MOMENTUM_SIGNALS.has(signalType)) {
    return { label: '观察买入', status: 'watch_buy', orderable: false, nextStep: '高位动能默认不买；只保留人工复核。' }
  }
  if (decision === 'BUY') {
    return { label: '可执行买入', status: 'executable_buy', orderable: true, nextStep: '仍需人工按支撑、回落与仓位纪律复核。' }
  }
  if (decision === 'WATCH') return { label: '观察买入', status: 'watch_buy', orderable: false, nextStep: '继续观察，未达到直接开仓口径。' }
  if (decision === 'SKIP') return { label: '禁止新仓', status: 'blocked', orderable: false, nextStep: '暂不买入。' }
  return { label: '未知', status: 'unknown', orderable: false, nextStep: '决策缺失或无法识别。' }
}

function toneFromStatus(status: string, decision: string): TailBuyExecutionSemantics['tone'] {
  if (status === 'executable_buy') return 'buy'
  if (status === 'watch_buy' || status === 'next_day_watch') return 'watch'
  if (status === 'blocked' || decision === 'SKIP') return 'skip'
  return 'unknown'
}
