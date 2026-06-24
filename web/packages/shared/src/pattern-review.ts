export const PATTERN_REVIEW_EMPTY_MESSAGE = '暂无形态复盘记录'
export const PATTERN_REVIEW_SCOPE_NOTE = 'AI推荐才进入交易研判，观察/信号复盘不等于买入。'

export interface PatternReviewRow {
  code: string | number
  name: string
  recommend_date: string | number
  recommend_count?: number | null
  initial_price?: number | null
  current_price?: number | null
  change_pct?: number | null
  is_ai_recommended?: boolean | number | string | null
}

function isAiRecommended(value: PatternReviewRow['is_ai_recommended']): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    return ['1', 'true', 't', 'yes', 'y', 'ai', 'ai推荐'].includes(value.trim().toLowerCase())
  }
  return false
}

function formatPrice(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--'
}

function formatChange(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return value >= 0 ? `+${value.toFixed(2)}%` : `${value.toFixed(2)}%`
}

function formatCount(value: number | null | undefined): number {
  return Number.isFinite(Number(value)) && Number(value) > 0 ? Math.trunc(Number(value)) : 1
}

export function patternReviewRole(row: PatternReviewRow): string {
  return isAiRecommended(row.is_ai_recommended) ? 'AI推荐' : '观察/信号复盘'
}

export function formatPatternReviewLine(row: PatternReviewRow): string {
  const code = String(row.code).padStart(6, '0')
  const pricePath = `${formatPrice(row.initial_price)}→${formatPrice(row.current_price)}`
  return [
    `${code} ${row.name}`,
    patternReviewRole(row),
    `入选日${row.recommend_date}`,
    `入选${formatCount(row.recommend_count)}次`,
    `${pricePath} ${formatChange(row.change_pct)}`,
  ].join(' | ')
}

export function formatPatternReviewDigest(rows: PatternReviewRow[]): string {
  if (rows.length === 0) return PATTERN_REVIEW_EMPTY_MESSAGE
  const lines = rows.map(formatPatternReviewLine)
  return `最近 ${rows.length} 条形态复盘记录：${PATTERN_REVIEW_SCOPE_NOTE}\n\n${lines.join('\n')}`
}
