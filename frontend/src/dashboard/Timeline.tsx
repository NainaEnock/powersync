// Task timeline (PRD §17): one row per appliance, bars at run times for the schedule picked in the
// chart's switch, a dashed finish-by marker, the deadline in words, and a "requested" marker while a
// resident's deadline change waits for confirmation. Short bars put their label outside.
import { useRef } from 'react'
import { slotToTick, slotToTime } from '../time'
import type { NeighborhoodState, ScheduleEntry, ScheduleKind } from '../types'
import { windowEnd } from './DemandChart'

const VIEW_LABEL: Record<ScheduleKind, string> = {
  baseline: 'Preferred times',
  independent: 'Cheap timer',
  coordinated: 'The actual plan',
}

export function Timeline({ state, focus }: { state: NeighborhoodState; focus: ScheduleKind }) {
  const schedules: Record<ScheduleKind, ScheduleEntry[] | null> = {
    baseline: state.baseline_schedule,
    independent: state.independent_schedule,
    coordinated: state.coordinated_schedule,
  }
  const shownKind: ScheduleKind = schedules[focus] ? focus : 'baseline'
  const schedule = schedules[shownKind] ?? []

  // Remember each task's first deadline in this demo run, so a changed one can say what it was.
  const firstDeadline = useRef<{ gen: number; map: Map<string, number> }>({ gen: -1, map: new Map() })
  if (firstDeadline.current.gen !== state.generation) firstDeadline.current = { gen: state.generation, map: new Map() }
  // Forget removed appliances, so one removed and added again with a new time isn't shown as "changed".
  const present = new Set(state.tasks.map((t) => t.id))
  for (const id of [...firstDeadline.current.map.keys()]) if (!present.has(id)) firstDeadline.current.map.delete(id)
  for (const t of state.tasks) if (!firstDeadline.current.map.has(t.id)) firstDeadline.current.map.set(t.id, t.deadline_slot)

  // A resident's requested deadline that isn't confirmed yet (dashboard view carries pending changes).
  const requested = new Map<string, number>()
  for (const p of state.pending_changes ?? []) {
    if (p.status !== 'pending' || !p.feasible) continue
    for (const e of p.proposed_edits.edits) if (e.field === 'deadline_slot') requested.set(e.task_id, e.new_value)
  }

  const end = windowEnd(state.tasks)
  const pct = (slot: number) => `${(Math.min(slot, end) / end) * 100}%`
  const ticks = Array.from({ length: end / 8 + 1 }, (_, i) => i * 8)
  const color = new Map(state.homes.map((h) => [h.id, h.color]))
  const tasks = [...state.tasks].sort((a, b) => a.home_id.localeCompare(b.home_id) || a.name.localeCompare(b.name))
  const eyebrow =
    shownKind === 'coordinated'
      ? `The actual plan · ${state.coordination?.plan_name ?? 'committed'}`
      : `${VIEW_LABEL[shownKind]}${state.coordinated_schedule ? ' · for comparison' : ' · not coordinated yet'}`

  return (
    <section className="card timeline-card">
      <div className="card-head">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2>Appliances find their window.</h2>
        </div>
        <ul className="legend legend-sm">
          {state.homes.map((h) => (
            <li key={h.id}><span className="dot" style={{ background: h.color }} />{h.name}</li>
          ))}
          <li><span className="deadline-key" aria-hidden />Finish-by deadline</li>
          {requested.size > 0 && <li><span className="deadline-key requested" aria-hidden />Requested, waiting for confirm</li>}
        </ul>
      </div>

      <div className="tl">
        <div className="tl-axis">
          <span className="tl-label tl-label-head">Home / appliance · finish by</span>
          <div className="tl-track">
            {ticks.map((t) => (
              <span key={t} className="tl-tick" style={{ left: pct(t) }}>{slotToTick(t)}</span>
            ))}
          </div>
        </div>
        {tasks.map((t) => {
          const e = schedule.find((x) => x.task_id === t.id)
          const c = color.get(t.home_id) ?? '#7a847d'
          const startPct = e ? (e.start_slot / end) * 100 : 0
          const widthPct = e ? (e.duration_slots / end) * 100 : 0
          const wide = widthPct > 9
          const range = e ? `${slotToTime(e.start_slot)}–${slotToTime(e.start_slot + e.duration_slots)}` : ''
          const late = e ? e.start_slot + e.duration_slots > t.deadline_slot : false
          const was = firstDeadline.current.map.get(t.id)
          const changed = was !== undefined && was !== t.deadline_slot
          const req = requested.get(t.id)
          return (
            <div key={t.id} className="tl-row">
              <span className="tl-label">
                <span className="dot" style={{ background: c }} />
                <b>Home {t.home_id}</b> <span className="muted">{t.name}</span>
                <span className={`tl-due ${changed ? 'changed' : ''}`}
                  title={changed ? `Changed from ${slotToTime(was!)} to ${slotToTime(t.deadline_slot)}` : 'Finish-by deadline'}>
                  by {slotToTime(t.deadline_slot)}{changed ? ` (was ${slotToTime(was!)})` : ''}
                </span>
              </span>
              <div className="tl-track">
                {ticks.map((k) => <span key={k} className="tl-grid" style={{ left: pct(k) }} />)}
                <span className={`tl-deadline ${changed ? 'changed' : ''}`} style={{ left: pct(t.deadline_slot), borderColor: c }}
                  title={`Finish by ${slotToTime(t.deadline_slot)}`} />
                {req !== undefined && req !== t.deadline_slot && (
                  <span className="tl-deadline requested" style={{ left: pct(req) }}
                    title={`Requested: finish by ${slotToTime(req)} (waiting for the resident to confirm)`}>
                    <span className="tl-req-label">requested {slotToTime(req)}</span>
                  </span>
                )}
                {e && (
                  <span
                    className={`tl-bar ${late ? 'late' : ''}`}
                    style={{ left: `${startPct}%`, width: `${widthPct}%`, background: c }}
                    title={`Home ${t.home_id} ${t.name}: ${range} · ${t.power_kw} kW · finish by ${slotToTime(t.deadline_slot)}`}
                  >
                    {wide && <span className="tl-bar-label">{range}</span>}
                  </span>
                )}
                {e && !wide && (
                  <span className="tl-out-label" style={{ left: `calc(${startPct + widthPct}% + 6px)` }}>
                    {slotToTime(e.start_slot)}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
