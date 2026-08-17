import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProvider } from '../../api/providers'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { EndpointScope, ProviderProfile } from '../../api/types'

interface ProviderConfigStepProps {
  projectId: string
  onProviderReady: (provider: ProviderProfile, remoteConsentGranted: boolean) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

function ProviderCreateForm({
  name,
  setName,
  baseUrl,
  setBaseUrl,
  model,
  setModel,
  endpointScope,
  setEndpointScope,
  apiKey,
  setApiKey,
  onSubmit,
  isPending,
  error,
}: {
  name: string
  setName: (value: string) => void
  baseUrl: string
  setBaseUrl: (value: string) => void
  model: string
  setModel: (value: string) => void
  endpointScope: EndpointScope
  setEndpointScope: (value: EndpointScope) => void
  apiKey: string
  setApiKey: (value: string) => void
  onSubmit: () => void
  isPending: boolean
  error: unknown
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        <h2 ref={headingRef} tabIndex={-1}>
          Provider configuration
        </h2>
        <div className="field">
          <label htmlFor="provider-name">Provider name</label>
          <input id="provider-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>

        <div className="field">
          <label htmlFor="provider-base-url">Base URL</label>
          <input
            id="provider-base-url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder="e.g. http://127.0.0.1:11434/v1 or https://generativelanguage.googleapis.com/v1beta/openai"
          />
          <small>
            Include the full API path — it is appended with /chat/completions and /models exactly as written,
            nothing is added automatically.
          </small>
        </div>

        <div className="field">
          <label htmlFor="provider-model">Model</label>
          <input id="provider-model" value={model} onChange={(event) => setModel(event.target.value)} />
        </div>

        <div className="field">
          <label htmlFor="provider-scope">Endpoint scope</label>
          <select
            id="provider-scope"
            value={endpointScope}
            onChange={(event) => setEndpointScope(event.target.value as EndpointScope)}
          >
            <option value="local">Local</option>
            <option value="remote">Remote</option>
          </select>
        </div>

        <div className="field">
          <label htmlFor="provider-api-key">
            API key (optional — leave blank to use the pre-configured Gemini key)
          </label>
          <input
            id="provider-api-key"
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </div>

        <div className="button-row">
          <button type="submit" disabled={isPending}>
            Create provider
          </button>
        </div>
        {error != null && <p role="alert">{errorMessage(error)}</p>}
      </form>
    </section>
  )
}

function ProviderReadyPanel({
  provider,
  needsConsent,
  consentGranted,
  setConsentGranted,
  canContinue,
  onContinue,
}: {
  provider: ProviderProfile
  needsConsent: boolean
  consentGranted: boolean
  setConsentGranted: (value: boolean) => void
  canContinue: boolean
  onContinue: () => void
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Provider ready
      </h2>
      <p>
        Provider <strong>{provider.name}</strong> ready ({provider.endpoint_scope}).
      </p>

      {needsConsent && (
        <div className="field">
          <label htmlFor="remote-consent">
            <input
              id="remote-consent"
              type="checkbox"
              checked={consentGranted}
              onChange={(event) => setConsentGranted(event.target.checked)}
            />
            I consent to sending project document text to this remote provider
          </label>
        </div>
      )}

      <div className="button-row">
        <button type="button" disabled={!canContinue} onClick={onContinue}>
          Continue
        </button>
      </div>
    </section>
  )
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
      <ProviderCreateForm
        name={name}
        setName={setName}
        baseUrl={baseUrl}
        setBaseUrl={setBaseUrl}
        model={model}
        setModel={setModel}
        endpointScope={endpointScope}
        setEndpointScope={setEndpointScope}
        apiKey={apiKey}
        setApiKey={setApiKey}
        onSubmit={() => createMutation.mutate()}
        isPending={createMutation.isPending}
        error={createMutation.isError ? createMutation.error : null}
      />
    )
  }

  return (
    <ProviderReadyPanel
      provider={provider}
      needsConsent={needsConsent}
      consentGranted={consentGranted}
      setConsentGranted={setConsentGranted}
      canContinue={canContinue}
      onContinue={() => onProviderReady(provider, consentGranted)}
    />
  )
}
