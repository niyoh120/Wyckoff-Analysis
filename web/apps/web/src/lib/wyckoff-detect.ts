interface KlineRow {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface WyckoffMarker {
  date: string
  type: 'spring' | 'sos' | 'lps' | 'evr'
  label: string
  position: 'aboveBar' | 'belowBar'
}

export interface TradingRangeResult {
  support: number
  resistance: number
  mid: number
  widthPct: number
}

export interface WyckoffAnnotation {
  tradingRange: TradingRangeResult | null
  markers: WyckoffMarker[]
  stage: string
}

export function detectWyckoffAnnotations(data: KlineRow[]): WyckoffAnnotation {
  const tr = identifyTradingRange(data)
  const markers = tr ? detectTriggers(data, tr) : []
  const stage = inferStage(data, tr, markers)
  return { tradingRange: tr, markers, stage }
}

function identifyTradingRange(data: KlineRow[], lookback = 90): TradingRangeResult | null {
  if (data.length < 40) return null
  const window = data.slice(-Math.min(lookback, data.length), -1)
  if (window.length < 40) return null

  const lows = window.map((d) => d.low)
  const highs = window.map((d) => d.high)
  const swingLows = swingValues(lows, 'low', 3)
  const swingHighs = swingValues(highs, 'high', 3)

  const support = swingLows.length >= 2 ? median(swingLows.slice(-5)) : quantile(lows, 0.1)
  const resistance = swingHighs.length >= 2 ? median(swingHighs.slice(-5)) : quantile(highs, 0.9)

  if (support <= 0 || resistance <= support) return null
  const widthPct = ((resistance - support) / support) * 100
  if (widthPct < 4.0 || widthPct > 45.0) return null

  const firstClose = window[0]!.close
  const lastClose = window[window.length - 1]!.close
  const driftPct = Math.abs((lastClose - firstClose) / firstClose) * 100
  if (driftPct > 18.0) return null

  const tolerance = 0.035
  const supportTests = window.filter((d) => d.low <= support * (1 + tolerance)).length
  const resistanceTests = window.filter((d) => d.high >= resistance * (1 - tolerance)).length
  if (supportTests < 2 || resistanceTests < 2) return null

  const mid = (support + resistance) / 2
  return { support, resistance, mid, widthPct }
}

function detectTriggers(data: KlineRow[], tr: TradingRangeResult): WyckoffMarker[] {
  const markers: WyckoffMarker[] = []
  const start = Math.max(20, data.length - 60)

  for (let i = start; i < data.length; i++) {
    const bar = data[i]!
    const prev = data[i - 1]
    const refSlice = data.slice(Math.max(0, i - 5), i)
    const volAvg5 = avg(refSlice.map((d) => d.volume))
    const refSlice20 = data.slice(Math.max(0, i - 20), i)
    const volAvg20 = avg(refSlice20.map((d) => d.volume))
    const pctChange = prev ? ((bar.close - prev.close) / prev.close) * 100 : 0
    const width = tr.resistance - tr.support

    if (detectSpring(bar, prev, tr, volAvg5, width)) {
      markers.push({ date: bar.date, type: 'spring', label: 'Spring', position: 'belowBar' })
    } else if (detectSOS(bar, tr, pctChange, volAvg20)) {
      markers.push({ date: bar.date, type: 'sos', label: 'SOS', position: 'belowBar' })
    } else if (detectLPS(data, i, tr, width)) {
      markers.push({ date: bar.date, type: 'lps', label: 'LPS', position: 'belowBar' })
    } else if (detectEVR(bar, tr, pctChange, volAvg20)) {
      markers.push({ date: bar.date, type: 'evr', label: 'EVR', position: 'aboveBar' })
    }
  }
  return markers.slice(-8)
}

function detectSpring(
  bar: KlineRow,
  prev: KlineRow | undefined,
  tr: TradingRangeResult,
  volAvg5: number,
  width: number,
): boolean {
  const pierced = Math.min(prev?.low ?? bar.low, bar.low) <= tr.support * 0.995
  const recovered = bar.close > tr.support * 1.005
  const inRange = bar.close < tr.mid + width * 0.25
  const volOk = volAvg5 > 0 && bar.volume / volAvg5 >= 1.1
  return pierced && recovered && inRange && volOk
}

function detectSOS(bar: KlineRow, tr: TradingRangeResult, pctChange: number, volAvg20: number): boolean {
  const atResistance = bar.close >= tr.resistance * 0.99
  const strongDay = pctChange >= 6.0
  const highVol = volAvg20 > 0 && bar.volume / volAvg20 >= 2.5
  return atResistance && strongDay && highVol
}

function detectLPS(data: KlineRow[], index: number, tr: TradingRangeResult, width: number): boolean {
  if (index < 63) return false
  const recent3 = data.slice(index - 2, index + 1)
  const recentLow = Math.min(...recent3.map((d) => d.low))
  const nearSupport = recentLow <= tr.support + width * 0.35
  const holdsAbove = data[index]!.close > tr.support
  const recentMaxVol = Math.max(...recent3.map((d) => d.volume))
  const refVols = data.slice(Math.max(0, index - 63), index - 3)
  const refMaxVol = Math.max(...refVols.map((d) => d.volume))
  const dryUp = refMaxVol > 0 && recentMaxVol / refMaxVol <= 0.5
  return nearSupport && holdsAbove && dryUp
}

function detectEVR(bar: KlineRow, tr: TradingRangeResult, pctChange: number, volAvg20: number): boolean {
  const highVol = volAvg20 > 0 && bar.volume / volAvg20 >= 1.5
  const inLowerHalf = bar.close <= tr.mid
  const narrowChange = pctChange >= -2.0 && pctChange <= 2.0
  const aboveFloor = bar.close >= tr.support * 0.98
  return highVol && inLowerHalf && narrowChange && aboveFloor
}

function inferStage(data: KlineRow[], tr: TradingRangeResult | null, markers: WyckoffMarker[]): string {
  if (!tr || data.length === 0) return ''
  const last = data[data.length - 1]!
  const hasSOS = markers.some((m) => m.type === 'sos')
  const hasSpring = markers.some((m) => m.type === 'spring')

  if (hasSOS && last.close > tr.resistance) return 'Markup'
  if (hasSpring) return 'Accum_C'
  if (last.close > tr.mid) return 'Accum_B'
  return '区间观察'
}

function swingValues(series: number[], kind: 'low' | 'high', window: number): number[] {
  const results: number[] = []
  for (let i = window; i < series.length - window; i++) {
    const neighborhood = series.slice(i - window, i + window + 1)
    const val = series[i]!
    if (kind === 'low' && val <= Math.min(...neighborhood)) results.push(val)
    if (kind === 'high' && val >= Math.max(...neighborhood)) results.push(val)
  }
  return results
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1]! + sorted[mid]!) / 2 : sorted[mid]!
}

function quantile(values: number[], q: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const pos = q * (sorted.length - 1)
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (pos - lo)
}

function avg(values: number[]): number {
  return values.length > 0 ? values.reduce((s, v) => s + v, 0) / values.length : 0
}
