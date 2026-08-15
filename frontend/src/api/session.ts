// Holds the process-generated bearer token in memory only — never localStorage,
// never a cookie. A page reload always re-fetches from the server, which is
// exactly the "held in memory only, never persisted" contract this app requires.
let cachedToken: Promise<string> | null = null

export function getSessionToken(): Promise<string> {
  if (!cachedToken) {
    cachedToken = fetch('/api/session')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`session bootstrap failed: ${response.status}`)
        }
        return response.json() as Promise<{ token: string }>
      })
      .then(({ token }) => token)
      .catch((error: unknown) => {
        cachedToken = null
        throw error
      })
  }
  return cachedToken
}

export function resetSessionTokenForTests(): void {
  cachedToken = null
}
