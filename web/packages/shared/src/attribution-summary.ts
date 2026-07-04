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

export function attributionOperatorSummary(input: AttributionOperatorSummaryInput): string {
  const summary = optionalText(input.operations?.operator_summary)
  if (summary) return summary

  const actions = input.actions || []
  return [
    `下一步=${operatorNextAction(input.execution)}`,
    `作用范围=${operatorScope(input.execution, actions)}`,
    `正式dynamic=${operatorFormalDynamic(input.execution)}`,
    operatorShadowSummary(input.latest, input.selection),
    optionalText(input.operations?.action_summary) || `调权=${actions.length}项`,
  ].join('；')
}

function operatorNextAction(execution: AttributionOperatorSummaryInput['execution']): string {
  return optionalText(execution?.next_action_summary) || optionalText(execution?.next_action) || '-'
}

function operatorScope(
  execution: AttributionOperatorSummaryInput['execution'],
  actions: AttributionOperatorAction[],
): string {
  return optionalText(execution?.scope) || (actions.length ? 'tail_buy_only' : 'none')
}

function operatorFormalDynamic(execution: AttributionOperatorSummaryInput['execution']): string {
  if (execution?.formal_dynamic_allowed === true) return 'allowed'
  if (execution?.formal_dynamic_allowed === false) {
    const reason = optionalText(execution.formal_dynamic_block_reason)
    return reason ? `blocked(${reason})` : 'blocked'
  }
  if (optionalText(execution?.next_action) === 'manual_review_dynamic_on') return 'allowed'
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
