import { useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { checkWhitelist } from '@/lib/kline'
import { WyckoffLoading } from '@/components/loading'
import { financialValueClass } from '@/lib/financial-colors'
import { useAuthStore } from '@/stores/auth'

type JsonMap = Record<string, unknown>

interface AttributionReport {
  report_date: string
  market: string
  window_start: string
  window_end: string
  horizons: number[]
  signal_stats_json: Record<string, Record<string, MetricStats>>
  score_bucket_stats_json?: JsonMap
  shadow_diff_stats_json: JsonMap
  top_winners_json: StockOutcome[]
  top_losers_json: StockOutcome[]
  recommendations_json: AttributionRecommendation[]
  created_at: string
}

interface MetricStats {
  count?: number
  avg_return_pct?: number
  median_return_pct?: number
  win_rate_pct?: number
  big_win_rate_pct?: number
  big_loss_rate_pct?: number
  avg_drawdown_pct?: number | null
}

interface ObservationCoverageMetric {
  observations?: number
  with_any_outcome?: number
  outcome_coverage_pct?: number
  features_coverage_pct?: number
  current_like_pct?: number
  legacy_like_pct?: number
  latest_trade_date?: string
  h1_coverage_pct?: number
  h3_coverage_pct?: number
  h5_coverage_pct?: number
  h10_coverage_pct?: number
  h20_coverage_pct?: number
}

interface StockOutcome {
  trade_date?: string
  code?: string
  name?: string | null
  signal_type?: string
  track?: string
  return_pct?: number
  candidate_shadow_score?: number | null
  candidate_shadow_grade?: string | null
  data_lineage_coverage_score?: number | null
  data_lineage_coverage_grade?: string | null
  data_lineage_evidence_keys?: string[] | null
  selection_mode?: string | null
  strategy_version?: string | null
  candidate_lane?: string | null
  entry_type?: string | null
}

interface AttributionRecommendation {
  type?: string
  horizon?: string
  target?: string
  reason?: string
}

async function fetchLatestReport(): Promise<AttributionReport | null> {
  const { data, error } = await supabase
    .from('strategy_attribution_reports')
    .select('*')
    .eq('market', 'cn')
    .order('report_date', { ascending: false })
    .limit(1)
    .maybeSingle()
  if (error) throw new Error(error.message)
  return data
}

export function AttributionPage() {
  const user = useAuthStore((s) => s.user)
  const userId = user?.id
  const whitelist = useQuery({
    queryKey: ['whitelist', userId],
    queryFn: () => checkWhitelist(userId || ''),
    enabled: !!userId,
  })
  const report = useQuery({
    queryKey: ['strategy-attribution-report'],
    queryFn: fetchLatestReport,
    enabled: whitelist.data === true,
  })

  if (whitelist.isLoading) return <WyckoffLoading />
  if (whitelist.data !== true) return <LockedView />
  if (report.isLoading) return <WyckoffLoading />

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Strategy Attribution</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">策略归因报告</h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            固定周期结果、形态表现、分数分桶和 shadow 差异的聚合视图。这里只展示分析快照，不参与漏斗出股。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void report.refetch()}
          className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <RefreshCw size={15} />
          刷新
        </button>
      </div>
      {report.error ? <ErrorBox message={report.error.message} /> : report.data ? <ReportView report={report.data} /> : <EmptyView />}
    </div>
  )
}

function ReportView({ report }: { report: AttributionReport }) {
  const signalRows = useMemo(() => flattenSignalStats(report.signal_stats_json), [report.signal_stats_json])
  const candidateShadowRows = useMemo(
    () => flattenCandidateShadowStats(report.score_bucket_stats_json),
    [report.score_bucket_stats_json],
  )
  const dataLineageRows = useMemo(
    () => flattenDataLineageStats(report.score_bucket_stats_json),
    [report.score_bucket_stats_json],
  )
  const observationCoverageRows = useMemo(
    () => flattenObservationCoverage(report.score_bucket_stats_json),
    [report.score_bucket_stats_json],
  )
  return (
    <div className="space-y-6">
      <Summary report={report} />
      <ObservationCoverage rows={observationCoverageRows} />
      <Recommendations rows={report.recommendations_json} />
      <CandidateShadowStats rows={candidateShadowRows} />
      <DataLineageStats rows={dataLineageRows} />
      <SignalStats rows={signalRows} />
      <OutcomeTables winners={report.top_winners_json} losers={report.top_losers_json} />
      <ShadowBox data={report.shadow_diff_stats_json} />
    </div>
  )
}

function Summary({ report }: { report: AttributionReport }) {
  return (
    <section className="grid gap-3 md:grid-cols-4">
      <MetricCard label="报告日期" value={report.report_date} />
      <MetricCard label="样本窗口" value={`${report.window_start} ~ ${report.window_end}`} />
      <MetricCard label="周期" value={report.horizons.join('/')} />
      <MetricCard label="生成时间" value={formatDateTime(report.created_at)} />
    </section>
  )
}

function ObservationCoverage({
  rows,
}: {
  rows: Array<{ group: string; value: string; stats: ObservationCoverageMetric }>
}) {
  if (!rows.length) {
    return (
      <Panel title="数据口径与覆盖">
        <p className="text-sm text-muted-foreground">当前归因快照缺少覆盖率元数据，等待下一次归因任务刷新。</p>
      </Panel>
    )
  }
  return (
    <Panel title="数据口径与覆盖">
      <div className="overflow-auto">
        <table className="w-full min-w-[980px] text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2">口径</th>
              <th>值</th>
              <th>观察</th>
              <th>有结果</th>
              <th>总覆盖</th>
              <th>h1</th>
              <th>h3</th>
              <th>h5</th>
              <th>证据覆盖</th>
              <th>当前口径</th>
              <th>旧口径</th>
              <th>最新日期</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ group, value, stats }) => (
              <tr key={`${group}-${value}`} className="border-b border-border/60">
                <td className="py-2 text-muted-foreground">{formatCoverageGroup(group)}</td>
                <td className="font-medium">{formatCoverageValue(value)}</td>
                <td>{fmtCount(stats.observations)}</td>
                <td>{fmtCount(stats.with_any_outcome)}</td>
                <td>{fmtPct(stats.outcome_coverage_pct)}</td>
                <td>{fmtPct(stats.h1_coverage_pct)}</td>
                <td>{fmtPct(stats.h3_coverage_pct)}</td>
                <td>{fmtPct(stats.h5_coverage_pct)}</td>
                <td>{fmtPct(stats.features_coverage_pct)}</td>
                <td>{fmtPct(stats.current_like_pct)}</td>
                <td>{fmtPct(stats.legacy_like_pct)}</td>
                <td>{stats.latest_trade_date || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function Recommendations({ rows }: { rows: AttributionRecommendation[] }) {
  if (!rows.length) {
    return <Panel title="策略建议"><p className="text-sm text-muted-foreground">暂无需要降权的信号。</p></Panel>
  }
  return (
    <Panel title="策略建议">
      <div className="space-y-2">
        {rows.map((row) => (
          <div key={`${row.horizon}-${row.target}`} className="rounded-lg border border-border bg-muted/30 p-3">
            <div className="text-sm font-medium">{row.type === 'downweight' ? '建议降权' : row.type} · {row.target} · h={row.horizon}</div>
            <p className="mt-1 break-words text-xs text-muted-foreground">{row.reason}</p>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function CandidateShadowStats({ rows }: { rows: Array<{ horizon: string; grade: string; stats: MetricStats }> }) {
  if (!rows.length) {
    return <Panel title="候选影子分表现"><p className="text-sm text-muted-foreground">暂无候选影子分样本。</p></Panel>
  }
  return (
    <Panel title="候选影子分表现">
      <div className="overflow-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2">周期</th>
              <th>评级</th>
              <th>样本</th>
              <th>均值</th>
              <th>中位数</th>
              <th>胜率</th>
              <th>大涨</th>
              <th>大跌</th>
              <th>平均回撤</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ horizon, grade, stats }) => (
              <tr key={`${horizon}-${grade}`} className="border-b border-border/60">
                <td className="py-2">{horizon}</td>
                <td className="font-medium">{formatGrade(grade)}</td>
                <td>{stats.count ?? 0}</td>
                <td className={tone(stats.avg_return_pct)}>{fmtPct(stats.avg_return_pct)}</td>
                <td className={tone(stats.median_return_pct)}>{fmtPct(stats.median_return_pct)}</td>
                <td>{fmtPct(stats.win_rate_pct)}</td>
                <td>{fmtPct(stats.big_win_rate_pct)}</td>
                <td>{fmtPct(stats.big_loss_rate_pct)}</td>
                <td className={tone(stats.avg_drawdown_pct)}>{fmtPct(stats.avg_drawdown_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

interface DataLineageRows {
  coverage: Array<{ horizon: string; grade: string; stats: MetricStats }>
  evidence: Array<{ horizon: string; evidence: string; stats: MetricStats }>
}

function DataLineageStats({ rows }: { rows: DataLineageRows }) {
  if (!rows.coverage.length && !rows.evidence.length) {
    return <Panel title="证据覆盖表现"><p className="text-sm text-muted-foreground">暂无证据覆盖样本。</p></Panel>
  }
  return (
    <Panel title="证据覆盖表现">
      <div className="grid gap-5 xl:grid-cols-2">
        <CoverageTable rows={rows.coverage} />
        <EvidenceTable rows={rows.evidence} />
      </div>
    </Panel>
  )
}

function CoverageTable({ rows }: { rows: DataLineageRows['coverage'] }) {
  return (
    <div className="overflow-auto">
      <div className="mb-2 text-xs font-medium text-muted-foreground">按覆盖等级</div>
      <table className="w-full min-w-[700px] text-left text-sm">
        <DataLineageTableHead label="覆盖" />
        <tbody>
          {rows.map(({ horizon, grade, stats }) => (
            <DataLineageRow key={`${horizon}-${grade}`} horizon={horizon} label={formatCoverageGrade(grade)} stats={stats} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EvidenceTable({ rows }: { rows: DataLineageRows['evidence'] }) {
  return (
    <div className="overflow-auto">
      <div className="mb-2 text-xs font-medium text-muted-foreground">按证据项</div>
      <table className="w-full min-w-[700px] text-left text-sm">
        <DataLineageTableHead label="证据项" />
        <tbody>
          {rows.map(({ horizon, evidence, stats }) => (
            <DataLineageRow key={`${horizon}-${evidence}`} horizon={horizon} label={formatEvidenceKey(evidence)} stats={stats} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DataLineageTableHead({ label }: { label: string }) {
  return (
    <thead className="text-xs text-muted-foreground">
      <tr className="border-b border-border">
        <th className="py-2">周期</th>
        <th>{label}</th>
        <th>样本</th>
        <th>均值</th>
        <th>胜率</th>
        <th>大涨</th>
        <th>大跌</th>
        <th>平均回撤</th>
      </tr>
    </thead>
  )
}

function DataLineageRow({ horizon, label, stats }: { horizon: string; label: string; stats: MetricStats }) {
  return (
    <tr className="border-b border-border/60">
      <td className="py-2">{horizon}</td>
      <td className="font-medium">{label}</td>
      <td>{stats.count ?? 0}</td>
      <td className={tone(stats.avg_return_pct)}>{fmtPct(stats.avg_return_pct)}</td>
      <td>{fmtPct(stats.win_rate_pct)}</td>
      <td>{fmtPct(stats.big_win_rate_pct)}</td>
      <td>{fmtPct(stats.big_loss_rate_pct)}</td>
      <td className={tone(stats.avg_drawdown_pct)}>{fmtPct(stats.avg_drawdown_pct)}</td>
    </tr>
  )
}

function SignalStats({ rows }: { rows: Array<{ horizon: string; signal: string; stats: MetricStats }> }) {
  return (
    <Panel title="信号表现">
      <div className="overflow-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2">周期</th>
              <th>信号</th>
              <th>样本</th>
              <th>均值</th>
              <th>中位数</th>
              <th>胜率</th>
              <th>大涨</th>
              <th>大跌</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ horizon, signal, stats }) => (
              <tr key={`${horizon}-${signal}`} className="border-b border-border/60">
                <td className="py-2">{horizon}</td>
                <td className="font-medium">{signal}</td>
                <td>{stats.count ?? 0}</td>
                <td className={tone(stats.avg_return_pct)}>{fmtPct(stats.avg_return_pct)}</td>
                <td className={tone(stats.median_return_pct)}>{fmtPct(stats.median_return_pct)}</td>
                <td>{fmtPct(stats.win_rate_pct)}</td>
                <td>{fmtPct(stats.big_win_rate_pct)}</td>
                <td>{fmtPct(stats.big_loss_rate_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function OutcomeTables({ winners, losers }: { winners: StockOutcome[]; losers: StockOutcome[] }) {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <OutcomeTable title="涨幅样本" rows={winners} />
      <OutcomeTable title="跌幅样本" rows={losers} />
    </div>
  )
}

function OutcomeTable({ title, rows }: { title: string; rows: StockOutcome[] }) {
  return (
    <Panel title={title}>
      <div className="space-y-2">
        {rows.slice(0, 12).map((row) => (
          <div key={`${row.trade_date}-${row.code}-${row.signal_type}`} className="grid grid-cols-[1fr_auto] gap-3 rounded-lg border border-border bg-background p-3">
            <div>
              <div className="text-sm font-medium">{row.code} {row.name || ''}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {row.trade_date} · {row.signal_type || '-'} · {row.track || '-'} · 影子分 {fmtScore(row.candidate_shadow_score)} · {formatGrade(row.candidate_shadow_grade)}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                证据 {formatCoverageGrade(row.data_lineage_coverage_grade)} {fmtScore(row.data_lineage_coverage_score)}
                {row.data_lineage_evidence_keys?.length ? ` · ${row.data_lineage_evidence_keys.map(formatEvidenceKey).join('/')}` : ''}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {formatCoverageValue(row.selection_mode || row.strategy_version || row.candidate_lane || row.entry_type || '-')}
              </div>
            </div>
            <div className={`text-right text-sm font-semibold ${tone(row.return_pct)}`}>{fmtPct(row.return_pct)}</div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function ShadowBox({ data }: { data: JsonMap }) {
  return (
    <Panel title="Shadow 差异">
      <div className="grid gap-3 md:grid-cols-3">
        <MetricCard label="记录数" value={String(data.count ?? 0)} />
        <MetricCard label="平均新增" value={String(data.avg_added ?? 0)} />
        <MetricCard label="平均移除" value={String(data.avg_removed ?? 0)} />
      </div>
    </Panel>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-2 break-words text-sm font-semibold">{value}</div>
    </div>
  )
}

function LockedView() {
  return (
    <div className="h-full p-6">
      <div className="rounded-lg border border-border bg-card p-6">
        <h1 className="text-xl font-semibold">策略归因报告</h1>
        <p className="mt-2 text-sm text-muted-foreground">该视图仅对白名单用户开放。</p>
      </div>
    </div>
  )
}

function EmptyView() {
  return (
    <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
      暂无归因报告。先运行 `scripts/strategy_attribution_report.py` 生成一条快照。
    </div>
  )
}

function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-4 text-sm text-destructive">{message}</div>
}

function flattenObservationCoverage(data: JsonMap | undefined) {
  const raw = data?._observation_coverage
  if (!raw || typeof raw !== 'object') return []
  const groupOrder: Record<string, number> = {
    signal_type: 0,
    selection_mode: 1,
    strategy_version: 2,
    candidate_lane: 3,
    entry_type: 4,
  }
  return Object.entries(raw as Record<string, Record<string, ObservationCoverageMetric>>)
    .flatMap(([group, stats]) =>
      Object.entries(stats || {}).map(([value, item]) => ({ group, value, stats: item })),
    )
    .sort((a, b) => {
      const groupDiff = (groupOrder[a.group] ?? 99) - (groupOrder[b.group] ?? 99)
      if (groupDiff !== 0) return groupDiff
      return (b.stats.observations ?? 0) - (a.stats.observations ?? 0)
    })
}

function flattenSignalStats(data: AttributionReport['signal_stats_json']) {
  return Object.entries(data || {}).flatMap(([horizon, stats]) =>
    Object.entries(stats || {}).map(([signal, item]) => ({ horizon, signal, stats: item })),
  )
}

function flattenCandidateShadowStats(data: JsonMap | undefined) {
  const raw = data?._candidate_shadow_grade
  if (!raw || typeof raw !== 'object') return []
  const gradeOrder: Record<string, number> = { S: 0, A: 1, B: 2, C: 3, D: 4, unknown: 5 }
  return Object.entries(raw as Record<string, Record<string, MetricStats>>)
    .flatMap(([horizon, stats]) =>
      Object.entries(stats || {}).map(([grade, item]) => ({ horizon, grade, stats: item })),
    )
    .sort((a, b) => {
      const horizonDiff = Number(a.horizon) - Number(b.horizon)
      if (Number.isFinite(horizonDiff) && horizonDiff !== 0) return horizonDiff
      return (gradeOrder[a.grade] ?? 99) - (gradeOrder[b.grade] ?? 99)
    })
}

function flattenDataLineageStats(data: JsonMap | undefined) {
  const raw = data?._data_lineage
  if (!raw || typeof raw !== 'object') return { coverage: [], evidence: [] }
  const lineage = raw as JsonMap
  const coverageRaw = lineage.coverage_grade
  const evidenceRaw = lineage.evidence_key
  const coverageOrder: Record<string, number> = { strong: 0, medium: 1, thin: 2, weak: 3, unknown: 4 }
  const evidenceOrder: Record<string, number> = {
    daily_signal: 0,
    price_action: 1,
    springboard: 2,
    intraday_tail: 3,
    external_capital: 4,
    ai_review: 5,
  }
  const coverage = (!coverageRaw || typeof coverageRaw !== 'object' ? [] :
    Object.entries(coverageRaw as Record<string, Record<string, MetricStats>>)
      .flatMap(([horizon, stats]) =>
        Object.entries(stats || {}).map(([grade, item]) => ({ horizon, grade, stats: item })),
      ))
    .sort((a, b) => {
      const horizonDiff = Number(a.horizon) - Number(b.horizon)
      if (Number.isFinite(horizonDiff) && horizonDiff !== 0) return horizonDiff
      return (coverageOrder[a.grade] ?? 99) - (coverageOrder[b.grade] ?? 99)
    })
  const evidence = (!evidenceRaw || typeof evidenceRaw !== 'object' ? [] :
    Object.entries(evidenceRaw as Record<string, Record<string, MetricStats>>)
      .flatMap(([horizon, stats]) =>
        Object.entries(stats || {}).map(([evidence, item]) => ({ horizon, evidence, stats: item })),
      ))
    .sort((a, b) => {
      const horizonDiff = Number(a.horizon) - Number(b.horizon)
      if (Number.isFinite(horizonDiff) && horizonDiff !== 0) return horizonDiff
      return (evidenceOrder[a.evidence] ?? 99) - (evidenceOrder[b.evidence] ?? 99)
    })
  return { coverage, evidence }
}

function fmtPct(raw: number | null | undefined) {
  return typeof raw === 'number' && Number.isFinite(raw) ? `${raw.toFixed(1)}%` : '-'
}

function fmtScore(raw: number | null | undefined) {
  return typeof raw === 'number' && Number.isFinite(raw) ? raw.toFixed(1) : '-'
}

function fmtCount(raw: number | null | undefined) {
  return typeof raw === 'number' && Number.isFinite(raw) ? String(raw) : '0'
}

function formatGrade(raw: string | null | undefined) {
  const text = String(raw || '').trim()
  return text && text !== 'unknown' ? text : '未评分'
}

function formatCoverageGrade(raw: string | null | undefined) {
  const text = String(raw || '').trim()
  const labels: Record<string, string> = {
    strong: '强覆盖',
    medium: '中覆盖',
    thin: '薄覆盖',
    weak: '弱覆盖',
  }
  return labels[text] || '未知覆盖'
}

function formatEvidenceKey(raw: string) {
  const labels: Record<string, string> = {
    daily_signal: '日线信号',
    price_action: '量价痕迹',
    springboard: '起跳板',
    intraday_tail: '尾盘确认',
    external_capital: '外部资金',
    ai_review: 'AI复核',
  }
  return labels[raw] || raw
}

function formatCoverageGroup(raw: string) {
  const labels: Record<string, string> = {
    signal_type: '信号',
    selection_mode: '选择模式',
    strategy_version: '策略版本',
    candidate_lane: '入选路径',
    entry_type: '买点类型',
  }
  return labels[raw] || raw
}

function formatCoverageValue(raw: string) {
  const labels: Record<string, string> = {
    candidate_lane_shadow: '入选路径观察',
    mainline_shadow: '主线观察',
    tradeable_l4: '正式买点',
    legacy_layered: '旧五层漏斗',
    candidate_lane_v1: '入选路径 v1',
    launchpad: '起跳板',
    trend_breakout: '趋势突破',
    trend_lane_pullback: '趋势回踩',
    mainline: '主线',
    main_force_entry: '主力入场',
    unknown: '未知/旧字段缺失',
  }
  return labels[raw] || raw
}

function tone(raw: number | null | undefined) {
  return financialValueClass(raw, '')
}

function formatDateTime(raw: string) {
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString()
}
