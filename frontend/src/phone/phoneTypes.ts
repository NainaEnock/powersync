// Shapes the phone app reads. Field names follow PRD §10 and §11 exactly.
// When B's frontend/src/types.ts lands, these should be replaced by imports
// from there (or types.ts should re-export compatible types). Proposed
// contract for A + B + D: see frontend/src/phone/CONTRACT-PROPOSAL.md.

export type HomeId = 'A' | 'B' | 'C';
export const HOME_IDS: HomeId[] = ['A', 'B', 'C'];

export interface Home {
  id: HomeId;
  name: string;
  color: string;
  preferences?: unknown;
}

export interface Task {
  id: string;
  home_id: HomeId;
  name: string;
  power_kw: number;
  duration_slots: number;
  earliest_slot: number;
  deadline_slot: number;
  preferred_start_slot: number;
  interruptible: boolean;
}

export interface ScheduleEntry {
  task_id: string;
  home_id: HomeId;
  start_slot: number;
  duration_slots: number;
  power_kw: number;
}

export interface HomeMetrics {
  energy_kwh: number;
  variable_cost_usd: number;
  peak_kw: number;
}

export interface Metrics {
  energy_kwh: number;
  variable_cost_usd: number;
  peak_kw: number;
  missed_deadlines: number;
  capacity_violations: number;
  tasks_completed: number;
  tasks_total: number;
  per_home: Partial<Record<HomeId, HomeMetrics>>;
}

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
  | 'info';

export interface AgentEvent {
  id: string;
  sequence: number;
  job_id: string | null;
  sender: string;
  recipient: string;
  type: EventType;
  text: string;
  round?: number | null;
  proposal_id?: string | null;
  reply_to_event_id?: string | null;
  source: 'model' | 'system_template';
  data?: Record<string, unknown> | null;
  timestamp: string;
  revision: number;
}

export interface ProposedEdit {
  task_id: string;
  field: 'deadline_slot' | 'earliest_slot' | 'preferred_start_slot';
  old_value: number;
  new_value: number;
  old_time: string;
  new_time: string;
}

export interface PendingChange {
  id: string;
  home_id: HomeId;
  proposed_edits: { edits: ProposedEdit[] };
  explanation: string;
  prepared_revision: number;
  request_id: string;
  job_id: string;
  feasible: boolean;
  infeasible_reasons: string[];
  status: string; // 'pending' | 'confirmed' | 'rejected' | 'stale' ...
  created_at: string;
}

export type JobStatus = 'queued' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed';

export interface Job {
  id: string;
  kind: 'message' | 'action' | 'coordinate';
  home_id: HomeId | null;
  request_id: string | null;
  status: JobStatus;
  stage?: string | null;
  result?: { outcome: string; message: string; [k: string]: unknown } | null;
  error?: string | null; // "CODE: message"
  created_at: string;
  updated_at: string;
}

/** GET /api/state?home=X — the household (private) view, PRD §11.3. */
export interface HouseholdState {
  revision: number;
  generation: number;
  scenario_id?: string;
  horizon_start: string;
  slot_minutes: number;
  capacity_kw: number;
  activity: string | null;
  tariff_mode: 'tou' | 'flat';
  tariff_label: string;
  homes: Home[];
  tasks: Task[];
  baseline_schedule: ScheduleEntry[];
  independent_schedule?: ScheduleEntry[];
  coordinated_schedule: ScheduleEntry[] | null;
  metrics: {
    baseline: Metrics | null;
    independent?: Metrics | null;
    coordinated: Metrics | null;
  };
  coordination?: {
    status: string;
    explanation?: string | null;
    reasons?: string[];
    job_id?: string | null;
    source?: 'live' | 'stub' | 'deterministic_fallback';
  } | null;
  events: AgentEvent[];
  pending_changes: PendingChange[];
  job_status?: unknown;
  data_mode?: string;
  ai_mode?: 'live' | 'unavailable' | 'replay';
}

export interface MessageRequest {
  home_id: HomeId;
  text: string;
  request_id: string;
  expected_revision: number;
}

export interface ActionRequest {
  home_id: HomeId;
  action: 'confirm_change' | 'reject_change';
  pending_change_id: string;
  request_id: string;
  expected_revision: number;
}

export interface JobAccepted {
  job_id: string;
  status: JobStatus;
  accepted_revision: number;
  duplicate?: boolean;
}

/** Codes from PRD §11.2 plus BACKEND_DOWN for "proxy/backend unreachable". */
export type ApiErrorCode =
  | 'BAD_REQUEST'
  | 'UNKNOWN_HOME'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'STALE_REVISION'
  | 'JOB_RUNNING'
  | 'PAYLOAD_TOO_LARGE'
  | 'RATE_LIMITED'
  | 'BACKEND_DOWN'
  | string;

/** Anything api methods throw should look like this (B's adapter). */
export interface ApiErrorLike {
  status: number;
  code: ApiErrorCode;
  message: string;
}

export function isApiError(e: unknown): e is ApiErrorLike {
  return typeof e === 'object' && e !== null && 'code' in e && 'message' in e;
}

export type DataMode = 'live' | 'sample';
export type Connection = 'connected' | 'connecting' | 'backend_down' | 'error';
export type AuthMode = 'dev-open' | 'partial' | 'enforced' | 'unknown';

/**
 * What the phone needs from B's api adapter. B's adapter polls
 * GET /api/state?home=<homeId> every second while visible and passes the
 * result in as `state`; these methods do the rest.
 */
export interface PhoneApi {
  dataMode: DataMode;
  connection: Connection;
  authMode: AuthMode;
  /** Last error from state polling (e.g. UNAUTHORIZED / FORBIDDEN), or null. */
  stateError: ApiErrorLike | null;
  sendMessage(req: MessageRequest): Promise<JobAccepted>;
  sendAction(req: ActionRequest): Promise<JobAccepted>;
  getJob(jobId: string): Promise<Job>;
  /** Re-fetch state now (used after 409 STALE_REVISION). */
  refresh(): Promise<void>;
  /** Save this home's code; adapter sends it as Authorization: Bearer. */
  setToken(home: HomeId, token: string): void;
  hasToken(home: HomeId): boolean;
  /** Switch household (null = show picker). Updates storage + URL pin. */
  setHome(home: HomeId | null): void;
}

export interface PhoneAppProps {
  homeId: HomeId | null;
  state: HouseholdState | null;
  api: PhoneApi;
}
