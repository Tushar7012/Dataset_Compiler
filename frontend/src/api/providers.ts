import { apiFetch } from './client'
import type { ProviderProfile, ProviderProfileInput } from './types'

export function createProvider(projectId: string, input: ProviderProfileInput): Promise<ProviderProfile> {
  return apiFetch<ProviderProfile>('/api/providers', {
    method: 'POST',
    json: { project_id: projectId, ...input },
  })
}
