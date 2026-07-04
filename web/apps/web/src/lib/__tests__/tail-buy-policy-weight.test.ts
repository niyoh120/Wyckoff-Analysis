import { describe, expect, it } from 'vitest'
import { formatTailBuyPolicyWeightText, tailBuyPolicyWeightMultiplier } from '@wyckoff/shared'

describe('tail-buy policy weight formatting', () => {
  it('formats persisted policy metadata consistently for web and reading room', () => {
    const row = {
      signal_type: 'lps',
      features_json: JSON.stringify({
        policy_weight_signal: 'lps',
        policy_weight_multiplier: 0.5,
        policy_weight_old_score: 80,
        policy_weight_new_score: 40,
        policy_weight_source: '远端',
        policy_weight_report_date: '2026-07-04',
        policy_weight_horizon: '5',
        policy_weight_execution_policy: 'shadow',
        policy_weight_execution_scope: 'tail_buy_and_funnel_shadow',
        policy_weight_next_action: 'manual_review_dynamic_on',
        policy_weight_tail_buy_weights_active: true,
        policy_weight_funnel_shadow_weights_active: true,
        policy_weight_funnel_formal_weights_active: false,
      }),
    }

    expect(formatTailBuyPolicyWeightText(row, { prefix: ' | 归因调权 ' })).toBe(
      ' | 归因调权 lps x0.50 80.0→40.0（远端, report=2026-07-04, h=5, mode=shadow, next=进入人工晋级评审（非正式生效）, active=尾盘+漏斗shadow）',
    )
    expect(tailBuyPolicyWeightMultiplier(row)).toBe(0.5)
  })

  it('uses caller-specific empty text when there is no policy weight', () => {
    expect(formatTailBuyPolicyWeightText({ signal_type: 'sos', features_json: {} }, { emptyText: '-' })).toBe('-')
  })
})
