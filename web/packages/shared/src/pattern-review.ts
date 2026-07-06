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
  candidate_lane?: string | null
  entry_type?: string | null
  signal_key?: string | null
  candidate_status?: string | null
  mainline_score?: number | null
  source_type?: string | null
  signal_status?: string | null
  signal_type?: string | null
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
  if (row.source_type === 'signal_pending') {
    return row.signal_status === 'confirmed' ? '已确认信号' : '待确认信号'
  }
  return isAiRecommended(row.is_ai_recommended) ? 'AI推荐' : '观察/信号复盘'
}

export function labelCandidateTerm(value: string): string | null {
  const clean = value.trim()
  if (!clean) return null
  const labels: Record<string, string> = {
    mainline: '主线买点',
    trend_breakout: '趋势突破',
    trend_lane_pullback: '趋势回踩',
    sector_strength: '板块强势',
    wyckoff_structure: 'Wyckoff结构',
    sos: 'SOS点火',
    evr: 'EVR放量不跌',
    lps: 'LPS缩量回踩',
    spring: 'Spring震仓',
    Lane: '入选路径',
    可买主线: '主线买点候选',
    主线买点候选: '主线买点候选',
    主线观察: '主线观察',
    过热不追: '过热不追',
  }
  return labels[clean] || clean
}

export function formatPatternReviewLine(row: PatternReviewRow): string {
  const code = String(row.code).padStart(6, '0')
  const pricePath = `${formatPrice(row.initial_price)}→${formatPrice(row.current_price)}`
  const lane = [row.candidate_lane || row.signal_key || row.signal_type, row.entry_type || row.candidate_status]
    .map(item => String(item || '').trim())
    .filter(Boolean)
    .map(labelCandidateTerm)
    .filter(Boolean)
    .join('/')
  const mainline = typeof row.mainline_score === 'number' ? `主线${Math.round(row.mainline_score * 100)}` : ''
  const dateLabel = row.source_type === 'signal_pending' ? '信号日' : '入选日'
  return [
    `${code} ${row.name}`,
    patternReviewRole(row),
    `${dateLabel}${row.recommend_date}`,
    `入选${formatCount(row.recommend_count)}次`,
    lane || mainline ? `入选路径${[lane, mainline].filter(Boolean).join(' ')}` : '',
    `${pricePath} ${formatChange(row.change_pct)}`,
  ].filter(Boolean).join(' | ')
}

export function formatPatternReviewDigest(rows: PatternReviewRow[]): string {
  if (rows.length === 0) return PATTERN_REVIEW_EMPTY_MESSAGE
  const lines = rows.map(formatPatternReviewLine)
  return `最近 ${rows.length} 条形态复盘记录：${PATTERN_REVIEW_SCOPE_NOTE}\n\n${lines.join('\n')}`
}
