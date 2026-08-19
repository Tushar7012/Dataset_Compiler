import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getSessionToken, resetSessionTokenForTests } from './session'

describe('session bootstrap', () => {
  beforeEach(() => {
    resetSessionTokenForTests()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resolves the token from /api/session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ token: 'tok-1' }),
      }),
    )

    await expect(getSessionToken()).resolves.toBe('tok-1')
  })

  it('only calls /api/session once across repeated calls', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ token: 'tok-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getSessionToken()
    await getSessionToken()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('resets the cache and lets a later call retry after a failed bootstrap', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'tok-2' }) })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getSessionToken()).rejects.toThrow()
    await expect(getSessionToken()).resolves.toBe('tok-2')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
