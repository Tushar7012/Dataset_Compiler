import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { PreviewStep } from './PreviewStep'

vi.mock('../../api/runs', () => ({
  createPreview: vi.fn(),
  approveFull: vi.fn(),
  listRunRecords: vi.fn(),
}))
vi.mock('../../api/runEvents', () => ({
  subscribeToRunEvents: vi.fn(),
}))

import { approveFull, createPreview, listRunRecords } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'

const mockCreatePreview = vi.mocked(createPreview)
const mockApproveFull = vi.mocked(approveFull)
const mockListRunRecords = vi.mocked(listRunRecords)
const mockSubscribe = vi.mocked(subscribeToRunEvents)

describe('PreviewStep', () => {
  it('shows a Generate preview button initially', () => {
    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={false}
        onApprovedFull={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /generate preview/i })).toBeInTheDocument()
  })

  it('creates the preview, streams progress, and shows accepted rows on completion', async () => {
    const user = userEvent.setup()
    mockCreatePreview.mockResolvedValue({ id: 'run-1', status: 'pending', is_preview: true })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 1, total_rows: 20 })
      onEvent({ run_id: runId, sequence: 1, stage: 'completed', completed_rows: 5, total_rows: 20 })
    })
    mockListRunRecords.mockResolvedValue({
      canonical_schema: 'CPTRecord',
      records: [{ text: 'row 1' }],
      total_accepted: 5,
    })

    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={false}
        onApprovedFull={vi.fn()}
      />,
    )
    await user.click(screen.getByRole('button', { name: /generate preview/i }))

    expect(await screen.findByText(/completed/i)).toBeInTheDocument()
    expect(await screen.findByText(/5 row\(s\) accepted/i)).toBeInTheDocument()
    expect(mockCreatePreview).toHaveBeenCalledWith({
      planId: 'plan-1',
      generatorProfileId: 'prov-1',
      judgeProfileId: undefined,
      remoteConsent: false,
    })
  })

  it('shows Approve full run once completed and calls onApprovedFull', async () => {
    const user = userEvent.setup()
    mockCreatePreview.mockResolvedValue({ id: 'run-1', status: 'pending', is_preview: true })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'completed', completed_rows: 5, total_rows: 20 })
    })
    mockListRunRecords.mockResolvedValue({ canonical_schema: 'CPTRecord', records: [], total_accepted: 5 })
    const fullRun = { id: 'run-2', status: 'pending' as const, is_preview: false }
    mockApproveFull.mockResolvedValue(fullRun)
    const onApprovedFull = vi.fn()

    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={true}
        onApprovedFull={onApprovedFull}
      />,
    )
    await user.click(screen.getByRole('button', { name: /generate preview/i }))
    const approveButton = await screen.findByRole('button', { name: /approve full run/i })
    await user.click(approveButton)

    expect(mockApproveFull).toHaveBeenCalledWith('run-1', true)
    await waitFor(() => expect(onApprovedFull).toHaveBeenCalledWith(fullRun))
  })

  it('shows an error if preview creation fails', async () => {
    const user = userEvent.setup()
    mockCreatePreview.mockRejectedValue(new ApiError(404, 'plan not found'))

    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={false}
        onApprovedFull={vi.fn()}
      />,
    )
    await user.click(screen.getByRole('button', { name: /generate preview/i }))

    expect(await screen.findByText('plan not found')).toBeInTheDocument()
  })
})
