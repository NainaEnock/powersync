// Request → job → confirmation → applied flow for one phone (PRD §11, §16).
import { useCallback, useEffect, useRef, useState } from 'react';
import { newRequestId } from './format';
import {
  isApiError,
  type ApiErrorLike,
  type HomeId,
  type HouseholdState,
  type Job,
  type PendingChange,
  type PhoneApi,
} from './phoneTypes';

export type FlowPhase =
  | 'idle'
  | 'queued'
  | 'interpreting'
  | 'confirm'
  | 'planning'
  | 'applied'
  | 'rejected'
  | 'infeasible'
  | 'failed';

export interface FlowState {
  phase: FlowPhase;
  jobId: string | null;
  kind: 'message' | 'action' | null;
  stage: string | null;
  /** Plain-English line for the status card. */
  message: string | null;
  /** Error that the screen should react to (token entry, forbidden, etc). */
  error: ApiErrorLike | null;
}

const IDLE: FlowState = { phase: 'idle', jobId: null, kind: null, stage: null, message: null, error: null };
const POLL_MS = 1000;
const TERMINAL: Job['status'][] = ['completed', 'failed', 'awaiting_confirmation'];

export function errorText(err: ApiErrorLike): string {
  switch (err.code) {
    case 'UNAUTHORIZED':
      return 'This phone needs its household code.';
    case 'FORBIDDEN':
      return "That code isn't for this home.";
    case 'STALE_REVISION':
      return 'The plan changed while you were typing. Here is the current plan. Send your request again.';
    case 'JOB_RUNNING':
      return 'Planning is running. Try again in a moment.';
    case 'RATE_LIMITED':
      return 'Busy, retry in a moment.';
    case 'NOT_FOUND':
      return 'That request was lost, maybe because the demo was reset. Please send it again.';
    case 'PAYLOAD_TOO_LARGE':
      return 'That message is too long. Try something shorter.';
    case 'BACKEND_DOWN':
      return 'Backend not running on port 8000.';
    default:
      return err.message || 'Something went wrong.';
  }
}

function toApiError(e: unknown): ApiErrorLike {
  if (isApiError(e)) return e;
  return { status: 0, code: 'BACKEND_DOWN', message: e instanceof Error ? e.message : String(e) };
}

function phaseForRunning(kind: 'message' | 'action', job: Job): FlowPhase {
  if (job.status === 'queued') return 'queued';
  return kind === 'message' ? 'interpreting' : 'planning';
}

function jobErrorText(job: Job): string {
  if (job.error) {
    const idx = job.error.indexOf(':');
    return idx >= 0 ? job.error.slice(idx + 1).trim() : job.error;
  }
  return job.result?.message ?? 'The request failed.';
}

export function usePhoneFlow(homeId: HomeId | null, state: HouseholdState | null, api: PhoneApi) {
  const [flow, setFlow] = useState<FlowState>(IDLE);
  const timer = useRef<number | null>(null);
  const alive = useRef(true);
  const generation = state?.generation;

  const stopPolling = useCallback(() => {
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      stopPolling();
    };
  }, [stopPolling]);

  // A reset (generation bump) or household switch drops any in-flight flow.
  useEffect(() => {
    stopPolling();
    setFlow(IDLE);
  }, [generation, homeId, stopPolling]);

  const poll = useCallback(
    (jobId: string, kind: 'message' | 'action', quiet = false) => {
      const tick = async () => {
        if (!alive.current) return;
        let job: Job;
        try {
          job = await api.getJob(jobId);
        } catch (e) {
          const err = toApiError(e);
          if (err.code === 'NOT_FOUND') {
            setFlow({ ...IDLE, phase: 'failed', message: errorText(err), error: err });
            return;
          }
          // Transient: keep the current phase, show the problem, keep polling.
          setFlow((f) => ({ ...f, error: err }));
          timer.current = window.setTimeout(tick, POLL_MS * 2);
          return;
        }
        if (!alive.current) return;
        if (!TERMINAL.includes(job.status)) {
          setFlow((f) => ({ ...f, phase: phaseForRunning(kind, job), stage: job.stage ?? null, error: null }));
          timer.current = window.setTimeout(tick, POLL_MS);
          return;
        }
        // Make sure the plan/pending change on screen matches the job result.
        api.refresh().catch(() => undefined);
        if (quiet && job.status !== 'failed') {
          setFlow(IDLE);
          return;
        }
        const outcome = job.result?.outcome ?? '';
        const msg = job.result?.message ?? null;
        if (job.status === 'failed') {
          setFlow({ ...IDLE, phase: 'failed', jobId, kind, message: jobErrorText(job) });
        } else if (job.status === 'awaiting_confirmation') {
          setFlow({ ...IDLE, phase: 'confirm', jobId, kind, message: msg });
        } else if (outcome === 'infeasible' || outcome.includes('infeasible')) {
          setFlow({ ...IDLE, phase: 'infeasible', jobId, kind, message: msg });
        } else if (kind === 'action' && outcome.includes('reject')) {
          setFlow({ ...IDLE, phase: 'rejected', jobId, kind, message: msg ?? 'Change rejected. Your plan stays the same.' });
        } else {
          setFlow({ ...IDLE, phase: 'applied', jobId, kind, message: msg });
        }
      };
      stopPolling();
      timer.current = window.setTimeout(tick, 300);
    },
    [api, stopPolling],
  );

  const busy = flow.phase === 'queued' || flow.phase === 'interpreting' || flow.phase === 'planning';

  const send = useCallback(
    async (text: string): Promise<boolean> => {
      if (!homeId || !state || busy) return false;
      const trimmed = text.trim();
      if (!trimmed) return false;
      setFlow({ ...IDLE, phase: 'queued', kind: 'message', message: null });
      try {
        const res = await api.sendMessage({
          home_id: homeId,
          text: trimmed,
          request_id: newRequestId(homeId),
          expected_revision: state.revision,
        });
        if (!alive.current) return true;
        setFlow((f) => ({ ...f, jobId: res.job_id }));
        poll(res.job_id, 'message');
        return true;
      } catch (e) {
        const err = toApiError(e);
        if (err.code === 'STALE_REVISION') api.refresh().catch(() => undefined);
        setFlow({ ...IDLE, phase: 'idle', message: errorText(err), error: err });
        return false;
      }
    },
    [api, busy, homeId, poll, state],
  );

  const act = useCallback(
    async (change: PendingChange, action: 'confirm_change' | 'reject_change') => {
      // Dismissing an infeasible result is just "OK", not a rejection to announce.
      const quiet = !change.feasible;
      if (!homeId || !state || busy) return;
      setFlow({ ...IDLE, phase: action === 'confirm_change' ? 'planning' : 'queued', kind: 'action' });
      try {
        const res = await api.sendAction({
          home_id: homeId,
          action,
          pending_change_id: change.id,
          request_id: newRequestId(homeId),
          expected_revision: state.revision,
        });
        if (!alive.current) return;
        setFlow((f) => ({ ...f, jobId: res.job_id }));
        poll(res.job_id, 'action', quiet);
      } catch (e) {
        const err = toApiError(e);
        if (err.code === 'STALE_REVISION' || err.code === 'NOT_FOUND') api.refresh().catch(() => undefined);
        setFlow({ ...IDLE, phase: 'idle', message: errorText(err), error: err });
      }
    },
    [api, busy, homeId, poll, state],
  );

  const dismiss = useCallback(() => {
    stopPolling();
    setFlow(IDLE);
  }, [stopPolling]);

  return { flow, busy, send, act, dismiss };
}
