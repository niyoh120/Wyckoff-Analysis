export function MarkdownContent({ content, className = '' }: { content: string; className?: string }) {
  const html = content
    .replace(/^### (.+)$/gm, '<h3 class="mt-3 mb-1.5 text-sm font-semibold">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="mt-4 mb-2 text-base font-semibold">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="mt-5 mb-2 text-lg font-bold">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="rounded bg-black/5 px-1 py-0.5 text-xs font-mono">$1</code>')
    .replace(/^- (.+)$/gm, '<li class="ml-4 mb-0.5 list-disc">$1</li>')
    .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 mb-0.5 list-decimal">$1. $2</li>')
    .replace(/\n\n/g, '</p><p class="mb-2">')
    .replace(/\n/g, '<br/>')

  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: `<p class="mb-2">${html}</p>` }}
    />
  )
}
