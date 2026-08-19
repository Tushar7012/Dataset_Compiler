// Holds the process-generated bearer token in memory only — never localStorage,
// never a cookie. A page reload always re-fetches from the server, which is
// exactly the "held in memory only, never persisted" contract this app requires.
interface SessionBootstrap {
  token: string
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

export function resetSessionTokenForTests(): void {
  cachedSession = null
}
