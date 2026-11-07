import { RotateCcw, Users } from 'lucide-react'
import { useHealth, usePoll, type Api } from '../api'
import { StatusBadge } from '../StatusBadge'
import type { Metrics } from '../types'
import './dashboard.css'

const usd = (n: number) => `$${n.toFixed(2)}`

export function Dashboard({ api }: { api: Api }) {
  const health = useHealth(api)
  const state = usePoll((signal) => api.state(undefined, signal), [api])
  const s = state.data

  const rows: [string, Metrics | null | undefined][] = [
    ['Everyone at preferred times', s?.metrics.baseline],
    ['Everyone uses a cheap timer', s?.metrics.independent],
    ['Coordinated plan', s?.metrics.coordinated],
  ]

  return (
    <div className="dash">
      <header className="dash-top">
        <h1>PowerSync</h1>
        <StatusBadge api={api} health={health} />
        <div className="dash-top-right">
          {s && <span className="muted">Revision {s.revision}</span>}
          {s && <span className="muted">{s.tariff_label}</span>}
          <button disabled title="Coming in B8"><Users size={16} /> Coordinate neighborhood</button>
          <button disabled title="Coming in B8"><RotateCcw size={16} /> Reset</button>
        </div>
      </header>

      {api.mode === 'sample' && (
        <div className="banner-sample">Sample data. These numbers come from the PRD scenario, not the live backend.</div>
      )}
      {state.error && <div className="banner-error">{state.error.message}</div>}

      {s && (
        <section className="card">
          <h2>Neighborhood totals (limit {s.capacity_kw} kW)</h2>
          <table className="metrics">
            <thead>
              <tr>
                <th>Schedule</th><th>Energy charge</th><th>Peak demand</th>
                <th>Over-limit periods</th><th>Energy</th><th>Tasks done</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, m]) => (
                <tr key={label}>
                  <td>{label}</td>
                  {m ? (
                    <>
                      <td>{usd(m.variable_cost_usd)}</td>
                      <td>{m.peak_kw.toFixed(1)} kW</td>
                      <td>{m.capacity_violations}</td>
                      <td>{m.energy_kwh.toFixed(2)} kWh</td>
                      <td>{m.tasks_completed}/{m.tasks_total}</td>
                    </>
                  ) : (
                    <td colSpan={5} className="muted">Not planned yet</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
