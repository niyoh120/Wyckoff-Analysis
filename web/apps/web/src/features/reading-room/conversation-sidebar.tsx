import { useCallback, useEffect, useState } from 'react'
import { Check, History, MessageSquareText, PanelLeftClose, PanelLeftOpen, Pencil, Plus, X } from 'lucide-react'
import {
  formatConversationDate,
  normalizeConversationTitle,
  type ReadingRoomConversation,
} from './conversations'

export interface ConversationSidebarProps {
  conversations: ReadingRoomConversation[]
  activeId: string
  collapsed: boolean
  onCreate: () => void
  onToggle: () => void
  onSelect: (id: string) => void
  onRemove: (id: string) => void
  onRename: (id: string, title: string) => void
}

interface ConversationListItemProps {
  conversation: ReadingRoomConversation
  active: boolean
  canRemove: boolean
  onSelect: () => void
  onRemove: () => void
  onRename: (title: string) => void
}

export function ConversationSidebar({
  conversations,
  activeId,
  collapsed,
  onCreate,
  onToggle,
  onSelect,
  onRemove,
  onRename,
}: ConversationSidebarProps) {
  if (collapsed) {
    return <CollapsedConversationSidebar count={conversations.length} onToggle={onToggle} />
  }
  return (
    <aside className="flex h-48 shrink-0 flex-col overflow-hidden rounded-2xl glass-panel lg:h-full lg:w-72 shadow-sm select-none">
      <ConversationSidebarHeader count={conversations.length} onCreate={onCreate} onToggle={onToggle} />
      <ConversationList conversations={conversations} activeId={activeId} onSelect={onSelect} onRemove={onRemove} onRename={onRename} />
    </aside>
  )
}

function CollapsedConversationSidebar({ count, onToggle }: { count: number; onToggle: () => void }) {
  return (
    <aside className="flex h-12 shrink-0 overflow-hidden rounded-2xl glass-panel lg:h-full lg:w-14 shadow-sm select-none">
      <button
        type="button"
        onClick={onToggle}
        aria-label="展开对话历史"
        title="展开对话历史"
        className="flex h-full w-full items-center justify-center gap-2 text-muted-foreground hover:bg-muted/40 hover:text-foreground lg:flex-col cursor-pointer transition-colors duration-200"
      >
        <PanelLeftOpen size={15} />
        <span className="text-[10px] font-bold tracking-wider lg:[writing-mode:vertical-rl] lg:my-2">历史 {count}</span>
      </button>
    </aside>
  )
}

function ConversationSidebarHeader({ count, onCreate, onToggle }: { count: number; onCreate: () => void; onToggle: () => void }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-border/50 px-3.5 py-3 bg-muted/15">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-xs font-bold text-foreground">
          <History size={14} className="text-primary" />
          对话历史
        </div>
        <p className="mt-0.5 text-[10px] text-muted-foreground font-medium">本地保存 · {count} 个</p>
      </div>
      <div className="flex items-center gap-1.5">
        <button type="button" onClick={onToggle} aria-label="收起对话历史" title="收起对话历史" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-colors">
          <PanelLeftClose size={14} />
        </button>
        <button type="button" onClick={onCreate} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg bg-primary px-2.5 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 shadow-sm transition-all cursor-pointer">
          <Plus size={13} />
          新对话
        </button>
      </div>
    </div>
  )
}

function ConversationList({
  conversations,
  activeId,
  onSelect,
  onRemove,
  onRename,
}: Omit<ConversationSidebarProps, 'collapsed' | 'onCreate' | 'onToggle'>) {
  return (
    <div className="min-h-0 flex-1 space-y-1 overflow-auto p-2">
      {conversations.map((conversation) => (
        <ConversationListItem
          key={conversation.id}
          conversation={conversation}
          active={conversation.id === activeId}
          canRemove={conversations.length > 1}
          onSelect={() => onSelect(conversation.id)}
          onRemove={() => onRemove(conversation.id)}
          onRename={(title) => onRename(conversation.id, title)}
        />
      ))}
    </div>
  )
}

function ConversationListItem({
  conversation,
  active,
  canRemove,
  onSelect,
  onRemove,
  onRename,
}: ConversationListItemProps) {
  const messageCount = conversation.messages.length
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conversation.title)

  useEffect(() => {
    if (!editing) setDraft(conversation.title)
  }, [conversation.title, editing])

  const commitRename = useCallback(() => {
    const next = normalizeConversationTitle(draft)
    if (next) onRename(next)
    setEditing(false)
  }, [draft, onRename])

  return (
    <div
      className={`group flex w-full items-start gap-1 rounded-xl border transition-all duration-200 ${
        active
          ? 'border-primary/20 bg-primary/5 text-primary'
          : 'border-transparent text-muted-foreground hover:bg-muted/30 hover:text-foreground'
      }`}
    >
      {editing ? (
        <ConversationRenameForm
          draft={draft}
          originalTitle={conversation.title}
          onCancel={() => { setDraft(conversation.title); setEditing(false) }}
          onCommit={commitRename}
          onDraft={setDraft}
        />
      ) : (
        <ConversationSelectButton conversation={conversation} active={active} messageCount={messageCount} onSelect={onSelect} />
      )}
      {!editing && <ConversationListItemActions canRemove={canRemove} title={conversation.title} onEdit={() => setEditing(true)} onRemove={onRemove} />}
    </div>
  )
}

function ConversationRenameForm(props: {
  draft: string
  originalTitle: string
  onCancel: () => void
  onCommit: () => void
  onDraft: (value: string) => void
}) {
  return (
    <form onSubmit={(event) => { event.preventDefault(); props.onCommit() }} className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-2">
      <input
        autoFocus
        value={props.draft}
        onChange={(event) => props.onDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            props.onCancel()
          }
        }}
        className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
      />
      <button type="submit" aria-label="保存对话名" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg hover:bg-muted cursor-pointer"><Check size={12} /></button>
      <button type="button" aria-label={`取消改名 ${props.originalTitle}`} onClick={props.onCancel} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg hover:bg-muted cursor-pointer"><X size={12} /></button>
    </form>
  )
}

function ConversationSelectButton({ conversation, active, messageCount, onSelect }: {
  conversation: ReadingRoomConversation
  active: boolean
  messageCount: number
  onSelect: () => void
}) {
  return (
    <button type="button" onClick={onSelect} className="flex min-w-0 flex-1 items-start gap-2 px-2.5 py-2.5 text-left cursor-pointer">
      <MessageSquareText size={14} className={`mt-0.5 shrink-0 ${active ? 'text-primary' : 'text-muted-foreground/75'}`} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-semibold">{conversation.title}</span>
        <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[10px] opacity-75 font-medium">
          <span className="truncate">{formatConversationDate(conversation.updatedAt)}</span>
          <span>·</span>
          <span className="shrink-0">{messageCount} 条消息</span>
        </span>
      </span>
    </button>
  )
}

function ConversationListItemActions({ canRemove, title, onEdit, onRemove }: {
  canRemove: boolean
  title: string
  onEdit: () => void
  onRemove: () => void
}) {
  return (
    <>
      <button type="button" aria-label={`重命名 ${title}`} onClick={onEdit} className="mt-2 shrink-0 rounded-md p-1 opacity-70 hover:bg-muted hover:text-foreground lg:opacity-0 lg:group-hover:opacity-80 cursor-pointer transition">
        <Pencil size={11} />
      </button>
      {canRemove && (
        <button type="button" aria-label={`删除 ${title}`} onClick={onRemove} className="mr-1 mt-2 shrink-0 rounded-md p-1 opacity-70 hover:bg-muted hover:text-foreground lg:opacity-0 lg:group-hover:opacity-80 cursor-pointer transition">
          <X size={11} />
        </button>
      )}
    </>
  )
}
