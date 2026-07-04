import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { supabase } from '@/lib/supabase'
import { checkWhitelist } from '@/lib/kline'
import { WyckoffLoading } from '@/components/loading'
import { usePreferences } from '@/lib/preferences'
import { financialValueClass } from '@/lib/financial-colors'
import { useAuthStore } from '@/stores/auth'

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
  features_json?: unknown
}

type TailBuySortKey =
  | 'code'
  | 'name'
  | 'runDate'
  | 'signal'
  | 'decision'
  | 'entryPrice'
  | 'currentPrice'
  | 'changePct'
  | 'vwap'
  | 'distVwap'
  | 'last30Ret'
  | 'policyWeight'
  | 'ruleScore'
  | 'priorityScore'
  | 'llmDecision'
  | 'reason'

type SortOrder = 'desc' | 'asc'

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

function resolveEntryPrice(record: TailBuyRecord): number | undefined {
  return record.initial_price && record.initial_price > 0 ? record.initial_price : record.last_close
}

function resolveCurrentPrice(record: TailBuyRecord): number | undefined {
  return record.current_price && record.current_price > 0 ? record.current_price : resolveEntryPrice(record)
}

function parseFeatures(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, unknown>
  if (typeof raw !== 'string' || raw.trim() === '') return {}
  try {
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function numberFeature(features: Record<string, unknown>, key: string): number | undefined {
  const value = features[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function policyWeightText(record: TailBuyRecord): string {
  const features = parseFeatures(record.features_json)
  const multiplier = numberFeature(features, 'policy_weight_multiplier')
  if (multiplier === undefined) return '-'
  const signal = String(features.policy_weight_signal || record.signal_type || 'unknown')
  const oldScore = numberFeature(features, 'policy_weight_old_score')
  const newScore = numberFeature(features, 'policy_weight_new_score')
  const scoreText = oldScore !== undefined && newScore !== undefined ? ` ${oldScore.toFixed(1)}→${newScore.toFixed(1)}` : ''
  return `${signal} x${multiplier.toFixed(2)}${scoreText}`
}

function policyWeightSortValue(record: TailBuyRecord): number | undefined {
  return numberFeature(parseFeatures(record.features_json), 'policy_weight_multiplier')
}

function TailBuyRecordRow({ record }: { record: TailBuyRecord }) {
  const entryPrice = resolveEntryPrice(record)
  const currentPrice = resolveCurrentPrice(record)
  const changePct = resolveChangePct(entryPrice, currentPrice, record.change_pct)
  const changeClass = financialValueClass(changePct)
  const policyText = policyWeightText(record)

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
      <td className="max-w-[150px] truncate px-3 py-2 text-right text-xs text-muted-foreground" title={policyText}>
        {policyText}
      </td>
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
  const user = useAuthStore((s) => s.user)
  const userId = user?.id
  const whitelist = useQuery({
    queryKey: ['whitelist', userId],
    queryFn: () => checkWhitelist(userId || ''),
    enabled: !!userId,
  })
  const tailBuy = useQuery({
    queryKey: ['tail-buy'],
    queryFn: fetchTailBuy,
    enabled: whitelist.data === true,
  })

  if (whitelist.isLoading) return <WyckoffLoading />
  if (whitelist.data !== true) return <TailBuyLockedView />
  if (tailBuy.isLoading) return <WyckoffLoading />

  return <TailBuyReadyContent data={tailBuy.data || []} />
}

function TailBuyReadyContent({ data }: { data: TailBuyRecord[] }) {
  const { t } = usePreferences()
  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t('tailBuy.title')}</h1>
        <span className="text-xs text-muted-foreground">{t('tailBuy.total', { count: data.length })}</span>
      </div>

      {data.length === 0 ? (
        <TailBuyEmptyView />
      ) : (
        <TailBuyTable data={data} />
      )}
    </div>
  )
}

function TailBuyEmptyView() {
  const { t } = usePreferences()
  return (
    <div className="flex flex-1 items-center justify-center text-muted-foreground">
      <div className="text-center">
        <div className="mb-3 text-4xl">🌙</div>
        <p className="text-sm">{t('tailBuy.empty')}</p>
        <p className="mt-1 text-xs">{t('tailBuy.emptySubtitle')}</p>
      </div>
    </div>
  )
}

function TailBuyTable({ data }: { data: TailBuyRecord[] }) {
  const [sortBy, setSortBy] = useState<TailBuySortKey>('runDate')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const sortedData = useMemo(() => sortTailBuyRecords(data, sortBy, sortOrder), [data, sortBy, sortOrder])
  const handleSort = (next: TailBuySortKey) => {
    if (next === sortBy) {
      setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')
      return
    }
    setSortBy(next)
    setSortOrder('desc')
  }

  return (
    <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
      <div className="h-full overflow-auto">
        <table className="w-full text-sm">
          <TailBuyTableHead sortBy={sortBy} sortOrder={sortOrder} onSortChange={handleSort} />
          <tbody>
            {sortedData.map((record) => <TailBuyRecordRow key={`${record.code}-${record.run_date}`} record={record} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TailBuyTableHead({
  sortBy,
  sortOrder,
  onSortChange,
}: {
  sortBy: TailBuySortKey
  sortOrder: SortOrder
  onSortChange: (sortBy: TailBuySortKey) => void
}) {
  const { t } = usePreferences()
  return (
    <thead className="sticky top-0 bg-muted/80 backdrop-blur">
      <tr>
        <SortableHeader align="left" active={sortBy === 'code'} label={t('common.code')} order={sortOrder} onClick={() => onSortChange('code')} />
        <SortableHeader align="left" active={sortBy === 'name'} label={t('common.name')} order={sortOrder} onClick={() => onSortChange('name')} />
        <SortableHeader align="right" active={sortBy === 'runDate'} label={t('common.date')} order={sortOrder} onClick={() => onSortChange('runDate')} />
        <SortableHeader align="center" active={sortBy === 'signal'} label={t('tailBuy.signal')} order={sortOrder} onClick={() => onSortChange('signal')} />
        <SortableHeader align="center" active={sortBy === 'decision'} label="决策" order={sortOrder} onClick={() => onSortChange('decision')} />
        <SortableHeader align="right" active={sortBy === 'entryPrice'} label="入库价" order={sortOrder} onClick={() => onSortChange('entryPrice')} />
        <SortableHeader align="right" active={sortBy === 'currentPrice'} label="现价" order={sortOrder} onClick={() => onSortChange('currentPrice')} />
        <SortableHeader align="right" active={sortBy === 'changePct'} label="涨跌" order={sortOrder} onClick={() => onSortChange('changePct')} />
        <SortableHeader align="right" active={sortBy === 'vwap'} label="VWAP" order={sortOrder} onClick={() => onSortChange('vwap')} />
        <SortableHeader align="right" active={sortBy === 'distVwap'} label="距VWAP" order={sortOrder} onClick={() => onSortChange('distVwap')} />
        <SortableHeader align="right" active={sortBy === 'last30Ret'} label="30m" order={sortOrder} onClick={() => onSortChange('last30Ret')} />
        <SortableHeader align="right" active={sortBy === 'policyWeight'} label="归因调权" order={sortOrder} onClick={() => onSortChange('policyWeight')} />
        <SortableHeader align="right" active={sortBy === 'ruleScore'} label={t('tailBuy.ruleScore')} order={sortOrder} onClick={() => onSortChange('ruleScore')} />
        <SortableHeader align="right" active={sortBy === 'priorityScore'} label={t('tailBuy.priorityScore')} order={sortOrder} onClick={() => onSortChange('priorityScore')} />
        <SortableHeader align="center" active={sortBy === 'llmDecision'} label={t('tailBuy.llmDecision')} order={sortOrder} onClick={() => onSortChange('llmDecision')} />
        <SortableHeader align="left" active={sortBy === 'reason'} label={t('tailBuy.reason')} order={sortOrder} onClick={() => onSortChange('reason')} />
      </tr>
    </thead>
  )
}

function SortableHeader({
  active,
  align,
  label,
  order,
  onClick,
}: {
  active: boolean
  align: 'left' | 'right' | 'center'
  label: string
  order: SortOrder
  onClick: () => void
}) {
  const alignClass = align === 'right' ? 'justify-end text-right' : align === 'center' ? 'justify-center text-center' : 'justify-start text-left'
  return (
    <th className={`px-3 py-2.5 font-medium ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'}`}>
      <button type="button" onClick={onClick} className={`inline-flex w-full items-center gap-1 rounded px-1 py-0.5 hover:bg-muted ${alignClass}`}>
        <span>{label}</span>
        <span className={`min-w-3 text-[10px] ${active ? 'text-primary' : 'text-muted-foreground'}`}>
          {active ? (order === 'desc' ? '↓' : '↑') : '--'}
        </span>
      </button>
    </th>
  )
}

function sortTailBuyRecords(records: TailBuyRecord[], sortBy: TailBuySortKey, sortOrder: SortOrder): TailBuyRecord[] {
  return [...records].sort((left, right) => {
    const result = compareTailBuyValue(sortValue(left, sortBy), sortValue(right, sortBy))
    if (result !== 0) return sortOrder === 'desc' ? -result : result
    return compareTailBuyValue(left.run_date, right.run_date) * -1 || compareTailBuyValue(left.code, right.code)
  })
}

function sortValue(record: TailBuyRecord, sortBy: TailBuySortKey): string | number | undefined {
  switch (sortBy) {
    case 'code': return record.code
    case 'name': return record.name
    case 'runDate': return record.run_date
    case 'signal': return record.signal_type
    case 'decision': return record.final_decision
    case 'entryPrice': return resolveEntryPrice(record)
    case 'currentPrice': return resolveCurrentPrice(record)
    case 'changePct': return resolveChangePct(resolveEntryPrice(record), resolveCurrentPrice(record), record.change_pct)
    case 'vwap': return record.vwap
    case 'distVwap': return record.dist_vwap_pct
    case 'last30Ret': return record.last30_ret_pct
    case 'policyWeight': return policyWeightSortValue(record)
    case 'ruleScore': return record.rule_score
    case 'priorityScore': return record.priority_score
    case 'llmDecision': return record.llm_decision
    case 'reason': return record.llm_reason
  }
}

function compareTailBuyValue(left: string | number | undefined, right: string | number | undefined): number {
  if (left == null && right == null) return 0
  if (left == null) return -1
  if (right == null) return 1
  if (typeof left === 'number' && typeof right === 'number') return left - right
  return String(left).localeCompare(String(right), 'zh-CN', { numeric: true, sensitivity: 'base' })
}

function TailBuyLockedView() {
  const { t } = usePreferences()
  return (
    <div className="h-full p-6">
      <div className="rounded-lg border border-border bg-card p-6">
        <h1 className="text-xl font-semibold">{t('tailBuy.title')}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{t('tailBuy.lockedDesc')}</p>
      </div>
    </div>
  )
}
