import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ModelSelectionStep } from './ModelSelectionStep'

vi.mock('../../api/models', () => ({
  analyzeModel: vi.fn(),
}))

import { analyzeModel } from '../../api/models'

const mockAnalyzeModel = vi.mocked(analyzeModel)

const profile = {
  id: 'profile-1',
  source: 'huggingface' as const,
  model_id: 'Qwen/Qwen2.5-1.5B-Instruct',
  architecture: 'Qwen2ForCausalLM',
  model_type: 'qwen2',
  is_causal_lm: true,
  is_chat_model: true,
  chat_template_found: true,
  context_length: 32768,
  modalities: ['text'],
  evidence: [
    { field: 'architecture', value: 'Qwen2ForCausalLM', source: 'config.json', detail: 'architectures[0]' },
  ],
  confidence: 0.95,
}

describe('ModelSelectionStep', () => {
  it('renders a model id field and an Analyze button, no evidence yet', () => {
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    expect(screen.getByLabelText(/model/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /analyze/i })).toBeInTheDocument()
    expect(screen.queryByText(/architecture/i)).not.toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    const { container } = renderWithProviders(
      <ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />,
    )
    await screen.findByLabelText(/model/i)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('analyzes the model and displays its evidence', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockResolvedValue(profile)
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/model/i), 'Qwen/Qwen2.5-1.5B-Instruct')
    await user.click(screen.getByRole('button', { name: /analyze/i }))

    expect(await screen.findByText('Qwen2ForCausalLM')).toBeInTheDocument()
    expect(screen.getByText(/chat template found/i)).toBeInTheDocument()
    expect(screen.getByText('config.json')).toBeInTheDocument()
    expect(mockAnalyzeModel).toHaveBeenCalledWith('proj-1', 'Qwen/Qwen2.5-1.5B-Instruct', 'huggingface')
  })

  it('shows the backend rejection message for an incompatible model', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockRejectedValue(new ApiError(422, 'not a text decoder-only causal language model'))
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/model/i), 'stabilityai/stable-diffusion-2')
    await user.click(screen.getByRole('button', { name: /analyze/i }))

    expect(await screen.findByText('not a text decoder-only causal language model')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /continue/i })).not.toBeInTheDocument()
  })

  it('calls onProfileReady with the analyzed profile when Continue is clicked', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockResolvedValue(profile)
    const onProfileReady = vi.fn()
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={onProfileReady} />)

    await user.type(screen.getByLabelText(/model/i), 'Qwen/Qwen2.5-1.5B-Instruct')
    await user.click(screen.getByRole('button', { name: /analyze/i }))
    await user.click(await screen.findByRole('button', { name: /continue/i }))

    expect(onProfileReady).toHaveBeenCalledWith(profile)
  })

  it('lets the user switch source to local before analyzing', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockResolvedValue({ ...profile, source: 'local' })
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    await user.selectOptions(screen.getByLabelText(/source/i), 'local')
    await user.type(screen.getByLabelText(/model/i), 'C:\\models\\my-model')
    await user.click(screen.getByRole('button', { name: /analyze/i }))

    expect(mockAnalyzeModel).toHaveBeenCalledWith('proj-1', 'C:\\models\\my-model', 'local')
  })
})
