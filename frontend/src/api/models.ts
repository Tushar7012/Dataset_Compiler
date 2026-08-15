import { apiFetch } from './client'
import type { ModelProfileResponse, ModelSource } from './types'

export function analyzeModel(
  projectId: string,
  modelId: string,
  source: ModelSource = 'huggingface',
): Promise<ModelProfileResponse> {
  return apiFetch<ModelProfileResponse>('/api/models/analyze', {
    method: 'POST',
    json: { project_id: projectId, model_id: modelId, source },
  })
}
