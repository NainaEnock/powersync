import { slotToTime } from '../time'
import type { HomeId, NeighborhoodState, ScheduleEntry } from '../types'
import { usd, usdDelta } from './format'

export function HomeCards({ state }: { state: NeighborhoodState }) {
  const plan = state.coordinated_schedule
  const { baseline, coordinated } = state.metrics
  const planName = state.coordination?.plan_name

  return (
    <section className="homes" aria-label="Homes">
      {state.homes.map((h) => {
        const tasks = state.tasks.filter((t) => t.home_id === h.id)
        const entries: ScheduleEntry[] = (plan ?? state.baseline_schedule).filter((e) => e.home_id === h.id)
        const before = baseline?.per_home[h.id as HomeId]?.variable_cost_usd
        const after = coordinated?.per_home[h.id as HomeId]?.variable_cost_usd
        const busy = state.activity?.includes(h.name)
        return (
          <article key={h.id} className="home-card" style={{ borderTopColor: h.color }}>
            <header>
              <span className="home-dot" style={{ background: h.color }} aria-hidden />
              <h3>{h.name}</h3>
              <span className={`home-status ${busy ? 'busy' : ''}`}>
                {busy ? state.activity : plan ? `On ${planName ?? 'the street plan'}` : 'Preferred times'}
              </span>
            </header>
            <ul className="home-tasks">
              {tasks.map((t) => {
                const e = entries.find((x) => x.task_id === t.id)
                return (
                  <li key={t.id}>
                    <span className="task-name">{t.name}</span>
                    <span className="task-time">
                      {e ? `${slotToTime(e.start_slot)}–${slotToTime(e.start_slot + e.duration_slots)}` : '—'}
                    </span>
                    <span className="muted task-deadline">done by {slotToTime(t.deadline_slot)}</span>
                  </li>
                )
              })}
            </ul>
            <div className="home-cost">
              {after !== undefined && before !== undefined ? (
                <>
                  <b>{usd(after)}</b>{' '}
                  <span className={after > before + 0.005 ? 'over' : 'muted'}>
                    {usdDelta(after, before)} vs. preferred times
                  </span>
                </>
              ) : before !== undefined ? (
                <span className="muted">{usd(before)} at preferred times</span>
              ) : null}
            </div>
          </article>
        )
      })}
    </section>
  )
}
