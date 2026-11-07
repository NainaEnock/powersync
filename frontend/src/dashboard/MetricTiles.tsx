// Metric tiles for whichever schedule the chart switch shows (preferred times, cheap timer, or the
// coordinated plan), each compared against the other two so the difference is always named.
import { CircleCheck, DollarSign, Gauge, Zap, type LucideIcon } from 'lucide-react'
import type { Metrics, NeighborhoodState, ScheduleKind } from '../types'
import { kw, kwh, usd, usdDelta } from './format'

export const SCHEDULE_NAME: Record<ScheduleKind, string> = {
  baseline: 'Preferred times',
  independent: 'Cheap timer',
  coordinated: 'Coordinated plan',
}
const SHORT: Record<ScheduleKind, string> = { baseline: 'Preferred', independent: 'Timer', coordinated: 'Plan' }

interface TileSpec {
  key: string
  title: string
  Icon: LucideIcon
  tint: string
  value: (m: Metrics) => number
  fmt: (n: number) => string
  /** One line about the shown schedule: compared with preferred times, or against the limit. */
  sub: (m: Metrics, base: Metrics | null, kind: ScheduleKind) => { text: string; bad?: boolean }
}

export function MetricTiles({ state, focus = 'coordinated' }: { state: NeighborhoodState; focus?: ScheduleKind }) {
  const all = state.metrics
  const kind: ScheduleKind = all[focus] ? focus : all.coordinated ? 'coordinated' : 'baseline'
  const head = all[kind] ?? null
  const base = all.baseline ?? null
  const cap = state.capacity_kw
  const others = (['baseline', 'independent', 'coordinated'] as const).filter((k) => k !== kind && all[k])

  const tiles: TileSpec[] = [
    {
      key: 'cost', title: state.tariff_mode === 'flat' ? 'Flat-rate charge' : 'Energy charge', Icon: DollarSign, tint: 'tint-green',
      value: (m) => m.variable_cost_usd, fmt: usd,
      sub: (m, b, k) => (k === 'baseline' || !b ? { text: 'Everyone at preferred times' } : {
        text: `${usdDelta(m.variable_cost_usd, b.variable_cost_usd)} vs. preferred times`,
        bad: m.variable_cost_usd > b.variable_cost_usd + 0.005,
      }),
    },
    {
      key: 'peak', title: 'Street peak', Icon: Gauge, tint: 'tint-blue',
      value: (m) => m.peak_kw, fmt: kw,
      sub: (m) => (m.peak_kw > cap + 1e-6
        ? { text: `${(m.peak_kw - cap).toFixed(1)} kW over the ${cap} kW limit`, bad: true }
        : { text: `${(cap - m.peak_kw).toFixed(1)} kW under the ${cap} kW limit` }),
    },
    {
      key: 'energy', title: 'Energy used', Icon: Zap, tint: 'tint-amber',
      value: (m) => m.energy_kwh, fmt: kwh,
      sub: () => ({ text: 'Same appliances, same energy.' }),
    },
    {
      key: 'done', title: 'Done on time', Icon: CircleCheck, tint: 'tint-violet',
      value: (m) => m.tasks_completed, fmt: (n) => `${n} / ${head?.tasks_total ?? 6}`,
      sub: (m) => (m.capacity_violations === 0
        ? { text: `Under ${cap} kW all night${kind === 'coordinated' ? ' · validated' : ''}` }
        : { text: `${m.capacity_violations} periods over the limit`, bad: true }),
    },
  ]

  return (
    <section className="tiles" aria-label={`Metrics for ${SCHEDULE_NAME[kind]}`}>
      {tiles.map((t) => {
        const sub = head ? t.sub(head, base, kind) : null
        return (
          <div key={t.key} className="tile">
            <div className="tile-head">
              <span className={`tile-icon ${t.tint}`}><t.Icon size={16} /></span>
              <span className="tile-title">{t.title}</span>
              <span className={`tile-kind kind-${kind}`}>{SHORT[kind]}</span>
            </div>
            {head ? (
              <>
                <div className="tile-value">{t.fmt(t.value(head))}</div>
                <div className={`tile-sub ${sub?.bad ? 'bad' : ''}`}>{sub?.text}</div>
                {others.length > 0 && (
                  <div className="tile-base">
                    {others.map((k) => `${SHORT[k]} ${t.fmt(t.value(all[k]!))}`).join(' · ')}
                  </div>
                )}
              </>
            ) : null}
          </div>
        )
      })}
    </section>
  )
}
