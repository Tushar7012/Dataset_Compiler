import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { estimateRows } from '../../api/plans'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { TrainingGoal } from '../../api/types'

export interface GoalDecision {
  goal: TrainingGoal
  targetRows: number
}

interface GoalWizardStepProps {
  projectId: string
  modelProfileId: string
  onGoalChosen: (decision: GoalDecision) => void
}

export function GoalWizardStep({ projectId, modelProfileId, onGoalChosen }: GoalWizardStepProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  const [goal, setGoal] = useState<TrainingGoal>('domain_adaptation')

  const estimateQuery = useQuery({
    queryKey: ['estimated-rows', projectId, modelProfileId],
    queryFn: () => estimateRows(projectId, modelProfileId),
  })
  const targetRows = estimateQuery.data
    ? Math.min(estimateQuery.data.total_rows, estimateQuery.data.capped_at)
    : undefined

  return (
    <section className="wizard-step">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!targetRows) return
          onGoalChosen({ goal, targetRows })
        }}
      >
        <h2 ref={headingRef} tabIndex={-1}>
          Training goal
        </h2>
        <div className="field">
          <label htmlFor="goal">Training goal</label>
          <select id="goal" value={goal} onChange={(event) => setGoal(event.target.value as TrainingGoal)}>
            <option value="domain_adaptation">CPT — continued pretraining on raw text</option>
            <option value="single_turn_instruction">SFT — single-turn (prompt / completion)</option>
            <option value="multi_turn_conversation">SFT — multi-turn conversation</option>
            <option value="preference_alignment">DPO — preference alignment</option>
          </select>
        </div>

        {estimateQuery.isError && (
          <p role="alert">Could not estimate rows — upload a document source first.</p>
        )}
        {estimateQuery.data && estimateQuery.data.total_rows === 0 && (
          <p role="alert">No rows to generate yet — upload a document source first.</p>
        )}
        {estimateQuery.data && estimateQuery.data.total_rows > 0 && (
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

        <div className="button-row">
          <button type="submit" disabled={!targetRows}>
            Continue
          </button>
        </div>
      </form>
    </section>
  )
}
