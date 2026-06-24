import { useMemo, useRef, useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { usePreferences } from '@/lib/preferences'
import {
  CONVERSATION_SIDEBAR_STORAGE_KEY,
  useAutoScroll,
  useChatConfig,
  useMessageQueue,
  useReadingRoomActions,
  useReadingRoomChat,
  useSubmitHandler,
} from '@/features/reading-room/chat-state'
import { useReadingRoomConversations } from '@/features/reading-room/conversations'
import { ChatHeader } from '@/features/reading-room/header'
import { buildRunRecords } from '@/features/reading-room/run-records'
import { ChatMessages, ErrorBanner } from '@/features/reading-room/transcript'
import type { ReadingRoomTab } from '@/features/reading-room/types'
import { readBooleanStorage } from '@/features/reading-room/utils'
import { useReadingRoomWatchlist } from '@/features/reading-room/watchlist-state'

export function ChatPage() {
  const session = useAuthStore((s) => s.session)
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const [input, setInput] = useState('')
  const [localError, setLocalError] = useState('')
  const [activeTab, setActiveTab] = useState<ReadingRoomTab>('desk')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readBooleanStorage(CONVERSATION_SIDEBAR_STORAGE_KEY, true))
  const scrollRef = useRef<HTMLDivElement>(null)
  const token = session?.access_token
  const config = useChatConfig(token, t)
  const chat = useReadingRoomChat(token, setLocalError, t)
  const loading = chat.status === 'submitted' || chat.status === 'streaming'
  const queue = useMessageQueue(chat, loading, token, config.configured, setLocalError, t)
  const conversations = useReadingRoomConversations(user?.id, chat.messages, chat.setMessages)
  const watchlist = useReadingRoomWatchlist(user?.id)
  const runRecords = useMemo(() => buildRunRecords(chat.messages, t), [chat.messages, t])
  useAutoScroll(scrollRef, activeTab === 'chat' ? chat.messages : [], activeTab === 'chat' && loading, activeTab === 'chat' ? queue.messages.length : 0)

  const handleSubmit = useSubmitHandler({
    chat,
    config,
    input,
    loading,
    queue,
    token,
    t,
    setActiveTab,
    setInput,
    setLocalError,
  })
  const actions = useReadingRoomActions({
    chat,
    config,
    conversations,
    loading,
    queue,
    scrollRef,
    token,
    t,
    setActiveTab,
    setInput,
    setLocalError,
    setSidebarCollapsed,
  })

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <ChatHeader
        config={config}
        hasUser={Boolean(user)}
        activeTab={activeTab}
        messageCount={chat.messages.length}
        watchCount={watchlist.items.length}
        onTabChange={setActiveTab}
      />
      <ChatMessages
        chat={chat}
        activeTab={activeTab}
        loading={loading}
        queuedMessages={queue.messages}
        conversations={conversations.items}
        activeConversationId={conversations.activeId}
        runRecords={runRecords}
        scrollRef={scrollRef}
        watchlist={watchlist.items}
        onOpenRecord={actions.openRunRecord}
        onNewConversation={actions.startNewConversation}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={actions.toggleSidebar}
        onSelectConversation={actions.selectConversation}
        onRemoveConversation={actions.removeConversation}
        onRenameConversation={actions.renameConversation}
        onPinStock={watchlist.add}
        onRemoveWatchItem={watchlist.remove}
        onStart={actions.startNewConversation}
        input={input}
        queuedCount={queue.messages.length}
        onClearQueue={queue.clear}
        onInput={setInput}
        onSubmit={handleSubmit}
        onStop={() => void chat.stop()}
      />
      <ErrorBanner message={localError || chat.error?.message || ''} />
    </div>
  )
}
