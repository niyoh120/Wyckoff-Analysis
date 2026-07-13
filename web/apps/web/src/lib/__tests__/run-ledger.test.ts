import { afterEach, describe, expect, it, vi } from 'vitest'
import { appendRunEvent, clearRunCheckpoint, finishRun, readRunCheckpoint } from '@/features/reading-room/run-ledger'

afterEach(() => vi.unstubAllGlobals())

function installStorage() {
  const values = new Map<string, string>()
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  })
}

describe('reading room run ledger', () => {
  it('keeps the latest run events and marks completion', () => {
    installStorage()
    const first = {
      runId: 'run-1',
      sequence: 1,
      type: 'tool_started',
      label: '读取 market_overview',
      timestamp: '2026-07-13T00:00:00.000Z',
    } as const
    const second = { ...first, sequence: 2, type: 'answer_started', label: '开始生成结论' } as const

    appendRunEvent('conversation-1', first)
    const checkpoint = appendRunEvent('conversation-1', second)
    expect(checkpoint?.status).toBe('running')
    expect(checkpoint?.events.map((event) => event.type)).toEqual(['tool_started', 'answer_started'])

    const completed = finishRun('conversation-1', 'completed')
    expect(completed?.status).toBe('completed')
    expect(readRunCheckpoint('conversation-1')?.events).toHaveLength(2)
  })

  it('clears a checkpoint without affecting another conversation', () => {
    installStorage()
    const event = {
      runId: 'run-2',
      sequence: 1,
      type: 'model_started',
      label: '开始使用 test-model',
      timestamp: '2026-07-13T00:00:00.000Z',
    } as const

    appendRunEvent('conversation-a', event)
    appendRunEvent('conversation-b', event)
    clearRunCheckpoint('conversation-a')

    expect(readRunCheckpoint('conversation-a')).toBeNull()
    expect(readRunCheckpoint('conversation-b')?.runId).toBe('run-2')
  })
})
