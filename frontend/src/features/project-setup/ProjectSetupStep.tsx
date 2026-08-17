import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProject, uploadSource } from '../../api/projects'
import { getSourceSchema } from '../../api/structured'
import { ApiError } from '../../api/client'
import { ColumnMappingStep } from '../column-mapping/ColumnMappingStep'
import type { Project, Source } from '../../api/types'

interface ProjectSetupStepProps {
  onProjectReady: (project: Project) => void
}

type MappingStatus = 'checking' | 'document' | 'awaiting-mapping' | 'mapped'

interface SourceWithStatus extends Source {
  mappingStatus: MappingStatus
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ProjectSetupStep({ onProjectReady }: ProjectSetupStepProps) {
  const [name, setName] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [sources, setSources] = useState<SourceWithStatus[]>([])

  const setSourceStatus = (sourceId: string, mappingStatus: MappingStatus) =>
    setSources((previous) => previous.map((source) => (source.id === sourceId ? { ...source, mappingStatus } : source)))

  const createProjectMutation = useMutation({
    mutationFn: () => createProject(name),
    onSuccess: setProject,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadSource(project!.id, file),
    onSuccess: (source) => {
      setSources((previous) => [...previous, { ...source, mappingStatus: 'checking' }])
      getSourceSchema(project!.id, source.id)
        .then(() => setSourceStatus(source.id, 'awaiting-mapping'))
        .catch(() => setSourceStatus(source.id, 'document'))
    },
  })

  const canContinue = sources.length > 0 && sources.every((source) => source.mappingStatus === 'document' || source.mappingStatus === 'mapped')

  if (!project) {
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault()
          createProjectMutation.mutate()
        }}
      >
        <label htmlFor="project-name">Project name</label>
        <input id="project-name" value={name} onChange={(event) => setName(event.target.value)} />
        <button type="submit" disabled={createProjectMutation.isPending}>
          Create project
        </button>
        {createProjectMutation.isError && <p role="alert">{errorMessage(createProjectMutation.error)}</p>}
      </form>
    )
  }

  return (
    <section>
      <h2>{project.name}</h2>
      <label htmlFor="source-upload">Upload a source document</label>
      <input
        id="source-upload"
        type="file"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) uploadMutation.mutate(file)
        }}
      />
      {uploadMutation.isError && <p role="alert">{errorMessage(uploadMutation.error)}</p>}
      <ul>
        {sources.map((source) => (
          <li key={source.id}>
            {source.filename}
            {source.mappingStatus === 'checking' && ' — checking format…'}
            {source.mappingStatus === 'awaiting-mapping' && (
              <ColumnMappingStep
                projectId={project.id}
                sourceId={source.id}
                onSchemaConfirmed={() => setSourceStatus(source.id, 'mapped')}
              />
            )}
          </li>
        ))}
      </ul>
      <button type="button" disabled={!canContinue} onClick={() => onProjectReady(project)}>
        Continue
      </button>
    </section>
  )
}
