// The one API client for phone and dashboard (PRD §11).
// - Relative /api URLs only (works via the Vite proxy in dev and same-origin in the demo).
// - Tokens go in the Authorization header only. Never in URLs, query strings, or logs.
// - Every request is cache: 'no-store'.

import { useCallback, useEffect, useRef, useState } from 'react'
import { SAMPLE_STATE, sampleHomeState } from './fixtures'
import type {
  ApplianceCatalog,
  ErrorCode,
  Health,
  HomeId,
  Job,
  JobAccepted,
  NeighborhoodState,
  TariffMode,
} from './types'

export const POLL_MS = 1000

// ---------- data mode ----------

export type DataMode = 'live' | 'sample'

/** Dev server starts in sample data; built app starts live. ?mode=live|fixture overrides. */
export function getDataMode(): DataMode {
  const q = new URLSearchParams(window.location.search).get('mode')
  if (q === 'live') return 'live'
  if (q === 'fixture') return 'sample'
  return import.meta.env.DEV ? 'sample' : 'live'
}

// ---------- tokens (local storage, per role) ----------

const tokenKey = (role: HomeId | 'admin') => `powersync.token.${role}`

export function getToken(role: HomeId | 'admin'): string {
  try {
    return localStorage.getItem(tokenKey(role)) ?? ''
  } catch {
    return ''
  }
}

export function setToken(role: HomeId | 'admin', token: string): void {
  try {
    if (token) localStorage.setItem(tokenKey(role), token)
    else localStorage.removeItem(tokenKey(role))
  } catch {
    /* storage unavailable: token lives for this page only */
  }
}

// ---------- errors ----------

export class ApiError extends Error {
  readonly code: ErrorCode
  readonly status: number
  constructor(code: ErrorCode, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

export const BACKEND_DOWN_MESSAGE = 'Backend not running on port 8000'

async function request<T>(
  path: string,
  opts: { method?: 'GET' | 'POST'; body?: unknown; token?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`

  let res: Response
  try {
    res = await fetch(path, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: 'no-store',
      signal: opts.signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(
      import.meta.env.DEV ? 'BACKEND_DOWN' : 'NETWORK',
      import.meta.env.DEV ? BACKEND_DOWN_MESSAGE : 'Cannot reach the PowerSync server',
      0,
    )
  }

  const text = await res.text()
  let json: unknown = null
  try {
    json = text ? JSON.parse(text) : null
  } catch {
    json = null
  }

  if (!res.ok) {
    const err = (json as { error?: { code?: string; message?: string } } | null)?.error
    if (err?.code) throw new ApiError(err.code as ErrorCode, err.message ?? err.code, res.status)
    // The Vite proxy answers 500/502/504 with a non-JSON body when FastAPI isn't up.
    if (import.meta.env.DEV && res.status >= 500) {
      throw new ApiError('BACKEND_DOWN', BACKEND_DOWN_MESSAGE, res.status)
    }
    throw new ApiError('UNKNOWN', `HTTP ${res.status}`, res.status)
  }
  return json as T
}

// ---------- request ids ----------

export function newRequestId(prefix: string): string {
  const id =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return `${prefix}-${id}`
}

// ---------- endpoints ----------

export interface Api {
  mode: DataMode
  health(): Promise<Health>
  /** Dashboard view when home is omitted (admin token), household view with ?home=. */
  state(home?: HomeId, signal?: AbortSignal): Promise<NeighborhoodState>
  message(home: HomeId, text: string, expectedRevision: number, requestId?: string): Promise<JobAccepted>
  action(
    home: HomeId,
    action: 'confirm_change' | 'reject_change',
    pendingChangeId: string,
    expectedRevision: number,
    requestId?: string,
  ): Promise<JobAccepted>
  coordinate(): Promise<JobAccepted>
  setTariff(mode: TariffMode): Promise<{ revision: number; tariff_mode: TariffMode }>
  reset(): Promise<unknown>
  job(id: string, signal?: AbortSignal): Promise<Job>
  applianceCatalog(): Promise<ApplianceCatalog>
  addAppliance(home: HomeId, kind: string, deadlineSlot?: number): Promise<{ revision: number; task_id: string }>
  removeAppliance(home: HomeId, taskId: string): Promise<{ revision: number; task_id: string }>
}

const SAMPLE_REJECT = () =>
  Promise.reject(new ApiError('BAD_REQUEST', 'Sample data mode: actions need the live backend (?mode=live)', 0))

export function createApi(mode: DataMode = getDataMode()): Api {
  const admin = () => getToken('admin')
  const homeTok = (h: HomeId) => getToken(h)

  if (mode === 'sample') {
    return {
      mode,
      health: () => request<Health>('/api/health'),
      state: async (home) => (home ? sampleHomeState(home) : SAMPLE_STATE),
      message: SAMPLE_REJECT,
      action: SAMPLE_REJECT,
      coordinate: SAMPLE_REJECT,
      setTariff: SAMPLE_REJECT,
      reset: SAMPLE_REJECT,
      job: SAMPLE_REJECT,
      applianceCatalog: () => request<ApplianceCatalog>('/api/appliances/catalog'),
      addAppliance: SAMPLE_REJECT,
      removeAppliance: SAMPLE_REJECT,
    }
  }

  return {
    mode,
    health: () => request<Health>('/api/health'),
    state: (home, signal) =>
      home
        ? request<NeighborhoodState>(`/api/state?home=${home}`, { token: homeTok(home) || admin(), signal })
        : request<NeighborhoodState>('/api/state', { token: admin(), signal }),
    message: (home, text, expected_revision, request_id = newRequestId(`phone-${home.toLowerCase()}`)) =>
      request<JobAccepted>('/api/message', {
        method: 'POST',
        token: homeTok(home),
        body: { home_id: home, text, request_id, expected_revision },
      }),
    action: (home, action, pending_change_id, expected_revision, request_id = newRequestId(`phone-${home.toLowerCase()}`)) =>
      request<JobAccepted>('/api/action', {
        method: 'POST',
        token: homeTok(home),
        body: { home_id: home, action, pending_change_id, expected_revision, request_id },
      }),
    coordinate: () => request<JobAccepted>('/api/coordinate', { method: 'POST', token: admin(), body: {} }),
    setTariff: (tariff_mode) =>
      request('/api/tariff', { method: 'POST', token: admin(), body: { tariff_mode } }),
    reset: () => request('/api/reset', { method: 'POST', token: admin(), body: {} }),
    job: (id, signal) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`, { signal }),
    applianceCatalog: () => request<ApplianceCatalog>('/api/appliances/catalog'),
    addAppliance: (home, kind, deadline_slot) =>
      request('/api/appliances', {
        method: 'POST',
        token: homeTok(home),
        body: { home_id: home, action: 'add', kind, ...(deadline_slot === undefined ? {} : { deadline_slot }) },
      }),
    removeAppliance: (home, task_id) =>
      request('/api/appliances', { method: 'POST', token: homeTok(home), body: { home_id: home, action: 'remove', task_id } }),
  }
}

// ---------- polling hooks ----------

export interface Polled<T> {
  data: T | null
  error: ApiError | null
  /** Time of the last successful response. */
  updatedAt: number | null
  refresh: () => void
}

/**
 * Poll `fetcher` every POLL_MS while the page is visible. Stops on unmount.
 * Keeps the last good data when a poll fails, so the old plan stays on screen.
 */
export function usePoll<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: unknown[], intervalMs = POLL_MS): Polled<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [tick, setTick] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    let ctrl: AbortController | undefined

    const run = async () => {
      if (cancelled) return
      if (document.visibilityState === 'visible') {
        ctrl = new AbortController()
        try {
          const d = await fetcherRef.current(ctrl.signal)
          if (!cancelled) {
            setData(d)
            setError(null)
            setUpdatedAt(Date.now())
          }
        } catch (e) {
          if (!cancelled && (e as Error).name !== 'AbortError') {
            setError(e instanceof ApiError ? e : new ApiError('UNKNOWN', String(e), 0))
          }
        }
      }
      if (!cancelled) timer = window.setTimeout(run, intervalMs)
    }

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        window.clearTimeout(timer)
        void run()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    void run()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      ctrl?.abort()
      document.removeEventListener('visibilitychange', onVisible)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, intervalMs])

  const refresh = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, updatedAt, refresh }
}

const JOB_STOP: Job['status'][] = ['completed', 'failed', 'awaiting_confirmation']

export interface JobPoll {
  job: Job | null
  /** Last poll error. NOT_FOUND means the job is gone (e.g. after a reset) and polling has stopped. */
  error: ApiError | null
}

/** Poll one job until it completes, fails, needs confirmation, or 404s. Pass null to stop. */
export function useJobState(api: Api, jobId: string | null): JobPoll {
  const [poll, setPoll] = useState<JobPoll>({ job: null, error: null })
  useEffect(() => {
    setPoll({ job: null, error: null })
    if (!jobId) return
    let cancelled = false
    let timer: number | undefined
    const ctrl = new AbortController()
    const run = async () => {
      try {
        const j = await api.job(jobId, ctrl.signal)
        if (cancelled) return
        setPoll({ job: j, error: null })
        if (JOB_STOP.includes(j.status)) return
      } catch (e) {
        if (cancelled || (e as Error).name === 'AbortError') return
        const err = e instanceof ApiError ? e : new ApiError('UNKNOWN', String(e), 0)
        setPoll((p) => ({ job: p.job, error: err }))
        if (err.code === 'NOT_FOUND') return
      }
      timer = window.setTimeout(run, POLL_MS)
    }
    void run()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      ctrl.abort()
    }
  }, [api, jobId])
  return poll
}

/** Same as useJobState but returns only the job (kept for existing callers). */
export function useJob(api: Api, jobId: string | null): Job | null {
  return useJobState(api, jobId).job
}

/** Health, polled more slowly. Drives the status badge. */
export function useHealth(api: Api): Polled<Health> {
  return usePoll((signal) => request<Health>('/api/health', { signal }), [api], 3000)
}
