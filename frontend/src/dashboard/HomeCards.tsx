// Per-home result for whichever schedule the chart switch shows, with the change vs. preferred times
// (increases included, shown in red).
import { Clock, House } from 'lucide-react'
import { slotToTime } from '../time'
import type { HomeId, NeighborhoodState, ScheduleEntry, ScheduleKind } from '../types'
import { usd, usdDelta } from './format'

export function HomeCards({ state, focus = 'coordinated' }: { state: NeighborhoodState; focus?: ScheduleKind }) {
  const schedules: Record<ScheduleKind, ScheduleEntry[] | null> = {
    baseline: state.baseline_schedule,
    independent: state.independent_schedule,
    coordinated: state.coordinated_schedule,
  }
  const kind: ScheduleKind = schedules[focus] && state.metrics[focus] ? focus : state.coordinated_schedule ? 'coordinated' : 'baseline'
  const schedule = schedules[kind] ?? []
  const shown = state.metrics[kind]
  const base = state.metrics.baseline

  return (
    <section className="card homes-card" aria-label="Homes">
      <div className="homes">
        {state.homes.map((h) => {
          const id = h.id as HomeId
          const tasks = state.tasks.filter((t) => t.home_id === id)
          const entries = schedule.filter((e) => e.home_id === id)
          const onTime = tasks.filter((t) => {
            const e = entries.find((x) => x.task_id === t.id)
            return e && e.start_slot + e.duration_slots <= t.deadline_slot
          }).length
          const before = base?.per_home[id]?.variable_cost_usd
          const now = shown?.per_home[id]?.variable_cost_usd
          const lastEnd = Math.max(...entries.map((e) => e.start_slot + e.duration_slots))
          const deadlines = [...new Set(tasks.map((t) => slotToTime(t.deadline_slot)))].join(' · ')
          const busy = state.activity?.includes(h.name)
          const showDelta = kind !== 'baseline' && now !== undefined && before !== undefined
          return (
            <article key={h.id} className="home">
              <span className="home-icon" style={{ color: h.color, background: `color-mix(in srgb, ${h.color} 12%, white)` }}>
                <House size={18} />
              </span>
              <div className="home-main">
                <div className="home-name">
                  <b>{h.name}</b> <span className="muted">{onTime}/{tasks.length} on time</span>
                </div>
                <div className="muted home-meta" title={`Finish by ${deadlines}`}>
                  {busy ? (
                    <span className="home-busy">{state.activity}</span>
                  ) : (
                    <><Clock size={12} /> {Number.isFinite(lastEnd) ? `All done by ${slotToTime(lastEnd)}` : ''}</>
                  )}
                </div>
              </div>
              <div className="home-cost" title="Modeled energy charge, change vs. preferred times">
                <b>{now !== undefined ? usd(now) : '—'}</b>
                <span className={showDelta && now! > before! + 0.005 ? 'up' : 'muted'}>
                  {showDelta ? usdDelta(now!, before!) : 'preferred times'}
                </span>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
