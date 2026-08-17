import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProject, uploadSource } from '../../api/projects'
import { getSourceSchema } from '../../api/structured'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import { ColumnMappingStep } from '../column-mapping/ColumnMappingStep'
import type { Project, Source } from '../../api/types'

interface ProjectSetupStepProps {
  onProjectReady: (project: Project) => void
}

type MappingStatus = 'checking' | 'document' | 'awaiting-mapping' | 'mapped' | 'probe-failed'

interface SourceWithStatus extends Source {
  mappingStatus: MappingStatus
  probeError?: string
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

function CreateProjectForm({
  name,
  setName,
  onSubmit,
  isPending,
  error,
}: {
  name: string
  setName: (value: string) => void
  onSubmit: () => void
  isPending: boolean
  error: unknown
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        <h2 ref={headingRef} tabIndex={-1}>
          Project setup
        </h2>
        <div className="field">
          <label htmlFor="project-name">Project name</label>
          <input id="project-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="button-row">
          <button type="submit" disabled={isPending}>
            Create project
          </button>
        </div>
        {error != null && <p role="alert">{errorMessage(error)}</p>}
      </form>
    </section>
  )
}

function UploadSourcesPanel({
  project,
  sources,
  canContinue,
  onUpload,
  onContinue,
  onProbe,
  onMapped,
  uploadError,
}: {
  project: Project
  sources: SourceWithStatus[]
  canContinue: boolean
  onUpload: (file: File) => void
  onContinue: () => void
  onProbe: (sourceId: string) => void
  onMapped: (sourceId: string) => void
  uploadError: unknown
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Upload sources
      </h2>
      <p>{project.name}</p>
      <div className="field">
        <label htmlFor="source-upload">Upload a source document</label>
        <input
          id="source-upload"
          type="file"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onUpload(file)
          }}
        />
      </div>
      {uploadError != null && <p role="alert">{errorMessage(uploadError)}</p>}
      <ul>
        {sources.map((source) => (
          <li key={source.id}>
            {source.filename}
            {source.mappingStatus === 'checking' && ' — checking format…'}
            {source.mappingStatus === 'awaiting-mapping' && (
              <ColumnMappingStep
                projectId={project.id}
                sourceId={source.id}
                onSchemaConfirmed={() => onMapped(source.id)}
              />
            )}
            {source.mappingStatus === 'probe-failed' && (
              <>
                <p role="alert">{source.probeError}</p>
                <button type="button" onClick={() => onProbe(source.id)}>
                  Retry
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      <div className="button-row">
        <button type="button" disabled={!canContinue} onClick={onContinue}>
          Continue
        </button>
      </div>
    </section>
  )
}

export function ProjectSetupStep({ onProjectReady }: ProjectSetupStepProps) {
  const [name, setName] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [sources, setSources] = useState<SourceWithStatus[]>([])

  const setSourceStatus = (sourceId: string, mappingStatus: MappingStatus, probeError?: string) =>
    setSources((previous) =>
      previous.map((source) => (source.id === sourceId ? { ...source, mappingStatus, probeError } : source)),
    )

  const probeSchema = (sourceId: string) => {
    setSourceStatus(sourceId, 'checking')
    getSourceSchema(project!.id, sourceId)
      .then(() => setSourceStatus(sourceId, 'awaiting-mapping'))
      .catch((error: unknown) => {
        // A 422 means the file genuinely didn't load as structured rows —
        // that's the expected "this is a document" signal. Anything else
        // (a network blip, a 500) is a real error and must not be silently
        // treated as "fine, it's a document" — that would hide a failure
        // the user needs to see and retry.
        if (error instanceof ApiError && error.status === 422) {
          setSourceStatus(sourceId, 'document')
        } else {
          setSourceStatus(sourceId, 'probe-failed', errorMessage(error))
        }
      })
  }

  const createProjectMutation = useMutation({
    mutationFn: () => createProject(name),
    onSuccess: setProject,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadSource(project!.id, file),
    onSuccess: (source) => {
      setSources((previous) => [...previous, { ...source, mappingStatus: 'checking' }])
      probeSchema(source.id)
    },
  })

  const canContinue =
    sources.length > 0 &&
    sources.every((source) => source.mappingStatus === 'document' || source.mappingStatus === 'mapped')

  if (!project) {
    return (
      <CreateProjectForm
        name={name}
        setName={setName}
        onSubmit={() => createProjectMutation.mutate()}
        isPending={createProjectMutation.isPending}
        error={createProjectMutation.isError ? createProjectMutation.error : null}
      />
    )
  }

  return (
    <UploadSourcesPanel
      project={project}
      sources={sources}
      canContinue={canContinue}
      onUpload={(file) => uploadMutation.mutate(file)}
      onContinue={() => onProjectReady(project)}
      onProbe={probeSchema}
      onMapped={(sourceId) => setSourceStatus(sourceId, 'mapped')}
      uploadError={uploadMutation.isError ? uploadMutation.error : null}
    />
  )
}
