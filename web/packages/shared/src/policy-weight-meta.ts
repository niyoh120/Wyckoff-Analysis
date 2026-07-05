import { attributionFormalDynamicReasonLabel, attributionNextActionLabel } from './attribution-summary'

export type PolicyWeightMetaInput = Record<string, unknown> | null | undefined

export function formatPolicyWeightMetaText(meta: PolicyWeightMetaInput): string {
  if (!meta) return ''
  const tokens = policySourceTokens(meta)
  const active = policyActiveScope(meta)
  if (active) tokens.push(`范围=${active}`)
  const formalBlock = textMeta(meta, 'formal_dynamic_block_reason')
  if (boolMeta(meta, 'formal_dynamic_allowed') === false && formalBlock) {
    tokens.push(`正式dynamic=${policyFormalDynamicLabel(meta)}`)
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
  const nextAction = textMeta(meta, 'next_action')

  if (source) tokens.push(source)
  if (reportDate) tokens.push(`报告=${reportDate}`)
  if (horizon) tokens.push(`周期=h${horizon}`)
  if (ageDays !== undefined && ageDays !== null && String(ageDays) !== '') tokens.push(`距今=${ageDays}天`)
  if (executionPolicy) tokens.push(`策略=${policyExecutionModeLabel(executionPolicy)}`)
  if (nextAction) tokens.push(`下一步=${attributionNextActionLabel(nextAction)}`)
  return tokens
}

function policyExecutionModeLabel(raw: unknown): string {
  const value = String(raw || '').trim()
  const labels: Record<string, string> = {
    on: '正式调权(on)',
    shadow: 'shadow 对照(shadow)',
    off: '静态策略(off)',
    unknown: '未知模式',
  }
  return labels[value] || (value ? `${value} 模式` : '未知模式')
}

function policyFormalDynamicLabel(meta: Record<string, unknown>): string {
  const allowed = boolMeta(meta, 'formal_dynamic_allowed')
  if (allowed === true) return '允许正式生效'
  if (allowed === false) {
    const reason = textMeta(meta, 'formal_dynamic_block_reason')
    return reason ? `未进正式漏斗(${attributionFormalDynamicReasonLabel(reason)})` : '未进正式漏斗'
  }
  return '未知'
}

function policyActiveScope(meta: Record<string, unknown>): string {
  const explicit = textMeta(meta, 'active_scope')
  if (explicit && explicit !== '无') return explicit
  const parts: string[] = []
  if (boolMeta(meta, 'tail_buy_weights_active') === true) parts.push('尾盘')
  if (boolMeta(meta, 'funnel_formal_weights_active') === true) {
    parts.push('正式漏斗')
  } else if (boolMeta(meta, 'funnel_shadow_weights_active') === true) {
    parts.push('漏斗shadow')
  }
  if (parts.length) return parts.join('+')
  const scope = textMeta(meta, 'execution_scope')
  if (scope === 'tail_buy_and_funnel') return '尾盘+正式漏斗'
  if (scope === 'tail_buy_and_funnel_shadow') return '尾盘+漏斗shadow'
  if (scope === 'tail_buy_only') return '尾盘'
  return ''
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
