import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from './test-utils'
import App from './App'

vi.mock('./features/project-setup/ProjectSetupStep', () => ({
  ProjectSetupStep: ({ onProjectReady }: any) => (
    <button onClick={() => onProjectReady({ id: 'proj-1', name: 'p', created_at: 'x' })}>stub-project-ready</button>
  ),
}))
vi.mock('./features/model-selection/ModelSelectionStep', () => ({
  ModelSelectionStep: ({ onProfileReady }: any) => (
    <button
      onClick={() =>
        onProfileReady({
          id: 'profile-1',
          source: 'huggingface',
          model_id: 'gpt2',
          architecture: 'a',
          model_type: 'm',
          is_causal_lm: true,
          is_chat_model: false,
          chat_template_found: false,
          context_length: 1024,
          modalities: ['text'],
          evidence: [],
          confidence: 0.9,
        })
      }
    >
      stub-model-ready
    </button>
  ),
}))
vi.mock('./features/goal-suggestion/GoalSuggestionStep', () => ({
  GoalSuggestionStep: ({ onDecision }: any) => (
    <button onClick={() => onDecision('preference_alignment', 'be concise')}>stub-decision</button>
  ),
}))
vi.mock('./features/provider-config/ProviderConfigStep', () => ({
  ProviderConfigStep: ({ onProviderReady }: any) => (
    <button
      onClick={() =>
        onProviderReady(
          { id: 'gen-1', name: 'generator', endpoint_scope: 'local' },
          { id: 'judge-1', name: 'judge', endpoint_scope: 'remote' },
          true,
        )
      }
    >
      stub-provider-ready
    </button>
  ),
}))
vi.mock('./features/goal-wizard/GoalWizardStep', () => ({
  GoalWizardStep: (props: any) => (
    <div
      data-testid="goal-wizard"
      data-initial-goal={props.initialGoal}
      data-initial-desired-behavior={props.initialDesiredBehavior}
      data-generator-profile-id={props.generatorProfileId}
      data-judge-profile-id={props.judgeProfileId}
    />
  ),
}))

describe('App wizard wiring', () => {
  it('runs provider config between goal-suggestion and the goal wizard, threading both into GoalWizardStep', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />)

    await user.click(screen.getByText('stub-project-ready'))
    await user.click(screen.getByText('stub-model-ready'))
    expect(screen.getByText('stub-decision')).toBeInTheDocument()
    await user.click(screen.getByText('stub-decision'))

    expect(screen.getByText('stub-provider-ready')).toBeInTheDocument()
    await user.click(screen.getByText('stub-provider-ready'))

    const goalWizard = screen.getByTestId('goal-wizard')
    expect(goalWizard).toHaveAttribute('data-initial-goal', 'preference_alignment')
    expect(goalWizard).toHaveAttribute('data-initial-desired-behavior', 'be concise')
    expect(goalWizard).toHaveAttribute('data-generator-profile-id', 'gen-1')
    expect(goalWizard).toHaveAttribute('data-judge-profile-id', 'judge-1')
  })
})
