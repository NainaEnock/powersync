// Task timeline (PRD §17): one row per appliance, bars at actual run times, a dashed finish-by marker.
// Short bars put their label outside so it stays readable.
import { slotToTick, slotToTime } from '../time'
import type { NeighborhoodState } from '../types'
import { windowEnd } from './DemandChart'

export function Timeline({ state }: { state: NeighborhoodState }) {
  const plan = state.coordinated_schedule
  const schedule = plan ?? state.baseline_schedule
  const end = windowEnd(state.tasks)
  const pct = (slot: number) => `${(Math.min(slot, end) / end) * 100}%`
  const ticks = Array.from({ length: end / 8 + 1 }, (_, i) => i * 8)
  const color = new Map(state.homes.map((h) => [h.id, h.color]))
  const tasks = [...state.tasks].sort((a, b) => a.home_id.localeCompare(b.home_id) || a.name.localeCompare(b.name))

  return (
    <section className="card timeline-card">
      <div className="card-head">
        <div>
          <div className="eyebrow">{plan ? `The actual plan · ${state.coordination?.plan_name ?? 'committed'}` : 'Preferred times · not coordinated yet'}</div>
          <h2>Appliances find their window.</h2>
        </div>
        <ul className="legend legend-sm">
          {state.homes.map((h) => (
            <li key={h.id}><span className="dot" style={{ background: h.color }} />{h.name}</li>
          ))}
          <li><span className="deadline-key" aria-hidden />Finish-by deadline</li>
        </ul>
      </div>

      <div className="tl">
        <div className="tl-axis">
          <span className="tl-label tl-label-head">Home / appliance</span>
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
          return (
            <div key={t.id} className="tl-row">
              <span className="tl-label">
                <span className="dot" style={{ background: c }} />
                <b>Home {t.home_id}</b> <span className="muted">{t.name}</span>
              </span>
              <div className="tl-track">
                {ticks.map((k) => <span key={k} className="tl-grid" style={{ left: pct(k) }} />)}
                <span className="tl-deadline" style={{ left: pct(t.deadline_slot), borderColor: c }}
                  title={`Finish by ${slotToTime(t.deadline_slot)}`} />
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
