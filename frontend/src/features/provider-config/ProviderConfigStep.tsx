import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProvider } from '../../api/providers'
import { ApiError } from '../../api/client'
import type { EndpointScope, ProviderProfile } from '../../api/types'

interface ProviderConfigStepProps {
  projectId: string
  onProviderReady: (provider: ProviderProfile, remoteConsentGranted: boolean) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ProviderConfigStep({ projectId, onProviderReady }: ProviderConfigStepProps) {
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [endpointScope, setEndpointScope] = useState<EndpointScope>('local')
  const [apiKey, setApiKey] = useState('')
  const [consentGranted, setConsentGranted] = useState(false)

  const createMutation = useMutation({
    mutationFn: () =>
      createProvider(projectId, { name, base_url: baseUrl, model, endpoint_scope: endpointScope, api_key: apiKey }),
  })

  const provider = createMutation.data
  const needsConsent = provider?.endpoint_scope === 'remote'
  const canContinue = provider !== undefined && (!needsConsent || consentGranted)

  if (!provider) {
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault()
          createMutation.mutate()
        }}
      >
        <label htmlFor="provider-name">Provider name</label>
        <input id="provider-name" value={name} onChange={(event) => setName(event.target.value)} />

        <label htmlFor="provider-base-url">Base URL</label>
        <input id="provider-base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />

        <label htmlFor="provider-model">Model</label>
        <input id="provider-model" value={model} onChange={(event) => setModel(event.target.value)} />

        <label htmlFor="provider-scope">Endpoint scope</label>
        <select
          id="provider-scope"
          value={endpointScope}
          onChange={(event) => setEndpointScope(event.target.value as EndpointScope)}
        >
          <option value="local">Local</option>
          <option value="remote">Remote</option>
        </select>

        <label htmlFor="provider-api-key">API key (optional)</label>
        <input
          id="provider-api-key"
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />

        <button type="submit" disabled={createMutation.isPending}>
          Create provider
        </button>
        {createMutation.isError && <p role="alert">{errorMessage(createMutation.error)}</p>}
      </form>
    )
  }

  return (
    <section>
      <p>
        Provider <strong>{provider.name}</strong> ready ({provider.endpoint_scope}).
      </p>

      {needsConsent && (
        <label htmlFor="remote-consent">
          <input
            id="remote-consent"
            type="checkbox"
            checked={consentGranted}
            onChange={(event) => setConsentGranted(event.target.checked)}
          />
          I consent to sending project document text to this remote provider
        </label>
      )}

      <button type="button" disabled={!canContinue} onClick={() => onProviderReady(provider, consentGranted)}>
        Continue
      </button>
    </section>
  )
}
