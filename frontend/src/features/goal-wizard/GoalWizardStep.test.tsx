import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { GoalWizardStep } from './GoalWizardStep'

vi.mock('../../api/plans', () => ({
  estimateRows: vi.fn(),
}))

import { estimateRows } from '../../api/plans'

const mockEstimateRows = vi.mocked(estimateRows)

describe('GoalWizardStep', () => {
  beforeEach(() => {
    mockEstimateRows.mockResolvedValue({ total_rows: 42, truncated: false, capped_at: 100_000 })
  })

  it('renders the goal select with no manual target-rows input', async () => {
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />)

    expect(screen.getByLabelText(/training goal/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/target rows/i)).not.toBeInTheDocument()
    expect(await screen.findByText('42')).toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    const { container } = renderWithProviders(
      <GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />,
    )
    await screen.findByLabelText(/training goal/i)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('moves focus to the step heading on mount', () => {
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />)
    expect(screen.getByRole('heading', { name: /^training goal$/i })).toHaveFocus()
  })

  it('shows a truncation warning when the estimate exceeds the accepted-row cap', async () => {
    mockEstimateRows.mockResolvedValue({ total_rows: 150_000, truncated: true, capped_at: 100_000 })
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />)

    expect(await screen.findByText(/only the first 100,000/i)).toBeInTheDocument()
  })

  it('disables submit and explains why when the estimate is zero rows', async () => {
    mockEstimateRows.mockResolvedValue({ total_rows: 0, truncated: false, capped_at: 100_000 })
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />)

    expect(await screen.findByText(/upload a document source/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('disables submit until the row estimate has loaded', () => {
    mockEstimateRows.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />)

    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('has the four goal options with the expected labels and values', () => {
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={vi.fn()} />)

    const select = screen.getByLabelText(/training goal/i)
    const options = Array.from(select.querySelectorAll('option')) as HTMLOptionElement[]

    expect(options.map((option) => ({ value: option.value, label: option.textContent }))).toEqual([
      { value: 'domain_adaptation', label: 'CPT — continued pretraining on raw text' },
      { value: 'single_turn_instruction', label: 'SFT — single-turn (prompt / completion)' },
      { value: 'multi_turn_conversation', label: 'SFT — multi-turn conversation' },
      { value: 'preference_alignment', label: 'DPO — preference alignment' },
    ])
  })

  it('submits the form using the estimate (capped) as target_rows', async () => {
    const user = userEvent.setup()
    mockEstimateRows.mockResolvedValue({ total_rows: 150_000, truncated: true, capped_at: 100_000 })
    const onGoalChosen = vi.fn()
    renderWithProviders(
      <GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onGoalChosen={onGoalChosen} />,
    )

    await screen.findByText(/only the first 100,000/i)
    await user.selectOptions(screen.getByLabelText(/training goal/i), 'multi_turn_conversation')
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onGoalChosen).toHaveBeenCalledWith({
      goal: 'multi_turn_conversation',
      targetRows: 100_000,
    })
  })
})
