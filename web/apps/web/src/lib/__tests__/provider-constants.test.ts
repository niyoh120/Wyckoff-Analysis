import { describe, expect, it } from 'vitest'
import { ALLOWED_MODEL_BASE_URLS, PROVIDER_BASE_URLS, isAllowedModelBaseUrl, isSafeProviderBaseUrl } from '@wyckoff/shared'

describe('provider constants', () => {
  it('uses the 1Route API gateway as the default base URL', () => {
    expect(PROVIDER_BASE_URLS['1route']).toBe('https://api.1route.dev/v1')
  })

  it('rejects unsafe server-side provider targets', () => {
    expect(isSafeProviderBaseUrl('https://api.openai.com/v1')).toBe(true)
    expect(isSafeProviderBaseUrl('http://api.openai.com/v1')).toBe(false)
    expect(isSafeProviderBaseUrl('https://127.0.0.1/v1')).toBe(false)
    expect(isSafeProviderBaseUrl('https://169.254.169.254/latest')).toBe(false)
    expect(isSafeProviderBaseUrl('https://user:pass@example.com/v1')).toBe(false)
    expect(isSafeProviderBaseUrl('https://example.com:8443/v1')).toBe(false)
  })

  it('does not allow the retired plaintext provider origin', () => {
    expect(ALLOWED_MODEL_BASE_URLS).not.toContain('http://token.thegun.cn:8317')
    expect(isAllowedModelBaseUrl('http://token.thegun.cn:8317/v1')).toBe(false)
  })

  it('allows Volcengine Ark OpenAI-compatible base URLs', () => {
    expect(ALLOWED_MODEL_BASE_URLS).toEqual(expect.arrayContaining([
      'https://ark.cn-beijing.volces.com/api/v3',
      'https://ark.cn-beijing.volces.com/api/coding/v3',
    ]))
    expect(isAllowedModelBaseUrl('https://ark.cn-beijing.volces.com/api/v3')).toBe(true)
    expect(isAllowedModelBaseUrl('https://ark.cn-beijing.volces.com/api/coding/v3')).toBe(true)
    expect(isAllowedModelBaseUrl('https://ark.cn-beijing.volces.com/api/other')).toBe(false)
  })
})
