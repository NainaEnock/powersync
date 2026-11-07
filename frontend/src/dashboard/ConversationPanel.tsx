// Live agent conversation (PRD §12.4). Shows only what the backend stored: no invented text.
// Sort by sequence, group by round, tag plans, activity line, Follow and Pause, hidden state.
// New messages arrive one at a time (see usePacedEvents) so people can read them.
import { ArrowDownToLine, Check, CircleAlert, FastForward, Lock, Pause, Play, ShieldCheck, Wrench, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { AgentEvent, Home, NeighborhoodState } from '../types'
import type { Paced } from './usePacedEvents'

const COORD = '#2f5d46'

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
  if (p.startsWith('agent_') && h) return `Home ${h} Agent`
  if (p.startsWith('resident_') && h) return `Home ${h} resident`
  switch (p) {
    case 'coordinator': return 'Neighborhood Coordinator'
    case 'all_agents': return 'All homes'
    case 'powersync-energy': return 'Energy tools (MCP)'
    case 'validator': return 'Safety check'
    case 'backend': return 'PowerSync'
    default: return p
  }
}

const isTool = (e: AgentEvent) => e.type === 'tool_call' || e.type === 'tool_result'

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

export function ConversationPanel({ state, paced, needsCode, size = 'side' }: {
  state: NeighborhoodState | null
  paced: Paced
  needsCode: boolean
  size?: 'side' | 'full'
}) {
  const [follow, setFollow] = useState(true)
  const [paused, setPaused] = useState(false)
  const [frozen, setFrozen] = useState<AgentEvent[] | null>(null)
  const [showTools, setShowTools] = useState(size === 'side')
  const listRef = useRef<HTMLDivElement>(null)

  const live = paced.shown
  const shown = paused && frozen ? frozen : live
  const newWhilePaused = paused && frozen ? live.length - frozen.length + paced.queued : 0
  const visible = showTools ? shown : shown.filter((e) => !isTool(e))
  const byId = useMemo(() => new Map(live.map((e) => [e.id, e])), [live])
  const groups = useMemo(() => groupByRound(visible), [visible])
  const homes: Home[] = state?.homes ?? []
  const colors = useMemo(() => new Map(homes.map((h) => [h.id, h.color])), [homes])
  const typing = !paused && paced.next && (showTools || !isTool(paced.next)) ? paced.next : null

  useEffect(() => {
    if (follow && !paused && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [visible.length, typing?.id, follow, paused])

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
  const running = state?.job_status === 'running'

  return (
    <section className={`card convo convo-${size}`} aria-label="Agent conversation">
      <div className="card-head">
        <div>
          <div className="eyebrow">{running || paced.queued > 0 ? 'Live negotiation' : 'Negotiation log'}</div>
          <h2>Agent Conversation</h2>
        </div>
        <div className="convo-controls">
          {paced.queued > 1 && (
            <button className="chip" onClick={paced.skip} title="Show every waiting message now">
              <FastForward size={13} /> Skip ({paced.queued})
            </button>
          )}
          <button className={`chip ${follow ? 'on' : ''}`} onClick={() => setFollow((f) => !f)} aria-pressed={follow} title="Auto-scroll to the newest message">
            <ArrowDownToLine size={13} /> Follow
          </button>
          <button className={`chip ${paused ? 'on' : ''}`} onClick={togglePause} aria-pressed={paused}>
            {paused ? <Play size={13} /> : <Pause size={13} />} {paused ? 'Resume' : 'Pause'}
          </button>
          <button className={`chip ${showTools ? 'on' : ''}`} onClick={() => setShowTools((t) => !t)} aria-pressed={showTools} title="Show MCP tool calls">
            <Wrench size={13} /> Tools
          </button>
        </div>
      </div>

      <ul className="legend convo-legend">
        {homes.map((h) => (
          <li key={h.id}><span className="dot" style={{ background: h.color }} />{h.name} Agent</li>
        ))}
        <li><span className="dot" style={{ background: COORD }} />Neighborhood Coordinator</li>
      </ul>

      <div className={`activity ${state?.activity || running ? 'busy' : ''}`} role="status" aria-live="polite">
        {state?.activity ? (
          <><span className="pulse" aria-hidden /> {state.activity}</>
        ) : running ? (
          <><span className="pulse" aria-hidden /> Working…</>
        ) : (
          <span className="muted">Idle</span>
        )}
        {newWhilePaused > 0 && <span className="paused-note">Paused · {newWhilePaused} new</span>}
      </div>

      <div className="convo-list" ref={listRef}>
        {hidden ? (
          <div className="convo-empty"><Lock size={16} /> Conversation hidden. Enter the admin code to view.</div>
        ) : visible.length === 0 && !typing ? (
          <div className="convo-empty muted">No messages yet. Press Coordinate neighborhood to start.</div>
        ) : (
          <>
            {groups.map((g) => (
              <div key={g.key + g.events[0].id} className="round">
                <div className="round-title">{g.title}</div>
                {g.events.map((e) => (
                  <EventItem key={e.id} e={e} replyTo={e.reply_to_event_id ? byId.get(e.reply_to_event_id) : undefined} colors={colors} />
                ))}
              </div>
            ))}
            {typing && <TypingBubble e={typing} colors={colors} />}
          </>
        )}
      </div>
    </section>
  )
}

function TypingBubble({ e, colors }: { e: AgentEvent; colors: Map<string, string> }) {
  const home = homeOf(e.sender)
  const accent = home ? colors.get(home) : COORD
  return (
    <div className="typing" aria-hidden style={{ borderColor: `color-mix(in srgb, ${accent} 30%, white)` }}>
      <span className="typing-who">{isTool(e) ? 'Energy tools' : who(e.sender)}</span>
      <span className="typing-dots"><i /><i /><i /></span>
    </div>
  )
}

function SourceTag({ e }: { e: AgentEvent }) {
  const stub = e.data?.agent_impl === 'stub'
  return (
    <span className="src" title={e.source === 'model' ? 'Written by the AI model' : 'Written by code'}>
      {e.source === 'model' ? 'AI' : stub ? 'stub agent' : 'code'}
    </span>
  )
}

function EventItem({ e, replyTo, colors }: { e: AgentEvent; replyTo?: AgentEvent; colors: Map<string, string> }) {
  const plan = planName(e.proposal_id)
  const stance = typeof e.data?.stance === 'string' ? STANCE[e.data.stance] : undefined

  if (isTool(e)) {
    const tool = typeof e.data?.tool === 'string' ? e.data.tool : 'tool'
    const ms = typeof e.data?.latency_ms === 'number' ? e.data.latency_ms : null
    return (
      <div className={`tool appear ${e.type === 'tool_result' ? 'result' : ''}`}>
        <Wrench size={13} aria-hidden className="tool-icon" />
        <div className="tool-body">
          <div className="tool-head">
            <b>{e.type === 'tool_call' ? `${who(e.sender)} asks the energy tools` : 'Energy tools answer'}</b>
            {plan && <span className="tag plan">{plan}</span>}
            {e.data?.valid === false && <span className="tag bad">invalid</span>}
          </div>
          <div className="tool-text">{e.text}</div>
          <details>
            <summary>Raw details</summary>
            <code>{tool}{ms !== null ? ` · ${ms} ms` : ''}{e.data?.valid != null ? ` · valid=${String(e.data.valid)}` : ''}</code>
          </details>
        </div>
      </div>
    )
  }

  if (e.type === 'commit') {
    return (
      <article className="msg msg-commit appear">
        <header>
          <ShieldCheck size={15} aria-hidden />
          <span className="msg-who">Applied · revision {e.revision}</span>
          {plan && <span className="tag plan-dark">{plan}</span>}
          <SourceTag e={e} />
        </header>
        <p>{e.text}</p>
      </article>
    )
  }

  const home = homeOf(e.sender)
  const accent = home ? colors.get(home) : e.sender === 'coordinator' ? COORD : undefined
  const style = accent
    ? { background: `color-mix(in srgb, ${accent} 9%, white)`, borderColor: `color-mix(in srgb, ${accent} 22%, white)` }
    : undefined

  return (
    <article className={`msg appear type-${e.type}`} style={style}>
      <header>
        <span className="msg-who">{who(e.sender)}</span>
        {e.recipient !== e.sender && <span className="muted msg-to">to {who(e.recipient)}</span>}
        {plan && <span className="tag plan">{plan}</span>}
        {stance && <span className={`tag ${stance.cls}`}><stance.Icon size={11} aria-hidden /> {stance.label}</span>}
        {e.type === 'validation' && (
          <span className={`tag ${e.data?.valid === false ? 'bad' : 'ok'}`}>{e.data?.valid === false ? 'Failed check' : 'Passed check'}</span>
        )}
        {e.type === 'error' && <span className="tag bad">Problem</span>}
        <SourceTag e={e} />
      </header>
      <p>{e.text}</p>
      {replyTo && replyTo.type !== 'tool_call' && (
        <div className="reply-to">Replying to {who(replyTo.sender)}</div>
      )}
    </article>
  )
}
