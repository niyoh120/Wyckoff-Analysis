import { useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { loadLLMConfig, type LLMConfig } from '@/lib/chat-agent'
import { MarkdownContent } from '@/components/markdown'
import { KlineChart } from '@/components/kline-chart'

interface KlineData {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface AnalysisResult {
  report: string
  symbol: string
  name: string
  klineData: KlineData[]
}

export function AnalysisPage() {
  const user = useAuthStore((s) => s.user)
  const [symbol, setSymbol] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState('')

  async function getTickFlowKey(): Promise<string | null> {
    if (!user) return null
    const { data } = await supabase
      .from('user_settings')
      .select('tickflow_api_key')
      .eq('user_id', user.id)
      .single()
    return data?.tickflow_api_key || null
  }

  async function fetchKline(code: string, apiKey: string): Promise<KlineData[]> {
    const end = new Date()
    end.setDate(end.getDate() - 1)
    const start = new Date()
    start.setDate(start.getDate() - 500)

    const url = `https://api.tickflow.io/v1/stock/history?symbol=${code}&start_date=${fmt(start)}&end_date=${fmt(end)}&adjust=qfq&limit=320`

    try {
      const resp = await fetch(url, {
        headers: { 'Authorization': `Bearer ${apiKey}` },
      })
      if (!resp.ok) return []
      const json = await resp.json()
      const rows = json.data || json.records || json || []
      if (!Array.isArray(rows)) return []

      return rows.map((r: Record<string, unknown>) => ({
        date: String(r.date || r.trade_date || '').replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'),
        open: Number(r.open || 0),
        high: Number(r.high || 0),
        low: Number(r.low || 0),
        close: Number(r.close || 0),
        volume: Number(r.volume || r.vol || 0),
      })).filter((d: KlineData) => d.date && d.close > 0)
    } catch {
      return []
    }
  }

  async function handleAnalyze() {
    const code = symbol.trim().replace(/\D/g, '')
    if (code.length !== 6) {
      setError('请输入有效的 6 位股票代码')
      return
    }

    setError('')
    setLoading(true)
    setResult(null)

    try {
      const config = await loadLLMConfig(user!.id)
      if (!config) {
        setError('请先在设置页配置 API Key')
        setLoading(false)
        return
      }

      const tickflowKey = await getTickFlowKey()

      const [stockInfoResult, klineData] = await Promise.all([
        supabase.from('recommendation_tracking').select('name').eq('code', parseInt(code)).limit(1).single(),
        tickflowKey ? fetchKline(code, tickflowKey) : Promise.resolve([]),
      ])

      const name = stockInfoResult.data?.name || code

      const klineSummary = klineData.length > 0
        ? buildKlineSummary(klineData)
        : ''

      const report = await callLLM(config, code, name, klineSummary)
      setResult({ report, symbol: code, name, klineData })
    } catch (err) {
      setError(err instanceof Error ? err.message : '分析失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-6 text-xl font-semibold">单股分析</h1>

      {/* Input */}
      <div className="mb-6 flex items-end gap-3">
        <div className="flex-1 max-w-xs">
          <label className="mb-1.5 block text-sm font-medium">股票代码</label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="例如：600519"
            maxLength={6}
            className="w-full rounded-lg border border-border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/20"
            onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
          />
        </div>
        <button
          onClick={handleAnalyze}
          disabled={loading || !symbol.trim()}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          {loading ? '分析中...' : '开始分析'}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>
      )}

      {/* Result */}
      {result && (
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="mb-4 flex items-center gap-2">
            <span className="rounded-full bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
              {result.symbol} {result.name}
            </span>
          </div>

          {/* K-line Chart */}
          {result.klineData.length > 0 && (
            <div className="mb-6 rounded-lg border border-border p-4">
              <KlineChart data={result.klineData} height={350} />
            </div>
          )}

          {/* Report */}
          <div className="rounded-lg border border-border p-6">
            <h2 className="mb-4 text-base font-semibold">威科夫大师研报</h2>
            <article className="prose prose-sm max-w-none text-foreground">
              <MarkdownContent content={result.report} />
            </article>
          </div>
        </div>
      )}

      {!result && !loading && (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <div className="text-center">
            <div className="mb-3 text-4xl">📊</div>
            <p className="text-sm">输入股票代码，开始威科夫大师分析</p>
            <p className="mt-1 text-xs">配置 TickFlow Key 后可显示 K 线图</p>
          </div>
        </div>
      )}
    </div>
  )
}

function fmt(d: Date): string {
  return d.toISOString().slice(0, 10).replace(/-/g, '')
}

function buildKlineSummary(data: KlineData[]): string {
  const last = data[data.length - 1]!
  const prev20 = data.slice(-20)
  const ma5 = avg(data.slice(-5).map((d) => d.close))
  const ma20 = avg(prev20.map((d) => d.close))
  const ma50 = data.length >= 50 ? avg(data.slice(-50).map((d) => d.close)) : 0

  return [
    `\n近期行情摘要（${data.length}根K线）：`,
    `最新收盘：${last.close.toFixed(2)}`,
    `MA5=${ma5.toFixed(2)} MA20=${ma20.toFixed(2)}${ma50 ? ` MA50=${ma50.toFixed(2)}` : ''}`,
    `近20日最高：${Math.max(...prev20.map((d) => d.high)).toFixed(2)}`,
    `近20日最低：${Math.min(...prev20.map((d) => d.low)).toFixed(2)}`,
    `近5日平均量：${avg(data.slice(-5).map((d) => d.volume)).toFixed(0)}`,
    `近20日平均量：${avg(prev20.map((d) => d.volume)).toFixed(0)}`,
  ].join('\n')
}

function avg(arr: number[]): number {
  return arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0
}

async function callLLM(config: LLMConfig, code: string, name: string, klineSummary: string): Promise<string> {
  const systemPrompt = `你是威科夫分析大师，精通量价分析和威科夫方法。请对给定股票进行深度分析，包括：
1. 当前所处威科夫阶段（积累/上涨/派发/下跌），Phase A-E 定位
2. 量价关系分析（供需力量对比）
3. 关键支撑与阻力位
4. 主力意图判断
5. 操作建议与风险提示（含止损位）

请用简洁、专业的中文回答。使用 markdown 格式，结构清晰。`

  const userMsg = `请分析股票 ${code} ${name}。基于威科夫理论给出当前阶段判断和操作建议。${klineSummary}`

  const response = await fetch(`${config.base_url}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${config.api_key}`,
    },
    body: JSON.stringify({
      model: config.model,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userMsg },
      ],
      temperature: 0.7,
      max_tokens: 4096,
    }),
  })

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}))
    throw new Error(errData.error?.message || `API 请求失败 (${response.status})`)
  }

  const data = await response.json()
  return data.choices?.[0]?.message?.content || '未获取到分析结果'
}

