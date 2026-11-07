import type { Metrics, NeighborhoodState } from '../types'
import { kw, kwh, usd, usdDelta } from './format'

type Pick = (m: Metrics) => number

interface TileSpec {
  title: string
  value: Pick
  fmt: (n: number) => string
  delta?: (after: number, before: number) => string
  note?: string
}

export function MetricTiles({ state }: { state: NeighborhoodState }) {
  const { baseline, independent, coordinated } = state.metrics
  const cap = state.capacity_kw

  const tiles: TileSpec[] = [
    { title: 'Energy charge', value: (m) => m.variable_cost_usd, fmt: usd, delta: usdDelta },
    {
      title: 'Peak street demand',
      value: (m) => m.peak_kw,
      fmt: kw,
      delta: (a, b) => (Math.abs(a - b) < 0.05 ? 'no change' : `${a < b ? '−' : '+'}${Math.abs(a - b).toFixed(1)} kW`),
    },
    { title: 'Energy used', value: (m) => m.energy_kwh, fmt: kwh, note: 'Moving appliances never changes it.' },
    {
      title: 'Appliances done on time',
      value: (m) => m.tasks_completed,
      fmt: (n) => `${n} of ${baseline?.tasks_total ?? coordinated?.tasks_total ?? 6}`,
    },
  ]

  return (
    <section className="tiles" aria-label="Metrics">
      {tiles.map((t) => {
        const head = coordinated ?? null
        return (
          <div key={t.title} className="tile">
            <div className="tile-title">{t.title}</div>
            <div className="tile-value">
              {head ? t.fmt(t.value(head)) : <span className="muted">Not planned yet</span>}
            </div>
            {head && baseline && t.delta && (
              <div className="tile-delta">{t.delta(t.value(head), t.value(baseline))} vs. preferred times</div>
            )}
            <dl className="tile-compare">
              {baseline && (
                <div>
                  <dt>Preferred times</dt>
                  <dd>
                    {t.fmt(t.value(baseline))}
                    {t.title === 'Peak street demand' && baseline.peak_kw > cap && <span className="over"> over limit</span>}
                  </dd>
                </div>
              )}
              {independent && (
                <div>
                  <dt>Cheap timer</dt>
                  <dd>
                    {t.fmt(t.value(independent))}
                    {t.title === 'Peak street demand' && independent.peak_kw > cap && <span className="over"> over limit</span>}
                  </dd>
                </div>
              )}
            </dl>
            {t.note && <div className="tile-note muted">{t.note}</div>}
          </div>
        )
      })}
    </section>
  )
}
