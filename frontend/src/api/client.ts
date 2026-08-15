import { getSessionToken } from './session'

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  json?: unknown
  formData?: FormData
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = await getSessionToken()
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  }

  let body: BodyInit | undefined
  if (options.formData) {
    body = options.formData
  } else if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  }

  const response = await fetch(path, { method: options.method ?? 'GET', headers, body })

  if (!response.ok) {
    throw new ApiError(response.status, await extractErrorDetail(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
    return JSON.stringify(body)
  } catch {
    return response.statusText
  }
}
