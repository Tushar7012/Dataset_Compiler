import { useEffect, useRef, useState } from 'react'
import { createProvider } from '../../api/providers'
import { approvePlan, recommendPlan } from '../../api/plans'
import { ApiError } from '../../api/client'
import { useFocusOnMount } from '../../useFocusOnMount'
import type { GoalDecision } from '../goal-wizard/GoalWizardStep'
import type { ProviderProfile, TrainingPlanResponse } from '../../api/types'

interface PreparingRunStepProps {
  projectId: string
  modelProfileId: string
  decision: GoalDecision
  onReady: (plan: TrainingPlanResponse, generatorProvider: ProviderProfile, judgeProvider?: ProviderProfile) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

// Hugging Face's OpenAI-compatible router. A provider created with these values
// and no api_key resolves the pre-configured HF_TOKEN credential automatically
// (see tuneforge.api.providers.HF_ROUTER_BASE_URL_MARKER) — the user never has
// to see or configure a provider at all, generator or judge.
const HF_ROUTER_BASE_URL = 'https://router.huggingface.co/v1'
const GENERATOR_PRESET = { name: 'hf-router-generator', model: 'Qwen/Qwen3-Next-80B-A3B-Instruct' }
// Qwen3-235B-A22B-Instruct-2507, not the -Thinking- sibling: the Thinking checkpoint
// wraps every answer in a long <think> reasoning block and routinely exceeds this
// app's provider timeout — same model family and size, without the latency cost,
// and still distinct from the generator model (DPO requires that distinctness).
const JUDGE_PRESET = { name: 'hf-router-judge', model: 'Qwen/Qwen3-235B-A22B-Instruct-2507' }

// No provider-configuration screen by design — which LLM backs generation is
// an implementation detail, not something the user chooses per run. Every
// provider is the pre-configured Hugging Face router; a judge is only ever
// created when the goal is preference alignment (DPO), since nothing else
// ever calls one. No plan-detail review screen either — the objective/schema/
// validators a plan recommendation carries are internal, not a decision
// point. This step exists only to cover the network round trip.
export function PreparingRunStep({ projectId, modelProfileId, decision, onReady }: PreparingRunStepProps) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>()
  const [error, setError] = useState<unknown>(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    const needsJudge = decision.goal === 'preference_alignment'

    Promise.all([
      createProvider(projectId, { name: GENERATOR_PRESET.name, base_url: HF_ROUTER_BASE_URL, model: GENERATOR_PRESET.model }),
      needsJudge
        ? createProvider(projectId, { name: JUDGE_PRESET.name, base_url: HF_ROUTER_BASE_URL, model: JUDGE_PRESET.model })
        : Promise.resolve(undefined),
    ])
      .then(([generatorProvider, judgeProvider]) =>
        recommendPlan(projectId, modelProfileId, {
          goal: decision.goal,
          target_rows: decision.targetRows,
          generator_profile_id: generatorProvider.id,
          judge_profile_id: judgeProvider?.id,
        }).then((plan) => approvePlan(plan.id).then(() => ({ plan, generatorProvider, judgeProvider }))),
      )
      .then(({ plan, generatorProvider, judgeProvider }) => onReady(plan, generatorProvider, judgeProvider))
      .catch(setError)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="wizard-step">
      <h2 ref={headingRef} tabIndex={-1}>
        Preparing…
      </h2>
      {error != null && <p role="alert">{errorMessage(error)}</p>}
    </section>
  )
}
