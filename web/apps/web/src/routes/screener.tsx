import { useState, useEffect } from 'react'
import { Filter, RefreshCw } from 'lucide-react'
import { supabase } from '@/lib/supabase'

interface ScreenerRow {
  code: number
  name: string
  recommend_date: number
  funnel_score: number | null
  change_pct: number | null
  initial_price: number | null
  current_price: number | null
}

export function ScreenerPage() {
  const [rows, setRows] = useState<ScreenerRow[]>([])
  const [loading, setLoading] = useState(true)
  const [latestDate, setLatestDate] = useState<number | null>(null)
  const [allDates, setAllDates] = useState<number[]>([])
  const [selectedDate, setSelectedDate] = useState<number | null>(null)

  useEffect(() => {
    loadDates()
  }, [])

  useEffect(() => {
    if (selectedDate) loadRows(selectedDate)
  }, [selectedDate])

  async function loadDates() {
    const { data } = await supabase
      .from('recommendation_tracking')
      .select('recommend_date')
      .eq('is_ai_recommended', true)
      .order('recommend_date', { ascending: false })
      .limit(200)

    if (!data || data.length === 0) {
      setLoading(false)
      return
    }

    const uniqueDates = [...new Set(data.map(r => r.recommend_date))].sort((a, b) => b - a)
    setAllDates(uniqueDates)
    setLatestDate(uniqueDates[0]!)
    setSelectedDate(uniqueDates[0]!)
  }

  async function loadRows(date: number) {
    setLoading(true)
    const { data } = await supabase
      .from('recommendation_tracking')
      .select('code, name, recommend_date, funnel_score, change_pct, initial_price, current_price')
      .eq('is_ai_recommended', true)
      .eq('recommend_date', date)
      .order('funnel_score', { ascending: false })

    setRows(data || [])
    setLoading(false)
  }

  function handleRefresh() {
    if (selectedDate) loadRows(selectedDate)
  }

  const fmtDate = (d: number) => {
    const s = String(d)
    return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : String(d)
  }

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">漏斗选股</h1>
          <Filter size={18} className="text-muted-foreground" />
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/50 disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {/* Date selector */}
      {allDates.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">选股日期：</span>
          {allDates.slice(0, 10).map((d) => (
            <button
              key={d}
              onClick={() => setSelectedDate(d)}
              className={`rounded-full px-3 py-1 text-xs transition-colors ${
                selectedDate === d
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border text-muted-foreground hover:bg-muted/50'
              }`}
            >
              {fmtDate(d)}
            </button>
          ))}
        </div>
      )}

      {/* Summary */}
      {!loading && rows.length > 0 && (
        <div className="mb-4 flex items-center gap-6">
          <div className="rounded-lg bg-primary/5 px-4 py-2">
            <div className="text-2xl font-bold text-primary">{rows.length}</div>
            <div className="text-xs text-muted-foreground">AI 候选</div>
          </div>
          {latestDate && (
            <div className="text-xs text-muted-foreground">
              最新选股日期: {fmtDate(latestDate)}
            </div>
          )}
        </div>
      )}

      {/* Table */}
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted/30 text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">代码</th>
              <th className="px-4 py-2.5 text-left font-medium">名称</th>
              <th className="px-4 py-2.5 text-right font-medium">漏斗分</th>
              <th className="px-4 py-2.5 text-right font-medium">推荐价</th>
              <th className="px-4 py-2.5 text-right font-medium">现价</th>
              <th className="px-4 py-2.5 text-right font-medium">涨跌幅</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  加载中...
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  暂无选股结果
                </td>
              </tr>
            ) : (
              rows.map((r) => {
                const code = String(r.code).padStart(6, '0')
                const chg = r.change_pct
                return (
                  <tr key={r.code} className="hover:bg-muted/20">
                    <td className="px-4 py-2.5 font-mono text-xs">{code}</td>
                    <td className="px-4 py-2.5">{r.name}</td>
                    <td className="px-4 py-2.5 text-right font-mono">
                      {r.funnel_score != null ? r.funnel_score.toFixed(2) : '--'}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono">
                      {r.initial_price?.toFixed(2) || '--'}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono">
                      {r.current_price?.toFixed(2) || '--'}
                    </td>
                    <td className={`px-4 py-2.5 text-right font-mono font-medium ${
                      chg == null ? '' : chg >= 0 ? 'text-up' : 'text-down'
                    }`}>
                      {chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '--'}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        数据来源：CLI 每日自动运行漏斗选股，结果写入云端。此页面仅展示 AI 推荐候选。
      </p>
    </div>
  )
}
