import { useMutation } from '@tanstack/react-query'
import { approvePlan } from '../../api/plans'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { TrainingPlanResponse } from '../../api/types'

interface PlanConfirmationStepProps {
  plan: TrainingPlanResponse
  onApproved: () => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function PlanConfirmationStep({ plan, onApproved }: PlanConfirmationStepProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  const approveMutation = useMutation({
    mutationFn: () => approvePlan(plan.id),
    onSuccess: onApproved,
  })

  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Confirm training plan
      </h2>
      <div className="card">
        <dl>
          <dt>Objective</dt>
          <dd>{plan.objective}</dd>
          <dt>Canonical schema</dt>
          <dd>{plan.canonical_schema}</dd>
          <dt>Target rows</dt>
          <dd>{plan.target_rows}</dd>
          <dt>Examples per chunk</dt>
          <dd>{plan.examples_per_chunk}</dd>
          <dt>Required validators</dt>
          <dd>{plan.required_validators.join(', ')}</dd>
          <dt>Confidence</dt>
          <dd>{Math.round(plan.confidence * 100)}%</dd>
        </dl>
      </div>

      <div className="button-row">
        <button type="button" disabled={approveMutation.isPending} onClick={() => approveMutation.mutate()}>
          Approve
        </button>
      </div>

      {approveMutation.isSuccess && <p>Plan approved.</p>}
      {approveMutation.isError && <p role="alert">{errorMessage(approveMutation.error)}</p>}
    </section>
  )
}
