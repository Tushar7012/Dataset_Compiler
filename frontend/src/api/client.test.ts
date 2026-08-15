import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, ApiError } from './client'
import { resetSessionTokenForTests } from './session'

describe('apiFetch', () => {
  beforeEach(() => {
    resetSessionTokenForTests()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mockFetchSequence(...responses: Response[]): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn()
    for (const response of responses) {
      fetchMock.mockResolvedValueOnce(response)
    }
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('fetches the session token once, then attaches it as a bearer header', async () => {
    const fetchMock = mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ id: '1', name: 'proj' }), { status: 201 }),
    )

    const result = await apiFetch<{ id: string; name: string }>('/api/projects', {
      method: 'POST',
      json: { name: 'proj' },
    })

    expect(result).toEqual({ id: '1', name: 'proj' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, projectCall] = fetchMock.mock.calls
    const [, requestInit] = projectCall as [string, RequestInit]
    const headers = requestInit.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer abc123')
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('reuses the cached session token across multiple calls', async () => {
    const fetchMock = mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )

    await apiFetch('/api/health')
    await apiFetch('/api/health')

    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('throws ApiError with the backend detail message on non-2xx responses', async () => {
    mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ detail: "'name' is required" }), { status: 422 }),
    )

    await expect(apiFetch('/api/projects', { method: 'POST', json: {} })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: "'name' is required",
    })
  })

  it('is an instance of ApiError so callers can narrow with instanceof', async () => {
    mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ detail: 'not found' }), { status: 404 }),
    )

    try {
      await apiFetch('/api/projects/missing')
      expect.unreachable('expected apiFetch to throw')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
    }
  })
})
