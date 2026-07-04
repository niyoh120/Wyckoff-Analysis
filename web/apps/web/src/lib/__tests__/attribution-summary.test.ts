import { describe, expect, it } from 'vitest'
import { attributionOperatorSummary } from '@wyckoff/shared'

describe('attributionOperatorSummary', () => {
  it('uses backend operator summary when present', () => {
    expect(attributionOperatorSummary({
      operations: {
        operator_summary: '下一步=人工复核；作用范围=tail_buy_and_funnel_shadow；Shadow=2026-07-03 RISK_ON 新增2 移除1',
      },
      execution: {
        scope: 'tail_buy_and_funnel_shadow',
        signal_action_count: 1,
      },
      actions: [{ target: 'lps' }],
    })).toBe('下一步=人工复核；作用范围=尾盘+漏斗shadow；Shadow=2026-07-03 RISK_ON 新增2 移除1')
  })

  it('synthesizes a summary for older attribution reports', () => {
    expect(attributionOperatorSummary({
      execution: {
        next_action_summary: 'shadow 新增组已跑赢移除组。',
        scope: 'tail_buy_and_funnel_shadow',
        next_action: 'manual_review_dynamic_on',
      },
      latest: {
        trade_date: '2026-07-03',
        regime: 'RISK_ON',
      },
      selection: {
        diff_added_count: 2,
        diff_removed_count: 1,
      },
      actions: [{ target: 'lps', weight_multiplier: 0.5 }],
    })).toBe(
      '下一步=shadow 新增组已跑赢移除组。；作用范围=尾盘+漏斗shadow；正式dynamic=allowed；Shadow=2026-07-03 RISK_ON 新增2 移除1；调权=1项',
    )
  })
})
