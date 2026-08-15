import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { recommendPlan } from '../../api/plans'
import { ApiError } from '../../api/client'
import type { TrainingGoal, TrainingPlanResponse } from '../../api/types'

interface GoalWizardStepProps {
  projectId: string
  modelProfileId: string
  onPlanRecommended: (plan: TrainingPlanResponse) => void
}

function errorDisplay(error: unknown): { message: string; needsProviderSetup: boolean } {
  if (error instanceof ApiError) {
    return { message: error.message, needsProviderSetup: error.status === 409 && /profile_id/.test(error.message) }
  }
  return { message: 'Something went wrong. Try again.', needsProviderSetup: false }
}

export function GoalWizardStep({ projectId, modelProfileId, onPlanRecommended }: GoalWizardStepProps) {
  const [goal, setGoal] = useState<TrainingGoal>('domain_adaptation')
  const [desiredBehavior, setDesiredBehavior] = useState('')
  const [language, setLanguage] = useState('en')
  const [targetRows, setTargetRows] = useState(200)

  const recommendMutation = useMutation({
    mutationFn: () =>
      recommendPlan(projectId, modelProfileId, {
        goal,
        desired_behavior: desiredBehavior,
        language,
        target_rows: targetRows,
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

      <label htmlFor="target-rows">Target rows</label>
      <input
        id="target-rows"
        type="number"
        value={targetRows}
        onChange={(event) => setTargetRows(Number(event.target.value))}
      />

      <button type="submit" disabled={recommendMutation.isPending}>
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
