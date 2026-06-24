import { type FormEvent, type RefObject } from 'react'
import { MessageSquareText } from 'lucide-react'
import type { UIMessage } from 'ai'
import { ChatComposer, ThinkingBubble } from './composer'
import { ConversationSidebar } from './conversation-sidebar'
import type { ReadingRoomConversation } from './conversations'
import { ReadingRoomDashboard } from './dashboard'
import type { ReadingRoomChat } from './chat-state'
import { MessageBubble, QueuedMessageBubble } from './tool-rendering'
import type { PinStockInput, QueuedMessage, ReadingRoomTab, RunRecord, WatchItem } from './types'
import { WatchlistPanelView } from './watchlist'

interface ChatMessagesProps {
  chat: ReadingRoomChat
  activeTab: ReadingRoomTab
  loading: boolean
  queuedMessages: QueuedMessage[]
  conversations: ReadingRoomConversation[]
  activeConversationId: string
  runRecords: RunRecord[]
  scrollRef: RefObject<HTMLDivElement | null>
  watchlist: WatchItem[]
  onOpenRecord: (messageId: string) => void
  onNewConversation: () => void
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  onSelectConversation: (id: string) => void
  onRemoveConversation: (id: string) => void
  onRenameConversation: (id: string, title: string) => void
  onPinStock: (item: PinStockInput) => void
  onRemoveWatchItem: (code: string) => void
  onStart: (value: string) => void
  input: string
  queuedCount: number
  onClearQueue: () => void
  onInput: (value: string) => void
  onSubmit: (e: FormEvent) => void
  onStop: () => void
}

export function ChatMessages(props: ChatMessagesProps) {
  const activeAssistantId = props.loading ? lastAssistantId(props.chat.messages) : null
  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      <div className="flex h-full w-full flex-col lg:flex-row">
        <ChatConversationSidebar props={props} />
        <div className="flex min-w-0 flex-1 flex-col">
          <div ref={props.scrollRef} className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6">
            <ReadingRoomMainContent
              activeTab={props.activeTab}
              activeAssistantId={activeAssistantId}
              chat={props.chat}
              loading={props.loading}
              queuedMessages={props.queuedMessages}
              runRecords={props.runRecords}
              watchlist={props.watchlist}
              onOpenRecord={props.onOpenRecord}
              onPinStock={props.onPinStock}
              onRemoveWatchItem={props.onRemoveWatchItem}
              onStart={props.onStart}
            />
          </div>
          <ChatComposerSlot props={props} />
        </div>
      </div>
    </div>
  )
}

function ChatConversationSidebar({ props }: { props: ChatMessagesProps }) {
  if (props.activeTab !== 'chat') return null
  return (
    <ConversationSidebar
      conversations={props.conversations}
      activeId={props.activeConversationId}
      collapsed={props.sidebarCollapsed}
      onCreate={props.onNewConversation}
      onToggle={props.onToggleSidebar}
      onSelect={props.onSelectConversation}
      onRemove={props.onRemoveConversation}
      onRename={props.onRenameConversation}
    />
  )
}

function ChatComposerSlot({ props }: { props: ChatMessagesProps }) {
  if (props.activeTab !== 'chat') return null
  return (
    <ChatComposer
      input={props.input}
      loading={props.loading}
      queuedCount={props.queuedCount}
      onClearQueue={props.onClearQueue}
      onInput={props.onInput}
      onSubmit={props.onSubmit}
      onStop={props.onStop}
    />
  )
}

function ReadingRoomMainContent({
  activeTab,
  activeAssistantId,
  chat,
  loading,
  queuedMessages,
  runRecords,
  watchlist,
  onOpenRecord,
  onPinStock,
  onRemoveWatchItem,
  onStart,
}: Pick<ChatMessagesProps, 'activeTab' | 'chat' | 'loading' | 'queuedMessages' | 'runRecords' | 'watchlist' | 'onOpenRecord' | 'onPinStock' | 'onRemoveWatchItem' | 'onStart'> & {
  activeAssistantId: string | null
}) {
  if (activeTab === 'desk') {
    return (
      <div className="mx-auto w-full max-w-5xl px-2 py-1 animate-fade-in-up">
        <ReadingRoomDashboard runRecords={runRecords} onOpenRecord={onOpenRecord} onStart={onStart} />
      </div>
    )
  }
  if (activeTab === 'watchlist') {
    return (
      <div className="mx-auto w-full max-w-5xl px-2 py-1 animate-fade-in-up">
        <WatchlistPanelView watchlist={watchlist} onRemove={onRemoveWatchItem} onStart={onStart} />
      </div>
    )
  }
  return (
    <div className="mx-auto w-full max-w-5xl">
      <ChatTranscript
        activeAssistantId={activeAssistantId}
        chat={chat}
        loading={loading}
        queuedMessages={queuedMessages}
        onPinStock={onPinStock}
      />
    </div>
  )
}

function ChatTranscript({
  activeAssistantId,
  chat,
  loading,
  queuedMessages,
  onPinStock,
}: Pick<ChatMessagesProps, 'chat' | 'loading' | 'queuedMessages' | 'onPinStock'> & { activeAssistantId: string | null }) {
  if (chat.messages.length === 0 && !loading && queuedMessages.length === 0) return <EmptyChatPanel />
  return (
    <div className="space-y-5 pb-4 animate-fade-in-up">
      {chat.messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          isActive={message.id === activeAssistantId}
          approve={(id) => void chat.addToolApprovalResponse({ id, approved: true })}
          deny={(id) => void chat.addToolApprovalResponse({ id, approved: false })}
          onPinStock={onPinStock}
        />
      ))}
      {queuedMessages.map((message, index) => <QueuedMessageBubble key={message.id} message={message} index={index + 1} />)}
      {loading && <ThinkingBubble />}
    </div>
  )
}

function lastAssistantId(messages: UIMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant') return message.id
  }
  return null
}

function EmptyChatPanel() {
  return (
    <div className="mx-auto flex min-h-[360px] w-full max-w-4xl flex-col items-center justify-center rounded-lg border border-dashed border-border/75 bg-background px-6 text-center">
      <div className="rounded-full bg-muted p-3 text-muted-foreground">
        <MessageSquareText size={22} />
      </div>
      <p className="mt-3 text-sm font-medium">对话还没有开始</p>
      <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">在下方输入你的读盘问题，执行过程和结论会保存在当前对话里。</p>
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  if (!message) return null
  return <div className="mx-6 mb-2 shrink-0 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-200">{message}</div>
}
