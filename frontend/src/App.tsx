import { useState } from 'react'
import { ProjectSetupStep } from './features/project-setup/ProjectSetupStep'
import { ModelSelectionStep } from './features/model-selection/ModelSelectionStep'
import { GoalSuggestionStep } from './features/goal-suggestion/GoalSuggestionStep'
import { GoalWizardStep } from './features/goal-wizard/GoalWizardStep'
import { PlanConfirmationStep } from './features/plan-confirmation/PlanConfirmationStep'
import { ProviderConfigStep } from './features/provider-config/ProviderConfigStep'
import { PreviewStep } from './features/preview/PreviewStep'
import { RunProgressStep } from './features/run-progress/RunProgressStep'
import { ExportStep } from './features/export/ExportStep'
import type { ModelProfileResponse, Project, ProviderProfile, TrainingGoal, TrainingPlanResponse } from './api/types'

type WizardStep =
  | 'project'
  | 'model'
  | 'goal-suggestion'
  | 'provider'
  | 'goal'
  | 'plan'
  | 'preview'
  | 'progress'
  | 'export'

function App() {
  const [step, setStep] = useState<WizardStep>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [modelProfile, setModelProfile] = useState<ModelProfileResponse | null>(null)
  const [goalDecision, setGoalDecision] = useState<{ goal: TrainingGoal | null; desiredBehavior: string }>({
    goal: null,
    desiredBehavior: '',
  })
  const [plan, setPlan] = useState<TrainingPlanResponse | null>(null)
  const [provider, setProvider] = useState<ProviderProfile | null>(null)
  const [judgeProvider, setJudgeProvider] = useState<ProviderProfile | null>(null)
  const [remoteConsentGranted, setRemoteConsentGranted] = useState(false)
  const [fullRunId, setFullRunId] = useState<string | null>(null)

  return (
    <main>
      <h1>TuneForge</h1>
      <p>Local dataset compiler for Unsloth fine-tuning.</p>

      {step === 'project' && (
        <ProjectSetupStep
          onProjectReady={(readyProject) => {
            setProject(readyProject)
            setStep('model')
          }}
        />
      )}

      {step === 'model' && project && (
        <ModelSelectionStep
          projectId={project.id}
          onProfileReady={(profile) => {
            setModelProfile(profile)
            setStep('goal-suggestion')
          }}
        />
      )}

      {step === 'goal-suggestion' && project && (
        <GoalSuggestionStep
          projectId={project.id}
          onDecision={(goal, desiredBehavior) => {
            setGoalDecision({ goal, desiredBehavior })
            setStep('provider')
          }}
        />
      )}

      {step === 'provider' && project && (
        <ProviderConfigStep
          projectId={project.id}
          onProviderReady={(readyProvider, readyJudgeProvider, consentGranted) => {
            setProvider(readyProvider)
            setJudgeProvider(readyJudgeProvider ?? null)
            setRemoteConsentGranted(consentGranted)
            setStep('goal')
          }}
        />
      )}

      {step === 'goal' && project && modelProfile && provider && (
        <GoalWizardStep
          projectId={project.id}
          modelProfileId={modelProfile.id}
          generatorProfileId={provider.id}
          judgeProfileId={judgeProvider?.id}
          initialGoal={goalDecision.goal ?? undefined}
          initialDesiredBehavior={goalDecision.desiredBehavior}
          onPlanRecommended={(recommendedPlan) => {
            setPlan(recommendedPlan)
            setStep('plan')
          }}
        />
      )}

      {step === 'plan' && plan && (
        <PlanConfirmationStep
          plan={plan}
          onApproved={() => {
            setStep('preview')
          }}
        />
      )}

      {step === 'preview' && plan && provider && (
        <PreviewStep
          planId={plan.id}
          generatorProfileId={provider.id}
          judgeProfileId={judgeProvider?.id}
          remoteConsentGranted={remoteConsentGranted}
          onApprovedFull={(fullRun) => {
            setFullRunId(fullRun.id)
            setStep('progress')
          }}
        />
      )}

      {step === 'progress' && fullRunId && (
        <RunProgressStep
          runId={fullRunId}
          onCompleted={() => {
            setStep('export')
          }}
        />
      )}

      {step === 'export' && fullRunId && <ExportStep runId={fullRunId} />}
    </main>
  )
}

export default App
