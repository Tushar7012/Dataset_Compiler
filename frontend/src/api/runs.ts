import { apiFetch } from './client'
import { getSessionToken } from './session'
import type { RunCreated, RunRecordsResponse, RunSummary } from './types'

interface CreatePreviewInput {
  planId: string
  generatorProfileId: string
  judgeProfileId?: string
}

export function createPreview(input: CreatePreviewInput): Promise<RunCreated> {
  return apiFetch<RunCreated>('/api/runs/preview', {
    method: 'POST',
    json: {
      plan_id: input.planId,
      generator_profile_id: input.generatorProfileId,
      judge_profile_id: input.judgeProfileId,
    },
  })
}

export function approveFull(runId: string): Promise<RunCreated> {
  return apiFetch<RunCreated>(`/api/runs/${runId}/approve-full`, { method: 'POST' })
}

export function getRun(runId: string): Promise<RunSummary> {
  return apiFetch<RunSummary>(`/api/runs/${runId}`)
}

export function cancelRun(runId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/runs/${runId}/cancel`, { method: 'POST' })
}

export function resumeRun(runId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/runs/${runId}/resume`, { method: 'POST' })
}

export function listRunRecords(runId: string, limit = 20): Promise<RunRecordsResponse> {
  return apiFetch<RunRecordsResponse>(`/api/runs/${runId}/records?limit=${limit}`)
}

export function exportRun(runId: string): Promise<{ run_id: string; export_dir: string }> {
  return apiFetch(`/api/runs/${runId}/export`, { method: 'POST' })
}

// apiFetch always parses a JSON body — a zip download needs the raw Response
// so its bytes can be read as a Blob instead, hence a plain fetch here with
// the same manual bearer-header attachment apiFetch does internally.
export async function downloadExport(runId: string): Promise<Blob> {
  const token = await getSessionToken()
  const response = await fetch(`/api/exports/${runId}/download`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new Error(`export download failed: ${response.status}`)
  }
  return response.blob()
}
