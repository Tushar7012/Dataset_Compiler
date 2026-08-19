import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ProjectSetupStep } from './ProjectSetupStep'

vi.mock('../../api/projects', () => ({
  createProject: vi.fn(),
  uploadSource: vi.fn(),
}))
vi.mock('../../api/structured', () => ({
  getSourceSchema: vi.fn(),
}))
vi.mock('../column-mapping/ColumnMappingStep', () => ({
  ColumnMappingStep: ({ onSchemaConfirmed }: { onSchemaConfirmed: (schemaName: string) => void }) => (
    <button type="button" onClick={() => onSchemaConfirmed('prompt_completion')}>
      Confirm mapping (stub)
    </button>
  ),
}))

import { createProject, uploadSource } from '../../api/projects'
import { getSourceSchema } from '../../api/structured'

const mockCreateProject = vi.mocked(createProject)
const mockUploadSource = vi.mocked(uploadSource)
const mockGetSourceSchema = vi.mocked(getSourceSchema)

describe('ProjectSetupStep', () => {
  beforeEach(() => {
    mockCreateProject.mockClear()
    // Default every upload to "this is a document" (a 422 from the schema probe)
    // so existing document-upload behavior stays exactly as before unless a
    // test explicitly overrides this to simulate a structured file.
    mockGetSourceSchema.mockRejectedValue(new ApiError(422, "unsupported structured format '.md'"))
  })

  it('shows the Setting up heading initially, before the project resolves', () => {
    mockCreateProject.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(screen.getByRole('heading', { name: /setting up/i })).toBeInTheDocument()
    expect(screen.queryByLabelText(/upload/i)).not.toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    const { container } = renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)
    await screen.findByRole('heading', { name: /upload sources/i })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('moves focus to the step heading on mount', () => {
    mockCreateProject.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)
    expect(screen.getByRole('heading', { name: /setting up/i })).toHaveFocus()
  })

  it('automatically creates the project and reveals the upload form without any user interaction', async () => {
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: /upload sources/i })).toHaveFocus()
    expect(mockCreateProject).toHaveBeenCalledTimes(1)
  })

  it('creates the project and reveals the upload form', async () => {
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(await screen.findByLabelText(/upload/i)).toBeInTheDocument()
    expect(mockCreateProject).toHaveBeenCalled()
  })

  it('shows an alert with the error message when project creation fails', async () => {
    mockCreateProject.mockRejectedValue(new ApiError(422, "'name' is required"))
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(await screen.findByText("'name' is required")).toBeInTheDocument()
  })

  it('uploads a source and lists it, enabling Continue', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    const fileInput = await screen.findByLabelText(/upload/i)
    const file = new File(['# Policy'], 'policy.md', { type: 'text/markdown' })
    await user.upload(fileInput, file)

    expect(await screen.findByText('policy.md')).toBeInTheDocument()
    expect(mockUploadSource).toHaveBeenCalledWith('proj-1', file)
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled()
  })

  it('disables Continue until at least one source is uploaded', async () => {
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(await screen.findByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('calls onProjectReady with the created project when Continue is clicked', async () => {
    const user = userEvent.setup()
    const project = { id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' }
    mockCreateProject.mockResolvedValue(project)
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    const onProjectReady = vi.fn()
    renderWithProviders(<ProjectSetupStep onProjectReady={onProjectReady} />)

    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['# Policy'], 'policy.md', { type: 'text/markdown' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onProjectReady).toHaveBeenCalledWith(project)
  })

  it('shows the column-mapping step for a structured upload and disables Continue until it is confirmed', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'data.csv', source_hash: 'abc' })
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion', confidence: 1.0, matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['prompt,completion'], 'data.csv', { type: 'text/csv' }))

    expect(await screen.findByRole('button', { name: /confirm mapping \(stub\)/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: /confirm mapping \(stub\)/i }))

    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled())
  })

  it('keeps Continue enabled for a plain document upload once the schema probe rejects with 422', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['# Policy'], 'policy.md', { type: 'text/markdown' }))

    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled())
    expect(screen.queryByRole('button', { name: /confirm mapping/i })).not.toBeInTheDocument()
  })

  it('shows a retryable error (not a silent document fallback) when the schema probe fails for a reason other than 422', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'data.csv', source_hash: 'abc' })
    mockGetSourceSchema.mockRejectedValueOnce(new ApiError(500, 'internal server error'))
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['prompt,completion'], 'data.csv', { type: 'text/csv' }))

    expect(await screen.findByText('internal server error')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()

    mockGetSourceSchema.mockRejectedValueOnce(new ApiError(422, "unsupported structured format '.csv'"))
    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled())
  })

  it('disables Continue while the schema probe for a newly uploaded source is still pending', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'data.csv', source_hash: 'abc' })
    let resolveProbe: (() => void) | undefined
    mockGetSourceSchema.mockReturnValue(
      new Promise((resolve) => {
        resolveProbe = () =>
          resolve({ schema_name: 'prompt_completion', confidence: 1.0, matched_keys: [], columns: [] })
      }),
    )
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['prompt,completion'], 'data.csv', { type: 'text/csv' }))

    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
    resolveProbe?.()
    await screen.findByRole('button', { name: /confirm mapping \(stub\)/i })
  })
})
