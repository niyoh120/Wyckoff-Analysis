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
    backtest_confirmation_text?: unknown
    promotion_checklist_summary?: unknown
  } | null
  execution?: {
    next_action_summary?: unknown
    next_action?: unknown
    scope?: unknown
    active_scope?: unknown
    signal_action_count?: unknown
    formal_dynamic_allowed?: unknown
    formal_dynamic_block_reason?: unknown
    promotion_checklist?: unknown
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

export function attributionModeRecommendationLabel(value: unknown): string {
  const labels: Record<string, string> = {
    review_promote_dynamic_policy: '评审是否切 on',
    keep_shadow: '保持 shadow',
    keep_static_policy: '保持静态策略',
  }
  return labels[optionalText(value)] || optionalText(value) || '保持 shadow'
}

export function attributionNextActionLabel(value: unknown): string {
  const labels: Record<string, string> = {
    manual_review_dynamic_on: '进入人工晋级评审（非正式生效）',
    formal_dynamic_approved: '正式 dynamic 已人工批准',
    run_backtest_confirmation: '先跑回测确认',
    keep_shadow_backtest_failed: '回测未通过，保持 shadow',
    review_policy_actions: '先复核调权治理项',
    keep_static_policy: '保持静态策略',
    collect_more_shadow_samples: '继续收集样本',
    keep_shadow_apply_signal_weights: '保持 shadow 并应用信号级调权',
    keep_shadow_observe: '保持 shadow 观察',
  }
  return labels[optionalText(value)] || optionalText(value) || '保持观察'
}

export function attributionPromotionStatusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    manual_review_required: '需人工复核',
    manual_approved: '已人工批准',
    do_not_promote: '禁止晋级',
    collect_more_samples: '继续收集样本',
    keep_shadow: '保持 shadow',
  }
  return labels[optionalText(value)] || optionalText(value) || '未知'
}

export function attributionGovernorStatusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    candidate: '可进入人工晋级评审',
    watch: '继续观察',
    reject: '不建议晋级',
    insufficient_sample: '样本不足',
  }
  return labels[optionalText(value)] || optionalText(value) || '未知'
}

export function attributionFormalDynamicLabel(
  execution: AttributionOperatorSummaryInput['execution'],
): string {
  if (execution?.formal_dynamic_allowed === true) return '允许正式生效'
  if (execution?.formal_dynamic_allowed === false) {
    const reason = optionalText(execution.formal_dynamic_block_reason)
    return reason ? `未进正式漏斗(${attributionFormalDynamicReasonLabel(reason)})` : '未进正式漏斗'
  }
  if (optionalText(execution?.next_action) === 'manual_review_dynamic_on') {
    return '未进正式漏斗(人工复核未完成)'
  }
  if (optionalText(execution?.next_action) === 'review_policy_actions') {
    return '未进正式漏斗(调权治理项待复核)'
  }
  if (optionalText(execution?.next_action) === 'formal_dynamic_approved') {
    return '允许正式生效'
  }
  if (optionalText(execution?.next_action) === 'run_backtest_confirmation') {
    return '未进正式漏斗(缺少回测确认)'
  }
  if (optionalText(execution?.next_action) === 'keep_shadow_backtest_failed') {
    return '未进正式漏斗(回测未通过)'
  }
  return '未知'
}

export function attributionFormalDynamicReasonLabel(reason: unknown): string {
  const text = optionalText(reason)
  const labels: Record<string, string> = {
    'auto_apply=false': '未启用自动晋级',
    backtest_confirmation_failed: '回测未通过',
    backtest_confirmation_required: '缺少回测确认',
    backtest_policy_evidence_required: '回测缺少策略治理证据',
    'execution_state=missing': '缺少后端执行态',
    'formal_dynamic_allowed=false': '治理器未放行',
    manual_approval_incomplete: '人工批准证据不完整',
    manual_review_required: '人工复核未完成',
    'promotion_checklist=missing': '晋级清单缺失',
    shadow_only: '仅 shadow 观察',
    selection_actions_review_required: '候选源治理待复核',
    signal_actions_review_required: '信号调权待复核',
  }
  if (labels[text]) return labels[text]
  if (text.startsWith('next_action=')) {
    return `下一步=${attributionNextActionLabel(text.slice('next_action='.length))}`
  }
  if (text.startsWith('promotion_status=')) {
    return `晋级状态=${attributionPromotionStatusLabel(text.slice('promotion_status='.length))}`
  }
  if (text.startsWith('promotion_checklist=')) {
    const details = text.slice('promotion_checklist='.length)
    return details ? `晋级清单未通过(${promotionChecklistDetailLabel(details)})` : '晋级清单未通过'
  }
  return text
}

function promotionChecklistDetailLabel(details: string): string {
  const parts = details.split(',').map((item) => item.trim()).filter(Boolean).map((item) => {
    const [key, status] = item.split(':', 2)
    return status ? `${promotionCheckKeyLabel(key)}:${promotionCheckStatusLabel(status)}` : promotionCheckKeyLabel(key)
  })
  return parts.length ? parts.join('，') : details
}

function promotionCheckKeyLabel(raw: string): string {
  const labels: Record<string, string> = {
    shadow_sample: '样本',
    shadow_performance: 'Shadow表现',
    shadow_added_outperforms_removed: '新增跑赢',
    selection_actions: '候选源治理',
    signal_actions: '信号调权',
    backtest_confirmation: '回测',
  }
  return labels[raw.trim()] || raw.trim() || '-'
}

function promotionCheckStatusLabel(raw: string): string {
  const labels: Record<string, string> = {
    pass: '通过',
    fail: '失败',
    review: '待复核',
    missing: '缺失',
    not_required: '不需要',
    unknown: '未知',
  }
  return labels[raw.trim()] || raw.trim() || '未知'
}

export function attributionOperatorSummary(input: AttributionOperatorSummaryInput): string {
  const summary = optionalText(input.operations?.operator_summary)
  if (summary) return normalizeOperatorSummary(summary, input.execution, input.actions || [])

  const actions = input.actions || []
  return [
    `下一步=${operatorNextAction(input.execution)}`,
    `作用范围=${operatorScope(input.execution, actions)}`,
    `正式dynamic=${operatorFormalDynamic(input.execution)}`,
    `回测确认=${operatorBacktestConfirmation(input)}`,
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

function normalizeOperatorSummary(
  summary: string,
  execution: AttributionOperatorSummaryInput['execution'],
  actions: AttributionOperatorAction[],
): string {
  return normalizeOperatorSummaryFormalDynamic(normalizeOperatorSummaryScope(summary, execution, actions), execution)
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

function normalizeOperatorSummaryFormalDynamic(
  summary: string,
  execution: AttributionOperatorSummaryInput['execution'],
): string {
  const formalLabel = attributionFormalDynamicLabel(execution)
  if (formalLabel !== '未知') {
    return summary.replace(/正式dynamic=[^；]+(?=；|$)/, `正式dynamic=${formalLabel}`)
  }
  return summary
    .replace(/正式dynamic=暂不晋级(?:\(([^；)]*)\))?(?=；|$)/g, (_match, reason: string | undefined) => (
      reason ? `正式dynamic=未进正式漏斗(${attributionFormalDynamicReasonLabel(reason)})` : '正式dynamic=未进正式漏斗'
    ))
    .replace(/正式dynamic=未进正式漏斗\(([^；)]*)\)(?=；|$)/g, (_match, reason: string) => (
      `正式dynamic=未进正式漏斗(${attributionFormalDynamicReasonLabel(reason)})`
    ))
}

function operatorNextAction(execution: AttributionOperatorSummaryInput['execution']): string {
  const summary = optionalText(execution?.next_action_summary)
  if (summary) return summary
  return attributionNextActionLabel(execution?.next_action)
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
  return attributionFormalDynamicLabel(execution)
}

function operatorBacktestConfirmation(input: AttributionOperatorSummaryInput): string {
  const explicit = optionalText(input.operations?.backtest_confirmation_text)
  if (explicit) return explicit
  const row = checklistItem(input.execution?.promotion_checklist, 'backtest_confirmation')
  if (!row) return '缺失(缺少检查项)'
  return `${statusLabel(row.status)}(${optionalText(row.summary) || '-'})`
}

function checklistItem(rows: unknown, key: string): Record<string, unknown> | null {
  if (!Array.isArray(rows)) return null
  for (const row of rows) {
    if (row && typeof row === 'object' && !Array.isArray(row) && optionalText((row as Record<string, unknown>).key) === key) {
      return row as Record<string, unknown>
    }
  }
  return null
}

function statusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    pass: '通过',
    fail: '失败',
    review: '待复核',
    missing: '缺失',
    not_required: '不需要',
    unknown: '未知',
  }
  return labels[optionalText(value)] || optionalText(value) || '未知'
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
