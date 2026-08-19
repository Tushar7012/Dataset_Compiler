import { useEffect, useState } from 'react'
import { cancelRun, resumeRun } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { RunStatus } from '../../api/types'

interface RunProgressStepProps {
  runId: string
  onCompleted: () => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function RunProgressStep({ runId, onCompleted }: RunProgressStepProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  const [stage, setStage] = useState<RunStatus | null>(null)
  const [progress, setProgress] = useState({ completed: 0, total: 0 })
  const [actionError, setActionError] = useState<string | null>(null)
  const [isActing, setIsActing] = useState(false)
  const [subscriptionKey, setSubscriptionKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    subscribeToRunEvents(
      runId,
      (event) => {
        setStage(event.stage as RunStatus)
        setProgress({ completed: event.completed_rows, total: event.total_rows })
      },
      controller.signal,
    ).catch(() => {})
    return () => controller.abort()
    // subscriptionKey has no value of its own — it exists only to force a
    // fresh subscription after a resume, since the run's terminal SSE stream
    // from before the resume already ended.
  }, [runId, subscriptionKey])

  useEffect(() => {
    if (stage === 'completed') onCompleted()
  }, [stage, onCompleted])

  const cancel = () => {
    setActionError(null)
    setIsActing(true)
    cancelRun(runId)
      .catch((error: unknown) => setActionError(errorMessage(error)))
      .finally(() => setIsActing(false))
  }

  const resume = () => {
    setActionError(null)
    setIsActing(true)
    resumeRun(runId)
      .then(() => setSubscriptionKey((key) => key + 1))
      .catch((error: unknown) => setActionError(errorMessage(error)))
      .finally(() => setIsActing(false))
  }

  const canCancel = stage === 'pending' || stage === 'running'
  const canResume = stage === 'cancelled' || stage === 'failed'

  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Run progress
      </h2>
      <div className="card">
        <p>
          Run status: <strong>{stage ?? 'pending'}</strong> ({progress.completed}/{progress.total} rows)
        </p>
        <progress className="run-progress-bar" value={progress.completed} max={progress.total || 1} />
      </div>

      <div className="button-row">
        {canCancel && (
          <button type="button" disabled={isActing} onClick={cancel}>
            Cancel
          </button>
        )}
        {canResume && (
          <button type="button" disabled={isActing} onClick={resume}>
            Resume
          </button>
        )}
      </div>
      {actionError && <p role="alert">{actionError}</p>}
    </section>
  )
}
