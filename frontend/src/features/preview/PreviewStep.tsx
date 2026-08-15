import { useEffect, useState } from 'react'
import { approveFull, createPreview, listRunRecords } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'
import { ApiError } from '../../api/client'
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
    return (
      <section>
        <button type="button" disabled={isCreating} onClick={startPreview}>
          Generate preview
        </button>
        {createError && <p role="alert">{createError}</p>}
      </section>
    )
  }

  return (
    <section>
      <p>
        Preview status: <strong>{stage ?? run.status}</strong> ({progress.completed}/{progress.total} rows)
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

      {stage === 'completed' && (
        <button type="button" disabled={isApproving} onClick={approve}>
          Approve full run
        </button>
      )}
      {approveError && <p role="alert">{approveError}</p>}
    </section>
  )
}
