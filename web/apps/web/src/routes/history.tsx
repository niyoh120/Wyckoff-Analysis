import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { BarChart3, Briefcase, Clock3, FileText, History, Search, Swords, Trash2, Cpu, Database, Hash, Calendar, ListCollapse, type LucideIcon } from 'lucide-react'
import { MarkdownContent } from '@/components/markdown'
import { KlineChart } from '@/components/kline-chart'
import { MultiStockChart, type ComparisonSeries } from '@/components/multi-stock-chart'
import { clearAllAnalysisHistory, clearAnalysisHistory, deleteAnalysisHistory, listAllAnalysisHistory, type AnalysisHistoryKind, type AnalysisHistoryRecord } from '@/lib/local-history'
import { formatValuePercent } from '@/lib/value-analysis'
import { usePreferences, type Locale } from '@/lib/preferences'
import { useAuthStore } from '@/stores/auth'
import { sourceLabel, type KlineRow, type ValueSnapshot } from '@wyckoff/shared'

type FilterKey = 'all' | AnalysisHistoryKind
type HistoryRecord = AnalysisHistoryRecord<HistoryPayload>
type HistoryPayload = SinglePayload | BattlePayload | PortfolioPayload | Record<string, unknown>

interface TraceMeta {
  inputSnapshotHash?: string
  promptVersion?: string
  model?: string
  generatedAt?: string
  valueSource?: string
  reportDate?: string
  klineRows?: number
}

interface SinglePayload {
  report: string
  symbol: string
  name: string
  klineData: KlineRow[]
  valueSnapshot: ValueSnapshot
  meta?: TraceMeta
}

interface BattlePayload {
  input: string
  stocks: BattleStockPayload[]
  selectedCodes: string[]
  mode: string
  overlayLimit: number
  report: string
  benchmark: KlineRow[]
  meta?: TraceMeta
}

interface BattleStockPayload {
  code: string
  name: string
  data: KlineRow[]
  stats: { ret20: number; ret60: number; ret120: number; drawdown60: number; volumeRatio: number; score: number }
  valueSnapshot: ValueSnapshot
}

interface PortfolioPayload {
  source: 'database' | 'manual'
  result: PortfolioResultPayload
  report: string
  meta?: TraceMeta
}

interface PortfolioResultPayload {
  report: string
  positions: PortfolioPositionPayload[]
  values: { code: string; name: string; snapshot: ValueSnapshot }[]
  summaryStats: { totalCost: number; totalMarket: number; pnlPct: number; freeCash: number; count: number }
}

interface PortfolioPositionPayload {
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

interface MetricItem {
  label: string
  value: string
  tone?: 'up' | 'down' | 'neutral'
}

interface HistoryCopy {
  title: string
  subtitle: string
  localOnly: string
  search: string
  all: string
  single: string
  battle: string
  portfolio: string
  emptyTitle: string
  emptyDesc: string
  clear: string
  clearConfirm: string
  delete: string
  deleteConfirm: string
  expiredTitle: string
  expiredDesc: string
  report: string
  chart: string
  value: string
  positions: string
  stocks: string
  input: string
}

const copyByLocale = {
  'zh-CN': {
    title: '分析历史',
    subtitle: '单股分析、多股对抗、持仓诊断都会保存在当前浏览器，方便回看图表、关键指标和报告正文。',
    localOnly: '仅本机浏览器保存，不写入数据库',
    search: '搜索代码、名称或报告内容',
    all: '全部',
    single: '单股',
    battle: '多股',
    portfolio: '持仓',
    emptyTitle: '还没有分析历史',
    emptyDesc: '完成一次单股分析、多股对抗或持仓诊断后，这里会自动出现可回看的详情。',
    clear: '清空当前筛选',
    clearConfirm: '确认清空当前筛选下的分析历史？',
    delete: '删除',
    deleteConfirm: '确认删除这条分析历史？',
    expiredTitle: '这条历史记录格式已过期',
    expiredDesc: '这通常来自旧版本浏览器缓存或不完整写入，可以删除后重新分析。',
    report: 'AI 报告',
    chart: '结构图',
    value: '价值快照',
    positions: '持仓明细',
    stocks: '对抗标的',
    input: '原始输入',
  },
  'en-US': {
    title: 'Analysis History',
    subtitle: 'Single-stock analysis, stock battle, and portfolio diagnosis are stored in this browser for chart, metric, and report review.',
    localOnly: 'Stored only in this browser; not written to the database',
    search: 'Search symbol, name, or report text',
    all: 'All',
    single: 'Single',
    battle: 'Battle',
    portfolio: 'Portfolio',
    emptyTitle: 'No analysis history yet',
    emptyDesc: 'Run a stock analysis, battle, or portfolio diagnosis, and the details will appear here automatically.',
    clear: 'Clear filter',
    clearConfirm: 'Clear analysis history under the current filter?',
    delete: 'Delete',
    deleteConfirm: 'Delete this history record?',
    expiredTitle: 'This history record format is outdated',
    expiredDesc: 'This usually comes from older browser cache or an incomplete write. Delete it and run the analysis again.',
    report: 'AI Report',
    chart: 'Structure Chart',
    value: 'Value Snapshot',
    positions: 'Positions',
    stocks: 'Battle Symbols',
    input: 'Original Input',
  },
} satisfies Record<Locale, HistoryCopy>

export function HistoryPage() {
  const user = useAuthStore((s) => s.user)
  const { locale } = usePreferences()
  const copy = copyByLocale[locale]
  const history = useHistoryRecords(user?.id)
  const [filter, setFilter] = useState<FilterKey>('all')
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => filterRecords(history.records, filter, query), [history.records, filter, query])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = filtered.find((record) => record.id === selectedId) ?? filtered[0] ?? null

  useEffect(() => {
    if (!selected || selected.id === selectedId) return
    setSelectedId(selected.id)
  }, [selected, selectedId])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <HistoryHeader copy={copy} total={history.records.length} />
      <HistoryToolbar copy={copy} records={history.records} filter={filter} query={query} setFilter={setFilter} setQuery={setQuery} onClear={() => history.clear(filter)} />
      <div className="grid min-h-0 flex-1 border-t border-border lg:grid-cols-[420px_minmax(0,1fr)]">
        <HistoryList copy={copy} records={filtered} selectedId={selected?.id ?? null} loading={history.loading} onSelect={setSelectedId} />
        <HistoryDetail copy={copy} record={selected} onDelete={history.remove} />
      </div>
    </div>
  )
}

function useHistoryRecords(userId: string | undefined) {
  const [records, setRecords] = useState<HistoryRecord[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setRecords(await listAllAnalysisHistory<HistoryPayload>(userId))
    } finally {
      setLoading(false)
    }
  }, [userId])

  async function remove(id: string) {
    await deleteAnalysisHistory(id)
    setRecords((rows) => rows.filter((row) => row.id !== id))
  }

  async function clear(filter: FilterKey) {
    if (filter === 'all') await clearAllAnalysisHistory(userId)
    else await clearAnalysisHistory(filter, userId)
    await refresh()
  }

  useEffect(() => { void refresh() }, [refresh])
  return { records, loading, remove, clear }
}

function HistoryHeader({ copy, total }: { copy: HistoryCopy; total: number }) {
  return (
    <header className="border-b border-border px-6 py-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold"><History size={21} />{copy.title}</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{copy.subtitle}</p>
        </div>
        <div className="rounded-lg border border-border px-3 py-2 text-right text-sm">
          <div className="font-semibold">{total}</div>
          <div className="text-xs text-muted-foreground">{copy.localOnly}</div>
        </div>
      </div>
    </header>
  )
}

function HistoryToolbar({
  copy, records, filter, query, setFilter, setQuery, onClear,
}: {
  copy: HistoryCopy
  records: HistoryRecord[]
  filter: FilterKey
  query: string
  setFilter: (filter: FilterKey) => void
  setQuery: (query: string) => void
  onClear: () => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3">
      <HistoryFilterTabs copy={copy} records={records} value={filter} onChange={setFilter} />
      <div className="flex flex-1 items-center justify-end gap-2">
        <SearchBox copy={copy} value={query} onChange={setQuery} />
        {records.length > 0 && <button type="button" onClick={() => { if (window.confirm(copy.clearConfirm)) onClear() }} className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground hover:text-destructive">{copy.clear}</button>}
      </div>
    </div>
  )
}

function HistoryFilterTabs({ copy, records, value, onChange }: { copy: HistoryCopy; records: HistoryRecord[]; value: FilterKey; onChange: (filter: FilterKey) => void }) {
  const counts = countByKind(records)
  const tabs: [FilterKey, string, number][] = [['all', copy.all, records.length], ['single-analysis', copy.single, counts['single-analysis']], ['stock-battle', copy.battle, counts['stock-battle']], ['portfolio-diagnosis', copy.portfolio, counts['portfolio-diagnosis']]]
  return (
    <div className="inline-flex rounded-lg border border-border bg-muted/30 p-1">
        {tabs.map(([key, label, count]) => (
        <button key={key} type="button" onClick={() => onChange(key)} aria-pressed={value === key} className={`rounded-md px-3 py-1.5 text-sm ${value === key ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
          {label} <span className="ml-1 text-xs opacity-70">{count}</span>
        </button>
      ))}
    </div>
  )
}

function SearchBox({ copy, value, onChange }: { copy: HistoryCopy; value: string; onChange: (value: string) => void }) {
  return (
    <div className="relative min-w-[220px] max-w-md flex-1">
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <input value={value} onChange={(event) => onChange(event.target.value)} aria-label={copy.search} placeholder={copy.search} className="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring/20" />
    </div>
  )
}

function HistoryList({ copy, records, selectedId, loading, onSelect }: { copy: HistoryCopy; records: HistoryRecord[]; selectedId: string | null; loading: boolean; onSelect: (id: string) => void }) {
  if (loading) return <aside className="border-r border-border p-6 text-sm text-muted-foreground">Loading...</aside>
  if (records.length === 0) return <EmptyList copy={copy} />
  return (
    <aside className="min-h-0 overflow-auto border-r border-border bg-sidebar/40 p-3">
      <div className="space-y-2">
        {records.map((record) => <HistoryListItem key={record.id} copy={copy} record={record} selected={record.id === selectedId} onSelect={() => onSelect(record.id)} />)}
      </div>
    </aside>
  )
}

function EmptyList({ copy }: { copy: HistoryCopy }) {
  return (
    <aside className="flex border-r border-border p-6">
      <div className="m-auto max-w-xs text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"><FileText size={18} /></div>
        <h2 className="text-sm font-semibold">{copy.emptyTitle}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{copy.emptyDesc}</p>
      </div>
    </aside>
  )
}

function HistoryListItem({ copy, record, selected, onSelect }: { copy: HistoryCopy; record: HistoryRecord; selected: boolean; onSelect: () => void }) {
  const metrics = recordMetrics(record)
  return (
    <button type="button" onClick={onSelect} className={`block w-full rounded-lg border p-3 text-left transition ${selected ? 'border-primary bg-primary/5 shadow-sm' : 'border-border bg-background hover:border-primary/40'}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <KindBadge copy={copy} kind={record.kind} />
        <span className="flex items-center gap-1 text-[11px] text-muted-foreground"><Clock3 size={12} />{formatHistoryTime(record.createdAt)}</span>
      </div>
      <h3 className="truncate text-sm font-semibold">{record.title}</h3>
      <p className="mt-1 truncate text-xs text-muted-foreground">{record.subtitle || record.symbols.join(', ')}</p>
      <SymbolChips symbols={record.symbols} />
      <MetricStrip metrics={metrics} />
      <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{reportExcerpt(record) || '--'}</p>
    </button>
  )
}

function KindBadge({ copy, kind }: { copy: HistoryCopy; kind: AnalysisHistoryKind }) {
  const Icon = kindIcon(kind)
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${kindTone(kind)}`}>
      <Icon size={13} />
      {kindLabel(copy, kind)}
    </span>
  )
}

function SymbolChips({ symbols }: { symbols: string[] }) {
  if (symbols.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {symbols.slice(0, 5).map((symbol) => <span key={symbol} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{symbol}</span>)}
      {symbols.length > 5 && <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">+{symbols.length - 5}</span>}
    </div>
  )
}

function MetricStrip({ metrics }: { metrics: MetricItem[] }) {
  return (
    <div className="mt-3 grid grid-cols-3 gap-2">
      {metrics.slice(0, 3).map((metric) => (
        <div key={metric.label} className="min-w-0 rounded-md bg-muted/50 px-2 py-1.5">
          <div className="truncate text-[10px] text-muted-foreground">{metric.label}</div>
          <div className={`truncate text-xs font-semibold ${metricClass(metric.tone)}`}>{metric.value}</div>
        </div>
      ))}
    </div>
  )
}

function HistoryDetail({ copy, record, onDelete }: { copy: HistoryCopy; record: HistoryRecord | null; onDelete: (id: string) => void }) {
  if (!record) return <section className="p-6 text-sm text-muted-foreground">{copy.emptyDesc}</section>
  return (
    <section className="flex min-h-0 flex-col">
      <DetailHeader copy={copy} record={record} onDelete={onDelete} />
      <div className="min-h-0 flex-1 overflow-auto p-5">
        {record.kind === 'single-analysis' && <SingleDetail copy={copy} payload={singlePayload(record)} />}
        {record.kind === 'stock-battle' && <BattleDetail copy={copy} payload={battlePayload(record)} />}
        {record.kind === 'portfolio-diagnosis' && <PortfolioDetail copy={copy} payload={portfolioPayload(record)} />}
      </div>
    </section>
  )
}

function DetailHeader({ copy, record, onDelete }: { copy: HistoryCopy; record: HistoryRecord; onDelete: (id: string) => void }) {
  function handleDelete() {
    if (window.confirm(copy.deleteConfirm)) void onDelete(record.id)
  }
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
      <div>
        <div className="mb-2 flex items-center gap-2"><KindBadge copy={copy} kind={record.kind} /><span className="text-xs text-muted-foreground">{formatFullTime(record.createdAt)}</span></div>
        <h2 className="text-lg font-semibold">{record.title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{record.subtitle}</p>
      </div>
      <button type="button" onClick={handleDelete} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:text-destructive">
        <Trash2 size={15} />{copy.delete}
      </button>
    </div>
  )
}

function SingleDetail({ copy, payload }: { copy: HistoryCopy; payload: SinglePayload | null }) {
  if (!payload) return <ExpiredRecord copy={copy} />
  const latest = payload.klineData.at(-1)
  const metrics = [{ label: '代码', value: payload.symbol }, { label: '最新价', value: formatNumber(latest?.close) }, { label: 'K线', value: `${payload.klineData.length}` }, { label: '价值源', value: sourceLabel(payload.valueSnapshot) }]
  return (
    <div className="space-y-5">
      <SummaryGrid items={metrics} />
      <HistoryTracePanel meta={payload.meta} />
      <Section title={copy.chart}>{payload.klineData.length > 0 && <KlineChart data={payload.klineData} height={360} />}</Section>
      <ValueSnapshotBlock title={copy.value} snapshot={payload.valueSnapshot} />
      <ReportBlock title={copy.report} report={payload.report} />
    </div>
  )
}

function BattleDetail({ copy, payload }: { copy: HistoryCopy; payload: BattlePayload | null }) {
  if (!payload) return <ExpiredRecord copy={copy} />
  const strongest = strongestBattleStock(payload)
  const metrics = [{ label: '标的', value: `${payload.stocks.length}` }, { label: '已选', value: `${payload.selectedCodes.length}` }, { label: '最强', value: strongest ? `${strongest.code} ${strongest.stats.score.toFixed(1)}` : '--' }, { label: '模式', value: payload.mode }]
  return (
    <div className="space-y-5">
      <SummaryGrid items={metrics} />
      <HistoryTracePanel meta={payload.meta} />
      <Section title={copy.chart}><BattleChart payload={payload} /></Section>
      <BattleStockTable copy={copy} stocks={payload.stocks} />
      <Section title={copy.input}><pre className="whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">{payload.input}</pre></Section>
      <ReportBlock title={copy.report} report={payload.report} />
    </div>
  )
}

function PortfolioDetail({ copy, payload }: { copy: HistoryCopy; payload: PortfolioPayload | null }) {
  if (!payload) return <ExpiredRecord copy={copy} />
  const result = payload.result
  const metrics = [{ label: '持仓', value: `${result.summaryStats.count}` }, { label: '总市值', value: formatMoney(result.summaryStats.totalMarket) }, { label: '现金', value: formatMoney(result.summaryStats.freeCash) }, { label: '盈亏', value: formatPercent(result.summaryStats.pnlPct), tone: pnlTone(result.summaryStats.pnlPct) }]
  return (
    <div className="space-y-5">
      <SummaryGrid items={metrics} />
      <HistoryTracePanel meta={payload.meta} />
      <PortfolioPositionTable copy={copy} positions={result.positions} />
      <PortfolioValueTable title={copy.value} values={result.values} />
      <ReportBlock title={copy.report} report={payload.report || result.report} />
    </div>
  )
}

function HistoryTracePanel({ meta }: { meta?: TraceMeta }) {
  if (!meta || !meta.inputSnapshotHash) return null
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground/80">
        <Cpu size={14} className="text-primary/70" />
        分析溯源信息 (Report Trace Panel)
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-xs">
        <div className="flex items-center gap-2 rounded bg-background p-2 border border-border">
          <Hash size={14} className="text-muted-foreground shrink-0" />
          <div className="truncate">
            <div className="text-muted-foreground scale-95 origin-left">输入快照 Hash</div>
            <div className="font-mono font-medium text-foreground select-all mt-0.5">{meta.inputSnapshotHash}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded bg-background p-2 border border-border">
          <Cpu size={14} className="text-muted-foreground shrink-0" />
          <div className="truncate">
            <div className="text-muted-foreground scale-95 origin-left">AI 模型 / 提示词版本</div>
            <div className="font-medium text-foreground mt-0.5">{meta.model} ({meta.promptVersion || 'v1.0'})</div>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded bg-background p-2 border border-border">
          <Calendar size={14} className="text-muted-foreground shrink-0" />
          <div className="truncate">
            <div className="text-muted-foreground scale-95 origin-left">生成时间</div>
            <div className="font-medium text-foreground mt-0.5">{new Date(meta.generatedAt || '').toLocaleString()}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded bg-background p-2 border border-border">
          <Database size={14} className="text-muted-foreground shrink-0" />
          <div className="truncate">
            <div className="text-muted-foreground scale-95 origin-left">基本面源 / 报告期</div>
            <div className="font-medium text-foreground mt-0.5">{meta.valueSource || 'N/A'} ({meta.reportDate || 'N/A'})</div>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded bg-background p-2 border border-border">
          <ListCollapse size={14} className="text-muted-foreground shrink-0" />
          <div className="truncate">
            <div className="text-muted-foreground scale-95 origin-left">历史行情长度</div>
            <div className="font-medium text-foreground mt-0.5">{meta.klineRows ? `${meta.klineRows} 行` : 'N/A'}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function SummaryGrid({ items }: { items: MetricItem[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border border-border bg-background p-3">
          <div className="text-xs text-muted-foreground">{item.label}</div>
          <div className={`mt-1 truncate text-base font-semibold ${metricClass(item.tone)}`}>{item.value}</div>
        </div>
      ))}
    </div>
  )
}

function ExpiredRecord({ copy }: { copy: HistoryCopy }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6">
      <h3 className="text-sm font-semibold">{copy.expiredTitle}</h3>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{copy.expiredDesc}</p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-background p-4">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

function ValueSnapshotBlock({ title, snapshot }: { title: string; snapshot: ValueSnapshot }) {
  const metrics = snapshot.metrics
  if (!metrics) return <Section title={title}><p className="text-sm text-muted-foreground">--</p></Section>
  const rows = [['ROE', formatValuePercent(metrics.roe)], ['净利润同比', formatValuePercent(metrics.net_income_yoy)], ['营收同比', formatValuePercent(metrics.revenue_yoy)], ['毛利率', formatValuePercent(metrics.gross_margin)], ['资产负债率', formatValuePercent(metrics.debt_to_asset_ratio)], ['现金流/营收', formatValuePercent(metrics.operating_cash_to_revenue)]]
  return (
    <Section title={`${title} · ${sourceLabel(snapshot)}`}>
      <div className="grid gap-2 sm:grid-cols-3">
        {rows.map(([label, value]) => <div key={label} className="rounded-md bg-muted/50 px-3 py-2"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 font-semibold">{value}</div></div>)}
      </div>
    </Section>
  )
}

function BattleChart({ payload }: { payload: BattlePayload }) {
  const series = battleSeries(payload)
  if (series.length === 0) return <p className="text-sm text-muted-foreground">--</p>
  return <MultiStockChart series={series} />
}

function BattleStockTable({ copy, stocks }: { copy: HistoryCopy; stocks: BattleStockPayload[] }) {
  const rows = [...stocks].sort((a, b) => b.stats.score - a.stats.score)
  return (
    <Section title={copy.stocks}>
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground"><tr>{['代码', '名称', '强度', '20D', '60D', '120D', '回撤'].map((head) => <th key={head} className="px-2 py-2 text-left font-medium">{head}</th>)}</tr></thead>
          <tbody>{rows.map((stock) => <tr key={stock.code} className="border-t border-border"><td className="px-2 py-2 font-mono">{stock.code}</td><td className="px-2 py-2">{stock.name}</td><td className="px-2 py-2 font-semibold">{stock.stats.score.toFixed(1)}</td><td className="px-2 py-2">{formatPercent(stock.stats.ret20)}</td><td className="px-2 py-2">{formatPercent(stock.stats.ret60)}</td><td className="px-2 py-2">{formatPercent(stock.stats.ret120)}</td><td className="px-2 py-2">{formatPercent(stock.stats.drawdown60)}</td></tr>)}</tbody>
        </table>
      </div>
    </Section>
  )
}

function PortfolioPositionTable({ copy, positions }: { copy: HistoryCopy; positions: PortfolioPositionPayload[] }) {
  return (
    <Section title={copy.positions}>
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground"><tr>{['代码', '名称', '股数', '成本', '现价', '市值', '盈亏', '仓位'].map((head) => <th key={head} className="px-2 py-2 text-left font-medium">{head}</th>)}</tr></thead>
          <tbody>{positions.map((row) => <tr key={row.code} className="border-t border-border"><td className="px-2 py-2 font-mono">{row.code}</td><td className="px-2 py-2">{row.name}</td><td className="px-2 py-2">{row.shares.toLocaleString()}</td><td className="px-2 py-2">{formatNumber(row.cost)}</td><td className="px-2 py-2">{formatNumber(row.latest)}</td><td className="px-2 py-2">{formatMoney(row.mktVal)}</td><td className={`px-2 py-2 font-semibold ${metricClass(pnlTone(row.pnlPct))}`}>{formatPercent(row.pnlPct)}</td><td className="px-2 py-2">{formatUnsignedPercent(row.weight)}</td></tr>)}</tbody>
        </table>
      </div>
    </Section>
  )
}

function PortfolioValueTable({ title, values }: { title: string; values: PortfolioResultPayload['values'] }) {
  if (values.length === 0) return null
  return (
    <Section title={title}>
      <div className="grid gap-2 md:grid-cols-2">
        {values.map(({ code, name, snapshot }) => <ValueMiniRow key={code} code={code} name={name} snapshot={snapshot} />)}
      </div>
    </Section>
  )
}

function ValueMiniRow({ code, name, snapshot }: { code: string; name: string; snapshot: ValueSnapshot }) {
  const metrics = snapshot.metrics
  return (
    <div className="rounded-md border border-border p-3 text-sm">
      <div className="flex items-center justify-between gap-2"><span className="font-medium">{code} {name}</span><span className="text-xs text-muted-foreground">{sourceLabel(snapshot)}</span></div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-muted-foreground">
        <span>ROE {formatValuePercent(metrics?.roe)}</span>
        <span>利润 {formatValuePercent(metrics?.net_income_yoy)}</span>
        <span>负债 {formatValuePercent(metrics?.debt_to_asset_ratio)}</span>
      </div>
    </div>
  )
}

function ReportBlock({ title, report }: { title: string; report: string }) {
  return (
    <Section title={title}>
      <article className="prose prose-sm max-w-none text-foreground"><MarkdownContent content={report || '--'} /></article>
    </Section>
  )
}

function filterRecords(records: HistoryRecord[], filter: FilterKey, query: string): HistoryRecord[] {
  const normalized = query.trim().toLowerCase()
  return records.filter((record) => {
    if (filter !== 'all' && record.kind !== filter) return false
    if (!normalized) return true
    return searchableText(record).includes(normalized)
  })
}

function searchableText(record: HistoryRecord): string {
  return [record.title, record.subtitle, record.symbols.join(' '), reportExcerpt(record)].join(' ').toLowerCase()
}

function recordMetrics(record: HistoryRecord): MetricItem[] {
  if (record.kind === 'single-analysis') {
    const payload = singlePayload(record)
    return payload ? singleMetrics(payload) : []
  }
  if (record.kind === 'stock-battle') {
    const payload = battlePayload(record)
    return payload ? battleMetrics(payload) : []
  }
  const payload = portfolioPayload(record)
  return payload ? portfolioMetrics(payload) : []
}

function singleMetrics(payload: SinglePayload): MetricItem[] {
  const latest = payload.klineData.at(-1)
  return [{ label: '最新价', value: formatNumber(latest?.close) }, { label: 'K线', value: `${payload.klineData.length}` }, { label: '价值源', value: sourceLabel(payload.valueSnapshot) }]
}

function battleMetrics(payload: BattlePayload): MetricItem[] {
  const strongest = strongestBattleStock(payload)
  return [{ label: '标的', value: `${payload.stocks.length}` }, { label: '最强', value: strongest?.code || '--' }, { label: '强度', value: strongest ? strongest.stats.score.toFixed(1) : '--' }]
}

function portfolioMetrics(payload: PortfolioPayload): MetricItem[] {
  const stats = payload.result.summaryStats
  return [{ label: '持仓', value: `${stats.count}` }, { label: '盈亏', value: formatPercent(stats.pnlPct), tone: pnlTone(stats.pnlPct) }, { label: '市值', value: formatCompactMoney(stats.totalMarket) }]
}

function countByKind(records: HistoryRecord[]): Record<AnalysisHistoryKind, number> {
  return {
    'single-analysis': records.filter((record) => record.kind === 'single-analysis').length,
    'stock-battle': records.filter((record) => record.kind === 'stock-battle').length,
    'portfolio-diagnosis': records.filter((record) => record.kind === 'portfolio-diagnosis').length,
  }
}

function reportExcerpt(record: HistoryRecord): string {
  const single = singlePayload(record)
  const battle = battlePayload(record)
  const portfolio = portfolioPayload(record)
  const report = single?.report || battle?.report || portfolio?.report || portfolio?.result.report || ''
  return stripMarkdown(report).slice(0, 180)
}

function singlePayload(record: HistoryRecord): SinglePayload | null {
  const payload = record.payload
  return isObject(payload)
    && typeof payload.report === 'string'
    && typeof payload.symbol === 'string'
    && typeof payload.name === 'string'
    && Array.isArray(payload.klineData)
    && isValueSnapshot(payload.valueSnapshot)
    ? payload as unknown as SinglePayload
    : null
}

function battlePayload(record: HistoryRecord): BattlePayload | null {
  const payload = record.payload
  return isObject(payload)
    && typeof payload.input === 'string'
    && typeof payload.report === 'string'
    && typeof payload.mode === 'string'
    && typeof payload.overlayLimit === 'number'
    && Array.isArray(payload.selectedCodes)
    && Array.isArray(payload.benchmark)
    && Array.isArray(payload.stocks)
    && payload.stocks.every(isBattleStockPayload)
    ? payload as unknown as BattlePayload
    : null
}

function portfolioPayload(record: HistoryRecord): PortfolioPayload | null {
  const payload = record.payload
  return isObject(payload)
    && (payload.source === 'database' || payload.source === 'manual')
    && typeof payload.report === 'string'
    && isPortfolioResultPayload(payload.result)
    ? payload as unknown as PortfolioPayload
    : null
}

function isBattleStockPayload(value: unknown): value is BattleStockPayload {
  return isObject(value)
    && typeof value.code === 'string'
    && typeof value.name === 'string'
    && Array.isArray(value.data)
    && isObject(value.stats)
    && typeof value.stats.score === 'number'
    && typeof value.stats.ret20 === 'number'
    && typeof value.stats.ret60 === 'number'
    && typeof value.stats.ret120 === 'number'
    && typeof value.stats.drawdown60 === 'number'
    && typeof value.stats.volumeRatio === 'number'
    && isValueSnapshot(value.valueSnapshot)
}

function isPortfolioResultPayload(value: unknown): value is PortfolioResultPayload {
  return isObject(value)
    && typeof value.report === 'string'
    && Array.isArray(value.positions)
    && value.positions.every(isPortfolioPositionPayload)
    && Array.isArray(value.values)
    && isObject(value.summaryStats)
    && typeof value.summaryStats.totalCost === 'number'
    && typeof value.summaryStats.totalMarket === 'number'
    && typeof value.summaryStats.pnlPct === 'number'
    && typeof value.summaryStats.freeCash === 'number'
    && typeof value.summaryStats.count === 'number'
}

function isPortfolioPositionPayload(value: unknown): value is PortfolioPositionPayload {
  return isObject(value)
    && typeof value.code === 'string'
    && typeof value.name === 'string'
    && typeof value.shares === 'number'
    && typeof value.cost === 'number'
    && typeof value.latest === 'number'
    && typeof value.mktVal === 'number'
    && typeof value.pnlPct === 'number'
    && typeof value.weight === 'number'
}

function isValueSnapshot(value: unknown): value is ValueSnapshot {
  return isObject(value) && typeof value.source === 'string'
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function stripMarkdown(value: string): string {
  return value.replace(/```[\s\S]*?```/g, ' ').replace(/[#>*_`|[\]-]/g, ' ').replace(/\s+/g, ' ').trim()
}

function kindLabel(copy: HistoryCopy, kind: AnalysisHistoryKind): string {
  if (kind === 'single-analysis') return copy.single
  if (kind === 'stock-battle') return copy.battle
  return copy.portfolio
}

function kindIcon(kind: AnalysisHistoryKind): LucideIcon {
  if (kind === 'single-analysis') return BarChart3
  if (kind === 'stock-battle') return Swords
  return Briefcase
}

function kindTone(kind: AnalysisHistoryKind): string {
  if (kind === 'single-analysis') return 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-300'
  if (kind === 'stock-battle') return 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300'
  return 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
}

function battleSeries(payload: BattlePayload): ComparisonSeries[] {
  const series = payload.stocks.slice(0, Math.max(1, payload.overlayLimit || 6)).map((stock) => ({ code: stock.code, name: stock.name, data: stock.data }))
  if (payload.benchmark?.length) series.push({ code: '399300', name: '沪深300', data: payload.benchmark })
  return series
}

function strongestBattleStock(payload: BattlePayload): BattleStockPayload | null {
  return [...payload.stocks].sort((a, b) => b.stats.score - a.stats.score)[0] ?? null
}

function metricClass(tone: MetricItem['tone']): string {
  if (tone === 'up') return 'text-up'
  if (tone === 'down') return 'text-down'
  return ''
}

function pnlTone(value: number): MetricItem['tone'] {
  return value >= 0 ? 'up' : 'down'
}

function formatHistoryTime(value: string): string {
  return new Date(value).toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatFullTime(value: string): string {
  return new Date(value).toLocaleString()
}

function formatNumber(value: number | undefined): string {
  return Number.isFinite(value) ? (value as number).toFixed(2) : '--'
}

function formatPercent(value: number | undefined): string {
  return Number.isFinite(value) ? `${(value as number) >= 0 ? '+' : ''}${(value as number).toFixed(2)}%` : '--'
}

function formatUnsignedPercent(value: number | undefined): string {
  return Number.isFinite(value) ? `${(value as number).toFixed(2)}%` : '--'
}

function formatMoney(value: number | undefined): string {
  return Number.isFinite(value) ? `¥${Math.round(value as number).toLocaleString()}` : '--'
}

function formatCompactMoney(value: number | undefined): string {
  if (!Number.isFinite(value)) return '--'
  const numeric = value as number
  if (Math.abs(numeric) >= 10000) return `¥${(numeric / 10000).toFixed(1)}万`
  return `¥${Math.round(numeric).toLocaleString()}`
}
