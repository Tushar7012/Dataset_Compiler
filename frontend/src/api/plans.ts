import { apiFetch } from './client'
import type { PlanApproval, RowEstimateResponse, TrainingIntentInput, TrainingPlanResponse } from './types'

export function recommendPlan(
  projectId: string,
  modelProfileId: string,
  intent: TrainingIntentInput,
): Promise<TrainingPlanResponse> {
  return apiFetch<TrainingPlanResponse>('/api/plans/recommend', {
    method: 'POST',
    json: {
      project_id: projectId,
      model_profile_id: modelProfileId,
      goal: intent.goal,
      target_rows: intent.target_rows,
      generator_profile_id: intent.generator_profile_id,
      judge_profile_id: intent.judge_profile_id,
      objective_override: intent.objective_override,
    },
  })
}

export function approvePlan(planId: string): Promise<PlanApproval> {
  return apiFetch<PlanApproval>(`/api/plans/${planId}/approve`, { method: 'POST' })
}

export function estimateRows(projectId: string, modelProfileId: string): Promise<RowEstimateResponse> {
  return apiFetch<RowEstimateResponse>(
    `/api/plans/estimated-rows?project_id=${projectId}&model_profile_id=${modelProfileId}`,
  )
}
