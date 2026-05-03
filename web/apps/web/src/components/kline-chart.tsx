import { useEffect, useRef } from 'react'
import { createChart, CandlestickSeries, HistogramSeries, type IChartApi, type CandlestickData, type HistogramData, type Time } from 'lightweight-charts'

interface KlineData {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface KlineChartProps {
  data: KlineData[]
  height?: number
}

export function KlineChart({ data, height = 400 }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#6b7194',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#f0f2f8' },
        horzLines: { color: '#f0f2f8' },
      },
      crosshair: {
        mode: 0,
      },
      rightPriceScale: {
        borderColor: '#e2e5f1',
      },
      timeScale: {
        borderColor: '#e2e5f1',
        timeVisible: false,
      },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#10b981',
      borderUpColor: '#ef4444',
      borderDownColor: '#10b981',
      wickUpColor: '#ef4444',
      wickDownColor: '#10b981',
    })

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    })

    const candles: CandlestickData<Time>[] = data.map((d) => ({
      time: d.date as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }))

    const volumes: HistogramData<Time>[] = data.map((d) => ({
      time: d.date as Time,
      value: d.volume,
      color: d.close >= d.open ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)',
    }))

    candleSeries.setData(candles)
    volumeSeries.setData(volumes)
    chart.timeScale().fitContent()

    chartRef.current = chart

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
      chartRef.current = null
    }
  }, [data, height])

  return <div ref={containerRef} className="w-full" />
}
