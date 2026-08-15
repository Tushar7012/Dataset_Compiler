import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { GoalWizardStep } from './GoalWizardStep'

vi.mock('../../api/plans', () => ({
  recommendPlan: vi.fn(),
  approvePlan: vi.fn(),
}))

import { recommendPlan } from '../../api/plans'

const mockRecommendPlan = vi.mocked(recommendPlan)

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
  it('renders the goal, desired behavior, language, and target rows fields', () => {
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    expect(screen.getByLabelText(/training goal/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/desired behavior/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/language/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/target rows/i)).toBeInTheDocument()
  })

  it('submits the form and reports the recommended plan', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockResolvedValue(plan)
    const onPlanRecommended = vi.fn()
    renderWithProviders(
      <GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={onPlanRecommended} />,
    )

    await user.selectOptions(screen.getByLabelText(/training goal/i), 'multi_turn_conversation')
    await user.type(screen.getByLabelText(/desired behavior/i), 'Answer HR policy questions')
    await user.clear(screen.getByLabelText(/target rows/i))
    await user.type(screen.getByLabelText(/target rows/i), '500')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(mockRecommendPlan).toHaveBeenCalledWith('proj-1', 'profile-1', {
      goal: 'multi_turn_conversation',
      desired_behavior: 'Answer HR policy questions',
      language: 'en',
      target_rows: 500,
    })
    expect(onPlanRecommended).toHaveBeenCalledWith(plan)
  })

  it('surfaces the chat-template-required rejection distinctly', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockRejectedValue(
      new ApiError(409, "org/base-model has no chat template, which 'multi_turn_conversation' requires"),
    )
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    await user.type(screen.getByLabelText(/desired behavior/i), 'x')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(await screen.findByText(/has no chat template/i)).toBeInTheDocument()
  })

  it('surfaces the distinct-judge-required rejection for preference alignment', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockRejectedValue(new ApiError(409, 'dpo requires a generator_profile_id'))
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    await user.selectOptions(screen.getByLabelText(/training goal/i), 'preference_alignment')
    await user.type(screen.getByLabelText(/desired behavior/i), 'x')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(await screen.findByText(/requires a generator_profile_id/i)).toBeInTheDocument()
    expect(screen.getByText(/provider setup/i)).toBeInTheDocument()
  })
})
