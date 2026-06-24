import { useCallback, useEffect, useMemo, useState } from 'react'
import type { PinStockInput, WatchItem } from './types'
import { asRecord, normalizeStockCode, nullableNumber, sanitizeText } from './utils'

const WATCHLIST_LIMIT = 18
const WATCHLIST_STORAGE_VERSION = 'reading-room-watchlist-v1'

export interface ReadingRoomWatchlist {
  items: WatchItem[]
  add: (item: PinStockInput) => void
  remove: (code: string) => void
}

export function useReadingRoomWatchlist(userId: string | undefined): ReadingRoomWatchlist {
  const storageKey = useMemo(() => watchlistStorageKey(userId), [userId])
  const [items, setItems] = useState<WatchItem[]>([])
  const [loadedKey, setLoadedKey] = useState('')

  useEffect(() => {
    setItems(readWatchlist(storageKey))
    setLoadedKey(storageKey)
  }, [storageKey])

  useEffect(() => {
    if (loadedKey !== storageKey) return
    writeWatchlist(storageKey, items)
  }, [items, loadedKey, storageKey])

  const add = useCallback((item: PinStockInput) => {
    const code = normalizeStockCode(item.code)
    if (!code) return
    const now = new Date().toISOString()
    setItems((current) => {
      const existing = current.find((entry) => entry.code === code)
      const nextItem: WatchItem = {
        id: existing?.id || `watch-${code}`,
        code,
        name: sanitizeText(item.name) || existing?.name || '',
        reason: item.reason || existing?.reason || '读盘室观察',
        source: item.source || existing?.source || '读盘室',
        trigger: sanitizeText(item.trigger) || existing?.trigger || '等放量突破或回踩确认',
        invalidation: sanitizeText(item.invalidation) || existing?.invalidation || '跌破关键支撑或证据消失',
        addedAt: existing?.addedAt || now,
        updatedAt: now,
        score: item.score ?? existing?.score ?? null,
        changePct: item.changePct ?? existing?.changePct ?? null,
        phase: sanitizeText(item.phase) || existing?.phase || null,
        action: sanitizeText(item.action) || existing?.action || null,
      }
      return [nextItem, ...current.filter((entry) => entry.code !== code)].slice(0, WATCHLIST_LIMIT)
    })
  }, [])

  const remove = useCallback((code: string) => {
    const normalized = normalizeStockCode(code)
    setItems((current) => current.filter((item) => item.code !== normalized))
  }, [])

  return useMemo(() => ({ items, add, remove }), [add, items, remove])
}

function watchlistStorageKey(userId: string | undefined): string {
  return `wyckoff:${userId || 'guest'}:${WATCHLIST_STORAGE_VERSION}`
}

function readWatchlist(key: string): WatchItem[] {
  if (typeof window === 'undefined') return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeWatchItem).filter(Boolean).slice(0, WATCHLIST_LIMIT) as WatchItem[]
  } catch {
    return []
  }
}

function writeWatchlist(key: string, items: WatchItem[]) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, JSON.stringify(items.slice(0, WATCHLIST_LIMIT)))
  } catch {
    // localStorage may be disabled; the in-memory basket still works for this session.
  }
}

function normalizeWatchItem(value: unknown): WatchItem | null {
  const item = asRecord(value)
  const code = normalizeStockCode(item?.code)
  if (!item || !code) return null
  return {
    id: sanitizeText(item.id) || `watch-${code}`,
    code,
    name: sanitizeText(item.name),
    reason: sanitizeText(item.reason) || '读盘室观察',
    source: sanitizeText(item.source) || '读盘室',
    trigger: sanitizeText(item.trigger) || '等放量突破或回踩确认',
    invalidation: sanitizeText(item.invalidation) || '跌破关键支撑或证据消失',
    addedAt: sanitizeText(item.addedAt) || new Date().toISOString(),
    updatedAt: sanitizeText(item.updatedAt) || new Date().toISOString(),
    score: nullableNumber(item.score),
    changePct: nullableNumber(item.changePct),
    phase: sanitizeText(item.phase) || null,
    action: sanitizeText(item.action) || null,
  }
}
