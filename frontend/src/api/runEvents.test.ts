import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { subscribeToRunEvents } from './runEvents'
import { resetSessionTokenForTests } from './session'
import type { RunEvent } from './runEvents'

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let index = 0
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]))
        index += 1
      } else {
        controller.close()
      }
    },
  })
}

describe('subscribeToRunEvents', () => {
  beforeEach(() => {
    resetSessionTokenForTests()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('parses SSE events and stops at a terminal stage', async () => {
    const events = [
      'data: {"run_id":"r1","sequence":0,"stage":"running","completed_rows":1,"total_rows":3}\n\n',
      'data: {"run_id":"r1","sequence":1,"stage":"completed","completed_rows":3,"total_rows":3}\n\n',
    ]
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'abc' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(sseStream(events), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const received: RunEvent[] = []
    await subscribeToRunEvents('r1', (event) => received.push(event))

    expect(received).toHaveLength(2)
    expect(received[0].stage).toBe('running')
    expect(received[1].stage).toBe('completed')

    const [, eventsCall] = fetchMock.mock.calls
    const [url, requestInit] = eventsCall as [string, RequestInit]
    expect(url).toBe('/api/runs/r1/events')
    const headers = requestInit.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer abc')
  })

  it('handles a chunk boundary that splits a single SSE event', async () => {
    const events = [
      'data: {"run_id":"r1","sequence":0,"stage":"running","completed_rows":1,"total_rows":3}',
      '\n\ndata: {"run_id":"r1","sequence":1,"stage":"completed","completed_rows":3,"total_rows":3}\n\n',
    ]
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'abc' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(sseStream(events), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const received: RunEvent[] = []
    await subscribeToRunEvents('r1', (event) => received.push(event))

    expect(received).toHaveLength(2)
  })

  it('stops on a failed stage without throwing', async () => {
    const events = ['data: {"run_id":"r1","sequence":0,"stage":"failed","completed_rows":0,"total_rows":3}\n\n']
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'abc' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(sseStream(events), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const received: RunEvent[] = []
    await subscribeToRunEvents('r1', (event) => received.push(event))

    expect(received).toHaveLength(1)
    expect(received[0].stage).toBe('failed')
  })
})
