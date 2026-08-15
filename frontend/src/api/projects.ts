import { apiFetch } from './client'
import type { Project, Source } from './types'

export function createProject(name: string): Promise<Project> {
  return apiFetch<Project>('/api/projects', { method: 'POST', json: { name } })
}

export function uploadSource(projectId: string, file: File): Promise<Source> {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch<Source>(`/api/projects/${projectId}/sources`, { method: 'POST', formData })
}
