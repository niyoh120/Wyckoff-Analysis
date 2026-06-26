import { describe, expect, it } from 'vitest'
import { PROVIDER_BASE_URLS } from '@wyckoff/shared'

describe('provider constants', () => {
  it('uses the 1Route API gateway as the default base URL', () => {
    expect(PROVIDER_BASE_URLS['1route']).toBe('https://api.1route.dev/v1')
  })
})
