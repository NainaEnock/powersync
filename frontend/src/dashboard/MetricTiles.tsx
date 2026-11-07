import { CircleCheck, DollarSign, Gauge, Zap, type LucideIcon } from 'lucide-react'
import type { Metrics, NeighborhoodState } from '../types'
import { kw, kwh, usd, usdDelta } from './format'

interface TileSpec {
  key: string
  title: string
  Icon: LucideIcon
  tint: string
  value: (m: Metrics) => number
  fmt: (n: number) => string
  sub: (head: Metrics, base: Metrics | null) => string
  baseLabel: (base: Metrics) => string
}

export function MetricTiles({ state }: { state: NeighborhoodState }) {
  const { baseline, independent, coordinated } = state.metrics
  const cap = state.capacity_kw
    const head = coordinated ?? null

  const tiles: TileSpec[] = [
    {
      key: 'cost', title: state.tariff_mode === 'flat' ? 'Flat-rate charge' : 'Energy charge', Icon: DollarSign, tint: 'tint-green',
      value: (m) => m.variable_cost_usd, fmt: usd,
      sub: (h, b) => (b ? `${usdDelta(h.variable_cost_usd, b.variable_cost_usd)} vs. preferred times` : ''),
      baseLabel: (b) => `Preferred ${usd(b.variable_cost_usd)} · Timer ${independent ? usd(independent.variable_cost_usd) : '—'}`,
    },
    {
      key: 'peak', title: 'Street peak', Icon: Gauge, tint: 'tint-blue',
      value: (m) => m.peak_kw, fmt: kw,
      sub: (h, b) => (b ? `−${(b.peak_kw - h.peak_kw).toFixed(1)} kW vs. preferred times` : ''),
      baseLabel: (b) => `Preferred ${kw(b.peak_kw)} · Timer ${independent ? kw(independent.peak_kw) : '—'}`,
    },
    {
      key: 'energy', title: 'Energy used', Icon: Zap, tint: 'tint-amber',
      value: (m) => m.energy_kwh, fmt: kwh,
      sub: () => 'Same appliances, same energy.',
      baseLabel: (b) => `Preferred ${kwh(b.energy_kwh)} · same`,
    },
    {
      key: 'done', title: 'Done on time', Icon: CircleCheck, tint: 'tint-violet',
      value: (m) => m.tasks_completed, fmt: (n) => `${n} / ${head?.tasks_total ?? baseline?.tasks_total ?? 6}`,
      sub: (h) => (h.capacity_violations === 0 ? `Under ${cap} kW all night · validated` : `${h.capacity_violations} periods over the limit`),
      baseLabel: (b) => `Preferred: ${b.capacity_violations} periods over limit`,
    },
  ]

  return (
    <section className="tiles" aria-label="Metrics">
      {tiles.map((t) => (
        <div key={t.key} className="tile">
          <div className="tile-head">
            <span className={`tile-icon ${t.tint}`}><t.Icon size={16} /></span>
            <span className="tile-title">{t.title}</span>
          </div>
          {head ? (
            <>
              <div className="tile-value">{t.fmt(t.value(head))}</div>
              <div className="tile-sub">{t.sub(head, baseline ?? null)}</div>
            </>
          ) : baseline ? (
            <>
              <div className="tile-value tile-value-muted">{t.fmt(t.value(baseline))}</div>
              <div className="tile-sub">Preferred times · not coordinated</div>
            </>
          ) : null}
          {head && baseline && <div className="tile-base">{t.baseLabel(baseline)}</div>}
        </div>
      ))}
    </section>
  )
}
