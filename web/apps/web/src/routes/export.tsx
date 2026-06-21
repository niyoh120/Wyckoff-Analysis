import { useMemo, useState, type ReactNode } from 'react'
import { Download, FileSpreadsheet, Loader2, Package } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { usePreferences } from '@/lib/preferences'
import {
  arrayToCSV,
  buildEnhancedRows,
  buildKlineParams,
  createZipBlob,
  downloadBlob,
  normalizeExportSymbol,
  parseExportSymbols,
  parseTickFlowToRows,
  type ExportAdjust,
  type ExportDataset,
  type ExportRow,
} from '@/lib/export-data'

type ExportMode = 'single' | 'batch'
type PreviewMode = 'enhanced' | 'raw'

interface BatchResult {
  symbol: string
  status: 'ok' | 'failed'
  rows: number
  error: string
}

async function getTickFlowKey(userId: string): Promise<string | null> {
  const { data } = await supabase
    .from('user_settings')
    .select('tickflow_api_key')
    .eq('user_id', userId)
    .single()
  return data?.tickflow_api_key || null
}

export function ExportPage() {
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [mode, setMode] = useState<ExportMode>('single')
  const [symbol, setSymbol] = useState('')
  const [batchText, setBatchText] = useState('')
  const [days, setDays] = useState(320)
  const [endOffset, setEndOffset] = useState(1)
  const [adjust, setAdjust] = useState<ExportAdjust>('qfq')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [datasets, setDatasets] = useState<ExportDataset[]>([])
  const [batchResults, setBatchResults] = useState<BatchResult[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [previewMode, setPreviewMode] = useState<PreviewMode>('enhanced')
  const [columnFilter, setColumnFilter] = useState('')
  const [selectedColumns, setSelectedColumns] = useState<string[]>([])

  const activeDataset = datasets[activeIndex] || null
  const activeRows = useMemo(
    () => activeDataset ? (previewMode === 'enhanced' ? activeDataset.enhancedRows : activeDataset.rawRows) : [],
    [activeDataset, previewMode],
  )
  const columns = useMemo(() => Object.keys(activeRows[0] || {}), [activeRows])
  const activeSelectedColumns = useMemo(() => selectedColumns.filter((column) => columns.includes(column)), [columns, selectedColumns])
  const columnSet = useMemo(() => new Set(activeSelectedColumns.length ? activeSelectedColumns : columns), [columns, activeSelectedColumns])
  const visibleColumns = useMemo(() => filterColumns(columns, columnFilter), [columns, columnFilter])
  const previewRows = useMemo(() => selectColumns(activeRows.slice(0, 10), columnsFromSet(columnSet, columns)), [activeRows, columnSet, columns])

  async function handleExport() {
    const apiKey = user ? await getTickFlowKey(user.id) : null
    if (!apiKey) {
      setError(t('export.configureTickflow'))
      return
    }
    const symbols = mode === 'single' ? [normalizeExportSymbol(symbol)] : parseExportSymbols(batchText)
    if (symbols.some((value) => !value)) {
      setError(t('export.invalidSymbol'))
      return
    }
    if (symbols.length === 0) {
      setError(t('export.batchEmpty'))
      return
    }
    if (mode === 'batch' && symbols.length > 6) {
      setError(t('export.batchTooMany', { count: symbols.length }))
      return
    }
    await runExport(apiKey, symbols)
  }

  async function runExport(apiKey: string, symbols: string[]) {
    resetOutput()
    setLoading(true)
    const nextResults: BatchResult[] = []
    const nextDatasets: ExportDataset[] = []
    for (const item of symbols) {
      try {
        const dataset = await fetchDataset(apiKey, item, days, endOffset, adjust)
        nextDatasets.push(dataset)
        nextResults.push({ symbol: item, status: 'ok', rows: dataset.rawRows.length, error: '' })
      } catch (err) {
        nextResults.push({ symbol: item, status: 'failed', rows: 0, error: errorMessage(err) })
      }
    }
    setDatasets(nextDatasets)
    setBatchResults(nextResults)
    setError(nextDatasets.length ? '' : t('export.failed'))
    setLoading(false)
  }

  function resetOutput() {
    setError('')
    setDatasets([])
    setBatchResults([])
    setActiveIndex(0)
    setSelectedColumns([])
    setColumnFilter('')
  }

  function downloadCurrent(kind: PreviewMode) {
    if (!activeDataset) return
    const rows = kind === 'enhanced' ? activeDataset.enhancedRows : activeDataset.rawRows
    downloadCsv(rows, `${activeDataset.fileStem}_${kind}.csv`)
  }

  function downloadSelected() {
    if (!activeDataset || activeRows.length === 0) return
    const selected = columnsFromSet(columnSet, columns)
    downloadCsv(selectColumns(activeRows, selected), `${activeDataset.fileStem}_${previewMode}_selected.csv`)
  }

  function downloadZip() {
    if (!datasets.length) return
    downloadBlob(createZipBlob(zipFiles(datasets)), `wyckoff_export_${formatStamp()}.zip`)
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-5 text-xl font-semibold">{t('export.title')}</h1>

      <section className="mb-5 rounded-lg border border-border p-4">
        <div className="mb-4 flex flex-wrap gap-2">
          <ModeButton active={mode === 'single'} onClick={() => setMode('single')}>{t('export.singleMode')}</ModeButton>
          <ModeButton active={mode === 'batch'} onClick={() => setMode('batch')}>{t('export.batchMode')}</ModeButton>
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_120px_120px_150px_auto] lg:items-end">
          {mode === 'single' ? (
            <TextField label={t('common.stockCode')} value={symbol} onChange={setSymbol} placeholder={t('export.symbolPlaceholder')} onEnter={handleExport} />
          ) : (
            <TextArea label={t('export.batchSymbols')} value={batchText} onChange={setBatchText} placeholder="601318; 000001; 510300; AAPL.US; 00700.HK" />
          )}
          <NumberField label={t('export.days')} value={days} min={10} max={700} onChange={setDays} />
          <NumberField label={t('export.endOffset')} value={endOffset} min={0} max={30} onChange={setEndOffset} />
          <div>
            <label className="mb-1.5 block text-sm font-medium">{t('export.adjust')}</label>
            <select value={adjust} onChange={(e) => setAdjust(e.target.value as ExportAdjust)} className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm">
              <option value="qfq">{t('export.qfq')}</option>
              <option value="hfq">{t('export.hfq')}</option>
              <option value="">{t('export.noneAdjust')}</option>
            </select>
          </div>
          <button onClick={handleExport} disabled={loading || (mode === 'single' ? !symbol.trim() : !batchText.trim())} className="flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
            {loading ? t('export.fetching') : t('export.fetch')}
          </button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{t('export.batchHint')}</p>
      </section>

      {error && <div className="mb-4 rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-200">{error}</div>}

      {batchResults.length > 0 && <BatchStatus rows={batchResults} okText={t('export.ok')} failedText={t('export.failedStatus')} rowsText={t('common.rows')} />}

      {activeDataset ? (
        <section className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <DatasetSelect datasets={datasets} activeIndex={activeIndex} onChange={setActiveIndex} label={t('export.dataset')} />
              <ModeButton active={previewMode === 'enhanced'} onClick={() => setPreviewMode('enhanced')}>{t('export.enhancedView')}</ModeButton>
              <ModeButton active={previewMode === 'raw'} onClick={() => setPreviewMode('raw')}>{t('export.rawView')}</ModeButton>
            </div>
            <div className="flex flex-wrap gap-2">
              <DownloadButton onClick={() => downloadCurrent('enhanced')} icon={<FileSpreadsheet size={15} />}>{t('export.enhancedCsv')}</DownloadButton>
              <DownloadButton onClick={() => downloadCurrent('raw')} icon={<FileSpreadsheet size={15} />}>{t('export.rawCsv')}</DownloadButton>
              <DownloadButton onClick={downloadSelected} icon={<Download size={15} />}>{t('export.selectedCsv')}</DownloadButton>
              <DownloadButton onClick={downloadZip} icon={<Package size={15} />}>{t('export.zip')}</DownloadButton>
            </div>
          </div>

          <div className="border-b border-border p-3">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <input value={columnFilter} onChange={(e) => setColumnFilter(e.target.value)} placeholder={t('export.columnFilter')} className="h-9 w-56 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/20" />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={visibleColumns.every((c) => columnSet.has(c))} onChange={(e) => setSelectedColumns(toggleColumns(columnSet, columns, visibleColumns, e.target.checked))} />
                {t('export.selectAll')}
              </label>
              <span className="text-xs text-muted-foreground">{t('export.selectedCount', { count: columnSet.size })}</span>
            </div>
            <div className="flex max-h-20 flex-wrap gap-2 overflow-auto">
              {visibleColumns.map((column) => (
                <label key={column} className="flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs">
                  <input type="checkbox" checked={columnSet.has(column)} onChange={(e) => setSelectedColumns(toggleColumns(columnSet, columns, [column], e.target.checked))} />
                  {column}
                </label>
              ))}
            </div>
          </div>

          <PreviewTable rows={previewRows} />
        </section>
      ) : (
        !loading && <EmptyState title={t('export.emptyTitle')} subtitle={t('export.emptySubtitle')} />
      )}
    </div>
  )
}

async function fetchDataset(apiKey: string, symbol: string, days: number, endOffset: number, adjust: ExportAdjust): Promise<ExportDataset> {
  const params = buildKlineParams(symbol, days, endOffset, adjust)
  const resp = await fetch(`/api/llm-proxy/v1/klines?${params}`, {
    headers: { 'x-api-key': apiKey, 'X-Target-URL': 'https://api.tickflow.org' },
  })
  if (!resp.ok) throw new Error(`TickFlow ${resp.status}: ${(await resp.text()).slice(0, 180)}`)
  const rawRows = parseTickFlowToRows(await resp.json())
  if (!rawRows.length) throw new Error('no data')
  return { symbol, fileStem: safeStem(symbol), rawRows, enhancedRows: buildEnhancedRows(rawRows) }
}

function downloadCsv(rows: ExportRow[], fileName: string) {
  downloadBlob(new Blob(['\uFEFF' + arrayToCSV(rows)], { type: 'text/csv;charset=utf-8;' }), fileName)
}

function zipFiles(datasets: ExportDataset[]) {
  return datasets.flatMap((dataset) => [
    { name: `${dataset.fileStem}_enhanced.csv`, content: '\uFEFF' + arrayToCSV(dataset.enhancedRows) },
    { name: `${dataset.fileStem}_raw.csv`, content: '\uFEFF' + arrayToCSV(dataset.rawRows) },
  ])
}

function selectColumns(rows: ExportRow[], columns: string[]): ExportRow[] {
  return rows.map((row) => Object.fromEntries(columns.map((column) => [column, row[column] ?? ''])))
}

function toggleColumns(current: Set<string>, allColumns: string[], target: string[], checked: boolean): string[] {
  const next = new Set(current.size ? current : allColumns)
  for (const column of target) {
    if (checked) next.add(column)
    else next.delete(column)
  }
  return allColumns.filter((column) => next.has(column))
}

function columnsFromSet(set: Set<string>, fallback: string[]): string[] {
  const selected = fallback.filter((column) => set.has(column))
  return selected.length ? selected : fallback
}

function filterColumns(columns: string[], filter: string): string[] {
  const q = filter.trim().toLowerCase()
  return q ? columns.filter((column) => column.toLowerCase().includes(q)) : columns
}

function safeStem(symbol: string): string {
  return symbol.replace(/[^0-9A-Z.-]+/g, '_').replace(/\.+/g, '_')
}

function formatStamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button type="button" onClick={onClick} className={`rounded-lg border px-3 py-1.5 text-sm ${active ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:bg-muted'}`}>
      {children}
    </button>
  )
}

function DownloadButton({ onClick, icon, children }: { onClick: () => void; icon: ReactNode; children: string }) {
  return (
    <button type="button" onClick={onClick} className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">
      {icon}
      {children}
    </button>
  )
}

function TextField({ label, value, onChange, placeholder, onEnter }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; onEnter: () => void }) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && onEnter()} placeholder={placeholder} className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/20" />
    </div>
  )
}

function TextArea({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} rows={2} className="min-h-10 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/20" />
    </div>
  )
}

function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <input type="number" value={value} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring/20" />
    </div>
  )
}

function DatasetSelect({ datasets, activeIndex, onChange, label }: { datasets: ExportDataset[]; activeIndex: number; onChange: (index: number) => void; label: string }) {
  if (datasets.length <= 1) return <span className="text-sm font-medium">{datasets[0]?.symbol}</span>
  return (
    <label className="flex items-center gap-2 text-sm">
      {label}
      <select value={activeIndex} onChange={(e) => onChange(Number(e.target.value))} className="rounded-lg border border-border bg-background px-2 py-1.5">
        {datasets.map((dataset, index) => <option key={dataset.symbol} value={index}>{dataset.symbol}</option>)}
      </select>
    </label>
  )
}

function BatchStatus({ rows, okText, failedText, rowsText }: { rows: BatchResult[]; okText: string; failedText: string; rowsText: string }) {
  return (
    <div className="mb-4 overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol} className="border-t border-border first:border-t-0">
              <td className="px-3 py-2 font-mono">{row.symbol}</td>
              <td className={row.status === 'ok' ? 'px-3 py-2 text-emerald-600' : 'px-3 py-2 text-red-600'}>{row.status === 'ok' ? okText : failedText}</td>
              <td className="px-3 py-2 text-muted-foreground">{row.status === 'ok' ? `${row.rows} ${rowsText}` : row.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PreviewTable({ rows }: { rows: ExportRow[] }) {
  if (!rows.length) return <div className="p-6 text-sm text-muted-foreground">No preview</div>
  const headers = Object.keys(rows[0]!)
  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur">
          <tr>{headers.map((key) => <th key={key} className="whitespace-nowrap px-3 py-2 text-left font-medium">{key}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-border hover:bg-muted/20">
              {headers.map((key) => <td key={key} className="whitespace-nowrap px-3 py-2">{formatCell(row[key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EmptyState({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex flex-1 items-center justify-center text-muted-foreground">
      <div className="text-center">
        <FileSpreadsheet className="mx-auto mb-3" size={38} />
        <p className="text-sm">{title}</p>
        <p className="mt-1 text-xs">{subtitle}</p>
      </div>
    </div>
  )
}

function formatCell(value: ExportRow[string] | undefined): string {
  return typeof value === 'number' ? value.toFixed(4).replace(/\.?0+$/, '') : String(value ?? '')
}
