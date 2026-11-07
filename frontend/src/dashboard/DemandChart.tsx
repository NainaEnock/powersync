// Street demand tonight (PRD §17): a focus line chosen by the segmented control, the preferred-times
// baseline as a dashed reference, the shared limit, over-limit fill, and expensive-hour shading.
import { useEffect, useMemo, useState } from 'react'
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
import type { NeighborhoodState, ScheduleKind, Task } from '../types'
import { kw } from './format'

const LABEL: Record<ScheduleKind, string> = {
  baseline: 'Preferred times',
  independent: 'Cheap timer',
  coordinated: 'Coordinated',
}
const FOCUS = '#2f5d46'
const REF = '#9aa39c'
const LIMIT = '#c8553d'

/** The part of the night where appliances can run: up to the latest deadline (at least 6:00 AM), on a 2-hour tick. */
export function windowEnd(tasks: Task[]): number {
  return Math.min(SLOTS, Math.ceil(Math.max(48, ...tasks.map((t) => t.deadline_slot)) / 8) * 8)
}

/** Contiguous runs of slots priced above the cheapest rate. Empty under a flat tariff. */
export function expensiveRuns(prices: number[]): [number, number][] {
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

/** Which schedule the chart and timeline show. Jumps to the coordinated plan when one first commits,
 *  and back to preferred times after a reset. Shared so both views always agree. */
export function useScheduleFocus(state: NeighborhoodState | null) {
  const hasPlan = !!state?.demand_kw.coordinated
  const [focus, setFocus] = useState<ScheduleKind>(hasPlan ? 'coordinated' : 'baseline')
  useEffect(() => {
    setFocus(hasPlan ? 'coordinated' : 'baseline')
  }, [hasPlan])
  return [focus, setFocus] as const
}

export function DemandChart({ state, focus, onFocus, onFlatChange, tariffBusy }: {
  state: NeighborhoodState
  focus: ScheduleKind
  onFocus: (k: ScheduleKind) => void
  onFlatChange: (flat: boolean) => void
  tariffBusy: boolean
}) {
  const setFocus = onFocus
  const cap = state.capacity_kw
  const d = state.demand_kw
  const xEnd = windowEnd(state.tasks)

  const rows = useMemo(() => {
    const at = (arr: number[] | null | undefined, s: number) => (arr ? arr[Math.min(s, SLOTS - 1)] : null)
    return Array.from({ length: SLOTS + 1 }, (_, s) => {
      const f = at(d[focus], s)
      return {
        slot: s,
        focus: f,
        baseline: at(d.baseline, s),
        over: [cap, Math.max(cap, f ?? 0)] as [number, number],
      }
    })
  }, [d, focus, cap])

  const runs = useMemo(() => expensiveRuns(state.tariff_usd_per_kwh), [state.tariff_usd_per_kwh])
  const peakAll = Math.max(cap, ...(d.baseline ?? []), ...(d.independent ?? []))
  const yMax = Math.ceil((peakAll + 2) / 5) * 5
  const yTicks = Array.from({ length: yMax / 5 + 1 }, (_, i) => i * 5)
  const xTicks = Array.from({ length: xEnd / 8 + 1 }, (_, i) => i * 8)
  const anyOver = rows.some((r) => (r.focus ?? 0) > cap + 1e-6)
  const peakPrice = Math.max(...state.tariff_usd_per_kwh)

  return (
    <section className="card chart-card">
      <div className="card-head">
        <div>
          <div className="eyebrow">Demand tonight</div>
          <h2>Peak, meet a better plan.</h2>
        </div>
        <div className="segmented" role="tablist" aria-label="Schedule">
          {(['baseline', 'independent', 'coordinated'] as const).map((k) => (
            <button key={k} role="tab" aria-selected={focus === k} className={focus === k ? 'on' : ''}
              disabled={!d[k]} onClick={() => setFocus(k)} title={!d[k] ? 'Not planned yet' : undefined}>
              {LABEL[k]}
            </button>
          ))}
        </div>
      </div>

      <div className="legend-row">
        <ul className="legend">
          <li><svg width="22" height="8" aria-hidden><line x1="1" y1="4" x2="21" y2="4" stroke={FOCUS} strokeWidth="2.5" strokeLinecap="round" /></svg>{LABEL[focus]}</li>
          {focus !== 'baseline' && (
            <li><svg width="22" height="8" aria-hidden><line x1="1" y1="4" x2="21" y2="4" stroke={REF} strokeWidth="1.5" strokeDasharray="4 3" /></svg>Preferred-times baseline</li>
          )}
          <li><svg width="22" height="8" aria-hidden><line x1="1" y1="4" x2="21" y2="4" stroke={LIMIT} strokeWidth="1.5" strokeDasharray="5 4" /></svg>{cap} kW shared limit</li>
          {anyOver && <li><span className="swatch swatch-over" aria-hidden />Over the limit</li>}
        </ul>
        <label className="check" title="Changes the prices the planner, agents, and metrics use (POST /api/tariff)">
          <input type="checkbox" checked={state.tariff_mode === 'flat'} disabled={tariffBusy}
            onChange={(e) => onFlatChange(e.target.checked)} />
          Flat-rate control
        </label>
      </div>

      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#eceee8" vertical={false} />
            {runs.map(([a, b]) => (
              <ReferenceArea key={a} x1={a} x2={b} fill="#fbe9df" fillOpacity={0.75} stroke="none" ifOverflow="hidden" />
            ))}
            <XAxis dataKey="slot" type="number" domain={[0, xEnd]} ticks={xTicks} allowDataOverflow
              tickFormatter={slotToTick} stroke="#cfd4ca" tick={{ fill: '#7a847d', fontSize: 12 }} tickLine={false} />
            <YAxis domain={[0, yMax]} ticks={yTicks} tickFormatter={(v: number) => `${v} kW`}
              tick={{ fill: '#7a847d', fontSize: 12 }} tickLine={false} axisLine={false} width={52} />
            <Area dataKey="over" type="stepAfter" stroke="none" fill={LIMIT} fillOpacity={0.16}
              isAnimationActive={false} activeDot={false} />
            {focus !== 'baseline' && (
              <Line dataKey="baseline" type="stepAfter" stroke={REF} strokeWidth={1.5} strokeDasharray="4 3"
                dot={false} activeDot={false} isAnimationActive={false} />
            )}
            <ReferenceLine y={cap} stroke={LIMIT} strokeDasharray="5 4" strokeWidth={1.5}
              label={{ value: `${cap} kW shared limit`, position: 'insideTopRight', fill: LIMIT, fontSize: 12 }} />
            <Line dataKey="focus" type="stepAfter" stroke={FOCUS} strokeWidth={2.5} dot={false}
              isAnimationActive={false} activeDot={{ r: 4, stroke: '#fff', strokeWidth: 2 }} />
            <Tooltip
              cursor={{ stroke: '#9aa39c', strokeWidth: 1 }}
              content={({ active, label }) => {
                const s = typeof label === 'number' ? Math.min(label, SLOTS - 1) : null
                if (!active || s === null) return null
                const r = rows[s]
                return (
                  <div className="tip">
                    <div className="tip-time">{slotToTime(s)}–{slotToTime(s + 1)}</div>
                    <div className="tip-row"><span className="tip-key" style={{ background: FOCUS }} />{LABEL[focus]}<b>{r.focus === null ? '—' : kw(r.focus)}</b></div>
                    {focus !== 'baseline' && (
                      <div className="tip-row"><span className="tip-key" style={{ background: REF }} />Preferred times<b>{r.baseline === null ? '—' : kw(r.baseline)}</b></div>
                    )}
                    <div className="tip-foot">${state.tariff_usd_per_kwh[s]?.toFixed(2)}/kWh · limit {cap} kW</div>
                  </div>
                )
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-foot">
        {runs.length > 0 ? (
          <span><span className="swatch swatch-peak" aria-hidden /> Shaded = expensive hours, ${peakPrice.toFixed(2)}/kWh</span>
        ) : (
          <span>Flat rate: every hour costs the same, so moving appliances can't change the bill.</span>
        )}
        <span>All demand is modeled.</span>
      </div>
    </section>
  )
}
