export interface WatchItem {
  id: string
  code: string
  name: string
  reason: string
  source: string
  trigger: string
  invalidation: string
  addedAt: string
  updatedAt: string
  score?: number | null
  changePct?: number | null
  phase?: string | null
  action?: string | null
}

export interface PinStockInput {
  code: string
  name?: string | null
  reason: string
  source: string
  trigger?: string | null
  invalidation?: string | null
  score?: number | null
  changePct?: number | null
  phase?: string | null
  action?: string | null
}

export interface ChatConfig {
  configured: boolean
  model: string | null
  error?: string
}

export interface QueuedMessage {
  id: string
  text: string
}

export type ReadingRoomTab = 'desk' | 'chat' | 'watchlist'

export interface RunRecord {
  id: string
  messageId: string
  title: string
  preview: string
  status: string
  toneClass: string
  toolLabels: string[]
}
