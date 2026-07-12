import type { FundamentalMetric, ValueSnapshot } from './agent-market'

export type ValueTone = 'good' | 'bad' | 'neutral'

export interface ValueSignal {
  code?: string
  label: string
  tone: ValueTone
  value?: number
  threshold?: number
  explanation?: string
}

export interface ValueScore {
  label: string
  tone: ValueTone
  score: number
  strengths: ValueSignal[]
  risks: ValueSignal[]
}

function applyBaseRules(
  metrics: FundamentalMetric,
  addStrength: (code: string, condition: boolean, label: string, explanation: string, value?: number, threshold?: number, points?: number) => void,
  addRisk: (code: string, condition: boolean, label: string, explanation: string, value?: number, threshold?: number, points?: number) => void
) {
  // 1. ROE Rules
  const roe = metrics.roe
  if (roe !== undefined && roe !== null) {
    addStrength('ROE_STRONG', roe >= 10, 'ROE 较强', '净资产收益率(ROE)维持在 10% 以上，盈利能力较强。', roe, 10, 2)
    addRisk('ROE_LOSS', roe < 0, 'ROE 为负', '净资产收益率(ROE)为负，公司处于亏损状态。', roe, 0, 2)
  }

  // 2. Net Income YoY
  const netIncomeYoY = metrics.net_income_yoy
  if (netIncomeYoY !== undefined && netIncomeYoY !== null) {
    addStrength('NET_INCOME_GROWTH', netIncomeYoY > 0, '净利润正增长', '净利润同比增长为正，盈利规模增长。', netIncomeYoY, 0, 1)
    addRisk('NET_INCOME_DECLINE', netIncomeYoY < 0, '净利润下滑', '净利润同比下滑，盈利空间受到积压。', netIncomeYoY, 0, 1)
  }

  // 3. Revenue YoY
  const revenueYoY = metrics.revenue_yoy
  if (revenueYoY !== undefined && revenueYoY !== null) {
    addStrength('REVENUE_GROWTH', revenueYoY > 0, '营收正增长', '营业收入同比增长为正，主营业务规模持续扩张。', revenueYoY, 0, 1)
    addRisk('REVENUE_DECLINE', revenueYoY < 0, '营收下滑', '营业收入同比下滑，面临市场需求萎缩或竞争加剧。', revenueYoY, 0, 1)
  }

  // 4. Gross Margin
  const grossMargin = metrics.gross_margin
  if (grossMargin !== undefined && grossMargin !== null) {
    addStrength('GROSS_MARGIN_HIGH', grossMargin >= 30, '毛利率较高', '毛利率处于 30% 以上的较高水平，产品溢价或定价权较强。', grossMargin, 30, 1)
    addRisk('GROSS_MARGIN_LOW', grossMargin < 15, '毛利率偏低', '毛利率低于 15%，产品定价权弱或成本管控压力偏大。', grossMargin, 15, 1)
  }

  // 5. Debt to Asset Ratio (Leverage)
  const debtRatio = metrics.debt_to_asset_ratio
  if (debtRatio !== undefined && debtRatio !== null) {
    addStrength('LOW_DEBT', debtRatio <= 55, '杠杆较低', '资产负债率低于 55%，整体财务杠杆较为适度。', debtRatio, 55, 1)
    addRisk('HIGH_LEVERAGE', debtRatio >= 70, '资产负债率偏高', '资产负债率高于 70%，杠杆风险偏高，需要结合行业属性评估偿债压力。', debtRatio, 70, 2)
  }

  // 6. Cash Flow
  const cashToRev = metrics.operating_cash_to_revenue
  if (cashToRev !== undefined && cashToRev !== null) {
    addStrength('CASH_FLOW_MATCH', cashToRev >= 5, '现金流匹配收入', '经营现金流/营业收入比值达到 5% 以上，销售回款与现金转化健康。', cashToRev, 5, 1)
    addRisk('CASH_FLOW_WEAK', cashToRev < 0, '经营现金流偏弱', '经营性现金流净额为负，日常经营入不敷出。', cashToRev, 0, 1)
  }
}

function applyCompoundRules(
  metrics: FundamentalMetric,
  addRisk: (code: string, condition: boolean, label: string, explanation: string, value?: number, threshold?: number, points?: number) => void
) {
  const roe = metrics.roe
  const netIncomeYoY = metrics.net_income_yoy
  const cashToRev = metrics.operating_cash_to_revenue

  if (netIncomeYoY !== undefined && netIncomeYoY !== null && cashToRev !== undefined && cashToRev !== null) {
    addRisk(
      'PROFIT_CASH_FLOW_DIVERGENCE',
      netIncomeYoY > 0 && cashToRev < 0,
      '净利润增长但经营现金流负',
      '净利润同比正增长，但经营现金流为负，量价/回款不匹配，需防范虚增利润与账账不合。',
      netIncomeYoY,
      0,
      0
    )
  }

  if (roe !== undefined && roe !== null && roe > 0 && cashToRev !== undefined && cashToRev !== null) {
    addRisk(
      'WEAK_CASH_EARNINGS',
      cashToRev < 0,
      '利润现金含量偏弱',
      '净资产收益率为正，但日常经营现金净流出。利润未有效转化为账面现金，回款节奏较差。',
      cashToRev,
      0,
      0
    )
  }
}

export function buildValueScore(metrics: FundamentalMetric | null): ValueScore {
  if (!metrics) return { label: '暂无', tone: 'neutral', score: -99, strengths: [], risks: [] }

  let score = 0
  const strengths: ValueSignal[] = []
  const risks: ValueSignal[] = []

  const addStrength = (code: string, condition: boolean, label: string, explanation: string, value?: number, threshold?: number, points = 1) => {
    if (!condition) return
    strengths.push({ code, label, tone: 'good', value, threshold, explanation })
    score += points
  }

  const addRisk = (code: string, condition: boolean, label: string, explanation: string, value?: number, threshold?: number, points = 1) => {
    if (!condition) return
    risks.push({ code, label, tone: 'bad', value, threshold, explanation })
    score -= points
  }

  applyBaseRules(metrics, addStrength, addRisk)
  applyCompoundRules(metrics, addRisk)

  const tone: ValueTone = score >= 3 ? 'good' : score < 0 ? 'bad' : 'neutral'
  const label = tone === 'good' ? '稳健' : tone === 'bad' ? '承压' : '中性'
  return { label, tone, score, strengths, risks }
}

export function sourceLabel(snapshot: ValueSnapshot): string {
  if (snapshot.source === 'tickflow') return 'TickFlow'
  if (snapshot.source === 'tushare') return 'Tushare'
  return '--'
}

export function buildValuePrompt(snapshot: ValueSnapshot): string {
  const metrics = snapshot.metrics
  if (!metrics) return '价值面摘要：暂无可用基本面指标，本次只基于量价结构分析。'
  return [
    `价值面摘要（来源：${sourceLabel(snapshot)}${metrics.period_end ? `，报告期：${metrics.period_end}` : ''}）：`,
    `ROE=${formatPromptPercent(metrics.roe)}，净利润同比=${formatPromptPercent(metrics.net_income_yoy)}，营收同比=${formatPromptPercent(metrics.revenue_yoy)}`,
    `毛利率=${formatPromptPercent(metrics.gross_margin)}，净利率=${formatPromptPercent(metrics.net_margin)}，资产负债率=${formatPromptPercent(metrics.debt_to_asset_ratio)}`,
    `经营现金流/营收=${formatPromptPercent(metrics.operating_cash_to_revenue)}，EPS=${formatPromptNumber(metrics.eps_basic)}，每股净资产=${formatPromptNumber(metrics.bps)}`,
  ].join('\n')
}

export function formatPromptPercent(value: number | undefined): string {
  return Number.isFinite(value) ? `${(value as number).toFixed(2)}%` : '暂无'
}

export function formatPromptNumber(value: number | undefined): string {
  return Number.isFinite(value) ? (value as number).toFixed(2) : '暂无'
}
