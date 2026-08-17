import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ColumnMappingStep } from './ColumnMappingStep'

vi.mock('../../api/structured', () => ({
  getSourceSchema: vi.fn(),
  normalizePreview: vi.fn(),
  confirmMapping: vi.fn(),
}))

import { confirmMapping, getSourceSchema, normalizePreview } from '../../api/structured'

const mockGetSourceSchema = vi.mocked(getSourceSchema)
const mockNormalizePreview = vi.mocked(normalizePreview)
const mockConfirmMapping = vi.mocked(confirmMapping)

describe('ColumnMappingStep', () => {
  it('shows the detected schema and a Preview button when detection succeeds', async () => {
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )

    expect(await screen.findByText(/prompt_completion/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /preview normalized rows/i })).toBeInTheDocument()
    expect(screen.queryByLabelText('prompt')).not.toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    const { container } = renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await screen.findByRole('button', { name: /preview normalized rows/i })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('moves focus to the detecting heading while schema detection is pending', () => {
    mockGetSourceSchema.mockReturnValue(new Promise(() => {}))
    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    expect(screen.getByRole('heading', { name: /detecting format/i })).toHaveFocus()
  })

  it('moves focus to the mapping heading once detection completes', async () => {
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    expect(await screen.findByRole('heading', { name: /column mapping/i })).toHaveFocus()
  })

  it('shows a mapping input per column when detection is inconclusive', async () => {
    mockGetSourceSchema.mockResolvedValue({
      schema_name: null,
      confidence: 0,
      matched_keys: [],
      columns: ['question', 'answer'],
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )

    expect(await screen.findByLabelText('question')).toBeInTheDocument()
    expect(screen.getByLabelText('answer')).toBeInTheDocument()
  })

  it('previews normalized rows for an auto-detected schema with no mapping', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))

    expect(await screen.findByText(/1 row\(s\) found/i)).toBeInTheDocument()
    expect(mockNormalizePreview).toHaveBeenCalledWith('proj-1', 'src-1', undefined)
  })

  it('previews with the manual mapping when detection is inconclusive', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: null,
      confidence: 0,
      matched_keys: [],
      columns: ['question', 'answer'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await user.type(await screen.findByLabelText('question'), 'prompt')
    await user.type(screen.getByLabelText('answer'), 'completion')
    await user.click(screen.getByRole('button', { name: /preview normalized rows/i }))

    expect(await screen.findByText(/1 row\(s\) found/i)).toBeInTheDocument()
    expect(mockNormalizePreview).toHaveBeenCalledWith('proj-1', 'src-1', { question: 'prompt', answer: 'completion' })
  })

  it('persists the mapping then calls onSchemaConfirmed when Confirm is clicked', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })
    mockConfirmMapping.mockResolvedValue({ schema_name: 'prompt_completion', total_rows: 1 })
    const onSchemaConfirmed = vi.fn()

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={onSchemaConfirmed} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))
    await user.click(await screen.findByRole('button', { name: /confirm/i }))

    expect(mockConfirmMapping).toHaveBeenCalledWith('proj-1', 'src-1', undefined)
    await waitFor(() => expect(onSchemaConfirmed).toHaveBeenCalledWith('prompt_completion'))
  })

  it('shows an error and does not call onSchemaConfirmed when persisting the mapping fails', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })
    mockConfirmMapping.mockRejectedValue(new ApiError(422, 'could not determine the training format'))
    const onSchemaConfirmed = vi.fn()

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={onSchemaConfirmed} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))
    await user.click(await screen.findByRole('button', { name: /confirm/i }))

    expect(await screen.findByText('could not determine the training format')).toBeInTheDocument()
    expect(onSchemaConfirmed).not.toHaveBeenCalled()
  })

  it('shows an error message when detection fails', async () => {
    mockGetSourceSchema.mockRejectedValue(new ApiError(422, "unsupported structured format '.txt'"))

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )

    expect(await screen.findByText("unsupported structured format '.txt'")).toBeInTheDocument()
  })

  it('shows an error message when the preview request fails', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: null,
      confidence: 0,
      matched_keys: [],
      columns: ['a', 'b'],
    })
    mockNormalizePreview.mockRejectedValue(
      new ApiError(422, 'could not determine the training format for this file — provide a column mapping'),
    )

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))

    expect(
      await screen.findByText('could not determine the training format for this file — provide a column mapping'),
    ).toBeInTheDocument()
  })
})
