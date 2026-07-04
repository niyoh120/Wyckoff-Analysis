export type PolicyWeightMetaInput = Record<string, unknown> | null | undefined

export function formatPolicyWeightMetaText(meta: PolicyWeightMetaInput): string {
  if (!meta) return ''
  const tokens = policySourceTokens(meta)
  const active = policyActiveScope(meta)
  if (active) tokens.push(`active=${active}`)
  const formalBlock = textMeta(meta, 'formal_dynamic_block_reason')
  if (boolMeta(meta, 'formal_dynamic_allowed') === false && formalBlock) {
    tokens.push(`formal_block=${formalBlock}`)
  }
  return tokens.length ? `（${tokens.join(', ')}）` : ''
}

function policySourceTokens(meta: Record<string, unknown>): string[] {
  const tokens: string[] = []
  const source = textMeta(meta, 'source')
  const reportDate = textMeta(meta, 'report_date')
  const horizon = textMeta(meta, 'horizon')
  const ageDays = rawMeta(meta, 'age_days')
  const executionPolicy = textMeta(meta, 'execution_policy')
  const executionScope = textMeta(meta, 'execution_scope')
  const nextAction = textMeta(meta, 'next_action')

  if (source) tokens.push(source)
  if (reportDate) tokens.push(`report=${reportDate}`)
  if (horizon) tokens.push(`h=${horizon}`)
  if (ageDays !== undefined && ageDays !== null && String(ageDays) !== '') tokens.push(`age=${ageDays}d`)
  if (executionPolicy) tokens.push(`mode=${executionPolicy}`)
  if (executionScope) tokens.push(`scope=${executionScope}`)
  if (nextAction) tokens.push(`next=${nextAction}`)
  return tokens
}

function policyActiveScope(meta: Record<string, unknown>): string {
  const parts: string[] = []
  if (boolMeta(meta, 'tail_buy_weights_active') === true) parts.push('尾盘')
  if (boolMeta(meta, 'funnel_formal_weights_active') === true) {
    parts.push('正式漏斗')
  } else if (boolMeta(meta, 'funnel_shadow_weights_active') === true) {
    parts.push('漏斗shadow')
  }
  return parts.join('+')
}

function textMeta(meta: Record<string, unknown>, key: string): string {
  return String(rawMeta(meta, key) ?? '').trim()
}

function boolMeta(meta: Record<string, unknown>, key: string): boolean | undefined {
  const value = rawMeta(meta, key)
  if (value === true || value === false) return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true') return true
    if (normalized === 'false') return false
  }
  return undefined
}

function rawMeta(meta: Record<string, unknown>, key: string): unknown {
  const prefixed = `policy_weight_${key}`
  return meta[key] ?? meta[prefixed]
}
