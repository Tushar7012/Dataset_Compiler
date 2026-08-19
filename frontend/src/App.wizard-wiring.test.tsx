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
vi.mock('./features/goal-wizard/GoalWizardStep', () => ({
  GoalWizardStep: (props: any) => (
    <div>
      <div data-testid="goal-wizard" />
      <button
        onClick={() =>
          props.onGoalChosen({
            goal: 'preference_alignment',
            targetRows: 500,
          })
        }
      >
        stub-goal-chosen
      </button>
    </div>
  ),
}))
vi.mock('./features/run-preparation/PreparingRunStep', () => ({
  PreparingRunStep: (props: any) => (
    <div>
      <div
        data-testid="preparing-run"
        data-project-id={props.projectId}
        data-model-profile-id={props.modelProfileId}
        data-decision-goal={props.decision.goal}
        data-decision-target-rows={props.decision.targetRows}
      />
      <button
        onClick={() =>
          props.onReady(
            { id: 'plan-1' },
            { id: 'gen-1', name: 'generator' },
            { id: 'judge-1', name: 'judge' },
          )
        }
      >
        stub-run-ready
      </button>
    </div>
  ),
}))
vi.mock('./features/preview/PreviewStep', () => ({
  PreviewStep: (props: any) => (
    <div
      data-testid="preview-step"
      data-plan-id={props.planId}
      data-generator-profile-id={props.generatorProfileId}
      data-judge-profile-id={props.judgeProfileId}
    />
  ),
}))

describe('App wizard wiring', () => {
  it('threads project and model into GoalWizardStep, then its decision into PreparingRunStep, and its onReady into PreviewStep', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />)

    await user.click(screen.getByText('stub-project-ready'))
    await user.click(screen.getByText('stub-model-ready'))

    expect(screen.getByTestId('goal-wizard')).toBeInTheDocument()

    await user.click(screen.getByText('stub-goal-chosen'))

    const preparingRun = screen.getByTestId('preparing-run')
    expect(preparingRun).toHaveAttribute('data-project-id', 'proj-1')
    expect(preparingRun).toHaveAttribute('data-model-profile-id', 'profile-1')
    expect(preparingRun).toHaveAttribute('data-decision-goal', 'preference_alignment')
    expect(preparingRun).toHaveAttribute('data-decision-target-rows', '500')

    await user.click(screen.getByText('stub-run-ready'))

    const previewStep = screen.getByTestId('preview-step')
    expect(previewStep).toHaveAttribute('data-plan-id', 'plan-1')
    expect(previewStep).toHaveAttribute('data-generator-profile-id', 'gen-1')
    expect(previewStep).toHaveAttribute('data-judge-profile-id', 'judge-1')
  })
})
