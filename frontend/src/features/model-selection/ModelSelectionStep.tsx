import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { analyzeModel } from '../../api/models'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { ModelProfileResponse, ModelSource } from '../../api/types'

interface ModelSelectionStepProps {
  projectId: string
  onProfileReady: (profile: ModelProfileResponse) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ModelSelectionStep({ projectId, onProfileReady }: ModelSelectionStepProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  const [modelId, setModelId] = useState('')
  const [source, setSource] = useState<ModelSource>('huggingface')

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeModel(projectId, modelId, source),
  })

  const profile = analyzeMutation.data

  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Model selection
      </h2>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          analyzeMutation.mutate()
        }}
      >
        <div className="field">
          <label htmlFor="model-source">Source</label>
          <select
            id="model-source"
            value={source}
            onChange={(event) => setSource(event.target.value as ModelSource)}
          >
            <option value="huggingface">Hugging Face</option>
            <option value="local">Local directory</option>
          </select>
        </div>

        <div className="field">
          <label htmlFor="model-id">Model</label>
          <input id="model-id" value={modelId} onChange={(event) => setModelId(event.target.value)} />
        </div>

        <div className="button-row">
          <button type="submit" disabled={analyzeMutation.isPending}>
            Analyze
          </button>
        </div>
      </form>

      {analyzeMutation.isError && <p role="alert">{errorMessage(analyzeMutation.error)}</p>}

      {profile && (
        <div className="card">
          <dl>
            <dt>Architecture</dt>
            <dd>{profile.architecture}</dd>
            <dt>Model type</dt>
            <dd>{profile.model_type}</dd>
            <dt>Causal LM</dt>
            <dd>{profile.is_causal_lm ? 'Yes' : 'No'}</dd>
            <dt>Chat model</dt>
            <dd>{profile.is_chat_model ? 'Yes' : 'No'}</dd>
            <dt>Chat template found</dt>
            <dd>{profile.chat_template_found ? 'Yes' : 'No'}</dd>
            <dt>Context length</dt>
            <dd>{profile.context_length}</dd>
            <dt>Confidence</dt>
            <dd>{Math.round(profile.confidence * 100)}%</dd>
            <dt>Evidence</dt>
            <dd>
              <ul>
                {profile.evidence.map((item) => (
                  <li key={`${item.field}-${item.source}`}>
                    <strong>{item.field}</strong>: {item.value} (<code>{item.source}</code> — {item.detail})
                  </li>
                ))}
              </ul>
            </dd>
          </dl>
        </div>
      )}

      {profile && (
        <div className="button-row">
          <button type="button" onClick={() => onProfileReady(profile)}>
            Continue
          </button>
        </div>
      )}
    </section>
  )
}
