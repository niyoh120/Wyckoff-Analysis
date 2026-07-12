import { describe, expect, it } from 'vitest'
import type { FundamentalMetric, ValueSnapshot } from '@wyckoff/shared'
import { buildValuePrompt, sourceLabel } from '@wyckoff/shared'
import type { TranslationKey } from '../preferences'
import type { Translate } from '../value-analysis'
import {
  buildValueDigest,
  buildValueScore,
  calculateInputSnapshotHash,
  formatValuePercent,
  numberTone,
  reverseNumberTone,
  valueUnavailableText,
} from '../value-analysis'

const translations: Partial<Record<TranslationKey, string>> = {
  'analysis.valueNoSource': '暂无来源',
  'analysis.valueScoreStrong': '稳健',
  'analysis.valueScoreNeutral': '中性',
  'analysis.valueScoreWeak': '承压',
  'analysis.valueSignalRoeStrong': 'ROE 维持在较好水平',
  'analysis.valueSignalProfitGrowth': '净利润保持正增长',
  'analysis.valueSignalRevenueGrowth': '营收保持正增长',
  'analysis.valueSignalGrossMargin': '毛利率较高',
  'analysis.valueSignalLowDebt': '杠杆压力较低',
  'analysis.valueSignalCashHealthy': '经营现金流匹配收入',
  'analysis.valueRiskRoeLoss': 'ROE 为负，盈利能力承压',
  'analysis.valueRiskProfitDrop': '净利润同比下滑',
  'analysis.valueRiskRevenueDrop': '营收同比下滑',
  'analysis.valueRiskGrossMarginLow': '毛利率偏低',
  'analysis.valueRiskHighDebt': '资产负债率偏高',
  'analysis.valueRiskCashWeak': '经营现金流偏弱',
  'analysis.valueRiskProfitCashFlowDivergence': '净利润增长但经营现金流负',
  'analysis.valueRiskWeakCashEarnings': '利润现金含量偏弱',
  'analysis.valueUnsupported': '价值面快照先支持 A 股。',
  'analysis.valueMissingSource': '需要 TickFlow 或 Tushare 数据源后展示价值面。',
  'analysis.valueUnavailable': '暂无可用基本面数据。',
}

const t: Translate = (key) => translations[key] ?? key

function snapshot(metrics: FundamentalMetric | null, source: ValueSnapshot['source'] = 'tickflow'): ValueSnapshot {
  return { symbol: '600519.SH', source, metrics, reason: metrics ? undefined : 'not-found' }
}

describe('value analysis helpers', () => {
  it('scores high-quality metrics as solid', () => {
    const score = buildValueScore({
      roe: 18,
      net_income_yoy: 12,
      revenue_yoy: 8,
      gross_margin: 92,
      debt_to_asset_ratio: 22,
      operating_cash_to_revenue: 18,
    }, t)

    expect(score.label).toBe('稳健')
    expect(score.tone).toBe('good')
    expect(score.score).toBeGreaterThanOrEqual(3)
    expect(score.strengths.map((item) => item.label)).toContain('ROE 维持在较好水平')
    expect(score.risks).toHaveLength(0)
  })

  it('scores weak metrics as pressured', () => {
    const score = buildValueScore({
      roe: -3,
      net_income_yoy: -28,
      revenue_yoy: -4,
      gross_margin: 12,
      debt_to_asset_ratio: 76,
      operating_cash_to_revenue: -2,
    }, t)

    expect(score.label).toBe('承压')
    expect(score.tone).toBe('bad')
    expect(score.score).toBeLessThan(0)
    expect(score.risks.map((item) => item.label)).toEqual(expect.arrayContaining(['净利润同比下滑', '资产负债率偏高']))
  })

  it('formats sources and unavailable reasons', () => {
    expect(sourceLabel(snapshot(null, 'tickflow'))).toBe('TickFlow')
    expect(sourceLabel(snapshot(null, 'tushare'))).toBe('Tushare')
    expect(sourceLabel(snapshot(null, 'none'))).toBe('--')
    expect(valueUnavailableText('missing-source', t)).toContain('TickFlow')
    expect(valueUnavailableText('unsupported-market', t)).toContain('A 股')
  })

  it('formats metric tones and percentages', () => {
    expect(formatValuePercent(105.234)).toBe('105.2%')
    expect(formatValuePercent(9.876)).toBe('9.88%')
    expect(formatValuePercent(undefined)).toBe('--')
    expect(numberTone(12, 10, 0)).toBe('good')
    expect(numberTone(-1, 10, 0)).toBe('bad')
    expect(reverseNumberTone(45, 55, 70)).toBe('good')
    expect(reverseNumberTone(72, 55, 70)).toBe('bad')
  })

  it('builds compact prompts for LLM inputs', () => {
    const metrics: FundamentalMetric = {
      period_end: '2026-03-31',
      roe: 18.2,
      net_income_yoy: 11.8,
      revenue_yoy: 6.5,
      gross_margin: 91.6,
      net_margin: 48.3,
      debt_to_asset_ratio: 21.4,
      operating_cash_to_revenue: 16.2,
      eps_basic: 12.34,
      bps: 98.76,
    }

    const prompt = buildValuePrompt(snapshot(metrics))
    const digest = buildValueDigest(snapshot(metrics))

    expect(prompt).toContain('价值面摘要（来源：TickFlow，报告期：2026-03-31）')
    expect(prompt).toContain('ROE=18.20%')
    expect(prompt).toContain('EPS=12.34')
    expect(digest).toContain('valueMetrics roe=18.20%')
    expect(digest).toContain('cashToRevenue=16.20%')
  })

  it('detects compound risk rules and rule codes', () => {
    const score = buildValueScore({
      roe: 12,
      net_income_yoy: 8,
      revenue_yoy: 5,
      gross_margin: 40,
      debt_to_asset_ratio: 40,
      operating_cash_to_revenue: -5,
    }, t)

    const riskCodes = score.risks.map(r => r.code)
    expect(riskCodes).toContain('PROFIT_CASH_FLOW_DIVERGENCE')
    expect(riskCodes).toContain('WEAK_CASH_EARNINGS')
    expect(score.risks.find(r => r.code === 'PROFIT_CASH_FLOW_DIVERGENCE')?.label).toBe('净利润增长但经营现金流负')
    expect(score.strengths[0]?.code).toBe('ROE_STRONG')
    expect(score.score).toBe(5)
  })

  it('calculates deterministic input snapshot hash', () => {
    const kline = [{ date: '2026-01-01', open: 1, high: 2, low: 1, close: 1.5, volume: 100 }]
    const snap = snapshot({ roe: 15, period_end: '2026-03-31' })
    const h1 = calculateInputSnapshotHash('600519.SH', kline, snap)
    const h2 = calculateInputSnapshotHash('600519.SH', kline, snap)
    const h3 = calculateInputSnapshotHash('000001.SZ', kline, snap)

    expect(h1).toBe(h2)
    expect(h1).not.toBe(h3)
    expect(typeof h1).toBe('string')
  })
})
