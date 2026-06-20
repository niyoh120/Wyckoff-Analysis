import { memo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const MD_COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mt-5 mb-2 text-lg font-bold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-4 mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-3 mb-1.5 text-sm font-semibold">{children}</h3>,
  p: ({ children }) => <p className="mb-2">{children}</p>,
  ul: ({ children }) => <ul className="ml-4 mb-2 list-disc">{children}</ul>,
  ol: ({ children }) => <ol className="ml-4 mb-2 list-decimal">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  code: ({ children }) => (
    <code className="rounded bg-black/5 px-1 py-0.5 text-xs font-mono dark:bg-white/10">{children}</code>
  ),
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
  strong: ({ children }) => <strong>{children}</strong>,
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
