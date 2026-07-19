import type { FundamentalMetric, ValueSnapshot } from './agent-market'

export type ValueTone = 'good' | 'bad' | 'neutral'
export type ValueDataQualityLevel = 'ready' | 'limited' | 'stale' | 'unavailable'

export const VALUE_RULESET_VERSION = 'value-rules-v2'
const STALE_REPORT_AGE_DAYS = 550

const CORE_VALUE_FIELDS = [
  'roe',
  'net_income_yoy',
  'revenue_yoy',
  'gross_margin',
  'debt_to_asset_ratio',
  'operating_cash_to_revenue',
] as const

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
  severe: boolean
  strengths: ValueSignal[]
  risks: ValueSignal[]
}

export interface ValueRule {
  code: string
  label: string
  tone: Exclude<ValueTone, 'neutral'>
  points: number
  explanation: string
  threshold?: number
  value: (metrics: FundamentalMetric) => number | undefined
  matches: (metrics: FundamentalMetric) => boolean
}

const defined = (value: number | undefined): value is number => Number.isFinite(value)

export const VALUE_RULES: readonly ValueRule[] = [
  { code: 'ROE_STRONG', label: 'ROE 较强', tone: 'good', points: 2, explanation: '净资产收益率(ROE)维持在 10% 以上，盈利能力较强。', threshold: 10, value: m => m.roe, matches: m => defined(m.roe) && m.roe >= 10 },
  { code: 'ROE_LOSS', label: 'ROE 为负', tone: 'bad', points: -2, explanation: '净资产收益率(ROE)为负，公司处于亏损状态。', threshold: 0, value: m => m.roe, matches: m => defined(m.roe) && m.roe < 0 },
  { code: 'NET_INCOME_GROWTH', label: '净利润正增长', tone: 'good', points: 1, explanation: '净利润同比增长为正，盈利规模增长。', threshold: 0, value: m => m.net_income_yoy, matches: m => defined(m.net_income_yoy) && m.net_income_yoy > 0 },
  { code: 'NET_INCOME_DECLINE', label: '净利润下滑', tone: 'bad', points: -1, explanation: '净利润同比下滑，盈利空间受到挤压。', threshold: 0, value: m => m.net_income_yoy, matches: m => defined(m.net_income_yoy) && m.net_income_yoy < 0 },
  { code: 'REVENUE_GROWTH', label: '营收正增长', tone: 'good', points: 1, explanation: '营业收入同比增长为正，主营业务规模持续扩张。', threshold: 0, value: m => m.revenue_yoy, matches: m => defined(m.revenue_yoy) && m.revenue_yoy > 0 },
  { code: 'REVENUE_DECLINE', label: '营收下滑', tone: 'bad', points: -1, explanation: '营业收入同比下滑，面临需求萎缩或竞争加剧。', threshold: 0, value: m => m.revenue_yoy, matches: m => defined(m.revenue_yoy) && m.revenue_yoy < 0 },
  { code: 'GROSS_MARGIN_HIGH', label: '毛利率较高', tone: 'good', points: 1, explanation: '毛利率处于 30% 以上的较高水平，产品溢价或定价权较强。', threshold: 30, value: m => m.gross_margin, matches: m => defined(m.gross_margin) && m.gross_margin >= 30 },
  { code: 'GROSS_MARGIN_LOW', label: '毛利率偏低', tone: 'bad', points: -1, explanation: '毛利率低于 15%，产品定价权弱或成本管控压力偏大。', threshold: 15, value: m => m.gross_margin, matches: m => defined(m.gross_margin) && m.gross_margin < 15 },
  { code: 'LOW_DEBT', label: '杠杆较低', tone: 'good', points: 1, explanation: '资产负债率低于 55%，整体财务杠杆较为适度。', threshold: 55, value: m => m.debt_to_asset_ratio, matches: m => defined(m.debt_to_asset_ratio) && m.debt_to_asset_ratio <= 55 },
  { code: 'HIGH_LEVERAGE', label: '资产负债率偏高', tone: 'bad', points: -2, explanation: '资产负债率高于 70%，杠杆风险偏高，需要结合行业属性评估偿债压力。', threshold: 70, value: m => m.debt_to_asset_ratio, matches: m => defined(m.debt_to_asset_ratio) && m.debt_to_asset_ratio >= 70 },
  { code: 'CASH_FLOW_MATCH', label: '现金流匹配收入', tone: 'good', points: 1, explanation: '经营现金流/营业收入比值达到 5% 以上，销售回款与现金转化健康。', threshold: 5, value: m => m.operating_cash_to_revenue, matches: m => defined(m.operating_cash_to_revenue) && m.operating_cash_to_revenue >= 5 },
  { code: 'CASH_FLOW_WEAK', label: '经营现金流偏弱', tone: 'bad', points: -1, explanation: '经营性现金流净额为负，日常经营入不敷出。', threshold: 0, value: m => m.operating_cash_to_revenue, matches: m => defined(m.operating_cash_to_revenue) && m.operating_cash_to_revenue < 0 },
  { code: 'PROFIT_CASH_FLOW_DIVERGENCE', label: '净利润增长但经营现金流负', tone: 'bad', points: 0, explanation: '净利润同比正增长，但经营现金流为负，利润与现金回款不匹配。', threshold: 0, value: m => m.net_income_yoy, matches: m => defined(m.net_income_yoy) && defined(m.operating_cash_to_revenue) && m.net_income_yoy > 0 && m.operating_cash_to_revenue < 0 },
  { code: 'WEAK_CASH_EARNINGS', label: '利润现金含量偏弱', tone: 'bad', points: 0, explanation: 'ROE 为正，但经营现金净流出，利润未有效转化为现金。', threshold: 0, value: m => m.operating_cash_to_revenue, matches: m => defined(m.roe) && defined(m.operating_cash_to_revenue) && m.roe > 0 && m.operating_cash_to_revenue < 0 },
]

export interface ValueDataQuality {
  level: ValueDataQualityLevel
  asOf?: string
  ageDays?: number
  coreFieldCount: number
  missingCoreFields: string[]
}

export interface ValueTraceMeta {
  rulesetVersion: string
  dataQuality: ValueDataQualityLevel
  ruleCodes: string[]
}

export function valueDataQuality(snapshot: ValueSnapshot, now = new Date()): ValueDataQuality {
  const metrics = snapshot.metrics
  if (!metrics) return { level: 'unavailable', coreFieldCount: 0, missingCoreFields: [...CORE_VALUE_FIELDS] }

  const missingCoreFields = CORE_VALUE_FIELDS.filter(field => !defined(metrics[field]))
  const asOf = metrics.period_end || metrics.announce_date
  const ageDays = ageInDays(asOf, now)
  const level: ValueDataQualityLevel = ageDays !== undefined && ageDays > STALE_REPORT_AGE_DAYS
    ? 'stale'
    : missingCoreFields.length >= 3 || !asOf
      ? 'limited'
      : 'ready'
  return { level, asOf, ageDays, coreFieldCount: CORE_VALUE_FIELDS.length - missingCoreFields.length, missingCoreFields }
}

function ageInDays(value: string | undefined, now: Date): number | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined
  const asOf = Date.parse(`${value}T00:00:00Z`)
  if (!Number.isFinite(asOf)) return undefined
  return Math.max(0, Math.floor((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - asOf) / 86_400_000))
}

export function valueDataQualityLabel(quality: ValueDataQuality): string {
  if (quality.level === 'ready') return '数据完整'
  if (quality.level === 'limited') return '字段不足'
  if (quality.level === 'stale') return '数据较旧'
  return '无数据'
}

export function valueDataQualityPrompt(snapshot: ValueSnapshot): string {
  const quality = valueDataQuality(snapshot)
  const age = quality.ageDays === undefined ? '' : `，距报告期 ${quality.ageDays} 天`
  const fields = `${quality.coreFieldCount}/${CORE_VALUE_FIELDS.length} 核心字段`
  if (quality.level === 'ready') return `数据质量：${valueDataQualityLabel(quality)}（${fields}${age}）；规则版本：${VALUE_RULESET_VERSION}。`
  return `数据质量：${valueDataQualityLabel(quality)}（${fields}${age}）；规则版本：${VALUE_RULESET_VERSION}。该价值面信息仅作风险校准，不得据此给出强确定性结论。`
}

export function evaluateValueRules(metrics: FundamentalMetric | null): ValueSignal[] {
  if (!metrics) return []
  return VALUE_RULES.filter(rule => rule.matches(metrics)).map(rule => ({
    code: rule.code,
    label: rule.label,
    tone: rule.tone,
    value: rule.value(metrics),
    threshold: rule.threshold,
    explanation: rule.explanation,
  }))
}

/** Mirrors core/fundamental_overlay.py::_severe_risk so both surfaces veto the same distress pattern. */
export function isSevereRisk(metrics: FundamentalMetric): boolean {
  const distress = [
    defined(metrics.roe) && metrics.roe < 0,
    defined(metrics.net_income_yoy) && metrics.net_income_yoy < -30,
    defined(metrics.revenue_yoy) && metrics.revenue_yoy < -20,
    defined(metrics.operating_cash_to_revenue) && metrics.operating_cash_to_revenue < 0,
  ].filter(Boolean).length
  const leveragedLoss = defined(metrics.debt_to_asset_ratio) && metrics.debt_to_asset_ratio >= 85
    && defined(metrics.roe) && metrics.roe < 0
  return distress >= 3 || leveragedLoss
}

export function buildValueScore(metrics: FundamentalMetric | null): ValueScore {
  if (!metrics) return { label: '暂无', tone: 'neutral', score: -99, severe: false, strengths: [], risks: [] }
  const matched = evaluateValueRules(metrics)
  const score = VALUE_RULES.filter(rule => rule.matches(metrics)).reduce((total, rule) => total + rule.points, 0)
  const strengths = matched.filter(signal => signal.tone === 'good')
  const risks = matched.filter(signal => signal.tone === 'bad')
  const severe = isSevereRisk(metrics)

  const tone: ValueTone = severe || score < 0 ? 'bad' : score >= 3 ? 'good' : 'neutral'
  const label = severe ? '高危' : tone === 'good' ? '稳健' : tone === 'bad' ? '承压' : '中性'
  return { label, tone, score, severe, strengths, risks }
}

export function valueTraceMeta(snapshot: ValueSnapshot): ValueTraceMeta {
  return {
    rulesetVersion: VALUE_RULESET_VERSION,
    dataQuality: valueDataQuality(snapshot).level,
    ruleCodes: evaluateValueRules(snapshot.metrics).flatMap(signal => signal.code ? [signal.code] : []),
  }
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
    valueDataQualityPrompt(snapshot),
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
