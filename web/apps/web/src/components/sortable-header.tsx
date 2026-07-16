export type SortOrder = 'desc' | 'asc'

interface SortableHeaderProps {
  active: boolean
  align: 'left' | 'right' | 'center'
  label: string
  order: SortOrder
  onClick: () => void
  /** 'compact' keeps the original tracking.tsx look (text DESC/ASC, left/right only). */
  variant?: 'full' | 'compact'
}

/** Shared sortable `<th>` header used by tracking and export tables. */
export function SortableHeader({ active, align, label, order, onClick, variant = 'full' }: SortableHeaderProps) {
  const alignText = align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
  if (variant === 'compact') {
    return (
      <th className={`px-3 py-2 font-medium ${alignText}`}>
        <button type="button" onClick={onClick} className="inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-muted">
          <span>{label}</span>
          <span className={`text-[10px] ${active ? 'text-primary' : 'text-muted-foreground'}`}>{active ? order.toUpperCase() : '--'}</span>
        </button>
      </th>
    )
  }
  const alignFlex = align === 'right' ? 'justify-end text-right' : align === 'center' ? 'justify-center text-center' : 'justify-start text-left'
  return (
    <th className={`px-3 py-2.5 font-medium ${alignText}`}>
      <button type="button" onClick={onClick} className={`inline-flex w-full items-center gap-1 rounded px-1 py-0.5 hover:bg-muted ${alignFlex}`}>
        <span>{label}</span>
        <span className={`min-w-3 text-[10px] ${active ? 'text-primary' : 'text-muted-foreground'}`}>
          {active ? (order === 'desc' ? '↓' : '↑') : '--'}
        </span>
      </button>
    </th>
  )
}
