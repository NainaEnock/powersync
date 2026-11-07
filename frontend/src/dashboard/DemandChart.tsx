// Street demand over the evening: preferred times, optional cheap timer, coordinated plan,
// the shared limit, and shading for expensive hours (PRD §17).
import { useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { SLOTS, slotToTick, slotToTime } from '../time'
import type { NeighborhoodState } from '../types'
import { kw } from './format'

// Validated (dataviz validate_palette.js, dark, surface #111c33): all checks pass.
export const SERIES = {
  baseline: { label: 'Everyone at preferred times', color: '#d95926', dash: undefined },
  independent: { label: 'Everyone uses a cheap timer', color: '#199e70', dash: '6 4' },
  coordinated: { label: 'Coordinated plan', color: '#3987e5', dash: undefined },
} as const

type Row = {
  slot: number
  baseline: number | null
  independent: number | null
  coordinated: number | null
  over: [number, number]
}

/** Contiguous runs of slots priced above the cheapest rate. Empty under a flat tariff. */
function expensiveRuns(prices: number[]): [number, number][] {
  if (prices.length === 0) return []
  const min = Math.min(...prices)
  const runs: [number, number][] = []
  let start: number | null = null
  prices.forEach((p, s) => {
    if (p > min + 1e-9 && start === null) start = s
    if (p <= min + 1e-9 && start !== null) {
      runs.push([start, s])
      start = null
    }
  })
  if (start !== null) runs.push([start, prices.length])
  return runs
}

export function DemandChart({ state }: { state: NeighborhoodState }) {
  const [showTimer, setShowTimer] = useState(true)
  const cap = state.capacity_kw
  const d = state.demand_kw
  const hasPlan = !!d.coordinated

  const rows = useMemo<Row[]>(() => {
    const at = (arr: number[] | null | undefined, s: number) => (arr ? arr[Math.min(s, SLOTS - 1)] : null)
    // One extra point at slot 96 closes the final step.
    return Array.from({ length: SLOTS + 1 }, (_, s) => {
      const b = at(d.baseline, s) ?? 0
      return {
        slot: s,
        baseline: at(d.baseline, s),
        independent: at(d.independent, s),
        coordinated: at(d.coordinated, s),
        over: [cap, Math.max(cap, b)],
      }
    })
  }, [d.baseline, d.independent, d.coordinated, cap])

  const runs = useMemo(() => expensiveRuns(state.tariff_usd_per_kwh), [state.tariff_usd_per_kwh])
  const yMax = Math.ceil(Math.max(cap + 3, ...rows.map((r) => Math.max(r.baseline ?? 0, r.independent ?? 0))) / 5) * 5
  const yTicks = Array.from({ length: yMax / 5 + 1 }, (_, i) => i * 5)
  // Zoom to the part of the night where appliances can run: up to the latest deadline
  // (at least 6:00 AM), rounded to a 2-hour tick. After that it's only always-on use.
  const xEnd = Math.min(SLOTS, Math.ceil(Math.max(48, ...state.tasks.map((t) => t.deadline_slot)) / 8) * 8)
  const xTicks = Array.from({ length: xEnd / 8 + 1 }, (_, i) => i * 8)

  const visible = (['baseline', 'independent', 'coordinated'] as const).filter(
    (k) => (k !== 'independent' || showTimer) && (k !== 'coordinated' || hasPlan),
  )

  return (
    <section className="card chart-card">
      <div className="chart-head">
        <h2>
          Street demand tonight <span className="muted chart-sub">· {state.tariff_label}</span>
        </h2>
        <ul className="legend" aria-label="Legend">
          {visible.map((k) => (
            <li key={k}>
              <svg width="22" height="8" aria-hidden>
                <line x1="1" y1="4" x2="21" y2="4" stroke={SERIES[k].color} strokeWidth="2"
                  strokeDasharray={SERIES[k].dash} strokeLinecap="round" />
              </svg>
              {SERIES[k].label}
            </li>
          ))}
          <li>
            <svg width="22" height="8" aria-hidden>
              <line x1="1" y1="4" x2="21" y2="4" stroke="var(--fg)" strokeWidth="1.5" strokeDasharray="3 3" />
            </svg>
            {cap} kW street limit
          </li>
          {runs.length > 0 && (
            <li><span className="swatch-peak" aria-hidden /> Expensive hours</li>
          )}
          {!hasPlan && <li className="muted">Coordinated plan: not planned yet</li>}
        </ul>
        <label className="toggle">
          <input type="checkbox" checked={showTimer} onChange={(e) => setShowTimer(e.target.checked)} />
          Show cheap timer
        </label>
      </div>

      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            {runs.map(([a, b]) => (
              <ReferenceArea key={a} x1={a} x2={b} fill="var(--peak-shade)" fillOpacity={1} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis
              dataKey="slot"
              type="number"
              domain={[0, xEnd]}
              ticks={xTicks}
              allowDataOverflow
              tickFormatter={slotToTick}
              stroke="var(--muted)"
              tick={{ fill: 'var(--muted)', fontSize: 12 }}
              tickLine={false}
            />
            <YAxis
              domain={[0, yMax]}
              ticks={yTicks}
              tickFormatter={(v: number) => `${v} kW`}
              stroke="var(--muted)"
              tick={{ fill: 'var(--muted)', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={56}
            />
            {/* Over-limit area under preferred times: always visible. */}
            <Area dataKey="over" type="stepAfter" stroke="none" fill={SERIES.baseline.color} fillOpacity={0.28}
              isAnimationActive={false} activeDot={false} />
            <ReferenceLine y={cap} stroke="var(--fg)" strokeDasharray="3 3" strokeWidth={1.5}
              label={{ value: `${cap} kW limit`, position: 'insideTopRight', fill: 'var(--fg)', fontSize: 12 }} />
            {visible.map((k) => (
              <Line key={k} dataKey={k} type="stepAfter" stroke={SERIES[k].color} strokeWidth={2}
                strokeDasharray={SERIES[k].dash} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: 'var(--card)', strokeWidth: 2 }} />
            ))}
            <Tooltip
              cursor={{ stroke: 'var(--muted)', strokeWidth: 1 }}
              content={({ active, label }) => {
                const s = typeof label === 'number' ? Math.min(label, SLOTS - 1) : null
                if (!active || s === null) return null
                const r = rows[s]
                return (
                  <div className="tip">
                    <div className="tip-time">{slotToTime(s)}–{slotToTime(s + 1)}</div>
                    {visible.map((k) => (
                      <div key={k} className="tip-row">
                        <span className="tip-key" style={{ background: SERIES[k].color }} />
                        <span>{SERIES[k].label}</span>
                        <b>{r[k] === null ? '—' : kw(r[k]!)}</b>
                      </div>
                    ))}
                    <div className="tip-foot">
                      ${state.tariff_usd_per_kwh[s]?.toFixed(2)}/kWh · limit {cap} kW
                    </div>
                  </div>
                )
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}
