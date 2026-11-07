// Request → job → confirmation → applied flow for one phone (PRD §11, §16).
// Uses B's api.message / api.action and useJob for job polling.
import { useCallback, useEffect, useState } from 'react';
import { ApiError, useJob, type Api } from '../api';
import type { HomeId, NeighborhoodState, PendingChange } from '../types';

export type FlowPhase =
  | 'idle'
  | 'queued'
  | 'interpreting'
  | 'confirm'
  | 'planning'
  | 'applied'
  | 'rejected'
  | 'infeasible'
  | 'clarify'
  | 'no_change'
  | 'failed';

export interface FlowState {
  phase: FlowPhase;
  jobId: string | null;
  kind: 'message' | 'action' | null;
  /** Dismissing an infeasible result: finish silently instead of announcing "rejected". */
  quiet: boolean;
  message: string | null;
  error: ApiError | null;
}

const IDLE: FlowState = { phase: 'idle', jobId: null, kind: null, quiet: false, message: null, error: null };

export function errorText(err: ApiError): string {
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
    default:
      return err.message || 'Something went wrong.';
  }
}

function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError('UNKNOWN', e instanceof Error ? e.message : String(e), 0);
}

// Job errors arrive as "CODE: message" (contract §2). Show residents plain English, never a code.
function jobErrorText(error: string | null, fallback?: string): string {
  const code = error?.split(':', 1)[0]?.trim() ?? '';
  if (code === 'RESET') return 'The demo was reset, so that request was cancelled. Please send it again.';
  if (code === 'BAD_MODEL_OUTPUT')
    return "Your agent couldn't understand that right now, so nothing was changed.";
  if (fallback) return fallback;
  if (error) {
    const idx = error.indexOf(':');
    return idx >= 0 ? error.slice(idx + 1).trim() : error;
  }
  return 'The request failed. Nothing was changed.';
}

export function usePhoneFlow(
  api: Api,
  homeId: HomeId | null,
  state: NeighborhoodState | null,
  refresh: () => void,
) {
  const [flow, setFlow] = useState<FlowState>(IDLE);
  const job = useJob(api, flow.jobId);
  const generation = state?.generation;

  // A reset (generation bump) or household switch drops any in-flight flow.
  useEffect(() => {
    setFlow(IDLE);
  }, [generation, homeId]);

  // Follow the job B's useJob is polling.
  useEffect(() => {
    if (!job || job.id !== flow.jobId) return;
    const kind = flow.kind ?? 'message';
    if (job.status === 'queued' || job.status === 'running') {
      const phase = job.status === 'queued' ? 'queued' : kind === 'message' ? 'interpreting' : 'planning';
      setFlow((f) => (f.phase === phase && f.message === job.stage ? f : { ...f, phase, message: job.stage }));
      return;
    }
    // Terminal or confirmation: pull fresh state so the plan / pending change matches.
    refresh();
    // Outcomes (C, G3): proposed_change, infeasible, needs_clarification, no_change, error,
    // plus applied / rejected for confirm and reject jobs. result.message is code-written text.
    const outcome = job.result?.outcome ?? '';
    const msg = job.result?.message ?? null;
    setFlow((f) => {
      if (f.jobId !== job.id) return f;
      const base = { ...IDLE, jobId: job.id, kind };
      if (job.status === 'failed') return { ...base, phase: 'failed', message: jobErrorText(job.error) };
      if (f.quiet) return IDLE;
      if (job.status === 'awaiting_confirmation' || outcome === 'proposed_change')
        return { ...base, phase: 'confirm', message: msg };
      if (outcome.includes('infeasible')) return { ...base, phase: 'infeasible', message: msg };
      if (outcome === 'needs_clarification') return { ...base, phase: 'clarify', message: msg };
      if (outcome === 'no_change') return { ...base, phase: 'no_change', message: msg };
      if (outcome === 'error')
        return { ...base, phase: 'failed', message: msg ?? "Your agent couldn't understand that right now, so nothing was changed." };
      if (kind === 'action' && outcome.includes('reject'))
        return { ...base, phase: 'rejected', message: msg ?? 'Change rejected. Your plan stays the same.' };
      if (kind === 'action') return { ...base, phase: 'applied', message: msg };
      // A message job with an outcome we don't know: show its text, don't claim success.
      return { ...base, phase: 'no_change', message: msg ?? 'Your agent finished. Nothing was changed.' };
    });
  }, [job, flow.jobId, flow.kind, refresh]);

  const busy = flow.phase === 'queued' || flow.phase === 'interpreting' || flow.phase === 'planning';

  const handleError = useCallback(
    (e: unknown) => {
      const err = toApiError(e);
      if (err.code === 'STALE_REVISION' || err.code === 'NOT_FOUND') refresh();
      setFlow({ ...IDLE, message: errorText(err), error: err });
    },
    [refresh],
  );

  /** Returns true when the request was accepted (so the text box can clear). */
  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const trimmed = text.trim();
      if (!homeId || !state || busy || !trimmed) return false;
      setFlow({ ...IDLE, phase: 'queued', kind: 'message' });
      try {
        const res = await api.message(homeId, trimmed, state.revision);
        setFlow((f) => ({ ...f, jobId: res.job_id }));
        return true;
      } catch (e) {
        handleError(e);
        return false;
      }
    },
    [api, busy, handleError, homeId, state],
  );

  const act = useCallback(
    async (change: PendingChange, action: 'confirm_change' | 'reject_change') => {
      if (!homeId || !state || busy) return;
      const quiet = !change.feasible;
      setFlow({ ...IDLE, phase: action === 'confirm_change' ? 'planning' : 'queued', kind: 'action', quiet });
      try {
        const res = await api.action(homeId, action, change.id, state.revision);
        setFlow((f) => ({ ...f, jobId: res.job_id }));
      } catch (e) {
        handleError(e);
      }
    },
    [api, busy, handleError, homeId, state],
  );

  const dismiss = useCallback(() => setFlow(IDLE), []);

  return { flow, busy, send, act, dismiss };
}
