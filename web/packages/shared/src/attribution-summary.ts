export interface AttributionOperatorAction {
  label?: unknown
  target?: unknown
  weight_multiplier?: unknown
  scope?: Record<string, unknown> | null
}

export interface AttributionOperatorSummaryInput {
  operations?: {
    operator_summary?: unknown
    action_summary?: unknown
  } | null
  execution?: {
    next_action_summary?: unknown
    next_action?: unknown
    scope?: unknown
    active_scope?: unknown
    signal_action_count?: unknown
    formal_dynamic_allowed?: unknown
    formal_dynamic_block_reason?: unknown
  } | null
  latest?: {
    trade_date?: unknown
    regime?: unknown
    selection_summary?: unknown
  } | null
  selection?: Record<string, unknown> | null
  actions?: AttributionOperatorAction[] | null
}

export interface AttributionExecutionImpactInput {
  execution?: {
    summary?: unknown
    signal_action_count?: unknown
    scope?: unknown
    active_scope?: unknown
    tail_buy_weights_active?: unknown
    funnel_shadow_weights_active?: unknown
    funnel_formal_weights_active?: unknown
  } | null
  actionCount?: unknown
  targetText?: unknown
}

export function attributionOperatorSummary(input: AttributionOperatorSummaryInput): string {
  const summary = optionalText(input.operations?.operator_summary)
  if (summary) return normalizeOperatorSummaryScope(summary, input.execution, input.actions || [])

  const actions = input.actions || []
  return [
    `下一步=${operatorNextAction(input.execution)}`,
    `作用范围=${operatorScope(input.execution, actions)}`,
    `正式dynamic=${operatorFormalDynamic(input.execution)}`,
    operatorShadowSummary(input.latest, input.selection),
    optionalText(input.operations?.action_summary) || `调权=${actions.length}项`,
  ].join('；')
}

export function attributionExecutionImpactText(input: AttributionExecutionImpactInput): string {
  const summary = optionalText(input.execution?.summary)
  if (summary) return summary

  const actionCount = Number(input.actionCount ?? input.execution?.signal_action_count ?? 0)
  if (actionCount <= 0) return '本期没有可执行的信号级调权，归因结果只用于观察与人工复盘。'

  const active = activeFlags(input.execution, actionCount)
  const targetText = optionalText(input.targetText) || '-'
  const impacts = []
  if (active.tail) impacts.push('尾盘策略会读取这些权重')
  if (active.formal) {
    impacts.push('正式漏斗候选排序会读取这些权重')
  } else if (active.shadow) {
    impacts.push('漏斗侧仅进入 shadow 对照，不影响正式推荐')
  }
  if (impacts.length === 0) impacts.push('当前只保留为归因观察，不进入执行排序')
  return `归因调权已沉淀为信号级权重输入，覆盖 ${targetText}。${impacts.join('；')}。`
}

function normalizeOperatorSummaryScope(
  summary: string,
  execution: AttributionOperatorSummaryInput['execution'],
  actions: AttributionOperatorAction[],
): string {
  const activeScope = operatorScope(execution, actions)
  return summary.replace(
    /作用范围=(tail_buy_and_funnel_shadow|tail_buy_and_funnel|tail_buy_only|none)(?=；|$)/,
    `作用范围=${activeScope}`,
  )
}

function operatorNextAction(execution: AttributionOperatorSummaryInput['execution']): string {
  return optionalText(execution?.next_action_summary) || optionalText(execution?.next_action) || '-'
}

function operatorScope(
  execution: AttributionOperatorSummaryInput['execution'],
  actions: AttributionOperatorAction[],
): string {
  const explicit = optionalText(execution?.active_scope)
  if (explicit) return explicit
  return activeScopeFromExecution(execution, actions)
}

function activeScopeFromExecution(
  execution: AttributionOperatorSummaryInput['execution'],
  actions: AttributionOperatorAction[],
): string {
  const actionCount = Number(execution?.signal_action_count ?? actions.length)
  const scope = optionalText(execution?.scope) || (actions.length ? 'tail_buy_only' : 'none')
  if (actionCount <= 0) return '无'
  if (scope === 'tail_buy_and_funnel') return '尾盘+正式漏斗'
  if (scope === 'tail_buy_and_funnel_shadow') return '尾盘+漏斗shadow'
  if (scope === 'tail_buy_only') return '尾盘'
  return '无'
}

function activeFlags(
  execution: AttributionExecutionImpactInput['execution'],
  actionCount: number,
): { tail: boolean, shadow: boolean, formal: boolean } {
  const tail = boolValue(execution?.tail_buy_weights_active)
  const shadow = boolValue(execution?.funnel_shadow_weights_active)
  const formal = boolValue(execution?.funnel_formal_weights_active)
  if (tail !== undefined || shadow !== undefined || formal !== undefined) {
    return { tail: tail === true, shadow: shadow === true, formal: formal === true }
  }

  const scope = optionalText(execution?.scope) || 'none'
  return {
    tail: actionCount > 0 && ['tail_buy_only', 'tail_buy_and_funnel_shadow', 'tail_buy_and_funnel'].includes(scope),
    shadow: actionCount > 0 && scope === 'tail_buy_and_funnel_shadow',
    formal: actionCount > 0 && scope === 'tail_buy_and_funnel',
  }
}

function boolValue(value: unknown): boolean | undefined {
  if (value === true || value === false) return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true') return true
    if (normalized === 'false') return false
  }
  return undefined
}

function operatorFormalDynamic(execution: AttributionOperatorSummaryInput['execution']): string {
  if (execution?.formal_dynamic_allowed === true) return 'allowed'
  if (execution?.formal_dynamic_allowed === false) {
    const reason = optionalText(execution.formal_dynamic_block_reason)
    return reason ? `blocked(${reason})` : 'blocked'
  }
  if (optionalText(execution?.next_action) === 'manual_review_dynamic_on') return 'blocked(manual_review_required)'
  return 'unknown'
}

function operatorShadowSummary(
  latest: AttributionOperatorSummaryInput['latest'],
  selection: Record<string, unknown> | null | undefined,
): string {
  const resolvedSelection = selection || selectionSummary(latest)
  if (!latest && !resolvedSelection) return 'Shadow=暂无最新对照'
  return [
    `Shadow=${optionalText(latest?.trade_date) || '-'}`,
    optionalText(latest?.regime) || '-',
    `新增${valueText(resolvedSelection?.diff_added_count)}`,
    `移除${valueText(resolvedSelection?.diff_removed_count)}`,
  ].join(' ')
}

function selectionSummary(latest: AttributionOperatorSummaryInput['latest']): Record<string, unknown> | null {
  const raw = latest?.selection_summary
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : null
}

function optionalText(value: unknown): string {
  return String(value ?? '').trim()
}

function valueText(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  return optionalText(value) || '-'
}
