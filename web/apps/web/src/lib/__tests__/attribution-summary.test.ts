import { describe, expect, it } from 'vitest'
import { attributionExecutionImpactText, attributionOperatorSummary } from '@wyckoff/shared'

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
      '下一步=shadow 新增组已跑赢移除组。；作用范围=尾盘+漏斗shadow；正式dynamic=blocked(manual_review_required)；Shadow=2026-07-03 RISK_ON 新增2 移除1；调权=1项',
    )
  })
})

describe('attributionExecutionImpactText', () => {
  it('uses backend execution summary when present', () => {
    expect(attributionExecutionImpactText({
      execution: {
        summary: '后端已解释生效范围。',
        signal_action_count: 1,
      },
      targetText: 'lps',
    })).toBe('后端已解释生效范围。')
  })

  it('states shadow funnel weights do not affect formal recommendations', () => {
    expect(attributionExecutionImpactText({
      execution: {
        signal_action_count: 1,
        tail_buy_weights_active: true,
        funnel_shadow_weights_active: true,
        funnel_formal_weights_active: false,
      },
      targetText: 'lps / evr',
    })).toBe(
      '归因调权已沉淀为信号级权重输入，覆盖 lps / evr。尾盘策略会读取这些权重；漏斗侧仅进入 shadow 对照，不影响正式推荐。',
    )
  })

  it('states formal funnel weights only when formal scope is active', () => {
    expect(attributionExecutionImpactText({
      execution: {
        signal_action_count: 1,
        scope: 'tail_buy_and_funnel',
      },
      targetText: 'sos',
    })).toBe(
      '归因调权已沉淀为信号级权重输入，覆盖 sos。尾盘策略会读取这些权重；正式漏斗候选排序会读取这些权重。',
    )
  })
})
