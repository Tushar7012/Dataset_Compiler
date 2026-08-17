import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { suggestGoal } from '../../api/plans'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { TrainingGoal } from '../../api/types'

interface GoalSuggestionStepProps {
  projectId: string
  onDecision: (initialGoal: TrainingGoal | null, initialDesiredBehavior: string) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

function ConsentPanel({
  consentGranted,
  setConsentGranted,
  isPending,
  error,
  onSuggest,
  onSkip,
}: {
  consentGranted: boolean
  setConsentGranted: (value: boolean) => void
  isPending: boolean
  error: unknown
  onSuggest: () => void
  onSkip: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Suggested training goal
      </h2>
      <p>
        Let Gemini suggest a training goal from your uploaded document. This sends a sample of your document text
        to Google&apos;s Gemini API.
      </p>

      <div className="field">
        <label htmlFor="goal-suggestion-consent">
          <input
            id="goal-suggestion-consent"
            type="checkbox"
            checked={consentGranted}
            onChange={(event) => setConsentGranted(event.target.checked)}
          />
          I consent to sending a sample of my project&apos;s document text to Gemini
        </label>
      </div>

      <div className="button-row">
        <button type="button" disabled={!consentGranted || isPending} onClick={onSuggest}>
          Get AI suggestion
        </button>
        <button type="button" onClick={onSkip}>
          Skip — I&apos;ll choose the goal myself
        </button>
      </div>

      {error != null && <p role="alert">{errorMessage(error)}</p>}
    </section>
  )
}

function SuggestionPanel({
  goal,
  rationale,
  desiredBehavior,
  onAccept,
  onReject,
}: {
  goal: TrainingGoal
  rationale: string
  desiredBehavior: string
  onAccept: () => void
  onReject: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Suggested training goal
      </h2>
      <p>
        Suggested goal: <strong>{goal}</strong>
      </p>
      <p>{rationale}</p>
      <p>Suggested desired behavior: {desiredBehavior}</p>
      <div className="button-row">
        <button type="button" onClick={onAccept}>
          Accept
        </button>
        <button type="button" onClick={onReject}>
          Reject
        </button>
      </div>
    </section>
  )
}

function OwnPurposePanel({
  ownPurpose,
  setOwnPurpose,
  onContinue,
}: {
  ownPurpose: string
  setOwnPurpose: (value: string) => void
  onContinue: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Describe your own goal
      </h2>
      <div className="field">
        <label htmlFor="own-purpose">Describe your own purpose</label>
        <textarea id="own-purpose" value={ownPurpose} onChange={(event) => setOwnPurpose(event.target.value)} />
      </div>
      <div className="button-row">
        <button type="button" onClick={onContinue}>
          Continue with my own goal
        </button>
      </div>
    </section>
  )
}

export function GoalSuggestionStep({ projectId, onDecision }: GoalSuggestionStepProps) {
  const [consentGranted, setConsentGranted] = useState(false)
  const [rejected, setRejected] = useState(false)
  const [ownPurpose, setOwnPurpose] = useState('')

  const suggestMutation = useMutation({ mutationFn: () => suggestGoal(projectId) })
  const suggestion = suggestMutation.data

  if (!suggestion) {
    return (
      <ConsentPanel
        consentGranted={consentGranted}
        setConsentGranted={setConsentGranted}
        isPending={suggestMutation.isPending}
        error={suggestMutation.isError ? suggestMutation.error : null}
        onSuggest={() => suggestMutation.mutate()}
        onSkip={() => onDecision(null, '')}
      />
    )
  }

  if (!rejected) {
    return (
      <SuggestionPanel
        goal={suggestion.goal}
        rationale={suggestion.rationale}
        desiredBehavior={suggestion.desired_behavior}
        onAccept={() => onDecision(suggestion.goal, suggestion.desired_behavior)}
        onReject={() => setRejected(true)}
      />
    )
  }

  return (
    <OwnPurposePanel
      ownPurpose={ownPurpose}
      setOwnPurpose={setOwnPurpose}
      onContinue={() => onDecision(null, ownPurpose)}
    />
  )
}
