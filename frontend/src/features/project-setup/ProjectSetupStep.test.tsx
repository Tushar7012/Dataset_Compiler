import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ProjectSetupStep } from './ProjectSetupStep'

vi.mock('../../api/projects', () => ({
  createProject: vi.fn(),
  uploadSource: vi.fn(),
}))

import { createProject, uploadSource } from '../../api/projects'

const mockCreateProject = vi.mocked(createProject)
const mockUploadSource = vi.mocked(uploadSource)

describe('ProjectSetupStep', () => {
  it('shows only the project name form initially', () => {
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(screen.getByLabelText(/project name/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/upload/i)).not.toBeInTheDocument()
  })

  it('creates the project and reveals the upload form', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))

    expect(await screen.findByLabelText(/upload/i)).toBeInTheDocument()
    expect(mockCreateProject).toHaveBeenCalledWith('HR Policy Bot')
  })

  it('shows a validation error when project creation fails', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockRejectedValue(new ApiError(422, "'name' is required"))
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /create project/i }))

    expect(await screen.findByText("'name' is required")).toBeInTheDocument()
  })

  it('uploads a source and lists it, enabling Continue', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))
    const fileInput = await screen.findByLabelText(/upload/i)
    const file = new File(['# Policy'], 'policy.md', { type: 'text/markdown' })
    await user.upload(fileInput, file)

    expect(await screen.findByText('policy.md')).toBeInTheDocument()
    expect(mockUploadSource).toHaveBeenCalledWith('proj-1', file)
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled()
  })

  it('disables Continue until at least one source is uploaded', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))

    expect(await screen.findByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('calls onProjectReady with the created project when Continue is clicked', async () => {
    const user = userEvent.setup()
    const project = { id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' }
    mockCreateProject.mockResolvedValue(project)
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    const onProjectReady = vi.fn()
    renderWithProviders(<ProjectSetupStep onProjectReady={onProjectReady} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))
    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['# Policy'], 'policy.md', { type: 'text/markdown' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onProjectReady).toHaveBeenCalledWith(project)
  })
})
