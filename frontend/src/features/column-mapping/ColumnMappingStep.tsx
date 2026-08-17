import { useEffect, useState } from 'react'
import { confirmMapping, getSourceSchema, normalizePreview } from '../../api/structured'
import { ApiError } from '../../api/client'
import type { NormalizePreviewResponse, SchemaDetection } from '../../api/types'

interface ColumnMappingStepProps {
  projectId: string
  sourceId: string
  onSchemaConfirmed: (schemaName: string) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ColumnMappingStep({ projectId, sourceId, onSchemaConfirmed }: ColumnMappingStepProps) {
  const [detected, setDetected] = useState<SchemaDetection | null>(null)
  const [detectError, setDetectError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<NormalizePreviewResponse | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)

  useEffect(() => {
    getSourceSchema(projectId, sourceId)
      .then(setDetected)
      .catch((error: unknown) => setDetectError(errorMessage(error)))
  }, [projectId, sourceId])

  const mappingToSend = detected?.schema_name ? undefined : mapping

  const loadPreview = () => {
    setPreviewError(null)
    setIsLoadingPreview(true)
    normalizePreview(projectId, sourceId, mappingToSend)
      .then(setPreview)
      .catch((error: unknown) => setPreviewError(errorMessage(error)))
      .finally(() => setIsLoadingPreview(false))
  }

  const confirm = () => {
    setConfirmError(null)
    setIsConfirming(true)
    confirmMapping(projectId, sourceId, mappingToSend)
      .then((response) => onSchemaConfirmed(response.schema_name))
      .catch((error: unknown) => setConfirmError(errorMessage(error)))
      .finally(() => setIsConfirming(false))
  }

  if (!detected) {
    return <p role="alert">{detectError ?? 'Detecting format…'}</p>
  }

  return (
    <section>
      <p>
        Detected format: <strong>{detected.schema_name ?? 'unrecognized'}</strong>
      </p>

      {detected.schema_name === null && (
        <div>
          <p>Map each column to a training field:</p>
          {detected.columns.map((column) => (
            <div key={column}>
              <label htmlFor={`map-${column}`}>{column}</label>
              <input
                id={`map-${column}`}
                value={mapping[column] ?? ''}
                onChange={(event) => setMapping((previous) => ({ ...previous, [column]: event.target.value }))}
              />
            </div>
          ))}
        </div>
      )}

      <button type="button" disabled={isLoadingPreview} onClick={loadPreview}>
        Preview normalized rows
      </button>
      {previewError && <p role="alert">{previewError}</p>}

      {preview && (
        <>
          <p>
            {preview.total_rows} row(s) found, format: {preview.schema_name}
          </p>
          <ol>
            {preview.preview.map((record, index) => (
              <li key={index}>
                <pre>{JSON.stringify(record, null, 2)}</pre>
              </li>
            ))}
          </ol>
          <button type="button" disabled={isConfirming} onClick={confirm}>
            Confirm
          </button>
          {confirmError && <p role="alert">{confirmError}</p>}
        </>
      )}
    </section>
  )
}
