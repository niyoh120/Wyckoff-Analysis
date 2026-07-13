import type { ChatRunEvent, RunCheckpoint } from './types'

const STORAGE_PREFIX = 'wyckoff:reading-room-run:'
const MAX_EVENTS = 80

export function readRunCheckpoint(conversationId: string): RunCheckpoint | null {
  if (!conversationId || typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(storageKey(conversationId))
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<RunCheckpoint>
    if (!value.runId || !value.conversationId || !Array.isArray(value.events)) return null
    return {
      runId: value.runId,
      conversationId: value.conversationId,
      status: value.status === 'completed' || value.status === 'interrupted' ? value.status : 'running',
      startedAt: value.startedAt || new Date().toISOString(),
      updatedAt: value.updatedAt || new Date().toISOString(),
      events: value.events.slice(-MAX_EVENTS) as ChatRunEvent[],
    }
  } catch {
    return null
  }
}

export function appendRunEvent(conversationId: string, event: ChatRunEvent): RunCheckpoint | null {
  if (!conversationId) return null
  const current = readRunCheckpoint(conversationId)
  const now = new Date().toISOString()
  const base = current?.runId === event.runId ? current : {
    runId: event.runId,
    conversationId,
    status: 'running' as const,
    startedAt: event.timestamp || now,
    updatedAt: now,
    events: [],
  }
  const next: RunCheckpoint = {
    ...base,
    status: 'running',
    updatedAt: now,
    events: [...base.events, event].slice(-MAX_EVENTS),
  }
  writeCheckpoint(next)
  return next
}

export function finishRun(conversationId: string, status: 'completed' | 'interrupted'): RunCheckpoint | null {
  const current = readRunCheckpoint(conversationId)
  if (!current) return null
  const next = { ...current, status, updatedAt: new Date().toISOString() }
  writeCheckpoint(next)
  return next
}

export function clearRunCheckpoint(conversationId: string): void {
  if (!conversationId || typeof window === 'undefined') return
  try { window.localStorage.removeItem(storageKey(conversationId)) } catch { /* browser storage is optional */ }
}

function writeCheckpoint(checkpoint: RunCheckpoint): void {
  if (typeof window === 'undefined') return
  try { window.localStorage.setItem(storageKey(checkpoint.conversationId), JSON.stringify(checkpoint)) } catch { /* browser storage is optional */ }
}

function storageKey(conversationId: string): string {
  return `${STORAGE_PREFIX}${conversationId}`
}
