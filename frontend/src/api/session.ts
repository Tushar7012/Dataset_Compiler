// Holds the process-generated bearer token in memory only — never localStorage,
// never a cookie. A page reload always re-fetches from the server, which is
// exactly the "held in memory only, never persisted" contract this app requires.
interface SessionBootstrap {
  token: string
  remote_parsing_enabled: boolean
}

let cachedSession: Promise<SessionBootstrap> | null = null

function fetchSession(): Promise<SessionBootstrap> {
  if (!cachedSession) {
    cachedSession = fetch('/api/session')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`session bootstrap failed: ${response.status}`)
        }
        return response.json() as Promise<SessionBootstrap>
      })
      .catch((error: unknown) => {
        cachedSession = null
        throw error
      })
  }
  return cachedSession
}

export function getSessionToken(): Promise<string> {
  return fetchSession().then((session) => session.token)
}

// True when the server has a remote (DGX) docling-parsing service configured.
// Provider endpoint_scope alone can't tell the wizard this — a project can use
// entirely local LLM providers and still need remote-parsing consent.
export function getRemoteParsingEnabled(): Promise<boolean> {
  return fetchSession().then((session) => session.remote_parsing_enabled)
}

export function resetSessionTokenForTests(): void {
  cachedSession = null
}
