import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { PlanConfirmationStep } from './PlanConfirmationStep'

vi.mock('../../api/plans', () => ({
  approvePlan: vi.fn(),
}))

import { approvePlan } from '../../api/plans'

const mockApprovePlan = vi.mocked(approvePlan)

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

describe('PlanConfirmationStep', () => {
  it('renders the recommended plan details', () => {
    renderWithProviders(<PlanConfirmationStep plan={plan} onApproved={vi.fn()} />)

    expect(screen.getByText('sft_conversation')).toBeInTheDocument()
    expect(screen.getByText('SFTConversationRecord')).toBeInTheDocument()
    expect(screen.getByText('500')).toBeInTheDocument()
    expect(screen.getByText(/structural, dedup/i)).toBeInTheDocument()
  })

  it('approves the plan and calls onApproved', async () => {
    const user = userEvent.setup()
    mockApprovePlan.mockResolvedValue({ id: 'plan-1', approved_at: '2026-08-15T00:00:00Z' })
    const onApproved = vi.fn()
    renderWithProviders(<PlanConfirmationStep plan={plan} onApproved={onApproved} />)

    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByText(/approved/i)).toBeInTheDocument()
    expect(mockApprovePlan).toHaveBeenCalledWith('plan-1')
    expect(onApproved).toHaveBeenCalled()
  })
})
