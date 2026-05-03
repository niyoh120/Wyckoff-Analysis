import { useState, useEffect } from 'react'

const CHANGELOG_URL = 'https://raw.githubusercontent.com/YoungCan-Wang/Wyckoff-Analysis/main/web/CHANGELOG.md'

export function ChangelogPage() {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(CHANGELOG_URL)
      .then((r) => r.ok ? r.text() : Promise.reject(r.status))
      .then(setContent)
      .catch(() => setContent(''))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
        <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-xs italic">市场从不说谎，但它经常保持沉默。</span>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-6">
      <h1 className="mb-6 text-xl font-semibold">更新日志</h1>
      {content ? (
        <article className="prose prose-sm max-w-none text-foreground">
          <ChangelogMarkdown content={content} />
        </article>
      ) : (
        <p className="text-sm text-muted-foreground">无法加载更新日志。</p>
      )}
    </div>
  )
}

function ChangelogMarkdown({ content }: { content: string }) {
  const html = content
    .replace(/^#### (.+)$/gm, '<h4 class="mt-3 mb-1 text-sm font-semibold">$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 class="mt-4 mb-2 text-base font-semibold">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="mt-8 mb-3 border-b border-border pb-2 text-lg font-semibold">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="mb-6 text-2xl font-bold">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="rounded bg-muted px-1.5 py-0.5 text-xs">$1</code>')
    .replace(/^- (.+)$/gm, '<li class="ml-4 mb-1">$1</li>')
    .replace(/\n\n/g, '</p><p class="mb-3">')
    .replace(/\n/g, '<br/>')

  return <div dangerouslySetInnerHTML={{ __html: `<p class="mb-3">${html}</p>` }} />
}
