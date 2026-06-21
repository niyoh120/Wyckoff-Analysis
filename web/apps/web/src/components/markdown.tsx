import { memo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const WYCKOFF_TERMS: Record<string, { bg: string; text: string; border: string }> = {
  // Positive markers / strength
  'spring': { bg: 'bg-emerald-500/10 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-500/20 dark:border-emerald-500/30' },
  'sos': { bg: 'bg-emerald-500/10 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-500/20 dark:border-emerald-500/30' },
  'lps': { bg: 'bg-blue-500/10 dark:bg-blue-500/20', text: 'text-blue-700 dark:text-blue-400', border: 'border-blue-500/20 dark:border-blue-500/30' },
  'bu': { bg: 'bg-blue-500/10 dark:bg-blue-500/20', text: 'text-blue-700 dark:text-blue-400', border: 'border-blue-500/20 dark:border-blue-500/30' },
  'jac': { bg: 'bg-indigo-500/10 dark:bg-indigo-500/20', text: 'text-indigo-700 dark:text-indigo-400', border: 'border-indigo-500/20 dark:border-indigo-500/30' },
  'sc': { bg: 'bg-amber-500/10 dark:bg-amber-500/20', text: 'text-amber-700 dark:text-amber-400', border: 'border-amber-500/20 dark:border-amber-500/30' },
  'st': { bg: 'bg-amber-500/10 dark:bg-amber-500/20', text: 'text-amber-700 dark:text-amber-400', border: 'border-amber-500/20 dark:border-amber-500/30' },
  'ar': { bg: 'bg-violet-500/10 dark:bg-violet-500/20', text: 'text-violet-700 dark:text-violet-400', border: 'border-violet-500/20 dark:border-violet-500/30' },

  // Negative markers / weakness
  'ut': { bg: 'bg-rose-500/10 dark:bg-rose-500/20', text: 'text-rose-700 dark:text-rose-400', border: 'border-rose-500/20 dark:border-rose-500/30' },
  'utad': { bg: 'bg-rose-500/10 dark:bg-rose-500/20', text: 'text-rose-700 dark:text-rose-400', border: 'border-rose-500/20 dark:border-rose-500/30' },
  'sow': { bg: 'bg-red-500/10 dark:bg-red-500/20', text: 'text-red-700 dark:text-red-400', border: 'border-red-500/20 dark:border-red-500/30' },
  'lpsy': { bg: 'bg-orange-500/10 dark:bg-orange-500/20', text: 'text-orange-700 dark:text-orange-400', border: 'border-orange-500/20 dark:border-orange-500/30' },
  'bc': { bg: 'bg-rose-500/10 dark:bg-rose-500/20', text: 'text-rose-700 dark:text-rose-400', border: 'border-rose-500/20 dark:border-rose-500/30' },

  // Phases
  'phase a': { bg: 'bg-cyan-500/10 dark:bg-cyan-500/20', text: 'text-cyan-700 dark:text-cyan-400', border: 'border-cyan-500/20 dark:border-cyan-500/30' },
  'phase b': { bg: 'bg-purple-500/10 dark:bg-purple-500/20', text: 'text-purple-700 dark:text-purple-400', border: 'border-purple-500/20 dark:border-purple-500/30' },
  'phase c': { bg: 'bg-fuchsia-500/10 dark:bg-fuchsia-500/20', text: 'text-fuchsia-700 dark:text-fuchsia-400', border: 'border-fuchsia-500/20 dark:border-fuchsia-500/30' },
  'phase d': { bg: 'bg-teal-500/10 dark:bg-teal-500/20', text: 'text-teal-700 dark:text-teal-400', border: 'border-teal-500/20 dark:border-teal-500/30' },
  'phase e': { bg: 'bg-emerald-500/10 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-500/20 dark:border-emerald-500/30' },
  'a阶段': { bg: 'bg-cyan-500/10 dark:bg-cyan-500/20', text: 'text-cyan-700 dark:text-cyan-400', border: 'border-cyan-500/20 dark:border-cyan-500/30' },
  'b阶段': { bg: 'bg-purple-500/10 dark:bg-purple-500/20', text: 'text-purple-700 dark:text-purple-400', border: 'border-purple-500/20 dark:border-purple-500/30' },
  'c阶段': { bg: 'bg-fuchsia-500/10 dark:bg-fuchsia-500/20', text: 'text-fuchsia-700 dark:text-fuchsia-400', border: 'border-fuchsia-500/20 dark:border-fuchsia-500/30' },
  'd阶段': { bg: 'bg-teal-500/10 dark:bg-teal-500/20', text: 'text-teal-700 dark:text-teal-400', border: 'border-teal-500/20 dark:border-teal-500/30' },
  'e阶段': { bg: 'bg-emerald-500/10 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-500/20 dark:border-emerald-500/30' },
}

function renderWyckoffTerm(children: React.ReactNode, fallback: React.ReactNode) {
  if (typeof children === 'string') {
    const term = children.trim()
    const normalized = term.toLowerCase()
    const style = WYCKOFF_TERMS[normalized]
    if (style) {
      return (
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-bold ${style.bg} ${style.text} ${style.border}`}>
          {term}
        </span>
      )
    }
  }
  return fallback
}

const MD_COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mt-5 mb-2 text-lg font-bold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-4 mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-3 mb-1.5 text-sm font-semibold">{children}</h3>,
  p: ({ children }) => <p className="mb-2">{children}</p>,
  ul: ({ children }) => <ul className="ml-4 mb-2 list-disc">{children}</ul>,
  ol: ({ children }) => <ol className="ml-4 mb-2 list-decimal">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  code: ({ children }) => {
    return renderWyckoffTerm(
      children,
      <code className="rounded bg-black/5 px-1 py-0.5 text-xs font-mono dark:bg-white/10">{children}</code>
    )
  },
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-border/60 bg-background/70">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  td: ({ children }) => <td className="border-t border-border/50 px-2.5 py-2 align-top">{children}</td>,
  th: ({ children }) => <th className="bg-muted/55 px-2.5 py-2 text-left font-medium">{children}</th>,
  a: ({ href, children }) => {
    const safe = href && /^https?:\/\//i.test(href)
    return safe ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{children}</a> : <span>{children}</span>
  },
  strong: ({ children }) => {
    return renderWyckoffTerm(children, <strong>{children}</strong>)
  },
  em: ({ children }) => <em>{children}</em>,
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  className = '',
}: {
  content: string
  className?: string
}) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{content}</ReactMarkdown>
    </div>
  )
})
