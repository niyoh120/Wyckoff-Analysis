import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, LayoutDashboard, Plus, Trash2 } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { WyckoffLoading } from '@/components/loading'
import { usePreferences } from '@/lib/preferences'
import { loadLLMConfig } from '@/lib/chat-agent'
import { streamLLMResponse } from '@/lib/llm-stream'
import { MarkdownContent } from '@/components/markdown'
import { UpgradeNotice } from '@/components/upgrade-notice'
import { AIDisclaimer } from '@/components/ai-disclaimer'
import { TICKFLOW_PURCHASE, fetchValueSnapshotWithFetch, normalizeCode } from '@wyckoff/shared'
import type { KlineRow, ValueSnapshot } from '@wyckoff/shared'
import { fetchKlineViaTickFlow, getUserDataKeys } from '@/lib/kline'
import { useWhitelistGate } from '@/lib/whitelist-gate'
import { avg } from '@/lib/math'
import { saveAnalysisHistory } from '@/lib/local-history'
import { sourceLabel, type ValueScore, type ValueTone } from '@wyckoff/shared'
import { buildValueDigest, buildValueScore, formatValuePercent, metricToneClass, numberTone, reverseNumberTone, signalClass, valueScoreClass, valueUnavailableText, type ValueView } from '@/lib/value-analysis'

interface Position {
  code: string | number
  name: string | null
  shares: number
  cost_price: number
  buy_dt: string | null
}

interface Portfolio {
  free_cash: number
  positions: Position[]
}

interface PositionPnL {
  code: string
  name: string
  shares: number
  cost: number
  latest: number
  costVal: number
  mktVal: number
  pnlPct: number
  weight: number
}

interface FullDiagnosisResult {
  report: string
  positions: PositionPnL[]
  values: PortfolioValueRow[]
  summaryStats: { totalCost: number; totalMarket: number; pnlPct: number; freeCash: number; count: number }
}

interface PortfolioValueRow {
  code: string
  name: string
  snapshot: ValueSnapshot
}

interface PortfolioHistoryPayload {
  source: 'database' | 'manual'
  result: FullDiagnosisResult
  report: string
}

async function fetchPortfolio(userId: string): Promise<Portfolio> {
  const portfolioId = `USER_LIVE:${userId}`
  const [{ data: pf }, { data: positions }] = await Promise.all([
    supabase.from('portfolios').select('free_cash').eq('portfolio_id', portfolioId).single(),
    supabase
      .from('portfolio_positions')
      .select('code, name, shares, cost_price, buy_dt')
      .eq('portfolio_id', portfolioId)
      .order('buy_dt', { ascending: false }),
  ])
  return { free_cash: Number(pf?.free_cash || 0), positions: positions || [] }
}

export function PortfolioPage() {
  const user = useAuthStore((s) => s.user)
  const portfolioData = usePortfolioData(user?.id)
  const fullDiag = useFullDiagnosisRunner()
  const [manualPortfolio, setManualPortfolio] = useState<Portfolio>({ free_cash: 0, positions: [] })
  const source = portfolioData.isWhitelisted ? 'database' : 'manual'
  usePortfolioHistory(user?.id, fullDiag.result, source)

  if (portfolioData.isLoading) return <WyckoffLoading />

  const portfolio = portfolioData.isWhitelisted ? portfolioData.portfolio : manualPortfolio

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-6">
      <PageHeader />
      {fullDiag.error && <UpgradeNotice message={fullDiag.error} />}
      {portfolioData.isWhitelisted ? (
        <Holdings portfolio={portfolio} fullLoading={fullDiag.loading} progress={fullDiag.progress} onFullDiagnosis={() => fullDiag.run(portfolio)} />
      ) : (
        <ManualInput portfolio={manualPortfolio} fullLoading={fullDiag.loading} progress={fullDiag.progress} onChange={setManualPortfolio} onDiagnosis={() => fullDiag.run(manualPortfolio)} />
      )}
      {fullDiag.result && <FullDiagnosisPanel result={fullDiag.result} report={fullDiag.streamingReport || fullDiag.result.report} streaming={fullDiag.loading && fullDiag.progress?.step === 'llm'} />}
    </div>
  )
}

function usePortfolioData(userId: string | undefined) {
  const whitelist = useWhitelistGate(userId)
  const portfolio = useQuery({
    queryKey: ['portfolio', userId],
    queryFn: () => fetchPortfolio(userId!),
    enabled: !!userId && whitelist.data === true,
  })
  const isWhitelisted = whitelist.data === true
  return {
    isWhitelisted,
    isLoading: whitelist.isLoading || (isWhitelisted && portfolio.isLoading),
    portfolio: portfolio.data || { free_cash: 0, positions: [] },
  }
}

interface DiagProgress {
  step: 'config' | 'kline' | 'llm'
  fetched: number
  total: number
}

function useFullDiagnosisRunner() {
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<FullDiagnosisResult | null>(null)
  const [streamingReport, setStreamingReport] = useState('')
  const [progress, setProgress] = useState<DiagProgress | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const streamBuf = useRef('')
  const rafRef = useRef(0)

  async function run(portfolio: Portfolio) {
    if (!user || loading || portfolio.positions.length === 0) return
    const total = portfolio.positions.length
    const abort = startDiagnosisRun(abortRef, streamBuf, rafRef)
    resetDiagnosisState(setError, setResult, setStreamingReport, setLoading, setProgress, total)
    try {
      const [config, keys] = await Promise.all([loadLLMConfig(user.id), getUserDataKeys(user.id)])
      if (!config) throw new Error(t('portfolio.missingModel'))

      setProgress({ step: 'kline', fetched: 0, total })
      const entries = await fetchAllPositionKlines(portfolio.positions, keys, (n) => setProgress({ step: 'kline', fetched: n, total }))
      if (abort.signal.aborted) return

      setResult(buildDiagnosisResult(entries, '', portfolio.free_cash))
      setProgress({ step: 'llm', fetched: total, total })
      const prompt = buildFullPortfolioPrompt(entries, portfolio.free_cash)
      const onDelta = (chunk: string) => {
        streamBuf.current += chunk
        scheduleStreamingReportFlush(streamBuf, rafRef, setStreamingReport)
      }
      const report = await callFullPortfolioLLM(config, prompt, abort.signal, onDelta)
      cancelAnimationFrame(rafRef.current)
      if (abort.signal.aborted) return
      setStreamingReport(report)
      setResult(buildDiagnosisResult(entries, report, portfolio.free_cash))
    } catch (err) {
      if (abort.signal.aborted) return
      setError(err instanceof Error ? err.message : t('portfolio.failed'))
    } finally {
      finishDiagnosisRun(rafRef, setLoading, setProgress)
    }
  }

  return { loading, error, result, streamingReport, progress, run }
}

function usePortfolioHistory(userId: string | undefined, result: FullDiagnosisResult | null, source: PortfolioHistoryPayload['source']) {
  const savedKey = useRef('')

  useEffect(() => {
    if (!userId || !result?.report) return
    const payload: PortfolioHistoryPayload = { source, result, report: result.report }
    const key = portfolioHistoryKey(payload)
    if (savedKey.current === key) return
    savedKey.current = key
    void saveAnalysisHistory({
      kind: 'portfolio-diagnosis',
      userId,
      title: `${result.summaryStats.count}只持仓诊断`,
      subtitle: `${source === 'database' ? '数据库持仓' : '手动持仓'} · ${formatSignedPct(result.summaryStats.pnlPct)}`,
      symbols: result.positions.map((position) => position.code),
      payload,
    }).catch(() => undefined)
  }, [result, source, userId])
}

function portfolioHistoryKey(payload: PortfolioHistoryPayload): string {
  return `${payload.source}:${payload.result.positions.map((position) => position.code).join(',')}:${payload.report.length}`
}

function formatSignedPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function startDiagnosisRun(
  abortRef: MutableRefObject<AbortController | null>,
  streamBuf: MutableRefObject<string>,
  rafRef: MutableRefObject<number>,
) {
  abortRef.current?.abort()
  cancelAnimationFrame(rafRef.current)
  const abort = new AbortController()
  abortRef.current = abort
  streamBuf.current = ''
  return abort
}

function resetDiagnosisState(
  setError: Dispatch<SetStateAction<string>>,
  setResult: Dispatch<SetStateAction<FullDiagnosisResult | null>>,
  setStreamingReport: Dispatch<SetStateAction<string>>,
  setLoading: Dispatch<SetStateAction<boolean>>,
  setProgress: Dispatch<SetStateAction<DiagProgress | null>>,
  total: number,
) {
  setError('')
  setResult(null)
  setStreamingReport('')
  setLoading(true)
  setProgress({ step: 'config', fetched: 0, total })
}

function finishDiagnosisRun(
  rafRef: MutableRefObject<number>,
  setLoading: Dispatch<SetStateAction<boolean>>,
  setProgress: Dispatch<SetStateAction<DiagProgress | null>>,
) {
  cancelAnimationFrame(rafRef.current)
  setLoading(false)
  setProgress(null)
}

function scheduleStreamingReportFlush(buf: MutableRefObject<string>, raf: MutableRefObject<number>, set: Dispatch<SetStateAction<string>>) {
  if (raf.current) return
  raf.current = requestAnimationFrame(() => {
    raf.current = 0
    set(buf.current)
  })
}

type PositionEntry = { position: Position; kline: KlineRow[]; valueSnapshot: ValueSnapshot }

async function fetchAllPositionKlines(positions: Position[], keys: Awaited<ReturnType<typeof getUserDataKeys>>, onProgress: (n: number) => void): Promise<PositionEntry[]> {
  if (!keys.tickflow) throw new Error(`触发数据源并发请求限制，请升级数据源：${TICKFLOW_PURCHASE}`)
  let fetched = 0
  const entries: PositionEntry[] = []
  const errors: string[] = []
  await Promise.all(
    positions.map(async (p, i) => {
      try {
        const code = normalizeCode(p.code)
        const [kline, valueSnapshot] = await Promise.all([
          fetchKlineViaTickFlow(code, keys.tickflow!),
          fetchValueSnapshotWithFetch(globalThis.fetch, code, keys).catch((): ValueSnapshot => ({ symbol: code, source: 'none', metrics: null, reason: 'not-found' })),
        ])
        if (kline.length > 0) entries.push({ position: positions[i]!, kline, valueSnapshot })
        else errors.push(normalizeCode(p.code))
      } catch (err) {
        errors.push(`${normalizeCode(p.code)}: ${err instanceof Error ? err.message : '失败'}`)
      }
      onProgress(++fetched)
    }),
  )
  if (errors.length > 0) throw new Error(`K 线获取失败: ${errors.join(', ')}`)
  if (entries.length === 0) throw new Error('无法获取任何持仓的 K 线数据')
  entries.sort((a, b) => positions.indexOf(a.position) - positions.indexOf(b.position))
  return entries
}

function buildDiagnosisResult(entries: PositionEntry[], report: string, freeCash: number): FullDiagnosisResult {
  const totalCost = entries.reduce((s, e) => s + Number(e.position.shares || 0) * Number(e.position.cost_price || 0), 0)
  const totalMarket = entries.reduce((s, e) => s + Number(e.position.shares || 0) * (e.kline[e.kline.length - 1]?.close || 0), 0)
  const positions: PositionPnL[] = entries.map((e) => {
    const shares = Number(e.position.shares || 0)
    const cost = Number(e.position.cost_price || 0)
    const latest = e.kline[e.kline.length - 1]?.close || 0
    const costVal = shares * cost
    const mktVal = shares * latest
    return {
      code: normalizeCode(e.position.code), name: e.position.name || normalizeCode(e.position.code),
      shares, cost, latest, costVal, mktVal,
      pnlPct: costVal > 0 ? ((mktVal - costVal) / costVal) * 100 : 0,
      weight: totalMarket > 0 ? (mktVal / totalMarket) * 100 : 0,
    }
  })
  const values: PortfolioValueRow[] = entries.map((e) => {
    const code = normalizeCode(e.position.code)
    return { code, name: e.position.name || code, snapshot: e.valueSnapshot }
  })
  return {
    report, positions, values,
    summaryStats: { totalCost, totalMarket, pnlPct: totalCost > 0 ? ((totalMarket - totalCost) / totalCost) * 100 : 0, freeCash, count: entries.length },
  }
}

function PageHeader() {
  const { t } = usePreferences()
  return (
    <header className="border-b border-border pb-5">
      <h1 className="text-xl font-semibold">{t('portfolio.title')}</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t('portfolio.fullDiagnosisHint')}</p>
    </header>
  )
}

function Holdings({
  portfolio,
  fullLoading,
  progress,
  onFullDiagnosis,
}: {
  portfolio: Portfolio
  fullLoading: boolean
  progress: DiagProgress | null
  onFullDiagnosis: () => void
}) {
  const { t } = usePreferences()
  const totalCost = portfolio.positions.reduce((sum, p) => sum + Number(p.shares || 0) * Number(p.cost_price || 0), 0)
  if (portfolio.positions.length === 0) return <EmptyBox text={t('portfolio.emptyDb')} />

  return (
    <section className="rounded-lg border border-border">
      <div className="flex items-center justify-between border-b border-border bg-muted/30 pr-4">
        <div className="grid flex-1 grid-cols-3 text-sm">
          <Metric label={t('portfolio.freeCash')} value={`¥${portfolio.free_cash.toLocaleString()}`} />
          <Metric label={t('portfolio.positionCost')} value={`¥${totalCost.toLocaleString()}`} />
          <Metric label={t('portfolio.positionCount')} value={String(portfolio.positions.length)} />
        </div>
        <button
          type="button"
          disabled={fullLoading}
          onClick={onFullDiagnosis}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {fullLoading ? <Loader2 size={16} className="animate-spin" /> : <LayoutDashboard size={16} />}
          {fullLoading ? t('portfolio.fullLoading') : t('portfolio.fullDiagnosis')}
        </button>
      </div>
      {progress && <DiagProgressBar progress={progress} />}
      <div className="divide-y divide-border">
        {portfolio.positions.map((position) => (
          <HoldingRow key={String(position.code)} position={position} />
        ))}
      </div>
    </section>
  )
}

function ManualInput({
  portfolio, fullLoading, progress, onChange, onDiagnosis,
}: {
  portfolio: Portfolio; fullLoading: boolean; progress: DiagProgress | null
  onChange: (p: Portfolio) => void; onDiagnosis: () => void
}) {
  const { t } = usePreferences()
  const addPosition = () => onChange({ ...portfolio, positions: [...portfolio.positions, { code: '', name: null, shares: 0, cost_price: 0, buy_dt: null }] })
  const removePosition = (i: number) => onChange({ ...portfolio, positions: portfolio.positions.filter((_, idx) => idx !== i) })
  const updatePosition = (i: number, patch: Partial<Position>) => onChange({ ...portfolio, positions: portfolio.positions.map((p, idx) => idx === i ? { ...p, ...patch } : p) })
  const canDiagnose = portfolio.positions.length > 0 && portfolio.positions.every(isValidManualPosition)

  return (
    <section className="rounded-lg border border-border">
      <div className="flex items-center justify-between border-b border-border bg-muted/30 p-4">
        <div className="space-y-1">
          <label className="text-sm font-medium">{t('portfolio.freeCash')}</label>
          <input type="number" min={0} value={portfolio.free_cash || ''} onChange={(e) => onChange({ ...portfolio, free_cash: Number(e.target.value) || 0 })} className="block w-40 rounded-md border border-border bg-background px-3 py-1.5 text-sm outline-none" placeholder="0" />
        </div>
        <button type="button" disabled={fullLoading || !canDiagnose} onClick={onDiagnosis} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          {fullLoading ? <Loader2 size={16} className="animate-spin" /> : <LayoutDashboard size={16} />}
          {fullLoading ? t('portfolio.fullLoading') : t('portfolio.fullDiagnosis')}
        </button>
      </div>
      {progress && <DiagProgressBar progress={progress} />}
      <div className="divide-y divide-border">
        {portfolio.positions.map((pos, i) => (
          <ManualPositionRow key={i} position={pos} onChange={(patch) => updatePosition(i, patch)} onRemove={() => removePosition(i)} />
        ))}
      </div>
      <button type="button" onClick={addPosition} className="flex w-full items-center justify-center gap-2 border-t border-border py-3 text-sm text-muted-foreground hover:bg-muted/30">
        <Plus size={14} /> {t('portfolio.addPosition')}
      </button>
    </section>
  )
}

function ManualPositionRow({ position, onChange, onRemove }: { position: Position; onChange: (patch: Partial<Position>) => void; onRemove: () => void }) {
  const { t } = usePreferences()
  const cls = 'rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none'
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      <input value={String(position.code)} onChange={(e) => onChange({ code: e.target.value })} placeholder={t('portfolio.code')} className={`${cls} w-28`} />
      <input value={position.name || ''} onChange={(e) => onChange({ name: e.target.value || null })} placeholder={t('portfolio.name')} className={`${cls} w-24`} />
      <input type="number" min={0} value={position.shares || ''} onChange={(e) => onChange({ shares: Number(e.target.value) || 0 })} placeholder={t('portfolio.shares')} className={`${cls} w-20`} />
      <input type="number" min={0} step={0.01} value={position.cost_price || ''} onChange={(e) => onChange({ cost_price: Number(e.target.value) || 0 })} placeholder={t('portfolio.costPrice')} className={`${cls} w-24`} />
      <input type="date" value={position.buy_dt || ''} onChange={(e) => onChange({ buy_dt: e.target.value || null })} className={`${cls} w-36`} aria-label={t('portfolio.buyDate')} />
      <button type="button" onClick={onRemove} className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"><Trash2 size={14} /></button>
    </div>
  )
}

function isValidManualPosition(position: Position): boolean {
  return Boolean(String(position.code).trim()) && Number(position.shares) > 0 && Number(position.cost_price) > 0
}

function DiagProgressBar({ progress }: { progress: DiagProgress }) {
  const { step, fetched, total } = progress
  let pct: number
  let label: string
  if (step === 'config') {
    pct = 5
    label = '加载配置...'
  } else if (step === 'kline') {
    pct = 5 + (total > 0 ? (fetched / total) * 70 : 0)
    label = `拉取 K 线 ${fetched}/${total}`
  } else {
    pct = 80
    label = '等待模型分析...'
  }
  return (
    <div className="border-b border-border bg-muted/10 px-4 py-2.5">
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono text-muted-foreground">{Math.round(pct)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-border">
        <div className="h-full rounded-full bg-indigo-500 transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function HoldingRow({ position }: { position: Position }) {
  const { t } = usePreferences()
  return (
    <div className="grid grid-cols-[1.2fr_0.8fr_0.8fr_0.8fr] items-center gap-3 px-4 py-3 text-sm">
      <div className="min-w-0">
        <div className="truncate font-medium">{position.name || normalizeCode(position.code)}</div>
        <div className="mt-0.5 font-mono text-xs text-muted-foreground">{normalizeCode(position.code)}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">{t('portfolio.shares')}</div>
        <div>{Number(position.shares || 0).toLocaleString()}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">{t('portfolio.costPrice')}</div>
        <div>¥{Number(position.cost_price || 0).toFixed(2)}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">{t('portfolio.buyDate')}</div>
        <div>{position.buy_dt || '-'}</div>
      </div>
    </div>
  )
}

function FullDiagnosisPanel({ result, report, streaming }: { result: FullDiagnosisResult; report: string; streaming: boolean }) {
  const { t } = usePreferences()
  const { summaryStats: s } = result
  return (
    <section className="space-y-4">
      <PnLTable positions={result.positions} stats={s} />
      <PortfolioValuePanel values={result.values} />
      <div className="rounded-lg border border-indigo-200 bg-indigo-50/30 p-5 dark:border-indigo-500/30 dark:bg-indigo-500/5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {streaming ? <Loader2 size={18} className="animate-spin text-indigo-600 dark:text-indigo-400" /> : <LayoutDashboard size={18} className="text-indigo-600 dark:text-indigo-400" />}
          <h2 className="text-base font-semibold">{t('portfolio.fullDiagnosis')}</h2>
        </div>
        <AIDisclaimer />
        <article className="mt-4 prose prose-sm max-w-none text-foreground">
          {report ? <MarkdownContent content={report} /> : <p className="text-sm text-muted-foreground">模型分析中...</p>}
        </article>
      </div>
    </section>
  )
}

function PortfolioValuePanel({ values }: { values: PortfolioValueRow[] }) {
  const { t } = usePreferences()
  const [view, setView] = useState<ValueView>('quality')
  if (values.length === 0) return null
  const rows = [...values].sort((a, b) => buildValueScore(b.snapshot.metrics).score - buildValueScore(a.snapshot.metrics).score)
  return (
    <section className="rounded-lg border border-border p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{t('analysis.valueTitle')}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t('analysis.valueSubtitle')}</p>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-muted/40 p-1" role="tablist" aria-label={t('analysis.valueTitle')}>
          {(['quality', 'risk'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setView(mode)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${view === mode ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              role="tab"
              aria-selected={view === mode}
            >
              {mode === 'quality' ? t('analysis.valueQuality') : t('analysis.valueRisk')}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {rows.map((row) => <PortfolioValueCard key={row.code} row={row} view={view} />)}
      </div>
    </section>
  )
}

function PortfolioValueCard({ row, view }: { row: PortfolioValueRow; view: ValueView }) {
  const { t } = usePreferences()
  const metrics = row.snapshot.metrics
  const value = buildValueScore(metrics, t)
  if (!metrics) {
    return (
      <div className="rounded-lg border border-border p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold">{row.code} {row.name}</h3>
            <p className="mt-1 text-xs text-muted-foreground">{valueUnavailableText(row.snapshot.reason, t)}</p>
          </div>
          <ValueBadge value={value} />
        </div>
      </div>
    )
  }
  const signals = view === 'quality' ? value.strengths : value.risks
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{row.code} {row.name}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{sourceLabel(row.snapshot)}{metrics.period_end ? ` · ${metrics.period_end}` : ''}</p>
        </div>
        <ValueBadge value={value} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-sm md:grid-cols-3">
        <ValueMetricCell label={t('analysis.valueRoe')} value={formatValuePercent(metrics.roe)} tone={numberTone(metrics.roe, 10, 0)} />
        <ValueMetricCell label={t('analysis.valueProfitYoy')} value={formatValuePercent(metrics.net_income_yoy)} tone={numberTone(metrics.net_income_yoy, 0, -10)} />
        <ValueMetricCell label={t('analysis.valueRevenueYoy')} value={formatValuePercent(metrics.revenue_yoy)} tone={numberTone(metrics.revenue_yoy, 0, -10)} />
        <ValueMetricCell label={t('analysis.valueGrossMargin')} value={formatValuePercent(metrics.gross_margin)} tone={numberTone(metrics.gross_margin, 30, 15)} />
        <ValueMetricCell label={t('analysis.valueDebtRatio')} value={formatValuePercent(metrics.debt_to_asset_ratio)} tone={reverseNumberTone(metrics.debt_to_asset_ratio, 55, 70)} />
        <ValueMetricCell label={t('analysis.valueCashRevenue')} value={formatValuePercent(metrics.operating_cash_to_revenue)} tone={numberTone(metrics.operating_cash_to_revenue, 5, 0)} />
      </div>
      <div className="mt-3 space-y-2">
        {signals.length > 0 ? signals.slice(0, 3).map((signal) => (
          <div key={signal.label} className={`rounded-md border px-3 py-2 text-xs ${signalClass(signal.tone)}`}>{signal.label}</div>
        )) : (
          <div className="rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">{t('analysis.valueNoSignals')}</div>
        )}
      </div>
    </div>
  )
}

function ValueMetricCell({ label, value, tone }: { label: string; value: string; tone: ValueTone }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 font-semibold ${metricToneClass(tone)}`}>{value}</div>
    </div>
  )
}

function ValueBadge({ value }: { value: ValueScore }) {
  return <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${valueScoreClass(value.tone)}`}>{value.label}</span>
}

function PnLTable({ positions, stats }: { positions: PositionPnL[]; stats: FullDiagnosisResult['summaryStats'] }) {
  const totalAssets = stats.totalMarket + stats.freeCash
  const cashWeight = totalAssets > 0 ? (stats.freeCash / totalAssets) * 100 : 0
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40">
          <tr>
            {['代码', '名称', '股数', '成本', '现价', '市值', '浮盈', '仓位'].map((h) => (
              <th key={h} scope="col" className="px-3 py-2 text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.code} className="border-t border-border">
              <td className="px-3 py-2 font-mono">{p.code}</td>
              <td className="px-3 py-2">{p.name}</td>
              <td className="px-3 py-2 text-right">{p.shares.toLocaleString()}</td>
              <td className="px-3 py-2 text-right">¥{p.cost.toFixed(2)}</td>
              <td className="px-3 py-2 text-right">¥{p.latest.toFixed(2)}</td>
              <td className="px-3 py-2 text-right">¥{p.mktVal.toLocaleString()}</td>
              <td className={`px-3 py-2 text-right font-medium ${p.pnlPct >= 0 ? 'text-up' : 'text-down'}`}>{p.pnlPct >= 0 ? '+' : ''}{p.pnlPct.toFixed(2)}%</td>
              <td className="px-3 py-2 text-right">{p.weight.toFixed(1)}%</td>
            </tr>
          ))}
          <tr className="border-t-2 border-border bg-muted/20 font-medium">
            <td className="px-3 py-2" colSpan={5}>合计</td>
            <td className="px-3 py-2 text-right">¥{stats.totalMarket.toLocaleString()}</td>
            <td className={`px-3 py-2 text-right ${stats.pnlPct >= 0 ? 'text-up' : 'text-down'}`}>{stats.pnlPct >= 0 ? '+' : ''}{stats.pnlPct.toFixed(2)}%</td>
            <td className="px-3 py-2 text-right">100%</td>
          </tr>
          <tr className="border-t border-border text-muted-foreground">
            <td className="px-3 py-2" colSpan={5}>现金</td>
            <td className="px-3 py-2 text-right">¥{stats.freeCash.toLocaleString()}</td>
            <td className="px-3 py-2" />
            <td className="px-3 py-2 text-right">{cashWeight.toFixed(1)}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-4 py-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-semibold">{value}</div>
    </div>
  )
}

function EmptyBox({ text }: { text: string }) {
  return <div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">{text}</div>
}

function buildFullPortfolioPrompt(entries: PositionEntry[], freeCash: number): string {
  const totalCost = entries.reduce((s, e) => s + Number(e.position.shares || 0) * Number(e.position.cost_price || 0), 0)
  const totalMarket = entries.reduce((s, e) => s + Number(e.position.shares || 0) * (e.kline[e.kline.length - 1]?.close || 0), 0)

  const sections = entries.map(({ position, kline, valueSnapshot }) => {
    const code = normalizeCode(position.code)
    const shares = Number(position.shares || 0)
    const cost = Number(position.cost_price || 0)
    const latest = kline[kline.length - 1]!.close
    const costVal = shares * cost
    const mktVal = shares * latest
    const pnlPct = costVal > 0 ? ((mktVal - costVal) / costVal) * 100 : 0
    const weight = totalCost > 0 ? ((costVal / totalCost) * 100).toFixed(1) : '0'
    const recent = kline.slice(-60)
    const ma5 = avg(kline.slice(-5).map((d) => d.close))
    const ma20 = avg(kline.slice(-20).map((d) => d.close))
    const csv = recent.map((d) => [d.date, d.close.toFixed(2), Math.round(d.volume)].join(',')).join('\n')
    return [
      `## ${code} ${position.name || code}`,
      `${shares}股 成本¥${cost.toFixed(2)} 最新¥${latest.toFixed(2)} 浮盈${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}% 仓位占比${weight}%`,
      `MA5=${ma5.toFixed(2)} MA20=${ma20.toFixed(2)} 60日高=${Math.max(...recent.map((d) => d.high)).toFixed(2)} 60日低=${Math.min(...recent.map((d) => d.low)).toFixed(2)}`,
      buildValueDigest(valueSnapshot),
      '```csv\ndate,close,volume', csv, '```',
    ].join('\n')
  })

  const totalPnl = totalCost > 0 ? ((totalMarket - totalCost) / totalCost) * 100 : 0
  const totalAssets = totalMarket + freeCash
  const cashPct = totalAssets > 0 ? (freeCash / totalAssets) * 100 : 0

  const header = [
    `# 账户概况`,
    `现金 ¥${freeCash.toLocaleString()}（${cashPct.toFixed(1)}%）| 持仓 ${entries.length} 只 | 总成本 ¥${totalCost.toLocaleString()} | 总市值 ¥${totalMarket.toLocaleString()} | 整体盈亏 ${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}%`,
  ].join('\n')

  return [header, '', ...sections].join('\n\n')
}

async function callFullPortfolioLLM(config: Parameters<typeof streamLLMResponse>[0], prompt: string, signal?: AbortSignal, onDelta?: (chunk: string) => void): Promise<string> {
  const result = await streamLLMResponse(config, [
    { role: 'system', content: '你是威科夫资产配置诊断专家。基于用户的全部持仓、真实K线和价值面快照做整体诊断。主框架仍是仓位、趋势和量价结构；价值面只用于校准公司质量、风险暴露和仓位置信度，不要用基本面替代K线事实。输出包含：\n1. 仓位分布评估（集中度、行业分散性）\n2. 各持仓当前威科夫阶段一句话判断，并说明价值面质量/风险如何影响持仓置信度\n3. 现金比例是否合理\n4. 整体风险暴露（哪些持仓需要警惕）\n5. 加减仓优先级建议\n6. 操作建议（先减谁、可加谁、现金该不该动）\n\n用简洁的 Markdown 格式回答。不编造数据。' },
    { role: 'user', content: `请对我的完整持仓做整体诊断和资产配置建议。\n\n${prompt}` },
  ], { temperature: 0.5, maxTokens: 4000, signal, onDelta })
  if (!result) throw new Error('模型未返回结果，请重试')
  return result
}
