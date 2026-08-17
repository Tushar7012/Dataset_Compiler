import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { GoalSuggestionStep } from './GoalSuggestionStep'

vi.mock('../../api/plans', () => ({
  suggestGoal: vi.fn(),
}))

import { suggestGoal } from '../../api/plans'

const mockSuggestGoal = vi.mocked(suggestGoal)

const suggestion = {
  goal: 'domain_adaptation' as const,
  rationale: 'The document reads like an internal policy handbook.',
  desired_behavior: 'Answer questions about company policy accurately.',
}

describe('GoalSuggestionStep', () => {
  beforeEach(() => {
    mockSuggestGoal.mockClear()
  })

  it('does not call suggestGoal until consent is checked', () => {
    renderWithProviders(<GoalSuggestionStep projectId="proj-1" onDecision={vi.fn()} />)

    expect(screen.getByRole('button', { name: /get ai suggestion/i })).toBeDisabled()
    expect(mockSuggestGoal).not.toHaveBeenCalled()
  })

  it('has no axe-detectable accessibility violations', async () => {
    const { container } = renderWithProviders(
      <GoalSuggestionStep projectId="proj-1" onDecision={vi.fn()} />,
    )
    await screen.findByRole('button', { name: /get ai suggestion/i })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('calls suggestGoal once consent is checked and the button is clicked', async () => {
    const user = userEvent.setup()
    mockSuggestGoal.mockResolvedValue(suggestion)
    renderWithProviders(<GoalSuggestionStep projectId="proj-1" onDecision={vi.fn()} />)

    await user.click(screen.getByLabelText(/consent/i))
    await user.click(screen.getByRole('button', { name: /get ai suggestion/i }))

    expect(mockSuggestGoal).toHaveBeenCalledWith('proj-1')
    expect(await screen.findByText(/domain_adaptation/)).toBeInTheDocument()
  })

  it('calls onDecision with the suggested goal and desired behavior on Accept', async () => {
    const user = userEvent.setup()
    mockSuggestGoal.mockResolvedValue(suggestion)
    const onDecision = vi.fn()
    renderWithProviders(<GoalSuggestionStep projectId="proj-1" onDecision={onDecision} />)

    await user.click(screen.getByLabelText(/consent/i))
    await user.click(screen.getByRole('button', { name: /get ai suggestion/i }))
    await user.click(await screen.findByRole('button', { name: /accept/i }))

    expect(onDecision).toHaveBeenCalledWith('domain_adaptation', suggestion.desired_behavior)
  })

  it('shows a free-text box on Reject and calls onDecision with null goal plus the typed text', async () => {
    const user = userEvent.setup()
    mockSuggestGoal.mockResolvedValue(suggestion)
    const onDecision = vi.fn()
    renderWithProviders(<GoalSuggestionStep projectId="proj-1" onDecision={onDecision} />)

    await user.click(screen.getByLabelText(/consent/i))
    await user.click(screen.getByRole('button', { name: /get ai suggestion/i }))
    await user.click(await screen.findByRole('button', { name: /reject/i }))
    await user.type(screen.getByLabelText(/describe your own purpose/i), 'I want a customer support bot')
    await user.click(screen.getByRole('button', { name: /continue with my own goal/i }))

    expect(onDecision).toHaveBeenCalledWith(null, 'I want a customer support bot')
  })

  it('lets the user skip the AI suggestion entirely without ever calling suggestGoal', async () => {
    const user = userEvent.setup()
    const onDecision = vi.fn()
    renderWithProviders(<GoalSuggestionStep projectId="proj-1" onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: /skip/i }))

    expect(mockSuggestGoal).not.toHaveBeenCalled()
    expect(onDecision).toHaveBeenCalledWith(null, '')
  })

  it('shows the API error message when the suggestion call fails', async () => {
    const user = userEvent.setup()
    mockSuggestGoal.mockRejectedValue(new ApiError(422, 'Gemini credential not configured'))
    renderWithProviders(<GoalSuggestionStep projectId="proj-1" onDecision={vi.fn()} />)

    await user.click(screen.getByLabelText(/consent/i))
    await user.click(screen.getByRole('button', { name: /get ai suggestion/i }))

    expect(await screen.findByText(/gemini credential not configured/i)).toBeInTheDocument()
  })
})
