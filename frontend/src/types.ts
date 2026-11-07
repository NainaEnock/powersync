// Mirrors the canonical schemas in docs/PRD.md §10.
// DRAFT until D merges docs/contract.md at G2. When the contract lands,
// D's field names win and this file is updated to match exactly.

export type HomeId = 'A' | 'B' | 'C'
export const HOME_IDS: HomeId[] = ['A', 'B', 'C']

export interface Task {
  id: string
  home_id: HomeId
  name: string
  power_kw: number
  duration_slots: number
  earliest_slot: number
  deadline_slot: number
  preferred_start_slot: number
  interruptible: boolean
}

export interface ScheduleEntry {
  task_id: string
  home_id: HomeId
  start_slot: number
  duration_slots: number
  power_kw: number
}

export interface HomeMetrics {
  energy_kwh: number
  variable_cost_usd: number
  peak_kw: number
}

export interface Metrics {
  energy_kwh: number
  variable_cost_usd: number
  peak_kw: number
  missed_deadlines: number
  capacity_violations: number
  tasks_completed: number
  tasks_total: number
  per_home: Partial<Record<HomeId, HomeMetrics>>
}

export interface Home {
  id: HomeId
  name: string
  color: string
  preferences: Record<string, unknown>
}

export type Participant =
  | `resident_${HomeId}`
  | `agent_${HomeId}`
  | 'coordinator'
  | 'all_agents'
  | 'powersync-energy'
  | 'validator'
  | 'backend'

export type EventType =
  | 'request'
  | 'proposal'
  | 'review'
  | 'counteroffer'
  | 'tool_call'
  | 'tool_result'
  | 'validation'
  | 'commit'
  | 'error'
  | 'info'

export interface AgentEvent {
  id: string
  sequence: number
  job_id: string | null
  sender: Participant | string
  recipient: Participant | string
  type: EventType
  text: string
  round: number | null
  proposal_id: string | null
  reply_to_event_id: string | null
  source: 'model' | 'system_template'
  // home_views is stripped by the server before sending; never rely on it client-side.
  data: Record<string, string | number | boolean | null> | null
  timestamp: string
  revision: number
}

export type EditableField = 'deadline_slot' | 'earliest_slot' | 'preferred_start_slot'

export interface ProposedEdit {
  task_id: string
  field: EditableField
  old_value: number
  new_value: number
  old_time: string
  new_time: string
}

export interface PendingChange {
  id: string
  home_id: HomeId
  proposed_edits: { edits: ProposedEdit[] }
  explanation: string
  prepared_revision: number
  request_id: string
  job_id: string
  feasible: boolean
  infeasible_reasons: string[]
  status: string
  created_at: string
}

export type ScheduleKind = 'baseline' | 'independent' | 'coordinated'
export type TariffMode = 'tou' | 'flat'

export interface Coordination {
  status: string
  explanation: string | null
  reasons: string[]
  job_id: string | null
  source: 'live' | 'stub' | 'deterministic_fallback' | null
}

export interface NeighborhoodState {
  revision: number
  generation: number
  requirements_version: number
  scenario_id: string
  horizon_start: string
  slot_minutes: number
  capacity_kw: number
  activity: string | null
  tariff_mode: TariffMode
  tariff_label: string
  homes: Home[]
  tasks: Task[]
  tariff_usd_per_kwh: number[]
  background_kw_by_home: Partial<Record<HomeId, number>>
  baseline_schedule: ScheduleEntry[]
  independent_schedule: ScheduleEntry[]
  coordinated_schedule: ScheduleEntry[] | null
  metrics: Partial<Record<ScheduleKind, Metrics | null>>
  metrics_flat_rate: Partial<Record<ScheduleKind, Metrics | null>>
  demand_kw: Partial<Record<ScheduleKind, number[] | null>>
  coordination: Coordination | null
  events: AgentEvent[]
  events_hidden: boolean
  pending_changes: PendingChange[]
  job_status: string | null
  data_mode: 'synthetic'
  ai_mode: 'live' | 'unavailable' | 'replay'
  agent_impl: { interpret: 'live' | 'stub'; coordinate: 'live' | 'stub' }
}

export type JobStatus = 'queued' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'

export interface Job {
  id: string
  kind: 'message' | 'action' | 'coordinate'
  home_id: HomeId | null
  request_id: string | null
  status: JobStatus
  stage: string | null
  result: { outcome: string; message: string; [k: string]: unknown } | null
  error: string | null
  created_at: string
  updated_at: string
}

export type AuthMode = 'dev-open' | 'partial' | 'enforced'

export interface Health {
  status: string
  version: string
  scenario_id: string
  revision: number
  generation: number
  auth_mode: AuthMode
  agent_impl: { interpret: 'live' | 'stub'; coordinate: 'live' | 'stub' }
  openrouter_configured: boolean
  model: string | null
}

export interface JobAccepted {
  job_id: string
  status: JobStatus
  accepted_revision: number
  duplicate?: boolean
}

export type ErrorCode =
  | 'BAD_REQUEST'
  | 'UNKNOWN_HOME'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'STALE_REVISION'
  | 'JOB_RUNNING'
  | 'PAYLOAD_TOO_LARGE'
  | 'RATE_LIMITED'
  // Client-side codes, never sent by the server:
  | 'BACKEND_DOWN'
  | 'NETWORK'
  | 'UNKNOWN'
