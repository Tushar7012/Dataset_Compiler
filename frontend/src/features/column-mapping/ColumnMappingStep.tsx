import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { confirmMapping, getSourceSchema, normalizePreview } from '../../api/structured'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
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

function DetectingPanel({ detectError }: { detectError: string | null }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Detecting format
      </h2>
      <p role="alert">{detectError ?? 'Detecting format…'}</p>
    </section>
  )
}

function MappingPanel({
  detected,
  mapping,
  setMapping,
  preview,
  previewError,
  isLoadingPreview,
  confirmError,
  isConfirming,
  onPreview,
  onConfirm,
}: {
  detected: SchemaDetection
  mapping: Record<string, string>
  setMapping: Dispatch<SetStateAction<Record<string, string>>>
  preview: NormalizePreviewResponse | null
  previewError: string | null
  isLoadingPreview: boolean
  confirmError: string | null
  isConfirming: boolean
  onPreview: () => void
  onConfirm: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Column mapping
      </h2>
      <p>
        Detected format: <strong>{detected.schema_name ?? 'unrecognized'}</strong>
      </p>

      {detected.schema_name === null && (
        <div>
          <p>Map each column to a training field:</p>
          {detected.columns.map((column) => (
            <div className="field" key={column}>
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

      <div className="button-row">
        <button type="button" disabled={isLoadingPreview} onClick={onPreview}>
          Preview normalized rows
        </button>
      </div>
      {previewError && <p role="alert">{previewError}</p>}

      {preview && (
        <div className="card">
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
          <div className="button-row">
            <button type="button" disabled={isConfirming} onClick={onConfirm}>
              Confirm
            </button>
          </div>
          {confirmError && <p role="alert">{confirmError}</p>}
        </div>
      )}
    </section>
  )
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
    return <DetectingPanel detectError={detectError} />
  }

  return (
    <MappingPanel
      detected={detected}
      mapping={mapping}
      setMapping={setMapping}
      preview={preview}
      previewError={previewError}
      isLoadingPreview={isLoadingPreview}
      confirmError={confirmError}
      isConfirming={isConfirming}
      onPreview={loadPreview}
      onConfirm={confirm}
    />
  )
}
