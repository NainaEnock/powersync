// PowerSync household phone app (PRD §16). Default export, injected props:
//   homeId — which household this phone is (null shows the picker)
//   state  — GET /api/state?home=<homeId>, already filtered by the server
//   api    — B's adapter (see phoneTypes.ts PhoneApi)
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import {
  AlertTriangle,
  BatteryCharging,
  Car,
  Check,
  CheckCircle2,
  Clock,
  KeyRound,
  Loader2,
  Send,
  Shirt,
  Utensils,
  WifiOff,
  X,
  Zap,
} from 'lucide-react';
import './phone.css';
import {
  applianceNoun,
  editFieldPhrase,
  formatKwh,
  formatUsd,
  slotToTime,
} from './format';
import { errorText, usePhoneFlow, type FlowState } from './usePhoneFlow';
import {
  HOME_IDS,
  type AgentEvent,
  type HomeId,
  type HouseholdState,
  type PendingChange,
  type PhoneApi,
  type PhoneAppProps,
  type ScheduleEntry,
  type Task,
} from './phoneTypes';

const SUGGESTIONS: Record<HomeId, string[]> = {
  A: ['I leave at 11 pm tonight. Have my car ready by then.', 'Car ready by 8 pm'],
  B: ['My dryer must finish by 10 pm. You can move the dishwasher.'],
  C: ['The car can charge anytime before 7 am.'],
};

const FALLBACK_COLORS: Record<HomeId, string> = { A: '#2563eb', B: '#d97706', C: '#059669' };

export default function PhoneApp({ homeId, state, api }: PhoneAppProps) {
  const [showTokenEntry, setShowTokenEntry] = useState(false);
  const { flow, busy, send, act, dismiss } = usePhoneFlow(homeId, state, api);

  const authError = flow.error?.code ?? api.stateError?.code ?? null;
  const needsToken = authError === 'UNAUTHORIZED';
  const forbidden = authError === 'FORBIDDEN';

  useEffect(() => {
    if (needsToken) setShowTokenEntry(true);
  }, [needsToken]);

  if (!homeId) {
    return (
      <Shell>
        <HouseholdPicker api={api} />
      </Shell>
    );
  }

  if (forbidden) {
    return (
      <Shell>
        <div className="ps-card ps-center">
          <AlertTriangle className="ps-icon-lg ps-warn" aria-hidden />
          <h2>That code isn't for this home</h2>
          <p>The code saved on this phone doesn't match Home {homeId}.</p>
          <button className="ps-btn ps-primary" onClick={() => setShowTokenEntry(true)}>
            Enter the code again
          </button>
          <button className="ps-btn" onClick={() => api.setHome(null)}>
            Change household
          </button>
        </div>
        {showTokenEntry && (
          <TokenEntry homeId={homeId} api={api} onDone={() => { setShowTokenEntry(false); dismiss(); }} />
        )}
      </Shell>
    );
  }

  const home = state?.homes.find((h) => h.id === homeId);
  const color = home?.color || FALLBACK_COLORS[homeId];

  return (
    <Shell color={color}>
      <Header homeId={homeId} homeName={home?.name} state={state} api={api} onCode={() => setShowTokenEntry(true)} />

      {showTokenEntry && (
        <TokenEntry homeId={homeId} api={api} onDone={() => { setShowTokenEntry(false); dismiss(); }} />
      )}

      {api.connection === 'backend_down' && (
        <div className="ps-banner ps-banner-error" role="alert">
          <WifiOff aria-hidden /> Backend not running on port 8000. {state ? 'Showing the last plan received.' : ''}
        </div>
      )}

      {!state ? (
        <div className="ps-card ps-center">
          <Loader2 className="ps-spin" aria-hidden />
          <p>{api.connection === 'backend_down' ? 'Waiting for the backend…' : 'Loading your plan…'}</p>
        </div>
      ) : (
        <>
          {state.activity && (
            <div className="ps-activity">
              <Loader2 className="ps-spin" aria-hidden /> {state.activity}
            </div>
          )}
          <SummaryTiles homeId={homeId} state={state} />
          <PlanCard homeId={homeId} state={state} replanning={busy && flow.kind === 'action'} />
          <ChangeCards homeId={homeId} state={state} flow={flow} busy={busy} onAct={act} />
          <FlowStatus flow={flow} onDismiss={dismiss} />
          <RequestBox homeId={homeId} busy={busy} onSend={send} />
          <Messages homeId={homeId} state={state} />
        </>
      )}
    </Shell>
  );
}

function Shell({ children, color }: { children: ReactNode; color?: string }) {
  return (
    <div className="ps-phone" style={color ? ({ '--ps-home': color } as CSSProperties) : undefined}>
      {children}
    </div>
  );
}

/* ---------------- header ---------------- */

function Header({
  homeId,
  homeName,
  state,
  api,
  onCode,
}: {
  homeId: HomeId;
  homeName?: string;
  state: HouseholdState | null;
  api: PhoneApi;
  onCode: () => void;
}) {
  const conn =
    api.connection === 'connected'
      ? 'connected'
      : api.connection === 'connecting'
        ? 'connecting'
        : api.connection === 'backend_down'
          ? 'backend down'
          : 'error';
  const sample = api.dataMode === 'sample';
  return (
    <header className="ps-header">
      <div className="ps-header-top">
        <div className="ps-home-dot" aria-hidden />
        <div className="ps-header-title">
          <h1>{homeName || `Home ${homeId}`}</h1>
          <span className="ps-sub">PowerSync{state ? ` · Plan revision ${state.revision}` : ''}</span>
        </div>
        <button className="ps-icon-btn" onClick={onCode} aria-label="Household code">
          <KeyRound aria-hidden />
        </button>
      </div>
      <div className="ps-badges">
        <span className={`ps-badge ${sample ? 'ps-badge-sample' : 'ps-badge-live'}`}>
          {sample ? 'Sample data' : 'Live'}
        </span>
        <span className={`ps-badge ${api.connection === 'connected' ? 'ps-badge-ok' : 'ps-badge-bad'}`}>{conn}</span>
        <span className="ps-badge">{api.authMode === 'unknown' ? 'auth ?' : api.authMode}</span>
        {!api.hasToken(homeId) && api.authMode !== 'dev-open' && <span className="ps-badge ps-badge-bad">no code</span>}
      </div>
    </header>
  );
}

/* ---------------- household picker + token entry ---------------- */

function HouseholdPicker({ api }: { api: PhoneApi }) {
  return (
    <div className="ps-card">
      <h1 className="ps-brand">
        <Zap aria-hidden /> PowerSync
      </h1>
      <p>Which household is this phone?</p>
      <div className="ps-picker">
        {HOME_IDS.map((h) => (
          <button
            key={h}
            className="ps-btn ps-picker-btn"
            style={{ '--ps-home': FALLBACK_COLORS[h] } as CSSProperties}
            onClick={() => api.setHome(h)}
          >
            Home {h}
          </button>
        ))}
      </div>
      <p className="ps-muted">You'll enter your household code next if this demo needs one.</p>
    </div>
  );
}

function TokenEntry({ homeId, api, onDone }: { homeId: HomeId; api: PhoneApi; onDone: () => void }) {
  const [code, setCode] = useState('');
  return (
    <div className="ps-overlay" role="dialog" aria-modal="true" aria-label="Household code">
      <form
        className="ps-card ps-sheet"
        onSubmit={(e) => {
          e.preventDefault();
          api.setToken(homeId, code);
          api.refresh().catch(() => undefined);
          onDone();
        }}
      >
        <h2>
          <KeyRound aria-hidden /> Home {homeId} code
        </h2>
        <p className="ps-muted">Ask the PowerSync team for this home's code. It stays on this phone.</p>
        <input
          className="ps-input"
          type="password"
          autoComplete="off"
          autoCapitalize="off"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Household code"
          autoFocus
        />
        <div className="ps-row">
          <button type="submit" className="ps-btn ps-primary" disabled={!code.trim()}>
            Save code
          </button>
          <button type="button" className="ps-btn" onClick={onDone}>
            Cancel
          </button>
        </div>
        <button type="button" className="ps-link" onClick={() => api.setHome(null)}>
          Change household
        </button>
      </form>
    </div>
  );
}

/* ---------------- summary tiles ---------------- */

function currentSchedule(state: HouseholdState): { entries: ScheduleEntry[]; coordinated: boolean } {
  if (state.coordinated_schedule) return { entries: state.coordinated_schedule, coordinated: true };
  return { entries: state.baseline_schedule ?? [], coordinated: false };
}

function onTime(entry: ScheduleEntry | undefined, task: Task): boolean {
  return !!entry && entry.start_slot + entry.duration_slots <= task.deadline_slot;
}

function SummaryTiles({ homeId, state }: { homeId: HomeId; state: HouseholdState }) {
  const { entries, coordinated } = currentSchedule(state);
  const metrics = coordinated ? state.metrics.coordinated : state.metrics.baseline;
  const mine = metrics?.per_home?.[homeId];
  const tasks = state.tasks.filter((t) => t.home_id === homeId);
  const ready = tasks.filter((t) => onTime(entries.find((e) => e.task_id === t.id), t)).length;
  return (
    <section className="ps-tiles" aria-label="Summary">
      <Tile label="Modeled cost" value={formatUsd(mine?.variable_cost_usd)} />
      <Tile label="Energy" value={formatKwh(mine?.energy_kwh)} />
      <Tile label="Ready on time" value={`${ready} of ${tasks.length}`} />
      <Tile label="Prices" value={state.tariff_mode === 'flat' ? 'Flat rate' : 'Time of use'} hint={state.tariff_label} />
    </section>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ps-tile">
      <span className="ps-tile-label">{label}</span>
      <span className="ps-tile-value">{value}</span>
      {hint && <span className="ps-tile-hint">{hint}</span>}
    </div>
  );
}

/* ---------------- today's plan ---------------- */

function TaskIcon({ name }: { name: string }) {
  const n = applianceNoun(name);
  if (n === 'car') return <Car aria-hidden />;
  if (n === 'dryer') return <Shirt aria-hidden />;
  if (n === 'dishwasher') return <Utensils aria-hidden />;
  return <BatteryCharging aria-hidden />;
}

function PlanCard({ homeId, state, replanning }: { homeId: HomeId; state: HouseholdState; replanning: boolean }) {
  const { entries, coordinated } = currentSchedule(state);
  const tasks = state.tasks.filter((t) => t.home_id === homeId);
  const t = (slot: number) => slotToTime(slot, state.horizon_start, state.slot_minutes);
  return (
    <section className="ps-card">
      <div className="ps-card-head">
        <h2>Today's plan</h2>
        {replanning && (
          <span className="ps-pill">
            <Loader2 className="ps-spin" aria-hidden /> Replanning
          </span>
        )}
      </div>
      <p className="ps-muted">
        {coordinated
          ? 'Agreed with the neighborhood and checked by PowerSync.'
          : 'Not coordinated yet. These are your preferred times.'}
      </p>
      <ul className="ps-plan">
        {tasks.map((task) => {
          const e = entries.find((x) => x.task_id === task.id);
          const ok = onTime(e, task);
          return (
            <li key={task.id} className="ps-plan-row">
              <div className="ps-plan-icon">
                <TaskIcon name={task.name} />
              </div>
              <div className="ps-plan-body">
                <div className="ps-plan-name">
                  {task.name} <span className="ps-muted">· {task.power_kw} kW</span>
                </div>
                <div className="ps-plan-time">
                  {e ? `${t(e.start_slot)} – ${t(e.start_slot + e.duration_slots)}` : 'Not scheduled'}
                </div>
                <div className="ps-plan-deadline">
                  <Clock aria-hidden /> Needs to finish by {t(task.deadline_slot)}
                </div>
              </div>
              <span className={`ps-status ${ok ? 'ps-ok' : 'ps-bad'}`}>{ok ? 'On time' : 'Late'}</span>
            </li>
          );
        })}
        {tasks.length === 0 && <li className="ps-muted">No appliances for this home.</li>}
      </ul>
    </section>
  );
}

/* ---------------- confirmation cards ---------------- */

function changeQuestion(change: PendingChange, tasks: Task[]): string {
  const parts = change.proposed_edits.edits.map((ed) => {
    const task = tasks.find((x) => x.id === ed.task_id);
    const noun = task ? applianceNoun(task.name) : 'appliance';
    return `your ${noun}'s ${editFieldPhrase(ed.field)} from ${ed.old_time} to ${ed.new_time}`;
  });
  if (parts.length === 0) return 'Apply this change?';
  return `Change ${parts.join(' and ')}?`;
}

function ChangeCards({
  homeId,
  state,
  flow,
  busy,
  onAct,
}: {
  homeId: HomeId;
  state: HouseholdState;
  flow: FlowState;
  busy: boolean;
  onAct: (c: PendingChange, a: 'confirm_change' | 'reject_change') => void;
}) {
  const pending = state.pending_changes.filter((c) => c.home_id === homeId && c.status === 'pending');
  if (pending.length === 0) return null;
  return (
    <>
      {pending.map((c) =>
        c.feasible ? (
          <section key={c.id} className="ps-card ps-confirm" aria-live="polite">
            <h2>Confirm a change</h2>
            <p className="ps-question">{changeQuestion(c, state.tasks)}</p>
            {c.explanation && <p className="ps-muted">{c.explanation}</p>}
            <p className="ps-muted">If you confirm, the neighborhood plans again around it.</p>
            <div className="ps-row">
              <button className="ps-btn ps-primary" disabled={busy} onClick={() => onAct(c, 'confirm_change')}>
                <Check aria-hidden /> Confirm
              </button>
              <button className="ps-btn" disabled={busy} onClick={() => onAct(c, 'reject_change')}>
                <X aria-hidden /> Reject
              </button>
            </div>
            {flow.jobId === c.job_id && flow.phase === 'confirm' && flow.message && (
              <p className="ps-muted">{flow.message}</p>
            )}
          </section>
        ) : (
          <section key={c.id} className="ps-card ps-infeasible" aria-live="polite">
            <h2>
              <AlertTriangle aria-hidden /> That can't work
            </h2>
            <p>{c.explanation || 'PowerSync could not fit that request.'}</p>
            {c.infeasible_reasons.length > 0 && (
              <ul className="ps-reasons">
                {c.infeasible_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            <p className="ps-muted">Your plan has not changed.</p>
            <button className="ps-btn" disabled={busy} onClick={() => onAct(c, 'reject_change')}>
              OK
            </button>
          </section>
        ),
      )}
    </>
  );
}

/* ---------------- flow status ---------------- */

const PHASE_LABEL: Partial<Record<FlowState['phase'], string>> = {
  queued: 'Request queued…',
  interpreting: 'Your agent is reading your request…',
  planning: 'Planning with the neighborhood…',
  confirm: 'Please confirm the change below.',
  applied: 'Done. Your new plan is above.',
  rejected: 'Change rejected. Your plan stays the same.',
  infeasible: "That request can't fit. Your plan has not changed.",
  failed: 'That request failed.',
};

function FlowStatus({ flow, onDismiss }: { flow: FlowState; onDismiss: () => void }) {
  if (flow.phase === 'idle' && !flow.message) return null;
  const running = flow.phase === 'queued' || flow.phase === 'interpreting' || flow.phase === 'planning';
  const bad = flow.phase === 'failed' || flow.phase === 'infeasible' || (flow.phase === 'idle' && !!flow.error);
  const good = flow.phase === 'applied';
  const headline =
    flow.phase === 'idle' ? (flow.error ? errorText(flow.error) : flow.message) : PHASE_LABEL[flow.phase];
  // The infeasible card already shows the explanation; don't repeat it here.
  const detail = flow.phase === 'idle' || flow.phase === 'infeasible' ? null : flow.message;
  return (
    <section className={`ps-status-card ${bad ? 'ps-status-bad' : good ? 'ps-status-good' : ''}`} aria-live="polite">
      <div className="ps-status-line">
        {running ? (
          <Loader2 className="ps-spin" aria-hidden />
        ) : good ? (
          <CheckCircle2 aria-hidden />
        ) : bad ? (
          <AlertTriangle aria-hidden />
        ) : null}
        <span>{headline}</span>
        {!running && (
          <button className="ps-icon-btn" onClick={onDismiss} aria-label="Dismiss">
            <X aria-hidden />
          </button>
        )}
      </div>
      {running && flow.stage && <div className="ps-muted">{flow.stage}</div>}
      {detail && detail !== headline && <div className="ps-muted">{detail}</div>}
      {running && flow.error && <div className="ps-muted">Connection problem: {errorText(flow.error)} Still trying…</div>}
    </section>
  );
}

/* ---------------- request box ---------------- */

function RequestBox({ homeId, busy, onSend }: { homeId: HomeId; busy: boolean; onSend: (t: string) => Promise<boolean> }) {
  const [text, setText] = useState('');
  const submit = async (value: string) => {
    const ok = await onSend(value);
    if (ok) setText('');
  };
  return (
    <section className="ps-card">
      <h2>Ask your agent</h2>
      <form
        className="ps-request"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(text);
        }}
      >
        <textarea
          className="ps-input"
          rows={2}
          maxLength={500}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit(text);
            }
          }}
          enterKeyHint="send"
          placeholder="For example: have my car ready by 11 pm"
          disabled={busy}
        />
        <button type="submit" className="ps-btn ps-primary ps-send" disabled={busy || !text.trim()} aria-label="Send">
          {busy ? <Loader2 className="ps-spin" aria-hidden /> : <Send aria-hidden />}
        </button>
      </form>
      <div className="ps-suggestions">
        {SUGGESTIONS[homeId].map((s) => (
          <button key={s} className="ps-chip" disabled={busy} onClick={() => setText(s)}>
            {s}
          </button>
        ))}
      </div>
    </section>
  );
}

/* ---------------- messages ---------------- */

function senderLabel(sender: string, homeId: HomeId): string {
  const [role, home] = sender.split('_');
  if (role === 'resident') return home === homeId ? 'You' : `Home ${home}`;
  if (role === 'agent') return home === homeId ? 'Your agent' : `Home ${home}'s agent`;
  if (sender === 'coordinator') return 'Neighborhood coordinator';
  if (sender === 'validator') return 'Plan check';
  if (sender === 'backend') return 'PowerSync';
  return sender;
}

function Messages({ homeId, state }: { homeId: HomeId; state: HouseholdState }) {
  const events = useMemo(() => [...state.events].sort((a, b) => a.sequence - b.sequence), [state.events]);
  return (
    <section className="ps-card">
      <h2>Messages</h2>
      {events.length === 0 ? (
        <p className="ps-muted">No messages yet. Your agent's conversations about your home will appear here.</p>
      ) : (
        <ol className="ps-messages">
          {events.map((ev) => (
            <MessageItem key={ev.id} ev={ev} homeId={homeId} />
          ))}
        </ol>
      )}
    </section>
  );
}

function MessageItem({ ev, homeId }: { ev: AgentEvent; homeId: HomeId }) {
  const mine = ev.sender === `resident_${homeId}`;
  const tone = ev.type === 'error' ? 'ps-msg-error' : ev.type === 'commit' ? 'ps-msg-commit' : '';
  return (
    <li className={`ps-msg ${mine ? 'ps-msg-mine' : ''} ${tone}`}>
      <div className="ps-msg-meta">
        <span className="ps-msg-from">{senderLabel(ev.sender, homeId)}</span>
        {ev.proposal_id && <span className="ps-pill">Plan {ev.proposal_id.replace(/^P-/, '')}</span>}
        <span className="ps-msg-src" title={ev.source === 'model' ? 'Written by AI' : 'Written by PowerSync'}>
          {ev.source === 'model' ? 'AI' : 'auto'}
        </span>
      </div>
      <div className="ps-msg-text">{ev.text}</div>
    </li>
  );
}
