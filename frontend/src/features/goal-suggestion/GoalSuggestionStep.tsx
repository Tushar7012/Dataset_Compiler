import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { suggestGoal } from '../../api/plans'
import { ApiError } from '../../api/client'
import type { TrainingGoal } from '../../api/types'

interface GoalSuggestionStepProps {
  projectId: string
  onDecision: (initialGoal: TrainingGoal | null, initialDesiredBehavior: string) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function GoalSuggestionStep({ projectId, onDecision }: GoalSuggestionStepProps) {
  const [consentGranted, setConsentGranted] = useState(false)
  const [rejected, setRejected] = useState(false)
  const [ownPurpose, setOwnPurpose] = useState('')

  const suggestMutation = useMutation({ mutationFn: () => suggestGoal(projectId) })
  const suggestion = suggestMutation.data

  if (!suggestion) {
    return (
      <section>
        <p>
          Let Gemini suggest a training goal from your uploaded document. This sends a sample of your document
          text to Google&apos;s Gemini API.
        </p>

        <label htmlFor="goal-suggestion-consent">
          <input
            id="goal-suggestion-consent"
            type="checkbox"
            checked={consentGranted}
            onChange={(event) => setConsentGranted(event.target.checked)}
          />
          I consent to sending a sample of my project&apos;s document text to Gemini
        </label>

        <button
          type="button"
          disabled={!consentGranted || suggestMutation.isPending}
          onClick={() => suggestMutation.mutate()}
        >
          Get AI suggestion
        </button>
        <button type="button" onClick={() => onDecision(null, '')}>
          Skip — I&apos;ll choose the goal myself
        </button>

        {suggestMutation.isError && <p role="alert">{errorMessage(suggestMutation.error)}</p>}
      </section>
    )
  }

  if (!rejected) {
    return (
      <section>
        <p>
          Suggested goal: <strong>{suggestion.goal}</strong>
        </p>
        <p>{suggestion.rationale}</p>
        <p>Suggested desired behavior: {suggestion.desired_behavior}</p>
        <button type="button" onClick={() => onDecision(suggestion.goal, suggestion.desired_behavior)}>
          Accept
        </button>
        <button type="button" onClick={() => setRejected(true)}>
          Reject
        </button>
      </section>
    )
  }

  return (
    <section>
      <label htmlFor="own-purpose">Describe your own purpose</label>
      <textarea id="own-purpose" value={ownPurpose} onChange={(event) => setOwnPurpose(event.target.value)} />
      <button type="button" onClick={() => onDecision(null, ownPurpose)}>
        Continue with my own goal
      </button>
    </section>
  )
}
