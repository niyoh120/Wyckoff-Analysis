import { useEffect, useMemo, useRef, type RefObject } from 'react'
import { watchChartResize } from '@/lib/chart-resize'
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts'
import type { KlineRow } from '@wyckoff/shared'

export interface ComparisonSeries {
  code: string
  name: string
  data: KlineRow[]
}

interface MultiStockChartProps {
  series: ComparisonSeries[]
  height?: number
}

interface SeriesRef {
  line: ISeriesApi<'Line'>
}

const COLORS = ['#ef4444', '#2563eb', '#f59e0b', '#10b981', '#7c3aed', '#ec4899', '#06b6d4', '#84cc16']

export function MultiStockChart({ series, height = 420 }: MultiStockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRefs = useRef<SeriesRef[]>([])
  const normalized = useMemo(() => series.map(normalizeSeries).filter((item) => item.points.length), [series])
  useChartShell(containerRef, chartRef, seriesRefs, height)
  useLineSeries(chartRef, seriesRefs, normalized)

  return (
    <div className="space-y-3">
      <div
        ref={containerRef}
        className="w-full overflow-hidden rounded-lg border border-border bg-background"
        style={{ height }}
      />
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        {normalized.map((item, index) => <Legend key={item.code} color={chartColor(index)} label={item.label} />)}
      </div>
    </div>
  )
}

function useChartShell(
  containerRef: RefObject<HTMLDivElement | null>,
  chartRef: RefObject<IChartApi | null>,
  seriesRefs: RefObject<SeriesRef[]>,
  height: number,
) {
  useEffect(() => {
    if (!containerRef.current) return
    const theme = readTheme()
    const chart = createChart(containerRef.current, {
      height,
      layout: { background: { color: theme.background }, textColor: theme.mutedText, fontSize: 11 },
      grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
      rightPriceScale: { borderColor: theme.border },
      timeScale: { borderColor: theme.border, timeVisible: false },
      localization: { priceFormatter: (value: number) => `${value.toFixed(1)}%` },
    })
    chartRef.current = chart
    const stopResize = watchChartResize(containerRef.current, chart)
    return () => {
      stopResize()
      chart.remove()
      chartRef.current = null
      seriesRefs.current = []
    }
  }, [containerRef, chartRef, seriesRefs, height])
}

function useLineSeries(
  chartRef: RefObject<IChartApi | null>,
  seriesRefs: RefObject<SeriesRef[]>,
  normalized: ReturnType<typeof normalizeSeries>[],
) {
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    seriesRefs.current.forEach(({ line }) => chart.removeSeries(line))
    seriesRefs.current = normalized.map((item, index) => {
      const line = chart.addSeries(LineSeries, {
        color: chartColor(index),
        lineWidth: index === 0 ? 3 : 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: item.label,
      })
      line.setData(item.points)
      return { line }
    })
    chart.timeScale().fitContent()
  }, [chartRef, seriesRefs, normalized])
}

function normalizeSeries(item: ComparisonSeries) {
  const first = item.data.find((row) => row.close > 0)
  const base = first?.close || 0
  const points: LineData<Time>[] = base > 0
    ? item.data.map((row) => ({ time: row.date as Time, value: (row.close / base - 1) * 100 }))
    : []
  return { code: item.code, label: `${item.code} ${item.name}`.trim(), points }
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-4 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  )
}

function chartColor(index: number): string {
  return COLORS[index % COLORS.length] || '#6b7280'
}

function readTheme() {
  const style = getComputedStyle(document.documentElement)
  const color = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    background: color('--color-background', '#ffffff'),
    mutedText: color('--color-muted-foreground', '#6b7194'),
    border: color('--color-border', '#e2e5f1'),
    grid: document.documentElement.classList.contains('dark') ? '#202938' : '#eef1f6',
  }
}
