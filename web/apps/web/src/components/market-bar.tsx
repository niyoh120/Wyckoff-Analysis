import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'

interface MarketSignal {
  benchmark_regime: string
  banner_title: string
  banner_message: string
  banner_tone: string
  main_index_close: number
  main_index_today_pct: number
  main_index_date: string
  a50_close: number
  a50_pct_chg: number
  a50_date: string
  vix_close: number
  vix_pct_chg: number
  vix_date: string
}

const REGIME_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  RISK_ON: { bg: 'bg-red-50', text: 'text-red-700', label: '偏强' },
  NEUTRAL: { bg: 'bg-blue-50', text: 'text-blue-700', label: '中性' },
  RISK_OFF: { bg: 'bg-purple-50', text: 'text-purple-700', label: '偏弱' },
  CRASH: { bg: 'bg-orange-50', text: 'text-orange-700', label: '极弱' },
  BLACK_SWAN: { bg: 'bg-red-100', text: 'text-red-800', label: '恶劣' },
}

const TONE_COLORS: Record<string, string> = {
  '乐观': 'bg-green-50 text-green-700',
  '谨慎乐观': 'bg-emerald-50 text-emerald-700',
  '谨慎': 'bg-blue-50 text-blue-700',
  '保守': 'bg-amber-50 text-amber-700',
  '恶劣': 'bg-red-50 text-red-700',
}

export function MarketBar() {
  const [signal, setSignal] = useState<MarketSignal | null>(null)

  useEffect(() => {
    loadSignal()
    const interval = setInterval(loadSignal, 60_000)
    return () => clearInterval(interval)
  }, [])

  async function loadSignal() {
    const { data } = await supabase
      .from('market_signal_daily')
      .select('*')
      .order('trade_date', { ascending: false })
      .limit(5)

    if (!data || data.length === 0) return

    const merged: Record<string, unknown> = {}
    let mainDate = ''
    let a50Date = ''
    let vixDate = ''
    for (const row of data) {
      for (const key of ['benchmark_regime', 'main_index_close', 'main_index_today_pct', 'main_index_ma50', 'main_index_ma200']) {
        if (merged[key] == null && row[key] != null) {
          merged[key] = row[key]
          if (key === 'main_index_close') mainDate = row.trade_date || ''
        }
      }
      for (const key of ['a50_close', 'a50_pct_chg']) {
        if (merged[key] == null && row[key] != null) {
          merged[key] = row[key]
          if (key === 'a50_close' && !a50Date) a50Date = row.a50_value_date || row.trade_date || ''
        }
      }
      for (const key of ['vix_close', 'vix_pct_chg']) {
        if (merged[key] == null && row[key] != null) {
          merged[key] = row[key]
          if (key === 'vix_close' && !vixDate) vixDate = row.vix_value_date || row.trade_date || ''
        }
      }
      for (const key of ['banner_title', 'banner_message', 'banner_tone']) {
        if (!merged[key] && row[key]) merged[key] = row[key]
      }
    }

    setSignal({
      benchmark_regime: String(merged.benchmark_regime || 'NEUTRAL'),
      banner_title: String(merged.banner_title || ''),
      banner_message: String(merged.banner_message || ''),
      banner_tone: String(merged.banner_tone || '谨慎'),
      main_index_close: Number(merged.main_index_close || 0),
      main_index_today_pct: Number(merged.main_index_today_pct || 0),
      main_index_date: mainDate,
      a50_close: Number(merged.a50_close || 0),
      a50_pct_chg: Number(merged.a50_pct_chg || 0),
      a50_date: a50Date,
      vix_close: Number(merged.vix_close || 0),
      vix_pct_chg: Number(merged.vix_pct_chg || 0),
      vix_date: vixDate,
    })
  }

  if (!signal) return null

  const regime = REGIME_COLORS[signal.benchmark_regime] || REGIME_COLORS.NEUTRAL!
  const toneClass = TONE_COLORS[signal.banner_tone] || 'bg-blue-50 text-blue-700'

  const fmtPct = (v: number) => v ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '--'
  const fmtDate = (d: string) => d ? d.slice(5).replace('-', '/') : ''

  return (
    <div className="border-b border-border bg-white px-6 py-2.5">
      <div className="flex flex-wrap items-center gap-4">
        {/* Tone Badge */}
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${toneClass}`}>
          {signal.banner_tone}
        </span>

        {/* Regime Badge */}
        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] ${regime.bg} ${regime.text}`}>
          {regime.label}
        </span>

        {/* SSE Index */}
        {signal.main_index_close > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">上证</span>
            <span className="text-sm font-medium">{signal.main_index_close.toFixed(0)}</span>
            <span className={`text-xs font-medium ${signal.main_index_today_pct >= 0 ? 'text-up' : 'text-down'}`}>
              {fmtPct(signal.main_index_today_pct)}
            </span>
            {signal.main_index_date && <span className="text-[10px] text-muted-foreground">{fmtDate(signal.main_index_date)}</span>}
          </div>
        )}

        {/* A50 */}
        {signal.a50_close > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">A50</span>
            <span className="text-xs font-medium">{signal.a50_close.toFixed(0)}</span>
            <span className={`text-xs font-medium ${signal.a50_pct_chg >= 0 ? 'text-up' : 'text-down'}`}>
              {fmtPct(signal.a50_pct_chg)}
            </span>
            {signal.a50_date && <span className="text-[10px] text-muted-foreground">{fmtDate(signal.a50_date)}</span>}
          </div>
        )}

        {/* VIX */}
        {signal.vix_close > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">VIX</span>
            <span className="text-xs font-medium">{signal.vix_close.toFixed(1)}</span>
            <span className={`text-xs font-medium ${signal.vix_pct_chg <= 0 ? 'text-up' : 'text-down'}`}>
              {fmtPct(signal.vix_pct_chg)}
            </span>
            {signal.vix_date && <span className="text-[10px] text-muted-foreground">{fmtDate(signal.vix_date)}</span>}
          </div>
        )}

        {/* Title */}
        {signal.banner_title && (
          <span className="ml-auto text-xs font-medium text-foreground">{signal.banner_title}</span>
        )}
      </div>

      {/* Body */}
      {signal.banner_message && (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{signal.banner_message}</p>
      )}
    </div>
  )
}
