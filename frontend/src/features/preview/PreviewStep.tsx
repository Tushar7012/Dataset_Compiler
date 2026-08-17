import { useEffect, useState } from 'react'
import { approveFull, createPreview, listRunRecords } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { RunCreated, RunRecordsResponse, RunStatus } from '../../api/types'

interface PreviewStepProps {
  planId: string
  generatorProfileId: string
  judgeProfileId?: string
  remoteConsentGranted: boolean
  onApprovedFull: (fullRun: RunCreated) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

function PreviewIdle({
  isCreating,
  createError,
  onStart,
}: {
  isCreating: boolean
  createError: string | null
  onStart: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Preview
      </h2>
      <div className="button-row">
        <button type="button" disabled={isCreating} onClick={onStart}>
          Generate preview
        </button>
      </div>
      {createError && <p role="alert">{createError}</p>}
    </section>
  )
}

function PreviewRunning({
  stage,
  status,
  progress,
  records,
  isApproving,
  approveError,
  onApprove,
}: {
  stage: RunStatus | null
  status: RunStatus
  progress: { completed: number; total: number }
  records: RunRecordsResponse | null
  isApproving: boolean
  approveError: string | null
  onApprove: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Preview
      </h2>
      <div className="card">
        <p>
          Preview status: <strong>{stage ?? status}</strong> ({progress.completed}/{progress.total} rows)
        </p>

        {records && (
          <>
            <p>
              {records.total_accepted} row(s) accepted, schema: {records.canonical_schema}
            </p>
            <ol>
              {records.records.map((record, index) => (
                <li key={index}>
                  <pre>{JSON.stringify(record, null, 2)}</pre>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>

      {stage === 'completed' && (
        <div className="button-row">
          <button type="button" disabled={isApproving} onClick={onApprove}>
            Approve full run
          </button>
        </div>
      )}
      {approveError && <p role="alert">{approveError}</p>}
    </section>
  )
}

export function PreviewStep({
  planId,
  generatorProfileId,
  judgeProfileId,
  remoteConsentGranted,
  onApprovedFull,
}: PreviewStepProps) {
  const [run, setRun] = useState<RunCreated | null>(null)
  const [stage, setStage] = useState<RunStatus | null>(null)
  const [progress, setProgress] = useState({ completed: 0, total: 0 })
  const [records, setRecords] = useState<RunRecordsResponse | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [isApproving, setIsApproving] = useState(false)

  useEffect(() => {
    if (!run) return undefined
    const controller = new AbortController()
    subscribeToRunEvents(
      run.id,
      (event) => {
        setStage(event.stage as RunStatus)
        setProgress({ completed: event.completed_rows, total: event.total_rows })
      },
      controller.signal,
    ).catch(() => {})
    return () => controller.abort()
  }, [run])

  useEffect(() => {
    if (stage === 'completed' && run) {
      listRunRecords(run.id).then(setRecords).catch(() => {})
    }
  }, [stage, run])

  const startPreview = () => {
    setCreateError(null)
    setIsCreating(true)
    createPreview({ planId, generatorProfileId, judgeProfileId, remoteConsent: remoteConsentGranted })
      .then(setRun)
      .catch((error: unknown) => setCreateError(errorMessage(error)))
      .finally(() => setIsCreating(false))
  }

  const approve = () => {
    if (!run) return
    setApproveError(null)
    setIsApproving(true)
    approveFull(run.id, remoteConsentGranted)
      .then(onApprovedFull)
      .catch((error: unknown) => setApproveError(errorMessage(error)))
      .finally(() => setIsApproving(false))
  }

  if (!run) {
    return <PreviewIdle isCreating={isCreating} createError={createError} onStart={startPreview} />
  }

  return (
    <PreviewRunning
      stage={stage}
      status={run.status}
      progress={progress}
      records={records}
      isApproving={isApproving}
      approveError={approveError}
      onApprove={approve}
    />
  )
}
