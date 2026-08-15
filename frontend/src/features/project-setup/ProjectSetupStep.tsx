import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProject, uploadSource } from '../../api/projects'
import { ApiError } from '../../api/client'
import type { Project, Source } from '../../api/types'

interface ProjectSetupStepProps {
  onProjectReady: (project: Project) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ProjectSetupStep({ onProjectReady }: ProjectSetupStepProps) {
  const [name, setName] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [sources, setSources] = useState<Source[]>([])

  const createProjectMutation = useMutation({
    mutationFn: () => createProject(name),
    onSuccess: setProject,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadSource(project!.id, file),
    onSuccess: (source) => setSources((previous) => [...previous, source]),
  })

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
          <li key={source.id}>{source.filename}</li>
        ))}
      </ul>
      <button type="button" disabled={sources.length === 0} onClick={() => onProjectReady(project)}>
        Continue
      </button>
    </section>
  )
}
