import { describe, expect, it } from 'vitest'
import { userHistoryKey } from '../local-history'

describe('userHistoryKey', () => {
  it('creates stable non-raw browser history keys', () => {
    expect(userHistoryKey('user-1')).toBe(userHistoryKey('user-1'))
    expect(userHistoryKey('user-1')).not.toBe('user-1')
    expect(userHistoryKey('user-1')).not.toBe(userHistoryKey('user-2'))
  })

  it('uses the anonymous bucket when no user id is available', () => {
    expect(userHistoryKey()).toBe(userHistoryKey(''))
    expect(userHistoryKey(null)).toBe(userHistoryKey('anonymous'))
  })
})
