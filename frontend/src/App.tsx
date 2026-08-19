import { useState } from 'react'
import { ProjectSetupStep } from './features/project-setup/ProjectSetupStep'
import { ModelSelectionStep } from './features/model-selection/ModelSelectionStep'
import { GoalWizardStep, type GoalDecision } from './features/goal-wizard/GoalWizardStep'
import { PreparingRunStep } from './features/run-preparation/PreparingRunStep'
import { PreviewStep } from './features/preview/PreviewStep'
import { RunProgressStep } from './features/run-progress/RunProgressStep'
import { ExportStep } from './features/export/ExportStep'
import type { ModelProfileResponse, Project, ProviderProfile, TrainingPlanResponse } from './api/types'

type WizardStep = 'project' | 'model' | 'goal' | 'preparing-run' | 'preview' | 'progress' | 'export'

function App() {
  const [step, setStep] = useState<WizardStep>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [modelProfile, setModelProfile] = useState<ModelProfileResponse | null>(null)
  const [goalDecision, setGoalDecision] = useState<GoalDecision | null>(null)
  const [plan, setPlan] = useState<TrainingPlanResponse | null>(null)
  const [provider, setProvider] = useState<ProviderProfile | null>(null)
  const [judgeProvider, setJudgeProvider] = useState<ProviderProfile | null>(null)
  const [fullRunId, setFullRunId] = useState<string | null>(null)

  return (
    <main>
      <h1>Dataset Compiler</h1>

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
          onGoalChosen={(decision) => {
            setGoalDecision(decision)
            setStep('preparing-run')
          }}
        />
      )}

      {step === 'preparing-run' && project && modelProfile && goalDecision && (
        <PreparingRunStep
          projectId={project.id}
          modelProfileId={modelProfile.id}
          decision={goalDecision}
          onReady={(readyPlan, readyProvider, readyJudgeProvider) => {
            setPlan(readyPlan)
            setProvider(readyProvider)
            setJudgeProvider(readyJudgeProvider ?? null)
            setStep('preview')
          }}
        />
      )}

      {step === 'preview' && plan && provider && (
        <PreviewStep
          planId={plan.id}
          generatorProfileId={provider.id}
          judgeProfileId={judgeProvider?.id}
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
