// Live agent conversation (PRD §12.4). Shows only what the backend stored: no invented text.
// Sort by sequence, group by round, tag plans, activity line, Follow and Pause, hidden state.
import { Check, CircleAlert, Lock, Pause, Play, ArrowDownToLine, Wrench, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { AgentEvent, Home, NeighborhoodState } from '../types'

const planName = (pid: string | null) => {
  const m = pid?.match(/^P-(\d+)$/)
  return m ? `Plan ${m[1]}` : null
}

function homeOf(who: string): string | null {
  const m = who.match(/_(A|B|C)$/)
  return m ? m[1] : null
}

function who(p: string): string {
  const h = homeOf(p)
  if (p.startsWith('agent_') && h) return `Home ${h}'s agent`
  if (p.startsWith('resident_') && h) return `Home ${h} resident`
  switch (p) {
    case 'coordinator': return 'Coordinator'
    case 'all_agents': return 'everyone'
    case 'powersync-energy': return 'Energy tools (MCP)'
    case 'validator': return 'Validator'
    case 'backend': return 'PowerSync'
    default: return p
  }
}

const STANCE: Record<string, { label: string; cls: string; Icon: typeof Check }> = {
  accept: { label: 'Accepts', cls: 'ok', Icon: Check },
  agree: { label: 'Agrees', cls: 'ok', Icon: Check },
  object: { label: 'Objects', cls: 'warn', Icon: CircleAlert },
  decline: { label: 'Declines', cls: 'bad', Icon: X },
}

type Group = { key: string; title: string; events: AgentEvent[] }

function groupByRound(events: AgentEvent[]): Group[] {
  const groups: Group[] = []
  let last: Group | null = null
  for (const e of events) {
    // Events without a round (validation, commit, resident requests) form their own run.
    const key = e.round != null ? `r${e.round}-${e.job_id ?? ''}` : `x-${e.job_id ?? ''}-${e.type === 'request' ? 'req' : 'final'}`
    if (!last || last.key !== key) {
      const title =
        e.round != null ? `Round ${e.round}` : e.type === 'request' || e.type === 'info' ? 'Requests' : 'Final check'
      last = { key, title, events: [] }
      groups.push(last)
    }
    last.events.push(e)
  }
  return groups
}

export function ConversationPanel({ state, needsCode }: { state: NeighborhoodState | null; needsCode: boolean }) {
  const [follow, setFollow] = useState(true)
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<AgentEvent[] | null>(null)
  const [showTools, setShowTools] = useState(true)
  const listRef = useRef<HTMLDivElement>(null)

  const live = useMemo(
    () => [...(state?.events ?? [])].sort((a, b) => a.sequence - b.sequence),
    [state?.events],
  )
  const shown = paused && frozen ? frozen : live
  const newWhilePaused = paused && frozen ? live.length - frozen.length : 0
  const visible = showTools ? shown : shown.filter((e) => e.type !== 'tool_call' && e.type !== 'tool_result')
  const byId = useMemo(() => new Map(live.map((e) => [e.id, e])), [live])
  const groups = useMemo(() => groupByRound(visible), [visible])
  const colors = useMemo(() => new Map((state?.homes ?? []).map((h: Home) => [h.id, h.color])), [state?.homes])

  useEffect(() => {
    if (follow && !paused && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [visible.length, follow, paused])

  const togglePause = () => {
    if (paused) {
      setPaused(false)
      setFrozen(null)
    } else {
      setFrozen(live)
      setPaused(true)
    }
  }

  const hidden = needsCode || state?.events_hidden

  return (
    <section className="card convo" aria-label="Agent conversation">
      <div className="convo-head">
        <h2>Agent conversation</h2>
        <div className="convo-controls">
          <button className={follow ? 'on' : ''} onClick={() => setFollow((f) => !f)} aria-pressed={follow} title="Auto-scroll to the newest message">
            <ArrowDownToLine size={14} /> Follow
          </button>
          <button className={paused ? 'on' : ''} onClick={togglePause} aria-pressed={paused}>
            {paused ? <Play size={14} /> : <Pause size={14} />} {paused ? 'Resume' : 'Pause'}
          </button>
          <button className={showTools ? 'on' : ''} onClick={() => setShowTools((t) => !t)} aria-pressed={showTools} title="Show MCP tool calls">
            <Wrench size={14} /> Tools
          </button>
        </div>
      </div>

      <div className={`activity ${state?.activity ? 'busy' : ''}`} role="status" aria-live="polite">
        {state?.activity ? (
          <><span className="pulse" aria-hidden /> {state.activity}</>
        ) : state?.job_status === 'running' ? (
          <><span className="pulse" aria-hidden /> Working…</>
        ) : (
          <span className="muted">Idle</span>
        )}
        {newWhilePaused > 0 && <span className="paused-note">Paused · {newWhilePaused} new</span>}
      </div>

      <div className="convo-list" ref={listRef}>
        {hidden ? (
          <div className="convo-empty"><Lock size={16} /> Conversation hidden. Enter the admin code to view.</div>
        ) : visible.length === 0 ? (
          <div className="convo-empty muted">No messages yet. Press Coordinate neighborhood to start.</div>
        ) : (
          groups.map((g) => (
            <div key={g.key + g.events[0].id} className="round">
              <div className="round-title">{g.title}</div>
              {g.events.map((e) => (
                <EventItem key={e.id} e={e} replyTo={e.reply_to_event_id ? byId.get(e.reply_to_event_id) : undefined} colors={colors} />
              ))}
            </div>
          ))
        )}
      </div>
    </section>
  )
}

function EventItem({ e, replyTo, colors }: { e: AgentEvent; replyTo?: AgentEvent; colors: Map<string, string> }) {
  const plan = planName(e.proposal_id)
  const stance = typeof e.data?.stance === 'string' ? STANCE[e.data.stance] : undefined
  const stub = e.data?.agent_impl === 'stub'
  const home = homeOf(e.sender)
  const accent = home ? colors.get(home) : undefined

  if (e.type === 'tool_call' || e.type === 'tool_result') {
    const tool = typeof e.data?.tool === 'string' ? e.data.tool : 'tool'
    const ms = typeof e.data?.latency_ms === 'number' ? e.data.latency_ms : null
    return (
      <div className={`tool ${e.type === 'tool_result' ? 'result' : ''}`}>
        <Wrench size={12} aria-hidden />
        <span className="tool-name">{e.type === 'tool_call' ? `${who(e.sender)} → ${tool}` : `${tool} result`}</span>
        {ms !== null && <span className="muted">{ms} ms</span>}
        {e.data?.valid === false && <span className="tag bad">invalid</span>}
        <div className="tool-text">{e.text}</div>
      </div>
    )
  }

  return (
    <article className={`msg type-${e.type}`} style={accent ? { borderLeftColor: accent } : undefined}>
      <header>
        <span className="msg-who">{who(e.sender)}</span>
        {e.recipient !== 'all_agents' && e.recipient !== 'coordinator' && (
          <span className="muted">→ {who(e.recipient)}</span>
        )}
        {plan && <span className="tag plan">{plan}</span>}
        {stance && (
          <span className={`tag ${stance.cls}`}><stance.Icon size={11} aria-hidden /> {stance.label}</span>
        )}
        {e.type === 'commit' && <span className="tag ok">Committed</span>}
        {e.type === 'validation' && (
          <span className={`tag ${e.data?.valid === false ? 'bad' : 'ok'}`}>{e.data?.valid === false ? 'Failed check' : 'Passed check'}</span>
        )}
        {e.type === 'error' && <span className="tag bad">Problem</span>}
        <span className="src" title={e.source === 'model' ? 'Written by the AI model' : 'Written by code'}>
          {e.source === 'model' ? 'AI' : stub ? 'stub agent' : 'code'}
        </span>
      </header>
      {replyTo && replyTo.type !== 'tool_call' && (
        <div className="reply-to">↳ replying to {who(replyTo.sender)}</div>
      )}
      <p>{e.text}</p>
    </article>
  )
}
