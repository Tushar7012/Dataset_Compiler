export interface Evidence {
  field: string
  value: string
  source: string
  detail: string
}

export type ModelSource = 'huggingface' | 'local'

export interface ModelProfile {
  source: ModelSource
  model_id: string
  architecture: string
  model_type: string
  is_causal_lm: boolean
  is_chat_model: boolean
  chat_template_found: boolean
  context_length: number
  modalities: string[]
  evidence: Evidence[]
  confidence: number
}

export interface ModelProfileResponse extends ModelProfile {
  id: string
}

export interface Project {
  id: string
  name: string
  created_at: string
}

export interface Source {
  id: string
  filename: string
  source_hash: string
}

export type TrainingGoal =
  | 'domain_adaptation'
  | 'single_turn_instruction'
  | 'multi_turn_conversation'
  | 'preference_alignment'

export interface TrainingIntentInput {
  goal: TrainingGoal
  target_rows: number
  generator_profile_id?: string
  judge_profile_id?: string
  objective_override?: TrainingObjective
}

export type TrainingObjective = 'cpt' | 'sft_prompt_completion' | 'sft_conversation' | 'dpo'

export interface TrainingPlan {
  objective: TrainingObjective
  canonical_schema: string
  target_rows: number
  examples_per_chunk: number
  generator_profile_id: string | null
  judge_profile_id: string | null
  required_validators: string[]
  evidence: Evidence[]
  confidence: number
  plan_hash: string
}

export interface TrainingPlanResponse extends TrainingPlan {
  id: string
}

export interface PlanApproval {
  id: string
  approved_at: string
}

export interface ProviderProfileInput {
  name: string
  base_url: string
  model: string
  api_key?: string
}

export interface ProviderProfile {
  id: string
  name: string
}

export type RunStatus = 'pending' | 'running' | 'cancel_requested' | 'cancelled' | 'completed' | 'failed'

export interface RunSummary {
  id: string
  status: RunStatus
  completed_rows: number
  total_rows: number
  is_preview: boolean
  assurance_level: string | null
}

export interface RunCreated {
  id: string
  status: RunStatus
  is_preview: boolean
}

export interface RunRecordsResponse {
  canonical_schema: string | null
  records: Record<string, unknown>[]
  total_accepted: number
}

export interface SchemaDetection {
  schema_name: string | null
  confidence: number
  matched_keys: string[]
  columns: string[]
}

export interface NormalizePreviewResponse {
  schema_name: string
  preview: Record<string, unknown>[]
  total_rows: number
}

export interface ConfirmMappingResponse {
  schema_name: string
  total_rows: number
}

export interface RowEstimateResponse {
  total_rows: number
  truncated: boolean
  capped_at: number
}
