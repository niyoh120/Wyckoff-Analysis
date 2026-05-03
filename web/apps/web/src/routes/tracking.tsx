import { useState, useEffect, useMemo } from 'react'
import { supabase } from '@/lib/supabase'

interface Recommendation {
  code: number
  name: string
  recommend_date: number
  initial_price: number
  current_price: number
  change_pct: number
  is_ai_recommended: boolean
  funnel_score: number
  recommend_count: number
  recommend_reason: string | null
}

export function TrackingPage() {
  const [data, setData] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [onlyAI, setOnlyAI] = useState(false)
  const [sortBy, setSortBy] = useState<'date' | 'change' | 'score'>('date')

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    const { data: rows } = await supabase
      .from('recommendation_tracking')
      .select('*')
      .order('recommend_date', { ascending: false })
      .limit(2000)

    setData(rows || [])
    setLoading(false)
  }

  const filtered = useMemo(() => {
    let result = data
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(
        (r) => String(r.code).includes(q) || r.name.toLowerCase().includes(q),
      )
    }
    if (onlyAI) {
      result = result.filter((r) => r.is_ai_recommended)
    }
    if (sortBy === 'change') {
      result = [...result].sort((a, b) => b.change_pct - a.change_pct)
    } else if (sortBy === 'score') {
      result = [...result].sort((a, b) => b.funnel_score - a.funnel_score)
    }
    return result
  }, [data, search, onlyAI, sortBy])

  const stats = useMemo(() => {
    if (data.length === 0) return null
    const avg = data.reduce((s, r) => s + r.change_pct, 0) / data.length
    const best = Math.max(...data.map((r) => r.change_pct))
    const worst = Math.min(...data.map((r) => r.change_pct))
    return { count: data.length, avg, best, worst }
  }, [data])

  if (loading) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">加载中...</div>
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-6 text-xl font-semibold">推荐跟踪</h1>

      {/* Stats */}
      {stats && (
        <div className="mb-6 grid grid-cols-4 gap-4">
          <StatCard label="覆盖股票" value={String(stats.count)} />
          <StatCard label="平均涨幅" value={`${stats.avg.toFixed(2)}%`} color={stats.avg >= 0 ? 'text-red-600' : 'text-green-600'} />
          <StatCard label="最佳" value={`+${stats.best.toFixed(2)}%`} color="text-red-600" />
          <StatCard label="最大回撤" value={`${stats.worst.toFixed(2)}%`} color="text-green-600" />
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索代码或名称..."
          className="rounded-lg border border-border px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/20"
        />
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={onlyAI}
            onChange={(e) => setOnlyAI(e.target.checked)}
            className="rounded"
          />
          只看 AI 推荐
        </label>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
          className="rounded-lg border border-border px-2 py-1.5 text-sm"
        >
          <option value="date">按日期</option>
          <option value="change">按涨幅</option>
          <option value="score">按评分</option>
        </select>
        <span className="text-xs text-muted-foreground">{filtered.length} 条</span>
      </div>

      {/* Table */}
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        <div className="h-full overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr>
                <th className="px-3 py-2 text-left font-medium">代码</th>
                <th className="px-3 py-2 text-left font-medium">名称</th>
                <th className="px-3 py-2 text-right font-medium">推荐日</th>
                <th className="px-3 py-2 text-right font-medium">初始价</th>
                <th className="px-3 py-2 text-right font-medium">现价</th>
                <th className="px-3 py-2 text-right font-medium">涨跌幅</th>
                <th className="px-3 py-2 text-right font-medium">评分</th>
                <th className="px-3 py-2 text-center font-medium">AI</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={`${r.code}-${r.recommend_date}-${i}`} className="border-t border-border hover:bg-muted/20">
                  <td className="px-3 py-2 font-mono">{String(r.code).padStart(6, '0')}</td>
                  <td className="px-3 py-2">{r.name}</td>
                  <td className="px-3 py-2 text-right text-muted-foreground">{formatDate(r.recommend_date)}</td>
                  <td className="px-3 py-2 text-right">{r.initial_price?.toFixed(2) || '-'}</td>
                  <td className="px-3 py-2 text-right">{r.current_price?.toFixed(2) || '-'}</td>
                  <td className={`px-3 py-2 text-right font-medium ${r.change_pct >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                    {r.change_pct >= 0 ? '+' : ''}{r.change_pct?.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 text-right">{r.funnel_score?.toFixed(1)}</td>
                  <td className="px-3 py-2 text-center">
                    {r.is_ai_recommended && <span className="inline-block h-2 w-2 rounded-full bg-green-500" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${color || ''}`}>{value}</div>
    </div>
  )
}

function formatDate(d: number): string {
  const s = String(d)
  if (s.length !== 8) return s
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
}
