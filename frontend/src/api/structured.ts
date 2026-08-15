import { apiFetch } from './client'
import type { NormalizePreviewResponse, SchemaDetection } from './types'

export function getSourceSchema(projectId: string, sourceId: string): Promise<SchemaDetection> {
  return apiFetch<SchemaDetection>(`/api/projects/${projectId}/sources/${sourceId}/schema`)
}

export function normalizePreview(
  projectId: string,
  sourceId: string,
  mapping?: Record<string, string>,
): Promise<NormalizePreviewResponse> {
  return apiFetch<NormalizePreviewResponse>(`/api/projects/${projectId}/sources/${sourceId}/normalize-preview`, {
    method: 'POST',
    json: { mapping },
  })
}
