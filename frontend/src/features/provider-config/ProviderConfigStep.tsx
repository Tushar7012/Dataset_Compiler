import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProvider } from '../../api/providers'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { EndpointScope, ProviderProfile } from '../../api/types'

interface ProviderConfigStepProps {
  projectId: string
  onProviderReady: (
    generatorProvider: ProviderProfile,
    judgeProvider: ProviderProfile | undefined,
    remoteConsentGranted: boolean,
  ) => void
}

interface HfPreset {
  label: string
  name: string
  model: string
}

// Hugging Face's OpenAI-compatible router (https://router.huggingface.co/v1). A provider
// created with these values and a blank API key resolves the pre-configured HF_TOKEN
// credential automatically (see tuneforge.api.providers.HF_ROUTER_BASE_URL_MARKER).
const HF_ROUTER_BASE_URL = 'https://router.huggingface.co/v1'

const HF_DPO_GENERATOR_PRESET: HfPreset = {
  label: 'Use Hugging Face router — Qwen3 DPO generator',
  name: 'hf-router-generator',
  model: 'Qwen/Qwen3-Next-80B-A3B-Instruct',
}

// Qwen3-235B-A22B-Instruct-2507, not the -Thinking- sibling: the Thinking checkpoint
// wraps every answer in a long <think> reasoning block and routinely exceeds this
// app's provider timeout (measured 30s+ per call vs ~1s here) — same model family
// and size, without the latency cost, and still distinct from the generator model.
const HF_DPO_JUDGE_PRESET: HfPreset = {
  label: 'Use Hugging Face router — Qwen3 DPO judge',
  name: 'hf-router-judge',
  model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

function ProviderCreateForm({
  title,
  preset,
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
  title: string
  preset: HfPreset
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
          {title}
        </h2>

        <div className="button-row">
          <button
            type="button"
            onClick={() => {
              setName(preset.name)
              setBaseUrl(HF_ROUTER_BASE_URL)
              setModel(preset.model)
              setEndpointScope('remote')
              setApiKey('')
            }}
          >
            {preset.label}
          </button>
        </div>

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
            API key (optional — leave blank to use a pre-configured Gemini or Hugging Face credential)
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

function JudgeChoicePanel({ onAdd, onSkip }: { onAdd: () => void; onSkip: () => void }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Judge model
      </h2>
      <p>
        Preference alignment (DPO) needs a second, distinct judge model. Add one now, or skip if this run
        won't use preference alignment.
      </p>
      <div className="button-row">
        <button type="button" onClick={onAdd}>
          Add judge provider
        </button>
        <button type="button" onClick={onSkip}>
          Skip — no judge model
        </button>
      </div>
    </section>
  )
}

function ProviderReadyPanel({
  generatorProvider,
  judgeProvider,
  needsConsent,
  consentGranted,
  setConsentGranted,
  canContinue,
  onContinue,
}: {
  generatorProvider: ProviderProfile
  judgeProvider: ProviderProfile | undefined
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
        Generator <strong>{generatorProvider.name}</strong> ready ({generatorProvider.endpoint_scope}).
      </p>
      {judgeProvider && (
        <p>
          Judge <strong>{judgeProvider.name}</strong> ready ({judgeProvider.endpoint_scope}).
        </p>
      )}

      {needsConsent && (
        <div className="field">
          <label htmlFor="remote-consent">
            <input
              id="remote-consent"
              type="checkbox"
              checked={consentGranted}
              onChange={(event) => setConsentGranted(event.target.checked)}
            />
            I consent to sending project document text to the remote provider(s) above
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

type JudgeChoice = 'undecided' | 'skip' | 'add'

export function ProviderConfigStep({ projectId, onProviderReady }: ProviderConfigStepProps) {
  const [genName, setGenName] = useState('')
  const [genBaseUrl, setGenBaseUrl] = useState('')
  const [genModel, setGenModel] = useState('')
  const [genScope, setGenScope] = useState<EndpointScope>('local')
  const [genApiKey, setGenApiKey] = useState('')

  const [judgeName, setJudgeName] = useState('')
  const [judgeBaseUrl, setJudgeBaseUrl] = useState('')
  const [judgeModel, setJudgeModel] = useState('')
  const [judgeScope, setJudgeScope] = useState<EndpointScope>('local')
  const [judgeApiKey, setJudgeApiKey] = useState('')

  const [judgeChoice, setJudgeChoice] = useState<JudgeChoice>('undecided')
  const [consentGranted, setConsentGranted] = useState(false)

  const generatorMutation = useMutation({
    mutationFn: () =>
      createProvider(projectId, {
        name: genName,
        base_url: genBaseUrl,
        model: genModel,
        endpoint_scope: genScope,
        api_key: genApiKey,
      }),
  })

  const judgeMutation = useMutation({
    mutationFn: () =>
      createProvider(projectId, {
        name: judgeName,
        base_url: judgeBaseUrl,
        model: judgeModel,
        endpoint_scope: judgeScope,
        api_key: judgeApiKey,
      }),
  })

  const generatorProvider = generatorMutation.data

  if (!generatorProvider) {
    return (
      <ProviderCreateForm
        title="Provider configuration"
        preset={HF_DPO_GENERATOR_PRESET}
        name={genName}
        setName={setGenName}
        baseUrl={genBaseUrl}
        setBaseUrl={setGenBaseUrl}
        model={genModel}
        setModel={setGenModel}
        endpointScope={genScope}
        setEndpointScope={setGenScope}
        apiKey={genApiKey}
        setApiKey={setGenApiKey}
        onSubmit={() => generatorMutation.mutate()}
        isPending={generatorMutation.isPending}
        error={generatorMutation.isError ? generatorMutation.error : null}
      />
    )
  }

  if (judgeChoice === 'undecided') {
    return <JudgeChoicePanel onAdd={() => setJudgeChoice('add')} onSkip={() => setJudgeChoice('skip')} />
  }

  const judgeProvider = judgeMutation.data

  if (judgeChoice === 'add' && !judgeProvider) {
    return (
      <ProviderCreateForm
        title="Judge provider configuration"
        preset={HF_DPO_JUDGE_PRESET}
        name={judgeName}
        setName={setJudgeName}
        baseUrl={judgeBaseUrl}
        setBaseUrl={setJudgeBaseUrl}
        model={judgeModel}
        setModel={setJudgeModel}
        endpointScope={judgeScope}
        setEndpointScope={setJudgeScope}
        apiKey={judgeApiKey}
        setApiKey={setJudgeApiKey}
        onSubmit={() => judgeMutation.mutate()}
        isPending={judgeMutation.isPending}
        error={judgeMutation.isError ? judgeMutation.error : null}
      />
    )
  }

  const effectiveJudgeProvider = judgeChoice === 'add' ? judgeProvider : undefined
  const needsConsent =
    generatorProvider.endpoint_scope === 'remote' || effectiveJudgeProvider?.endpoint_scope === 'remote'
  const canContinue = !needsConsent || consentGranted

  return (
    <ProviderReadyPanel
      generatorProvider={generatorProvider}
      judgeProvider={effectiveJudgeProvider}
      needsConsent={needsConsent}
      consentGranted={consentGranted}
      setConsentGranted={setConsentGranted}
      canContinue={canContinue}
      onContinue={() => onProviderReady(generatorProvider, effectiveJudgeProvider, consentGranted)}
    />
  )
}
