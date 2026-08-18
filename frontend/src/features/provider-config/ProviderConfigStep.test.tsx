import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ProviderConfigStep } from './ProviderConfigStep'

vi.mock('../../api/providers', () => ({
  createProvider: vi.fn(),
}))
vi.mock('../../api/session', () => ({
  getRemoteParsingEnabled: vi.fn(),
}))

import { createProvider } from '../../api/providers'
import { getRemoteParsingEnabled } from '../../api/session'

const mockCreateProvider = vi.mocked(createProvider)
const mockGetRemoteParsingEnabled = vi.mocked(getRemoteParsingEnabled)

async function createGenerator(
  user: ReturnType<typeof userEvent.setup>,
  { remote = false }: { remote?: boolean } = {},
) {
  if (remote) {
    await user.selectOptions(screen.getByLabelText(/endpoint scope/i), 'remote')
  }
  await user.type(screen.getByLabelText(/provider name/i), 'ollama')
  await user.type(screen.getByLabelText(/base url/i), 'http://127.0.0.1:11434')
  await user.type(screen.getByLabelText(/^model$/i), 'llama3')
  await user.click(screen.getByRole('button', { name: /create provider/i }))
  await screen.findByRole('heading', { name: /judge model/i })
}

describe('ProviderConfigStep', () => {
  beforeEach(() => {
    mockGetRemoteParsingEnabled.mockResolvedValue(false)
  })

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

  it('shows the judge-model choice after the generator provider is created', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await createGenerator(user)

    expect(screen.getByRole('heading', { name: /judge model/i })).toHaveFocus()
    expect(screen.getByRole('button', { name: /add judge provider/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /skip.*no judge model/i })).toBeInTheDocument()
  })

  it('skipping the judge choice reaches Continue with no consent step for a local generator', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await createGenerator(user)
    await user.click(screen.getByRole('button', { name: /skip.*no judge model/i }))

    const continueButton = await screen.findByRole('button', { name: /continue/i })
    expect(continueButton).toBeEnabled()
    await user.click(continueButton)

    expect(onProviderReady).toHaveBeenCalledWith(
      { id: 'prov-1', name: 'ollama', endpoint_scope: 'local' },
      undefined,
      false,
    )
  })

  it('requires consent for two local providers when the server has remote parsing configured', async () => {
    // Regression: needsConsent used to be derived only from provider
    // endpoint_scope, so a project with two local LLM providers would never
    // show the consent checkbox even when TUNEFORGE_DOCLING_REMOTE_URL is
    // configured server-side — the run would then 422 forever with no way
    // to grant consent through the UI. Found via a real Playwright e2e run.
    mockGetRemoteParsingEnabled.mockResolvedValue(true)
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await createGenerator(user)
    await user.click(screen.getByRole('button', { name: /skip.*no judge model/i }))

    const consentCheckbox = await screen.findByLabelText(/consent/i)
    const continueButton = screen.getByRole('button', { name: /continue/i })
    expect(continueButton).toBeDisabled()

    await user.click(consentCheckbox)
    expect(continueButton).toBeEnabled()
    await user.click(continueButton)

    expect(onProviderReady).toHaveBeenCalledWith(
      { id: 'prov-1', name: 'ollama', endpoint_scope: 'local' },
      undefined,
      true,
    )
  })

  it('keeps Continue disabled while remote-parsing-enabled is still loading, even with two local providers', async () => {
    // Regression guard for the fix above: needsConsent reads
    // remoteParsingQuery.data === true, which is undefined (falsy) while the
    // query is still in flight — canContinue must not treat "still loading"
    // as "answer is no consent needed" just because both providers are local.
    let resolveQuery: (value: boolean) => void = () => {}
    mockGetRemoteParsingEnabled.mockReturnValue(
      new Promise<boolean>((resolve) => {
        resolveQuery = resolve
      }),
    )
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await createGenerator(user)
    await user.click(screen.getByRole('button', { name: /skip.*no judge model/i }))

    const continueButton = await screen.findByRole('button', { name: /continue/i })
    expect(continueButton).toBeDisabled()

    resolveQuery(false)
    await waitFor(() => expect(continueButton).toBeEnabled())
  })

  it('requires an explicit consent checkbox for a remote generator before Continue is enabled', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'openai', endpoint_scope: 'remote' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await createGenerator(user, { remote: true })
    await user.click(screen.getByRole('button', { name: /skip.*no judge model/i }))

    const consentCheckbox = await screen.findByLabelText(/consent/i)
    const continueButton = screen.getByRole('button', { name: /continue/i })
    expect(continueButton).toBeDisabled()

    await user.click(consentCheckbox)
    expect(continueButton).toBeEnabled()
  })

  it('adding a judge provider shows a second, distinct provider form and both are reported ready', async () => {
    const user = userEvent.setup()
    mockCreateProvider
      .mockResolvedValueOnce({ id: 'prov-gen', name: 'ollama', endpoint_scope: 'local' })
      .mockResolvedValueOnce({ id: 'prov-judge', name: 'hf-router-judge', endpoint_scope: 'remote' })
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await createGenerator(user)
    await user.click(screen.getByRole('button', { name: /add judge provider/i }))

    expect(screen.getByRole('heading', { name: /judge provider configuration/i })).toHaveFocus()
    await user.type(screen.getByLabelText(/provider name/i), 'hf-router-judge')
    await user.type(screen.getByLabelText(/base url/i), 'https://router.huggingface.co/v1')
    await user.type(screen.getByLabelText(/^model$/i), 'Qwen/Qwen3-235B-A22B-Instruct-2507')
    await user.selectOptions(screen.getByLabelText(/endpoint scope/i), 'remote')
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByText('hf-router-judge')).toBeInTheDocument()
    const consentCheckbox = screen.getByLabelText(/consent/i)
    await user.click(consentCheckbox)
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onProviderReady).toHaveBeenCalledWith(
      { id: 'prov-gen', name: 'ollama', endpoint_scope: 'local' },
      { id: 'prov-judge', name: 'hf-router-judge', endpoint_scope: 'remote' },
      true,
    )
  })

  it('the Hugging Face router preset fills base URL, model, and remote scope', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'hf-router-generator', endpoint_scope: 'remote' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /use hugging face router/i }))
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(mockCreateProvider).toHaveBeenCalledWith('proj-1', {
      name: 'hf-router-generator',
      base_url: 'https://router.huggingface.co/v1',
      model: 'Qwen/Qwen3-Next-80B-A3B-Instruct',
      endpoint_scope: 'remote',
      api_key: '',
    })
  })

  it('shows a validation error when provider creation fails', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockRejectedValue(new ApiError(422, "endpoint_scope must be 'local' or 'remote'"))
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByText("endpoint_scope must be 'local' or 'remote'")).toBeInTheDocument()
  })
})
