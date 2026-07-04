import { describe, expect, it } from 'vitest'
import { formatPolicyWeightMetaText } from '@wyckoff/shared'

describe('formatPolicyWeightMetaText', () => {
  it('formats snapshot policy metadata with active scope', () => {
    expect(formatPolicyWeightMetaText({
      source: '远端',
      report_date: '2026-07-04',
      horizon: '5',
      execution_policy: 'on',
      execution_scope: 'tail_buy_and_funnel',
      tail_buy_weights_active: true,
      funnel_shadow_weights_active: true,
      funnel_formal_weights_active: true,
    })).toBe('（远端, report=2026-07-04, h=5, mode=on, active=尾盘+正式漏斗）')
  })

  it('formats persisted tail-buy features with prefixed keys', () => {
    expect(formatPolicyWeightMetaText({
      policy_weight_source: '远端',
      policy_weight_report_date: '2026-07-04',
      policy_weight_horizon: '5',
      policy_weight_age_days: 0,
      policy_weight_execution_policy: 'shadow',
      policy_weight_execution_scope: 'tail_buy_and_funnel_shadow',
      policy_weight_next_action: 'manual_review_dynamic_on',
      policy_weight_formal_dynamic_allowed: false,
      policy_weight_formal_dynamic_block_reason: 'shadow_only',
      policy_weight_tail_buy_weights_active: true,
      policy_weight_funnel_shadow_weights_active: true,
      policy_weight_funnel_formal_weights_active: false,
    })).toBe(
      '（远端, report=2026-07-04, h=5, age=0d, mode=shadow, next=进入人工晋级评审（非正式生效）, active=尾盘+漏斗shadow, formal_block=shadow_only）',
    )
  })

  it('derives active scope from legacy execution scope without echoing raw scope', () => {
    expect(formatPolicyWeightMetaText({
      source: '远端',
      execution_policy: 'shadow',
      execution_scope: 'tail_buy_and_funnel_shadow',
    })).toBe('（远端, mode=shadow, active=尾盘+漏斗shadow）')
  })
})
