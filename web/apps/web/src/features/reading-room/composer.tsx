import { LoaderCircle, Send, Square, X } from 'lucide-react'
import { AIDisclaimer } from '@/components/ai-disclaimer'
import { usePreferences } from '@/lib/preferences'

export function ChatComposer(props: {
  input: string
  loading: boolean
  queuedCount: number
  onClearQueue: () => void
  onInput: (value: string) => void
  onSubmit: (e: React.FormEvent) => void
  onStop: () => void
}) {
  return (
    <div className="shrink-0 bg-background/30 backdrop-blur-md px-4 pb-5 pt-2 sm:px-6 border-t border-border/20">
      <div className="mx-auto w-full max-w-5xl">
        <QueueNotice count={props.queuedCount} onClear={props.onClearQueue} />
        <form onSubmit={props.onSubmit} className="flex items-center gap-2 rounded-2xl border border-border/85 bg-card/85 px-3.5 py-2 shadow-md hover:shadow-lg focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary transition-all duration-200">
          <ComposerInput value={props.input} onInput={props.onInput} />
          <ComposerActions input={props.input} loading={props.loading} onStop={props.onStop} />
        </form>
        <div className="mt-2 text-center"><AIDisclaimer /></div>
      </div>
    </div>
  )
}

function QueueNotice({ count, onClear }: { count: number; onClear: () => void }) {
  const { t } = usePreferences()
  if (count === 0) return null
  return (
    <div className="mb-2 flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/45 px-3.5 py-1.5 text-xs text-muted-foreground">
      <span>{t('chat.queueCount').replace('{count}', String(count))}</span>
      <button type="button" onClick={onClear} className="inline-flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1 hover:bg-background hover:text-foreground cursor-pointer transition-colors duration-150">
        <X size={12} />
        {t('chat.clearQueue')}
      </button>
    </div>
  )
}

function ComposerInput({ value, onInput }: { value: string; onInput: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onInput(e.target.value)}
      placeholder={t('chat.placeholder')}
      aria-label={t('chat.placeholder')}
      className="flex-1 bg-transparent px-1.5 py-2 text-sm outline-none text-foreground placeholder:text-muted-foreground/60 font-semibold"
    />
  )
}

function ComposerActions({ input, loading, onStop }: { input: string; loading: boolean; onStop: () => void }) {
  const { t } = usePreferences()
  if (!loading) return <SendButton disabled={!input.trim()} label={t('chat.placeholder')} />
  return (
    <div className="flex items-center gap-1.5">
      <SendButton disabled={!input.trim()} label={t('chat.queueMessage')} />
      <button
        type="button"
        onClick={onStop}
        aria-label={t('chat.stop')}
        className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-600 text-white shadow-md shadow-rose-600/25 hover:bg-rose-700 hover:translate-y-[-1px] transition-all duration-200 cursor-pointer"
      >
        <Square size={14} fill="currentColor" />
      </button>
    </div>
  )
}

function SendButton({ disabled, label }: { disabled: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      aria-label={label}
      className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-indigo-600 text-white shadow-md shadow-primary/25 hover:shadow-lg hover:translate-y-[-1px] disabled:translate-y-0 disabled:opacity-40 disabled:shadow-none transition-all duration-200 cursor-pointer"
    >
      <Send size={15} />
    </button>
  )
}

export function ThinkingBubble() {
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[520px] overflow-hidden rounded-lg border border-border/70 bg-background text-xs text-muted-foreground shadow-sm">
        <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-foreground">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
            <LoaderCircle size={13} className="animate-spin" />
          </span>
          <span className="font-medium">读盘室正在执行</span>
        </div>
        <div className="grid gap-2 px-3 py-2 sm:grid-cols-3">
          <ProcessSkeletonStep active label="理解请求" detail="拆解读盘目标" />
          <ProcessSkeletonStep active label="准备数据源" detail="选择市场/持仓/候选工具" />
          <ProcessSkeletonStep label="等待结果" detail="汇总成操作清单" />
        </div>
      </div>
    </div>
  )
}

function ProcessSkeletonStep({ label, detail, active }: { label: string; detail: string; active?: boolean }) {
  return (
    <div className="rounded-md bg-muted/45 px-2 py-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
        <span className={`h-1.5 w-1.5 rounded-full ${active ? 'animate-pulse bg-primary' : 'bg-muted-foreground/40'}`} />
        {label}
      </div>
      <div className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</div>
    </div>
  )
}
