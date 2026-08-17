import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { estimateRows, recommendPlan } from '../../api/plans'
import { ApiError } from '../../api/client'
import type { TrainingGoal, TrainingPlanResponse } from '../../api/types'

interface GoalWizardStepProps {
  projectId: string
  modelProfileId: string
  initialGoal?: TrainingGoal
  initialDesiredBehavior?: string
  onPlanRecommended: (plan: TrainingPlanResponse) => void
}

function errorDisplay(error: unknown): { message: string; needsProviderSetup: boolean } {
  if (error instanceof ApiError) {
    return { message: error.message, needsProviderSetup: error.status === 409 && /profile_id/.test(error.message) }
  }
  return { message: 'Something went wrong. Try again.', needsProviderSetup: false }
}

export function GoalWizardStep({
  projectId,
  modelProfileId,
  initialGoal,
  initialDesiredBehavior,
  onPlanRecommended,
}: GoalWizardStepProps) {
  const [goal, setGoal] = useState<TrainingGoal>(initialGoal ?? 'domain_adaptation')
  const [desiredBehavior, setDesiredBehavior] = useState(initialDesiredBehavior ?? '')
  const [language, setLanguage] = useState('en')

  const estimateQuery = useQuery({
    queryKey: ['estimated-rows', projectId, modelProfileId],
    queryFn: () => estimateRows(projectId, modelProfileId),
  })
  const targetRows = estimateQuery.data
    ? Math.min(estimateQuery.data.total_rows, estimateQuery.data.capped_at)
    : undefined

  const recommendMutation = useMutation({
    mutationFn: () =>
      recommendPlan(projectId, modelProfileId, {
        goal,
        desired_behavior: desiredBehavior,
        language,
        target_rows: targetRows as number,
      }),
    onSuccess: (plan) => onPlanRecommended(plan),
  })

  const error = recommendMutation.isError ? errorDisplay(recommendMutation.error) : null

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        recommendMutation.mutate()
      }}
    >
      <label htmlFor="goal">Training goal</label>
      <select id="goal" value={goal} onChange={(event) => setGoal(event.target.value as TrainingGoal)}>
        <option value="domain_adaptation">Domain adaptation</option>
        <option value="single_turn_instruction">Single-turn instruction</option>
        <option value="multi_turn_conversation">Multi-turn conversation</option>
        <option value="preference_alignment">Preference alignment</option>
      </select>

      <label htmlFor="desired-behavior">Desired behavior</label>
      <textarea
        id="desired-behavior"
        value={desiredBehavior}
        onChange={(event) => setDesiredBehavior(event.target.value)}
      />

      <label htmlFor="language">Language</label>
      <input id="language" value={language} onChange={(event) => setLanguage(event.target.value)} />

      {estimateQuery.isError && (
        <p role="alert">Could not estimate rows — upload a document source first.</p>
      )}
      {estimateQuery.data && (
        <p>
          This will generate up to <strong>{targetRows}</strong> rows, covering every chunk of your uploaded
          sources.
          {estimateQuery.data.truncated && (
            <>
              {' '}
              Your sources contain {estimateQuery.data.total_rows} rows — only the first{' '}
              {estimateQuery.data.capped_at.toLocaleString('en-US')} will be processed.
            </>
          )}
        </p>
      )}

      <button type="submit" disabled={recommendMutation.isPending || targetRows === undefined}>
        Get recommendation
      </button>

      {error && (
        <p role="alert">
          {error.message}
          {error.needsProviderSetup && ' — finish provider setup, then try again.'}
        </p>
      )}
    </form>
  )
}
