import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ProviderConfigStep } from './ProviderConfigStep'

vi.mock('../../api/providers', () => ({
  createProvider: vi.fn(),
}))

import { createProvider } from '../../api/providers'

const mockCreateProvider = vi.mocked(createProvider)

describe('ProviderConfigStep', () => {
  it('renders the provider fields with no consent section yet', () => {
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    expect(screen.getByLabelText(/provider name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/base url/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^model$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/endpoint scope/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/api key/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/consent/i)).not.toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    const { container } = renderWithProviders(
      <ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />,
    )
    await screen.findByLabelText(/provider name/i)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('moves focus to the step heading on mount', () => {
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)
    expect(screen.getByRole('heading', { name: /provider configuration/i })).toHaveFocus()
  })

  it('moves focus to the ready heading after the provider is created', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/provider name/i), 'ollama')
    await user.type(screen.getByLabelText(/base url/i), 'http://127.0.0.1:11434')
    await user.type(screen.getByLabelText(/^model$/i), 'llama3')
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByRole('heading', { name: /provider ready/i })).toHaveFocus()
  })

  it('creates a local provider and enables Continue with no consent step', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/provider name/i), 'ollama')
    await user.type(screen.getByLabelText(/base url/i), 'http://127.0.0.1:11434')
    await user.type(screen.getByLabelText(/^model$/i), 'llama3')
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByRole('button', { name: /continue/i })).toBeEnabled()
    expect(mockCreateProvider).toHaveBeenCalledWith('proj-1', {
      name: 'ollama',
      base_url: 'http://127.0.0.1:11434',
      model: 'llama3',
      endpoint_scope: 'local',
      api_key: '',
    })
  })

  it('calls onProviderReady with remoteConsentGranted=false for a local provider', async () => {
    const user = userEvent.setup()
    const provider = { id: 'prov-1', name: 'ollama', endpoint_scope: 'local' as const }
    mockCreateProvider.mockResolvedValue(provider)
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await user.type(screen.getByLabelText(/provider name/i), 'ollama')
    await user.type(screen.getByLabelText(/base url/i), 'http://127.0.0.1:11434')
    await user.type(screen.getByLabelText(/^model$/i), 'llama3')
    await user.click(screen.getByRole('button', { name: /create provider/i }))
    await user.click(await screen.findByRole('button', { name: /continue/i }))

    expect(onProviderReady).toHaveBeenCalledWith(provider, false)
  })

  it('requires an explicit consent checkbox for a remote provider before Continue is enabled', async () => {
    const user = userEvent.setup()
    const provider = { id: 'prov-1', name: 'openai', endpoint_scope: 'remote' as const }
    mockCreateProvider.mockResolvedValue(provider)
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.selectOptions(screen.getByLabelText(/endpoint scope/i), 'remote')
    await user.type(screen.getByLabelText(/provider name/i), 'openai')
    await user.type(screen.getByLabelText(/base url/i), 'https://api.openai.com/v1')
    await user.type(screen.getByLabelText(/^model$/i), 'gpt-4')
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    const consentCheckbox = await screen.findByLabelText(/consent/i)
    const continueButton = screen.getByRole('button', { name: /continue/i })
    expect(continueButton).toBeDisabled()

    await user.click(consentCheckbox)
    expect(continueButton).toBeEnabled()
  })

  it('calls onProviderReady with remoteConsentGranted=true once consent is checked', async () => {
    const user = userEvent.setup()
    const provider = { id: 'prov-1', name: 'openai', endpoint_scope: 'remote' as const }
    mockCreateProvider.mockResolvedValue(provider)
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await user.selectOptions(screen.getByLabelText(/endpoint scope/i), 'remote')
    await user.type(screen.getByLabelText(/provider name/i), 'openai')
    await user.type(screen.getByLabelText(/base url/i), 'https://api.openai.com/v1')
    await user.type(screen.getByLabelText(/^model$/i), 'gpt-4')
    await user.click(screen.getByRole('button', { name: /create provider/i }))
    await user.click(await screen.findByLabelText(/consent/i))
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onProviderReady).toHaveBeenCalledWith(provider, true)
  })

  it('shows a validation error when provider creation fails', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockRejectedValue(new ApiError(422, "endpoint_scope must be 'local' or 'remote'"))
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByText("endpoint_scope must be 'local' or 'remote'")).toBeInTheDocument()
  })
})
