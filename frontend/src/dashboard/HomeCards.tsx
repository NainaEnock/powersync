import { Clock, House } from 'lucide-react'
import { slotToTime } from '../time'
import type { HomeId, NeighborhoodState } from '../types'
import { usd, usdDelta } from './format'

export function HomeCards({ state }: { state: NeighborhoodState }) {
  const plan = state.coordinated_schedule
  const { baseline, coordinated } = state.metrics

  return (
    <section className="card homes-card" aria-label="Homes">
      <div className="homes">
        {state.homes.map((h) => {
          const id = h.id as HomeId
          const tasks = state.tasks.filter((t) => t.home_id === id)
          const entries = (plan ?? state.baseline_schedule).filter((e) => e.home_id === id)
          const onTime = tasks.filter((t) => {
            const e = entries.find((x) => x.task_id === t.id)
            return e && e.start_slot + e.duration_slots <= t.deadline_slot
          }).length
          const before = baseline?.per_home[id]?.variable_cost_usd
          const after = coordinated?.per_home[id]?.variable_cost_usd
          const lastEnd = Math.max(...entries.map((e) => e.start_slot + e.duration_slots))
          const deadlines = [...new Set(tasks.map((t) => slotToTime(t.deadline_slot)))].join(' · ')
          const busy = state.activity?.includes(h.name)
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
                <b>{after !== undefined ? usd(after) : before !== undefined ? usd(before) : '—'}</b>
                <span className={after !== undefined && before !== undefined && after > before + 0.005 ? 'up' : 'muted'}>
                  {after !== undefined && before !== undefined ? usdDelta(after, before) : 'preferred times'}
                </span>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
