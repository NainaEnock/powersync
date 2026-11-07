import { ArrowUpRight, ExternalLink, LayoutDashboard, Loader2, MessagesSquare, RotateCcw, Smartphone, Waves, Zap } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ApiError, useHealth, useJobState, usePoll, type Api } from '../api'
import { StatusBadge } from '../StatusBadge'
import type { ErrorCode, NeighborhoodState } from '../types'
import { AdminCode } from './AdminCode'
import { ConversationPanel } from './ConversationPanel'
import { DemandChart, useScheduleFocus } from './DemandChart'
import { HomeCards } from './HomeCards'
import { MetricTiles } from './MetricTiles'
import { Timeline } from './Timeline'
import { usePacedEvents } from './usePacedEvents'
import './dashboard.css'

type View = 'overview' | 'chat'
const viewFromUrl = (): View => {
  const v = new URLSearchParams(window.location.search).get('view')
  return v === 'chat' ? 'chat' : 'overview'
}

const FRIENDLY: Partial<Record<ErrorCode, string>> = {
  JOB_RUNNING: 'Planning is running. Try again in a moment.',
  RATE_LIMITED: 'Busy. Try again in a moment.',
  UNAUTHORIZED: 'Enter the admin code first.',
  FORBIDDEN: 'That admin code is wrong.',
}

/** Compact side summary for the Conversation tab, so the result stays in view while people read. */
function PlanSummary({ state }: { state: NeighborhoodState }) {
  return (
    <aside className="chat-side">
      <MetricTiles state={state} />
      <HomeCards state={state} />
    </aside>
  )
}

export function Dashboard({ api }: { api: Api }) {
  const health = useHealth(api)
  const state = usePoll((signal) => api.state(undefined, signal), [api])
  const s = state.data
  const needsCode = state.error?.code === 'UNAUTHORIZED' || state.error?.code === 'FORBIDDEN'
  const [codeOpen, setCodeOpen] = useState(false)
  useEffect(() => {
    if (needsCode) setCodeOpen(true)
  }, [needsCode])

  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobState(api, jobId)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pending, setPending] = useState<'coordinate' | 'reset' | 'tariff' | null>(null)
  const [armReset, setArmReset] = useState(false)
  const armTimer = useRef<number | undefined>(undefined)

  const running = s?.job_status === 'running' || job.job?.status === 'queued' || job.job?.status === 'running'
  const paced = usePacedEvents(s?.events, s?.generation)
  const [focus, setFocus] = useScheduleFocus(s)

  const [view, setViewState] = useState<View>(viewFromUrl)
  const setView = (v: View) => {
    setViewState(v)
    const url = new URL(window.location.href)
    if (v !== 'overview') url.searchParams.set('view', v)
    else url.searchParams.delete('view')
    window.history.replaceState(null, '', url.toString())
  }
  const chatUrl = (() => {
    const url = new URL(window.location.href)
    url.searchParams.set('view', 'chat')
    return url.pathname + url.search
  })()

  const run = async (kind: 'coordinate' | 'reset' | 'tariff', fn: () => Promise<unknown>) => {
    setActionError(null)
    setPending(kind)
    try {
      await fn()
      state.refresh()
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError('UNKNOWN', String(e), 0)
      setActionError(FRIENDLY[err.code] ?? err.message)
      if (err.code === 'UNAUTHORIZED' || err.code === 'FORBIDDEN') setCodeOpen(true)
    } finally {
      setPending(null)
    }
  }

  const coordinate = () =>
    run('coordinate', async () => {
      const r = await api.coordinate()
      setJobId(r.job_id)
    })

  const reset = () => {
    if (!armReset) {
      setArmReset(true)
      window.clearTimeout(armTimer.current)
      armTimer.current = window.setTimeout(() => setArmReset(false), 3000)
      return
    }
    setArmReset(false)
    void run('reset', async () => {
      await api.reset()
      setJobId(null)
    })
  }

  const setFlat = (flat: boolean) => run('tariff', () => api.setTariff(flat ? 'flat' : 'tou'))

  const failed = job.job?.status === 'failed' ? job.job.error : null

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Zap size={18} /></span>
          <span className="brand-name">PowerSync</span>
          <span className="brand-sep" />
          <span className="brand-sub">Neighborhood energy</span>
        </div>
        <div className="topbar-right">
          <StatusBadge api={api} health={health} />
          <a className="icon-btn" href="/phone" target="_blank" rel="noreferrer" title="Open the phone app">
            <Smartphone size={17} />
          </a>
          <AdminCode open={codeOpen} onOpenChange={setCodeOpen} onSaved={state.refresh} />
          <button className={`btn ${armReset ? 'btn-danger' : ''}`} onClick={reset} disabled={pending !== null}>
            <RotateCcw size={15} /> {armReset ? 'Click again to reset' : 'Reset'}
          </button>
        </div>
      </header>

      <section className="hero">
        <div>
          <div className="eyebrow">
            Neighborhood control room <span className="dot-sep">·</span>{' '}
            <span className={running ? 'eyebrow-live' : ''}>{s?.activity ?? (running ? 'Planning…' : 'Planning clock paused')}</span>
          </div>
          <h1>Good evening, neighbors.</h1>
          <p className="hero-sub">Three homes share one 15 kW street limit. Their agents work out a plan that keeps every deadline.</p>
        </div>
        <div className="hero-actions">
          <button className="btn btn-primary btn-lg" onClick={coordinate} disabled={!s || running || pending !== null}>
            {running || pending === 'coordinate' ? <Loader2 size={18} className="spin" /> : <Zap size={18} />}
            {running ? 'Coordinating…' : 'Coordinate neighborhood'}
            {!running && <ArrowUpRight size={16} />}
          </button>
        </div>
      </section>

      <div className="strip">
        <Waves size={16} className="muted" />
        <b>Three-home evening scenario</b>
        <span className="muted">{s?.tariff_label ?? '…'}</span>
        <span className="strip-sep" />
        <span className="muted">{s ? `${s.capacity_kw} kW modeled shared limit` : ''}</span>
        <span className="strip-sep" />
        <span className="muted">Simulated homes, modeled results</span>
        {s?.coordination?.source && (
          <span className={`pill ${s.coordination.source === 'live' ? 'pill-ok' : 'pill-warn'}`}>
            {s.coordination.source === 'live' ? 'Plan from live agents' : s.coordination.source === 'stub' ? 'Plan from stub agents' : 'Safe engine plan (AI unavailable)'}
          </span>
        )}
        {s && <span className="rev">Rev {s.revision}</span>}
      </div>

      {api.mode === 'sample' && (
        <div className="banner banner-warn">Sample data. These numbers come from the PRD scenario, not the live backend.</div>
      )}
      {needsCode && (
        <div className="banner banner-bad">
          {state.error?.code === 'FORBIDDEN' ? 'That admin code is wrong.' : 'Enter the admin code to view the dashboard.'}
        </div>
      )}
      {!needsCode && state.error && <div className="banner banner-bad">{state.error.message}</div>}
      {actionError && <div className="banner banner-bad">{actionError}</div>}
      {failed && <div className="banner banner-bad">Coordination failed: {failed}</div>}
      {s?.coordination?.status === 'stale_tariff' && (
        <div className="banner banner-warn">{s.coordination.reasons[0] ?? 'Plan priced under the previous tariff. Coordinate again.'}</div>
      )}

      <nav className="tabs" role="tablist" aria-label="Dashboard view">
        <button role="tab" aria-selected={view === 'overview'} className={view === 'overview' ? 'on' : ''} onClick={() => setView('overview')}>
          <LayoutDashboard size={15} /> Graph &amp; data
        </button>
        <button role="tab" aria-selected={view === 'chat'} className={view === 'chat' ? 'on' : ''} onClick={() => setView('chat')}>
          <MessagesSquare size={15} /> Conversation
          {paced.shown.length > 0 && <span className="tab-count">{paced.shown.length}</span>}
          {paced.queued > 0 && <span className="tab-live" aria-label="new messages arriving" />}
        </button>
        <a className="tab-link" href={chatUrl} target="_blank" rel="noreferrer" title="Open the conversation in its own browser tab">
          <ExternalLink size={13} /> Open conversation in a new window
        </a>
      </nav>

      {view === 'overview' && (
        <div className="dash-view">
          {s && (
            <>
              <MetricTiles state={s} focus={focus} />
              <DemandChart
                state={s}
                focus={focus}
                onFocus={setFocus}
                onFlatChange={setFlat}
                tariffBusy={pending === 'tariff' || running || api.mode === 'sample'}
              />
              <Timeline state={s} focus={focus} />
              <HomeCards state={s} focus={focus} />
            </>
          )}
        </div>
      )}
      {view === 'chat' && (
        <div className="dash-chat">
          <ConversationPanel state={s} paced={paced} needsCode={needsCode} size="full" />
          {s && <PlanSummary state={s} />}
        </div>
      )}
    </div>
  )
}
