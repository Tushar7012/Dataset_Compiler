import { useState } from 'react'
import { ProjectSetupStep } from './features/project-setup/ProjectSetupStep'
import { ModelSelectionStep } from './features/model-selection/ModelSelectionStep'
import { GoalWizardStep } from './features/goal-wizard/GoalWizardStep'
import { PlanConfirmationStep } from './features/plan-confirmation/PlanConfirmationStep'
import { ProviderConfigStep } from './features/provider-config/ProviderConfigStep'
import { PreviewStep } from './features/preview/PreviewStep'
import { RunProgressStep } from './features/run-progress/RunProgressStep'
import { ExportStep } from './features/export/ExportStep'
import type { ModelProfileResponse, Project, ProviderProfile, TrainingPlanResponse } from './api/types'

type WizardStep = 'project' | 'model' | 'goal' | 'plan' | 'provider' | 'preview' | 'progress' | 'export'

function App() {
  const [step, setStep] = useState<WizardStep>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [modelProfile, setModelProfile] = useState<ModelProfileResponse | null>(null)
  const [plan, setPlan] = useState<TrainingPlanResponse | null>(null)
  const [provider, setProvider] = useState<ProviderProfile | null>(null)
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
            setStep('goal')
          }}
        />
      )}

      {step === 'goal' && project && modelProfile && (
        <GoalWizardStep
          projectId={project.id}
          modelProfileId={modelProfile.id}
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
            setStep('provider')
          }}
        />
      )}

      {step === 'provider' && project && (
        <ProviderConfigStep
          projectId={project.id}
          onProviderReady={(readyProvider, consentGranted) => {
            setProvider(readyProvider)
            setRemoteConsentGranted(consentGranted)
            setStep('preview')
          }}
        />
      )}

      {step === 'preview' && plan && provider && (
        <PreviewStep
          planId={plan.id}
          generatorProfileId={provider.id}
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
