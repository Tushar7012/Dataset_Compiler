import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { GoalWizardStep } from './GoalWizardStep'

vi.mock('../../api/plans', () => ({
  recommendPlan: vi.fn(),
  approvePlan: vi.fn(),
  estimateRows: vi.fn(),
}))

import { estimateRows, recommendPlan } from '../../api/plans'

const mockRecommendPlan = vi.mocked(recommendPlan)
const mockEstimateRows = vi.mocked(estimateRows)

const plan = {
  id: 'plan-1',
  objective: 'sft_conversation' as const,
  canonical_schema: 'SFTConversationRecord',
  target_rows: 500,
  examples_per_chunk: 2,
  generator_profile_id: null,
  judge_profile_id: null,
  required_validators: ['structural', 'dedup'],
  evidence: [],
  confidence: 0.9,
  plan_hash: 'hash123',
}

describe('GoalWizardStep', () => {
  beforeEach(() => {
    mockEstimateRows.mockResolvedValue({ total_rows: 42, truncated: false, capped_at: 100_000 })
  })

  it('renders goal, desired behavior, and language, with no manual target-rows input', async () => {
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    expect(screen.getByLabelText(/training goal/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/desired behavior/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/language/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/target rows/i)).not.toBeInTheDocument()
    expect(await screen.findByText('42')).toBeInTheDocument()
  })

  it('shows a truncation warning when the estimate exceeds the accepted-row cap', async () => {
    mockEstimateRows.mockResolvedValue({ total_rows: 150_000, truncated: true, capped_at: 100_000 })
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    expect(await screen.findByText(/only the first 100,000/i)).toBeInTheDocument()
  })

  it('disables submit until the row estimate has loaded', () => {
    mockEstimateRows.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    expect(screen.getByRole('button', { name: /get recommendation/i })).toBeDisabled()
  })

  it('submits the form using the estimate (capped) as target_rows', async () => {
    const user = userEvent.setup()
    mockEstimateRows.mockResolvedValue({ total_rows: 150_000, truncated: true, capped_at: 100_000 })
    mockRecommendPlan.mockResolvedValue(plan)
    const onPlanRecommended = vi.fn()
    renderWithProviders(
      <GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={onPlanRecommended} />,
    )

    await screen.findByText(/only the first 100,000/i)
    await user.selectOptions(screen.getByLabelText(/training goal/i), 'multi_turn_conversation')
    await user.type(screen.getByLabelText(/desired behavior/i), 'Answer HR policy questions')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(mockRecommendPlan).toHaveBeenCalledWith('proj-1', 'profile-1', {
      goal: 'multi_turn_conversation',
      desired_behavior: 'Answer HR policy questions',
      language: 'en',
      target_rows: 100_000,
    })
    expect(onPlanRecommended).toHaveBeenCalledWith(plan)
  })

  it('pre-fills goal and desired behavior from initialGoal/initialDesiredBehavior props', () => {
    renderWithProviders(
      <GoalWizardStep
        projectId="proj-1"
        modelProfileId="profile-1"
        initialGoal="preference_alignment"
        initialDesiredBehavior="Be concise"
        onPlanRecommended={vi.fn()}
      />,
    )

    expect(screen.getByLabelText(/training goal/i)).toHaveValue('preference_alignment')
    expect(screen.getByLabelText(/desired behavior/i)).toHaveValue('Be concise')
  })

  it('surfaces the chat-template-required rejection distinctly', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockRejectedValue(
      new ApiError(409, "org/base-model has no chat template, which 'multi_turn_conversation' requires"),
    )
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    await screen.findByText('42')
    await user.type(screen.getByLabelText(/desired behavior/i), 'x')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(await screen.findByText(/has no chat template/i)).toBeInTheDocument()
  })

  it('surfaces the distinct-judge-required rejection for preference alignment', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockRejectedValue(new ApiError(409, 'dpo requires a generator_profile_id'))
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    await screen.findByText('42')
    await user.selectOptions(screen.getByLabelText(/training goal/i), 'preference_alignment')
    await user.type(screen.getByLabelText(/desired behavior/i), 'x')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(await screen.findByText(/requires a generator_profile_id/i)).toBeInTheDocument()
    expect(screen.getByText(/provider setup/i)).toBeInTheDocument()
  })
})
