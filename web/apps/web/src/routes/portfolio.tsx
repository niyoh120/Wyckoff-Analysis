import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { WyckoffLoading } from '@/components/loading'

interface Position {
  code: string
  name: string
  shares: number
  cost_price: number
  buy_dt: string | null
}

interface Portfolio {
  free_cash: number
  positions: Position[]
}

export function PortfolioPage() {
  const user = useAuthStore((s) => s.user)
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingCash, setEditingCash] = useState(false)
  const [cashInput, setCashInput] = useState('')

  useEffect(() => {
    if (user) loadPortfolio()
  }, [user])

  async function loadPortfolio() {
    if (!user) return
    setLoading(true)
    const portfolioId = `USER_LIVE:${user.id}`

    const { data: pf } = await supabase
      .from('portfolios')
      .select('free_cash')
      .eq('portfolio_id', portfolioId)
      .single()

    const { data: positions } = await supabase
      .from('portfolio_positions')
      .select('code, name, shares, cost_price, buy_dt')
      .eq('portfolio_id', portfolioId)
      .order('buy_dt', { ascending: false })

    setPortfolio({
      free_cash: pf?.free_cash || 0,
      positions: positions || [],
    })
    setLoading(false)
  }

  async function saveCash() {
    if (!user) return
    const portfolioId = `USER_LIVE:${user.id}`
    const val = parseFloat(cashInput)
    if (isNaN(val)) return

    await supabase
      .from('portfolios')
      .upsert({ portfolio_id: portfolioId, free_cash: val })

    setEditingCash(false)
    await loadPortfolio()
  }

  async function deletePosition(code: string) {
    if (!user) return
    const portfolioId = `USER_LIVE:${user.id}`
    await supabase
      .from('portfolio_positions')
      .delete()
      .eq('portfolio_id', portfolioId)
      .eq('code', code)
    await loadPortfolio()
  }

  if (loading) {
    return <WyckoffLoading />
  }

  const totalCost = portfolio?.positions.reduce((s, p) => s + p.shares * p.cost_price, 0) || 0
  const totalAssets = totalCost + (portfolio?.free_cash || 0)

  return (
    <div className="h-full p-6">
      <h1 className="mb-6 text-xl font-semibold">持仓管理</h1>

      {/* Summary Cards */}
      <div className="mb-6 grid grid-cols-3 gap-4">
        <SummaryCard label="总资产（成本）" value={`¥${totalAssets.toLocaleString()}`} />
        <SummaryCard
          label="可用资金"
          value={`¥${(portfolio?.free_cash || 0).toLocaleString()}`}
          onClick={() => {
            setEditingCash(true)
            setCashInput(String(portfolio?.free_cash || 0))
          }}
        />
        <SummaryCard label="持仓数" value={String(portfolio?.positions.length || 0)} />
      </div>

      {/* Cash Edit Modal */}
      {editingCash && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-border p-3">
          <input
            type="number"
            value={cashInput}
            onChange={(e) => setCashInput(e.target.value)}
            className="flex-1 rounded-lg border border-border px-3 py-1.5 text-sm outline-none"
            autoFocus
          />
          <button onClick={saveCash} className="rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground">保存</button>
          <button onClick={() => setEditingCash(false)} className="rounded-lg border border-border px-3 py-1.5 text-sm">取消</button>
        </div>
      )}

      {/* Positions Table */}
      {portfolio?.positions.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">
          暂无持仓，可通过 CLI 或读盘室 Agent 添加
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-2.5 text-left font-medium">代码</th>
                <th className="px-4 py-2.5 text-left font-medium">名称</th>
                <th className="px-4 py-2.5 text-right font-medium">数量</th>
                <th className="px-4 py-2.5 text-right font-medium">成本价</th>
                <th className="px-4 py-2.5 text-right font-medium">建仓日</th>
                <th className="px-4 py-2.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {portfolio?.positions.map((p) => (
                <tr key={p.code} className="border-t border-border">
                  <td className="px-4 py-2.5 font-mono">{p.code}</td>
                  <td className="px-4 py-2.5">{p.name}</td>
                  <td className="px-4 py-2.5 text-right">{p.shares}</td>
                  <td className="px-4 py-2.5 text-right">{p.cost_price.toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-right text-muted-foreground">{p.buy_dt || '-'}</td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      onClick={() => deletePosition(p.code)}
                      className="text-xs text-destructive hover:underline"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function SummaryCard({ label, value, onClick }: { label: string; value: string; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border border-border p-4 ${onClick ? 'cursor-pointer hover:bg-muted/30' : ''}`}
    >
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  )
}
