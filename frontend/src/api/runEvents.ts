import { getSessionToken } from './session'

export interface RunEvent {
  run_id: string
  sequence: number
  stage: string
  completed_rows: number
  total_rows: number
}

// The backend's SSE endpoint requires a bearer Authorization header, which
// the native EventSource API cannot set — it only supports plain GET with no
// custom headers. fetch() plus a manual ReadableStream reader is the
// standard workaround: same auth path as every other request in this app,
// just parsed as "data: {...}\n\n" frames instead of a single JSON body.
const TERMINAL_STAGES = new Set(['completed', 'cancelled', 'failed'])

export async function subscribeToRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = await getSessionToken()
  const response = await fetch(`/api/runs/${runId}/events`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`failed to open run event stream: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const dataLine = rawEvent.split('\n').find((line) => line.startsWith('data: '))
      if (dataLine) {
        const event = JSON.parse(dataLine.slice('data: '.length)) as RunEvent
        onEvent(event)
        if (TERMINAL_STAGES.has(event.stage)) return
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}
