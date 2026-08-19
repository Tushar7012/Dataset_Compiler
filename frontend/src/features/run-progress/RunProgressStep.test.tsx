import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { RunProgressStep } from './RunProgressStep'

vi.mock('../../api/runs', () => ({
  cancelRun: vi.fn(),
  resumeRun: vi.fn(),
}))
vi.mock('../../api/runEvents', () => ({
  subscribeToRunEvents: vi.fn(),
}))

import { cancelRun, resumeRun } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'

const mockCancelRun = vi.mocked(cancelRun)
const mockResumeRun = vi.mocked(resumeRun)
const mockSubscribe = vi.mocked(subscribeToRunEvents)

describe('RunProgressStep', () => {
  it('shows status and progress from the event stream, with a Cancel button while running', async () => {
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 40, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)

    expect(await screen.findByText(/running/i)).toBeInTheDocument()
    expect(screen.getByText(/40\/100/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resume/i })).not.toBeInTheDocument()
    const progressBar = screen.getByRole('progressbar')
    expect(progressBar).toHaveAttribute('value', '40')
    expect(progressBar).toHaveAttribute('max', '100')
  })

  it('has no axe-detectable accessibility violations', async () => {
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 40, total_rows: 100 })
    })
    const { container } = renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    await screen.findByRole('button', { name: /cancel/i })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('moves focus to the step heading on mount', async () => {
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 40, total_rows: 100 })
    })
    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    expect(screen.getByRole('heading', { name: /run progress/i })).toHaveFocus()
  })

  it('cancels the run when Cancel is clicked', async () => {
    const user = userEvent.setup()
    mockCancelRun.mockResolvedValue({ status: 'cancel_requested' })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 10, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: /cancel/i }))

    expect(mockCancelRun).toHaveBeenCalledWith('run-1')
  })

  it('shows a Resume button once cancelled, and re-subscribes after resuming', async () => {
    const user = userEvent.setup()
    mockResumeRun.mockResolvedValue({ status: 'pending' })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'cancelled', completed_rows: 10, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    const resumeButton = await screen.findByRole('button', { name: /resume/i })
    expect(screen.queryByRole('button', { name: /cancel/i })).not.toBeInTheDocument()
    const subscribeCallsBeforeResume = mockSubscribe.mock.calls.length

    await user.click(resumeButton)

    expect(mockResumeRun).toHaveBeenCalledWith('run-1')
    await waitFor(() => expect(mockSubscribe.mock.calls.length).toBe(subscribeCallsBeforeResume + 1))
  })

  it('calls onCompleted when the stage becomes completed', async () => {
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'completed', completed_rows: 100, total_rows: 100 })
    })
    const onCompleted = vi.fn()

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={onCompleted} />)

    await waitFor(() => expect(onCompleted).toHaveBeenCalled())
  })

  it('shows an error message if cancelling fails', async () => {
    const user = userEvent.setup()
    mockCancelRun.mockRejectedValue(new ApiError(409, "run is 'completed', cannot cancel"))
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 10, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: /cancel/i }))

    expect(await screen.findByText("run is 'completed', cannot cancel")).toBeInTheDocument()
  })
})
