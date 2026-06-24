import {
  Compass,
  Gauge,
  History,
  Send,
  Sparkles,
  Target,
  type LucideIcon,
} from 'lucide-react'
import { usePreferences } from '@/lib/preferences'
import { SCENARIOS, SHORTCUTS, chatPromptSuggestions, type DeskScenario, type DeskShortcut } from './dashboard-config'
import type { RunRecord } from './types'

export function ReadingRoomDashboard({
  runRecords,
  onOpenRecord,
  onStart,
}: {
  runRecords: RunRecord[]
  onOpenRecord: (messageId: string) => void
  onStart: (value: string) => void
}) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-6 animate-fade-in-up">
      <ReadingRoomHero recordCount={runRecords.length} />
      <ScenarioPanel onStart={onStart} />
      <ShortcutPanel onStart={onStart} />
      <CompactRunRecords records={runRecords} onOpenRecord={onOpenRecord} />
      <PromptPanel onStart={onStart} />
    </div>
  )
}

function ReadingRoomHero({ recordCount }: { recordCount: number }) {
  const { t } = usePreferences()
  return (
    <section className="rounded-2xl border border-border bg-gradient-to-br from-indigo-500/5 via-primary/5 to-transparent p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-xl">
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-primary/10 border border-primary/20 px-2.5 py-1 text-[10px] font-bold text-primary uppercase tracking-wider">
            <Compass size={11} />
            Reading Desk
          </div>
          <h2 className="text-xl font-bold text-foreground">{t('chat.title')}</h2>
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
            {t('chat.emptyTitle')}。先定市场先验，再把持仓、候选、尾盘和归因串成一张当日操作清单。
          </p>
        </div>
        <div className="grid min-w-[280px] grid-cols-3 gap-2.5 rounded-xl border border-border/50 bg-background/50 p-2 text-center shadow-inner">
          <DeskStat label="场景" value="4" Icon={Sparkles} />
          <DeskStat label="情报" value="5" Icon={Target} />
          <DeskStat label="记录" value={String(recordCount)} Icon={History} />
        </div>
      </div>
    </section>
  )
}

function CompactRunRecords({ records, onOpenRecord }: { records: RunRecord[]; onOpenRecord: (messageId: string) => void }) {
  if (records.length === 0) return null
  return (
    <section className="rounded-2xl border border-border bg-card/45 p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold">最近记录</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">当前对话的关键轮次，点进去回看原文。</p>
        </div>
        <History size={15} className="text-muted-foreground/80" />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {records.slice(0, 6).map((record, index) => (
          <RecordButton key={record.id} record={record} index={index} onOpenRecord={onOpenRecord} />
        ))}
      </div>
    </section>
  )
}

function RecordButton({ record, index, onOpenRecord }: {
  record: RunRecord
  index: number
  onOpenRecord: (messageId: string) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onOpenRecord(record.messageId)}
      className="rounded-xl border border-border/60 bg-background p-3 text-left transition hover:border-primary/30 hover:bg-muted/20 hover:shadow-sm cursor-pointer"
    >
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="rounded-full bg-muted px-2 py-0.5 text-[9px] font-bold text-muted-foreground">#{index + 1}</span>
        <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${record.toneClass}`}>{record.status}</span>
      </div>
      <div className="line-clamp-1 text-xs font-semibold text-foreground">{record.title}</div>
      <RecordToolLabels labels={record.toolLabels} />
      <p className="mt-1.5 line-clamp-2 text-[10px] leading-relaxed text-muted-foreground/80">{record.preview || '等待模型返回结果。'}</p>
    </button>
  )
}

function RecordToolLabels({ labels }: { labels: string[] }) {
  if (labels.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {labels.slice(0, 3).map((label) => (
        <span key={label} className="rounded-md bg-muted px-1.5 py-0.5 text-[9px] font-semibold text-muted-foreground/80">
          {label}
        </span>
      ))}
    </div>
  )
}

function ScenarioPanel({ onStart }: { onStart: (value: string) => void }) {
  return (
    <section className="rounded-2xl border border-border bg-card/45 p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold">今日读盘场景</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">盘前、盘中、尾盘、复盘都能一键开局。</p>
        </div>
        <Sparkles size={15} className="shrink-0 text-muted-foreground/80" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {SCENARIOS.map((scenario) => <ScenarioButton key={scenario.id} scenario={scenario} onStart={onStart} />)}
      </div>
    </section>
  )
}

function ShortcutPanel({ onStart }: { onStart: (value: string) => void }) {
  return (
    <section className="rounded-2xl border border-border bg-card/45 p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold">情报入口</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">这些入口会直接调用读盘室工具，不只是一句静态提示。</p>
        </div>
        <Gauge size={15} className="text-muted-foreground/80" />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {SHORTCUTS.map((shortcut) => <ShortcutButton key={shortcut.title} shortcut={shortcut} onStart={onStart} />)}
      </div>
    </section>
  )
}

function PromptPanel({ onStart }: { onStart: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <section className="rounded-2xl border border-dashed border-border/80 bg-background/20 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs font-bold text-foreground">{t('chat.tryAsk')}</p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {chatPromptSuggestions(t).map((q) => (
              <button key={q} type="button" onClick={() => onStart(q)} className="rounded-full border border-border bg-background px-3 py-1 text-xs text-muted-foreground hover:bg-primary/5 hover:border-primary/30 hover:text-primary transition-all duration-150 cursor-pointer font-medium">
                {q}
              </button>
            ))}
          </div>
        </div>
        <p className="max-w-md text-[10px] leading-relaxed text-muted-foreground/75 font-medium">
          {t('chat.fullVersionPrefix')} · <code className="rounded bg-muted px-1.5 py-0.5 text-[9px] font-mono border border-border/30">curl -fsSL https://raw.githubusercontent.com/YoungCan-Wang/Wyckoff-Analysis/main/install.sh | bash</code> {t('chat.unlockFull')}
        </p>
      </div>
    </section>
  )
}

function DeskStat({ label, value, Icon }: { label: string; value: string; Icon: LucideIcon }) {
  return (
    <div className="rounded-lg bg-card/65 border border-border/40 py-2.5 hover:bg-card hover:border-primary/10 transition-all duration-200">
      <Icon size={14} className="mx-auto text-primary" />
      <div className="mt-1 text-base font-bold text-foreground">{value}</div>
      <div className="text-[10px] font-bold text-muted-foreground/80 tracking-wider mt-0.5">{label}</div>
    </div>
  )
}

function ScenarioButton({ scenario, onStart }: { scenario: DeskScenario; onStart: (value: string) => void }) {
  const { Icon } = scenario
  return (
    <button
      type="button"
      onClick={() => onStart(scenario.prompt)}
      className={`group flex min-h-[140px] flex-col justify-between rounded-xl border p-4 text-left transition-all duration-200 hover:translate-y-[-2px] hover:shadow-md cursor-pointer ${scenario.toneClass}`}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2">
          <span className="rounded-lg bg-background/80 p-1.5 shadow-sm border border-border/30">
            <Icon size={15} />
          </span>
          <span className="text-[10px] font-bold tracking-wide uppercase opacity-75">{scenario.eyebrow}</span>
        </span>
        <Send size={12} className="opacity-45 transition group-hover:translate-x-0.5 group-hover:opacity-90" />
      </span>
      <span>
        <span className="block text-base font-bold">{scenario.title}</span>
        <span className="mt-1 block text-xs leading-relaxed opacity-75">{scenario.description}</span>
      </span>
    </button>
  )
}

function ShortcutButton({ shortcut, onStart }: { shortcut: DeskShortcut; onStart: (value: string) => void }) {
  const { Icon } = shortcut
  return (
    <button
      type="button"
      onClick={() => onStart(shortcut.prompt)}
      className="flex min-h-[125px] flex-col justify-between rounded-xl border border-border bg-background p-4 text-left transition-all duration-200 hover:border-primary/30 hover:bg-muted/30 hover:translate-y-[-2px] hover:shadow-sm cursor-pointer"
    >
      <span className="flex items-center justify-between gap-2">
        <Icon size={15} className="text-primary" />
        <span className="rounded-full bg-primary/10 border border-primary/20 px-2 py-0.5 text-[9px] font-bold text-primary">{shortcut.metric}</span>
      </span>
      <span>
        <span className="block text-xs font-bold text-foreground">{shortcut.title}</span>
        <span className="mt-1 block text-[10px] leading-relaxed text-muted-foreground">{shortcut.description}</span>
      </span>
    </button>
  )
}
