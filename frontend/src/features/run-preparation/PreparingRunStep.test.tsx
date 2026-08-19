import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { PreparingRunStep } from './PreparingRunStep'
import type { GoalDecision } from '../goal-wizard/GoalWizardStep'

vi.mock('../../api/providers', () => ({
  createProvider: vi.fn(),
}))
vi.mock('../../api/plans', () => ({
  recommendPlan: vi.fn(),
  approvePlan: vi.fn(),
}))

import { createProvider } from '../../api/providers'
import { approvePlan, recommendPlan } from '../../api/plans'

const mockCreateProvider = vi.mocked(createProvider)
const mockRecommendPlan = vi.mocked(recommendPlan)
const mockApprovePlan = vi.mocked(approvePlan)

const generatorProvider = { id: 'gen-1', name: 'hf-router-generator' }
const judgeProvider = { id: 'judge-1', name: 'hf-router-judge' }
const plan = { id: 'plan-1', objective: 'x', schema: 'y' } as any
const decisionBase = { targetRows: 500 }

describe('PreparingRunStep', () => {
  beforeEach(() => {
    mockCreateProvider.mockReset()
    mockRecommendPlan.mockReset()
    mockApprovePlan.mockReset()
  })

  it('renders the Preparing heading', () => {
    mockCreateProvider.mockReturnValue(new Promise(() => {}))
    renderWithProviders(
      <PreparingRunStep
        projectId="proj-1"
        modelProfileId="profile-1"
        decision={{ ...decisionBase, goal: 'single_turn_instruction' } as GoalDecision}
        onReady={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: /preparing/i })).toBeInTheDocument()
  })

  it('for a non-DPO goal creates only the generator provider and calls onReady with no judge', async () => {
    mockCreateProvider.mockResolvedValue(generatorProvider)
    mockRecommendPlan.mockResolvedValue(plan)
    mockApprovePlan.mockResolvedValue({ id: 'plan-1', approved_at: 'x' })
    const onReady = vi.fn()

    renderWithProviders(
      <PreparingRunStep
        projectId="proj-1"
        modelProfileId="profile-1"
        decision={{ ...decisionBase, goal: 'single_turn_instruction' } as GoalDecision}
        onReady={onReady}
      />,
    )

    await vi.waitFor(() => expect(onReady).toHaveBeenCalled())

    expect(mockCreateProvider).toHaveBeenCalledTimes(1)
    expect(mockCreateProvider).toHaveBeenCalledWith('proj-1', {
      name: 'hf-router-generator',
      base_url: 'https://router.huggingface.co/v1',
      model: 'Qwen/Qwen3-Next-80B-A3B-Instruct',
    })
    expect(mockRecommendPlan).toHaveBeenCalledWith(
      'proj-1',
      'profile-1',
      expect.objectContaining({ generator_profile_id: 'gen-1', judge_profile_id: undefined }),
    )
    expect(mockApprovePlan).toHaveBeenCalledWith('plan-1')
    expect(onReady).toHaveBeenCalledWith(plan, generatorProvider, undefined)
  })

  it('for preference_alignment goal creates both generator and judge providers', async () => {
    mockCreateProvider.mockImplementation((_, input) =>
      Promise.resolve(input.name === 'hf-router-judge' ? judgeProvider : generatorProvider),
    )
    mockRecommendPlan.mockResolvedValue(plan)
    mockApprovePlan.mockResolvedValue({ id: 'plan-1', approved_at: 'x' })
    const onReady = vi.fn()

    renderWithProviders(
      <PreparingRunStep
        projectId="proj-1"
        modelProfileId="profile-1"
        decision={{ ...decisionBase, goal: 'preference_alignment' } as GoalDecision}
        onReady={onReady}
      />,
    )

    await vi.waitFor(() => expect(onReady).toHaveBeenCalled())

    expect(mockCreateProvider).toHaveBeenCalledTimes(2)
    expect(mockCreateProvider).toHaveBeenCalledWith('proj-1', {
      name: 'hf-router-judge',
      base_url: 'https://router.huggingface.co/v1',
      model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    })
    expect(onReady).toHaveBeenCalledWith(plan, generatorProvider, judgeProvider)
  })

  it('shows an alert with the error message when a call in the chain fails', async () => {
    mockCreateProvider.mockRejectedValue(new ApiError(500, 'provider creation failed'))

    renderWithProviders(
      <PreparingRunStep
        projectId="proj-1"
        modelProfileId="profile-1"
        decision={{ ...decisionBase, goal: 'single_turn_instruction' } as GoalDecision}
        onReady={vi.fn()}
      />,
    )

    expect(await screen.findByText('provider creation failed')).toBeInTheDocument()
  })
})
