import type { FundamentalMetric, ValueScore, ValueSnapshot, ValueTone } from '@wyckoff/shared'
import { buildValueScore as buildSharedValueScore, formatPromptPercent, sourceLabel, valueDataQuality, VALUE_RULESET_VERSION } from '@wyckoff/shared'

import type { TranslationKey } from './preferences'

export type ValueView = 'quality' | 'risk'

export type Translate = (key: TranslationKey, vars?: Record<string, string | number | null | undefined>) => string

const VALUE_SIGNAL_TRANSLATION_KEYS: Record<string, TranslationKey> = {
  ROE_STRONG: 'analysis.valueSignalRoeStrong',
  ROE_LOSS: 'analysis.valueRiskRoeLoss',
  NET_INCOME_GROWTH: 'analysis.valueSignalProfitGrowth',
  NET_INCOME_DECLINE: 'analysis.valueRiskProfitDrop',
  REVENUE_GROWTH: 'analysis.valueSignalRevenueGrowth',
  REVENUE_DECLINE: 'analysis.valueRiskRevenueDrop',
  GROSS_MARGIN_HIGH: 'analysis.valueSignalGrossMargin',
  GROSS_MARGIN_LOW: 'analysis.valueRiskGrossMarginLow',
  LOW_DEBT: 'analysis.valueSignalLowDebt',
  HIGH_LEVERAGE: 'analysis.valueRiskHighDebt',
  CASH_FLOW_MATCH: 'analysis.valueSignalCashHealthy',
  CASH_FLOW_WEAK: 'analysis.valueRiskCashWeak',
  PROFIT_CASH_FLOW_DIVERGENCE: 'analysis.valueRiskProfitCashFlowDivergence',
  WEAK_CASH_EARNINGS: 'analysis.valueRiskWeakCashEarnings',
}

export function buildValueScore(metrics: FundamentalMetric | null, t?: Translate): ValueScore {
  const tr = (key: TranslationKey, fallback: string) => t ? t(key) : fallback
  const score = buildSharedValueScore(metrics)
  const tone: ValueTone = score.tone
  const label = tone === 'good'
    ? tr('analysis.valueScoreStrong', '稳健')
    : tone === 'bad'
      ? tr('analysis.valueScoreWeak', '承压')
      : tr('analysis.valueScoreNeutral', '中性')
  return {
    ...score,
    label: metrics ? label : tr('analysis.valueNoSource', '暂无'),
    strengths: score.strengths.map(signal => ({ ...signal, label: tr(VALUE_SIGNAL_TRANSLATION_KEYS[signal.code || ''] || 'analysis.valueNoSignals', signal.label) })),
    risks: score.risks.map(signal => ({ ...signal, label: tr(VALUE_SIGNAL_TRANSLATION_KEYS[signal.code || ''] || 'analysis.valueNoSignals', signal.label) })),
  }
}

export function valueDataQualityText(snapshot: ValueSnapshot, t: Translate): string {
  const quality = valueDataQuality(snapshot)
  if (quality.level === 'ready') return t('analysis.valueDataReady')
  if (quality.level === 'limited') return t('analysis.valueDataLimited')
  if (quality.level === 'stale') return t('analysis.valueDataStale')
  return t('analysis.valueNoSource')
}

export function valueDataQualityTitle(snapshot: ValueSnapshot, t: Translate): string {
  const quality = valueDataQuality(snapshot)
  const fields = `${quality.coreFieldCount}/6`
  const age = quality.ageDays === undefined ? '' : ` · ${quality.ageDays}${t('analysis.valueDataAgeDays')}`
  return `${sourceLabel(snapshot)} · ${quality.asOf || t('analysis.valueNoSource')} · ${valueDataQualityText(snapshot, t)} · ${fields}${age}`
}

export function calculateInputSnapshotHash(
  symbol: string,
  klineData: { date: string }[],
  valueSnapshot: ValueSnapshot,
  valueRulesetVersion = VALUE_RULESET_VERSION,
): string {
  const start = klineData[0]?.date || ''
  const end = klineData[klineData.length - 1]?.date || ''
  const len = klineData.length
  const metricsJson = valueSnapshot.metrics ? JSON.stringify(valueSnapshot.metrics) : 'none'
  const source = valueSnapshot.source
  const raw = `${symbol}:${start}:${end}:${len}:${source}:${metricsJson}:${valueRulesetVersion}`

  let hash = 2166136261
  for (let i = 0; i < raw.length; i++) {
    hash = Math.imul(hash ^ raw.charCodeAt(i), 16777619)
  }
  return (hash >>> 0).toString(16)
}


export function valueUnavailableText(reason: ValueSnapshot['reason'], t: Translate): string {
  if (reason === 'unsupported-market') return t('analysis.valueUnsupported')
  if (reason === 'missing-source') return t('analysis.valueMissingSource')
  return t('analysis.valueUnavailable')
}

export function formatValuePercent(value: number | undefined): string {
  if (!Number.isFinite(value)) return '--'
  const numeric = value as number
  const digits = Math.abs(numeric) >= 100 ? 1 : 2
  return `${numeric.toFixed(digits)}%`
}

export function numberTone(value: number | undefined, goodAt: number, badBelow: number): ValueTone {
  if (!Number.isFinite(value)) return 'neutral'
  const numeric = value as number
  if (numeric >= goodAt) return 'good'
  if (numeric < badBelow) return 'bad'
  return 'neutral'
}

export function reverseNumberTone(value: number | undefined, goodAtOrBelow: number, badAtOrAbove: number): ValueTone {
  if (!Number.isFinite(value)) return 'neutral'
  const numeric = value as number
  if (numeric <= goodAtOrBelow) return 'good'
  if (numeric >= badAtOrAbove) return 'bad'
  return 'neutral'
}

export function metricToneClass(tone: ValueTone): string {
  if (tone === 'good') return 'text-down'
  if (tone === 'bad') return 'text-up'
  return 'text-foreground'
}

export function valueScoreClass(tone: ValueTone): string {
  if (tone === 'good') return 'bg-down/10 text-down'
  if (tone === 'bad') return 'bg-up/10 text-up'
  return 'bg-muted text-muted-foreground'
}

export function signalClass(tone: ValueTone): string {
  if (tone === 'good') return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
  if (tone === 'bad') return 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'
  return 'border-border text-muted-foreground'
}

export function buildValueDigest(snapshot: ValueSnapshot): string {
  const metrics = snapshot.metrics
  if (!metrics) return 'value: 暂无可用价值面指标'
  const quality = valueDataQuality(snapshot)
  return [
    `valueSource=${sourceLabel(snapshot)} period=${metrics.period_end || metrics.announce_date || 'unknown'} quality=${quality.level} coreFields=${quality.coreFieldCount}/6`,
    `valueMetrics roe=${formatPromptPercent(metrics.roe)} netProfitYoY=${formatPromptPercent(metrics.net_income_yoy)} revenueYoY=${formatPromptPercent(metrics.revenue_yoy)} grossMargin=${formatPromptPercent(metrics.gross_margin)} netMargin=${formatPromptPercent(metrics.net_margin)} debtRatio=${formatPromptPercent(metrics.debt_to_asset_ratio)} cashToRevenue=${formatPromptPercent(metrics.operating_cash_to_revenue)}`,
  ].join('\n')
}
