import { useState } from 'react'
import { ProjectSetupStep } from './features/project-setup/ProjectSetupStep'
import { ModelSelectionStep } from './features/model-selection/ModelSelectionStep'
import { GoalWizardStep } from './features/goal-wizard/GoalWizardStep'
import { PlanConfirmationStep } from './features/plan-confirmation/PlanConfirmationStep'
import type { ModelProfileResponse, Project, TrainingPlanResponse } from './api/types'

type WizardStep = 'project' | 'model' | 'goal' | 'plan'

function App() {
  const [step, setStep] = useState<WizardStep>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [modelProfile, setModelProfile] = useState<ModelProfileResponse | null>(null)
  const [plan, setPlan] = useState<TrainingPlanResponse | null>(null)

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
            // Provider setup, generation runs, and export are plan_9.md's scope.
          }}
        />
      )}
    </main>
  )
}

export default App
