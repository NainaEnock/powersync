// PowerSync household phone app (PRD §16).
//
//   <PhoneApp homeId={homeId} api={api} />            phone polls its own state
//   <PhoneApp homeId={homeId} api={api} state={polled} />  or B passes usePoll() output
//
// homeId comes from /phone?home=X (B's App.tsx). If null, the phone uses the
// household last chosen on this device, or shows the picker.
// State is GET /api/state?home=X, already filtered by the server (PRD §11.3).
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import {
  AlertTriangle,
  BatteryCharging,
  Car,
  Check,
  CheckCircle2,
  Clock,
  Info,
  KeyRound,
  Loader2,
  Send,
  Shirt,
  Utensils,
  WifiOff,
  X,
  Zap,
} from 'lucide-react';
import { getToken, setToken, useHealth, usePoll, type Api, type Polled } from '../api';
import { StatusBadge } from '../StatusBadge';
import { slotToTime } from '../time';
import {
  HOME_IDS,
  type AgentEvent,
  type HomeId,
  type NeighborhoodState,
  type PendingChange,
  type ScheduleEntry,
  type Task,
} from '../types';
import { applianceNoun, editFieldPhrase, formatKwh, formatUsd } from './format';
import { errorText, usePhoneFlow, type FlowState } from './usePhoneFlow';
import './phone.css';

const SUGGESTIONS: Record<HomeId, string[]> = {
  A: ['I leave at 11 pm tonight. Have my car ready by then.', 'Car ready by 8 pm'],
  B: ['My dryer must finish by 10 pm. You can move the dishwasher.'],
  C: ['The car can charge anytime before 7 am.'],
};

const FALLBACK_COLORS: Record<HomeId, string> = { A: '#2563eb', B: '#d97706', C: '#059669' };

// ---------- which household this device is ----------

const HOME_KEY = 'powersync.phone.home';

function storedHome(): HomeId | null {
  try {
    const v = localStorage.getItem(HOME_KEY);
    return HOME_IDS.includes(v as HomeId) ? (v as HomeId) : null;
  } catch {
    return null;
  }
}

function rememberHome(home: HomeId | null) {
  try {
    if (home) localStorage.setItem(HOME_KEY, home);
    else localStorage.removeItem(HOME_KEY);
  } catch {
    /* storage unavailable */
  }
  // Keep a ?home= pin in step so a reload shows the same household. Other params (?mode=) stay.
  const url = new URL(window.location.href);
  if (url.searchParams.has('home')) {
    if (home) url.searchParams.set('home', home);
    else url.searchParams.delete('home');
    window.history.replaceState(null, '', url.toString());
  }
}

export interface PhoneAppProps {
  homeId: HomeId | null;
  api: Api;
  /** Optional: B's usePoll(api.state(homeId)) result. If omitted the phone polls itself. */
  state?: Polled<NeighborhoodState>;
}

export default function PhoneApp({ homeId, api, state }: PhoneAppProps) {
  const [chosen, setChosen] = useState<HomeId | null>(() => homeId ?? storedHome());
  useEffect(() => {
    if (homeId) setChosen(homeId);
  }, [homeId]);

  const changeHome = useCallback((h: HomeId | null) => {
    rememberHome(h);
    setChosen(h);
  }, []);

  if (!chosen) {
    return (
      <Shell>
        <HouseholdPicker onPick={changeHome} />
      </Shell>
    );
  }
  return state ? (
    <PhoneHome key={chosen} homeId={chosen} api={api} polled={state} onChangeHome={changeHome} />
  ) : (
    <PolledPhoneHome key={chosen} homeId={chosen} api={api} onChangeHome={changeHome} />
  );
}

function PolledPhoneHome(props: { homeId: HomeId; api: Api; onChangeHome: (h: HomeId | null) => void }) {
  const { api, homeId } = props;
  const polled = usePoll((signal) => api.state(homeId, signal), [api, homeId]);
  return <PhoneHome {...props} polled={polled} />;
}

function PhoneHome({
  homeId,
  api,
  polled,
  onChangeHome,
}: {
  homeId: HomeId;
  api: Api;
  polled: Polled<NeighborhoodState>;
  onChangeHome: (h: HomeId | null) => void;
}) {
  const health = useHealth(api);
  const state = polled.data;
  const { flow, busy, send, act, dismiss } = usePhoneFlow(api, homeId, state, polled.refresh);
  const [showTokenEntry, setShowTokenEntry] = useState(false);

  const authError = flow.error?.code ?? polled.error?.code ?? null;
  const needsToken = authError === 'UNAUTHORIZED';
  const forbidden = authError === 'FORBIDDEN';
  const down = polled.error?.code === 'BACKEND_DOWN' || polled.error?.code === 'NETWORK';

  useEffect(() => {
    if (needsToken) setShowTokenEntry(true);
  }, [needsToken]);

  const tokenSheet = showTokenEntry && (
    <TokenEntry
      homeId={homeId}
      onSave={(code) => {
        setToken(homeId, code);
        setShowTokenEntry(false);
        dismiss();
        polled.refresh();
      }}
      onCancel={() => setShowTokenEntry(false)}
      onChangeHome={() => onChangeHome(null)}
    />
  );

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
          <button className="ps-btn" onClick={() => onChangeHome(null)}>
            Change household
          </button>
        </div>
        {tokenSheet}
      </Shell>
    );
  }

  const home = state?.homes.find((h) => h.id === homeId);
  const color = home?.color || FALLBACK_COLORS[homeId];

  return (
    <Shell color={color}>
      <header className="ps-header">
        <div className="ps-header-top">
          <div className="ps-home-dot" aria-hidden />
          <div className="ps-header-title">
            <h1>{home?.name || `Home ${homeId}`}</h1>
            <span className="ps-sub">PowerSync{state ? ` · Plan revision ${state.revision}` : ''}</span>
          </div>
          <button className="ps-icon-btn" onClick={() => setShowTokenEntry(true)} aria-label="Household code">
            <KeyRound aria-hidden />
          </button>
        </div>
        <StatusBadge api={api} health={health} />
        {!getToken(homeId) && health.data && health.data.auth_mode !== 'dev-open' && (
          <button className="ps-link" onClick={() => setShowTokenEntry(true)}>
            This phone has no household code. Enter it.
          </button>
        )}
      </header>

      {tokenSheet}

      {api.mode === 'sample' && (
        <div className="ps-banner ps-banner-sample">
          Sample data. Requests need the live backend (add ?mode=live).
        </div>
      )}

      {down && (
        <div className="ps-banner ps-banner-error" role="alert">
          <WifiOff aria-hidden /> {polled.error?.message}. {state ? 'Showing the last plan received.' : ''}
        </div>
      )}

      {!state ? (
        <div className="ps-card ps-center">
          <Loader2 className="ps-spin" aria-hidden />
          <p>{down ? 'Waiting for the backend…' : polled.error ? errorText(polled.error) : 'Loading your plan…'}</p>
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
          <ChangeCards homeId={homeId} state={state} busy={busy} onAct={act} />
          <FlowStatus
            flow={flow}
            onDismiss={dismiss}
            infeasibleCardShown={state.pending_changes.some(
              (c) => c.home_id === homeId && c.status === 'pending' && !c.feasible,
            )}
          />
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

/* ---------------- household picker + token entry ---------------- */

function HouseholdPicker({ onPick }: { onPick: (h: HomeId) => void }) {
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
            onClick={() => onPick(h)}
          >
            Home {h}
          </button>
        ))}
      </div>
      <p className="ps-muted">You'll enter your household code next if this demo needs one.</p>
    </div>
  );
}

function TokenEntry({
  homeId,
  onSave,
  onCancel,
  onChangeHome,
}: {
  homeId: HomeId;
  onSave: (code: string) => void;
  onCancel: () => void;
  onChangeHome: () => void;
}) {
  const [code, setCode] = useState('');
  return (
    <div className="ps-overlay" role="dialog" aria-modal="true" aria-label="Household code">
      <form
        className="ps-card ps-sheet"
        onSubmit={(e) => {
          e.preventDefault();
          if (code.trim()) onSave(code.trim());
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
          <button type="button" className="ps-btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
        <button type="button" className="ps-link" onClick={onChangeHome}>
          Change household
        </button>
      </form>
    </div>
  );
}

/* ---------------- summary tiles ---------------- */

function currentSchedule(state: NeighborhoodState): { entries: ScheduleEntry[]; coordinated: boolean } {
  if (state.coordinated_schedule) return { entries: state.coordinated_schedule, coordinated: true };
  return { entries: state.baseline_schedule ?? [], coordinated: false };
}

function onTime(entry: ScheduleEntry | undefined, task: Task): boolean {
  return !!entry && entry.start_slot + entry.duration_slots <= task.deadline_slot;
}

function SummaryTiles({ homeId, state }: { homeId: HomeId; state: NeighborhoodState }) {
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

function PlanCard({ homeId, state, replanning }: { homeId: HomeId; state: NeighborhoodState; replanning: boolean }) {
  const { entries, coordinated } = currentSchedule(state);
  const tasks = state.tasks.filter((t) => t.home_id === homeId);
  const t = slotToTime;
  const planName = state.coordination?.plan_name ?? null;
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
          ? `${planName ? `${planName}, a` : 'A'}greed with the neighborhood and checked by PowerSync.`
          : 'Not coordinated yet. These are your preferred times.'}
      </p>
      {coordinated && state.coordination?.explanation && <p>{state.coordination.explanation}</p>}
      {state.coordination?.status === 'stale_tariff' && (
        <p className="ps-muted">Prices changed since this plan was made. The neighborhood will plan again.</p>
      )}
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
                  {task.name} <span className="ps-muted ps-nowrap">· {task.power_kw} kW</span>
                </div>
                <div className="ps-plan-time">
                  {e ? (
                    <>
                      <span className="ps-nowrap">{t(e.start_slot)}</span> –{' '}
                      <span className="ps-nowrap">{t(e.start_slot + e.duration_slots)}</span>
                    </>
                  ) : (
                    'Not scheduled'
                  )}
                </div>
                <div className="ps-plan-deadline">
                  <Clock aria-hidden />
                  <span>
                    Needs to finish by <span className="ps-nowrap">{t(task.deadline_slot)}</span>
                  </span>
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
  busy,
  onAct,
}: {
  homeId: HomeId;
  state: NeighborhoodState;
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
            {/* D's default explanation is the same question in other words; only show extra context. */}
            {c.explanation && !c.explanation.trim().startsWith('Change ') && (
              <p className="ps-muted">{c.explanation}</p>
            )}
            <p className="ps-muted">If you confirm, the neighborhood plans again around it.</p>
            <div className="ps-row">
              <button className="ps-btn ps-primary" disabled={busy} onClick={() => onAct(c, 'confirm_change')}>
                <Check aria-hidden /> Confirm
              </button>
              <button className="ps-btn" disabled={busy} onClick={() => onAct(c, 'reject_change')}>
                <X aria-hidden /> Reject
              </button>
            </div>
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
  clarify: 'Your agent has a question.',
  no_change: 'Nothing to change.',
  failed: 'Nothing was changed.',
};

function FlowStatus({
  flow,
  onDismiss,
  infeasibleCardShown,
}: {
  flow: FlowState;
  onDismiss: () => void;
  infeasibleCardShown: boolean;
}) {
  if (flow.phase === 'idle' && !flow.message) return null;
  const running = flow.phase === 'queued' || flow.phase === 'interpreting' || flow.phase === 'planning';
  const bad = flow.phase === 'failed' || flow.phase === 'infeasible' || (flow.phase === 'idle' && !!flow.error);
  const good = flow.phase === 'applied';
  // Clarifying questions and "no change" replies are the agent's own text, so they lead.
  const textLeads = (flow.phase === 'clarify' || flow.phase === 'no_change' || flow.phase === 'failed') && !!flow.message;
  const headline =
    flow.phase === 'idle'
      ? flow.error
        ? errorText(flow.error)
        : flow.message
      : textLeads
        ? flow.message
        : PHASE_LABEL[flow.phase];
  // If an infeasible card is on screen it already shows the reason; otherwise show it here.
  const detail =
    flow.phase === 'idle' ||
    flow.phase === 'confirm' || // the confirmation card shows the change itself
    textLeads ||
    (flow.phase === 'infeasible' && infeasibleCardShown)
      ? null
      : flow.message;
  return (
    <section className={`ps-status-card ${bad ? 'ps-status-bad' : good ? 'ps-status-good' : ''}`} aria-live="polite">
      <div className="ps-status-line">
        {running ? (
          <Loader2 className="ps-spin" aria-hidden />
        ) : good ? (
          <CheckCircle2 aria-hidden />
        ) : bad ? (
          <AlertTriangle aria-hidden />
        ) : flow.phase === 'clarify' || flow.phase === 'no_change' ? (
          <Info aria-hidden />
        ) : null}
        <span>{headline}</span>
        {!running && (
          <button className="ps-icon-btn" onClick={onDismiss} aria-label="Dismiss">
            <X aria-hidden />
          </button>
        )}
      </div>
      {detail && detail !== headline && <div className="ps-muted">{detail}</div>}
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

function Messages({ homeId, state }: { homeId: HomeId; state: NeighborhoodState }) {
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
