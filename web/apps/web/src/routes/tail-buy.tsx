import { useQuery } from '@tanstack/react-query'
import { supabase } from '@/lib/supabase'
import { WyckoffLoading } from '@/components/loading'
import { usePreferences } from '@/lib/preferences'

interface TailBuyRecord {
  code: string
  name: string
  run_date: string
  signal_type: string
  final_decision?: string
  rule_decision?: string
  rule_score: number
  priority_score: number
  llm_decision: string
  llm_reason: string
  initial_price?: number
  current_price?: number
  change_pct?: number
  price_updated_at?: string
  last_close?: number
  vwap?: number
  dist_vwap_pct?: number
  last30_ret_pct?: number
}

async function fetchTailBuy(): Promise<TailBuyRecord[]> {
  const { data } = await supabase
    .from('tail_buy_history')
    .select('*')
    .order('run_date', { ascending: false })
    .limit(200)
  return data || []
}

function fmtNumber(value: number | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-'
}

function fmtPercent(value: number | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)}%` : '-'
}

function resolveChangePct(entry: number | undefined, current: number | undefined, stored: number | undefined): number | undefined {
  if (typeof stored === 'number' && Number.isFinite(stored)) return stored
  if (entry && current) return ((current - entry) / entry) * 100
  return undefined
}

function TailBuyRecordRow({ record }: { record: TailBuyRecord }) {
  const entryPrice = record.initial_price && record.initial_price > 0 ? record.initial_price : record.last_close
  const currentPrice = record.current_price && record.current_price > 0 ? record.current_price : entryPrice
  const changePct = resolveChangePct(entryPrice, currentPrice, record.change_pct)
  const changeClass = changePct && changePct > 0
    ? 'text-red-600'
    : changePct && changePct < 0
      ? 'text-emerald-600'
      : 'text-muted-foreground'

  return (
    <tr key={`${record.code}-${record.run_date}`} className="border-t border-border hover:bg-muted/20">
      <td className="px-3 py-2 font-mono">{String(record.code).padStart(6, '0')}</td>
      <td className="px-3 py-2">{record.name}</td>
      <td className="px-3 py-2 text-right text-muted-foreground">{record.run_date}</td>
      <td className="px-3 py-2 text-center">
        <span className="inline-flex rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">
          {record.signal_type || '-'}
        </span>
      </td>
      <td className="px-3 py-2 text-center">{record.final_decision || '-'}</td>
      <td className="px-3 py-2 text-right">{fmtNumber(entryPrice)}</td>
      <td className="px-3 py-2 text-right">{fmtNumber(currentPrice)}</td>
      <td className={`px-3 py-2 text-right ${changeClass}`}>{fmtPercent(changePct)}</td>
      <td className="px-3 py-2 text-right">{fmtNumber(record.vwap)}</td>
      <td className="px-3 py-2 text-right">{fmtPercent(record.dist_vwap_pct)}</td>
      <td className="px-3 py-2 text-right">{fmtPercent(record.last30_ret_pct)}</td>
      <td className="px-3 py-2 text-right">{record.rule_score?.toFixed(1)}</td>
      <td className="px-3 py-2 text-right">{record.priority_score?.toFixed(1)}</td>
      <td className="px-3 py-2 text-center">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
          record.llm_decision === 'BUY'
            ? 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200'
            : 'bg-muted text-muted-foreground'
        }`}>
          {record.llm_decision || '-'}
        </span>
      </td>
      <td className="max-w-[200px] truncate px-3 py-2 text-xs text-muted-foreground" title={record.llm_reason}>
        {record.llm_reason || '-'}
      </td>
    </tr>
  )
}

export function TailBuyPage() {
  const { t } = usePreferences()
  const { data = [], isLoading } = useQuery({
    queryKey: ['tail-buy'],
    queryFn: fetchTailBuy,
  })

  if (isLoading) {
    return <WyckoffLoading />
  }

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t('tailBuy.title')}</h1>
        <span className="text-xs text-muted-foreground">{t('tailBuy.total', { count: data.length })}</span>
      </div>

      {data.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          <div className="text-center">
            <div className="mb-3 text-4xl">🌙</div>
            <p className="text-sm">{t('tailBuy.empty')}</p>
            <p className="mt-1 text-xs">{t('tailBuy.emptySubtitle')}</p>
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
          <div className="h-full overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                <tr>
                  <th className="px-3 py-2.5 text-left font-medium">{t('common.code')}</th>
                  <th className="px-3 py-2.5 text-left font-medium">{t('common.name')}</th>
                  <th className="px-3 py-2.5 text-right font-medium">{t('common.date')}</th>
                  <th className="px-3 py-2.5 text-center font-medium">{t('tailBuy.signal')}</th>
                  <th className="px-3 py-2.5 text-center font-medium">决策</th>
                  <th className="px-3 py-2.5 text-right font-medium">入库价</th>
                  <th className="px-3 py-2.5 text-right font-medium">现价</th>
                  <th className="px-3 py-2.5 text-right font-medium">涨跌</th>
                  <th className="px-3 py-2.5 text-right font-medium">VWAP</th>
                  <th className="px-3 py-2.5 text-right font-medium">距VWAP</th>
                  <th className="px-3 py-2.5 text-right font-medium">30m</th>
                  <th className="px-3 py-2.5 text-right font-medium">{t('tailBuy.ruleScore')}</th>
                  <th className="px-3 py-2.5 text-right font-medium">{t('tailBuy.priorityScore')}</th>
                  <th className="px-3 py-2.5 text-center font-medium">{t('tailBuy.llmDecision')}</th>
                  <th className="px-3 py-2.5 text-left font-medium">{t('tailBuy.reason')}</th>
                </tr>
              </thead>
              <tbody>
                {data.map((record) => <TailBuyRecordRow key={`${record.code}-${record.run_date}`} record={record} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
