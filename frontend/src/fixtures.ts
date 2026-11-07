// SAMPLE DATA ONLY. Built from PRD §9 so the UI can render before the backend runs.
// Every screen that shows this must label it "Sample data".
// No agent events and no coordinated plan: those only ever come from the live backend.

import type {
  Home,
  HomeId,
  Metrics,
  NeighborhoodState,
  ScheduleEntry,
  Task,
} from './types'
import { SLOTS } from './time'

const CAPACITY_KW = 15
const BACKGROUND_KW = 1.2
const TOU_PEAK = 0.59
const TOU_OFF = 0.33
const FLAT = 0.18

const isPeakSlot = (s: number) => s < 12 || s >= 88

export const SAMPLE_TARIFF_TOU = Array.from({ length: SLOTS }, (_, s) =>
  isPeakSlot(s) ? TOU_PEAK : TOU_OFF,
)
export const SAMPLE_TARIFF_FLAT = Array.from({ length: SLOTS }, () => FLAT)

export const SAMPLE_HOMES: Home[] = [
  { id: 'A', name: 'Home A', color: '#2563eb', preferences: {} },
  { id: 'B', name: 'Home B', color: '#d97706', preferences: {} },
  { id: 'C', name: 'Home C', color: '#059669', preferences: {} },
]

const task = (
  id: string,
  home_id: HomeId,
  name: string,
  power_kw: number,
  duration_slots: number,
  deadline_slot: number,
  preferred_start_slot: number,
): Task => ({
  id,
  home_id,
  name,
  power_kw,
  duration_slots,
  earliest_slot: 0,
  deadline_slot,
  preferred_start_slot,
  interruptible: false,
})

export const SAMPLE_TASKS: Task[] = [
  task('a_ev', 'A', 'EV charging', 7.2, 12, 28, 0),
  task('a_dish', 'A', 'Dishwasher', 1.2, 4, 20, 6),
  task('b_dryer', 'B', 'Clothes dryer', 5.0, 3, 20, 2),
  task('b_dish', 'B', 'Dishwasher', 1.2, 4, 20, 6),
  task('c_ev', 'C', 'EV charging', 7.2, 12, 48, 0),
  task('c_dish', 'C', 'Dishwasher', 1.2, 4, 20, 6),
]

const entry = (t: Task, start_slot: number): ScheduleEntry => ({
  task_id: t.id,
  home_id: t.home_id,
  start_slot,
  duration_slots: t.duration_slots,
  power_kw: t.power_kw,
})

// Everyone at preferred times.
const baseline = SAMPLE_TASKS.map((t) => entry(t, t.preferred_start_slot))
// Cheap timer: every home starts everything at 9:00 PM (slot 12), the first cheap slot.
const independent = SAMPLE_TASKS.map((t) => entry(t, 12))

function loadBySlot(schedule: ScheduleEntry[], homeId?: HomeId): number[] {
  const homes = homeId ? 1 : SAMPLE_HOMES.length
  const load = Array.from({ length: SLOTS }, () => BACKGROUND_KW * homes)
  for (const e of schedule) {
    if (homeId && e.home_id !== homeId) continue
    for (let s = e.start_slot; s < e.start_slot + e.duration_slots; s++) load[s] += e.power_kw
  }
  return load
}

const round2 = (n: number) => Math.round(n * 100) / 100

function metricsFor(schedule: ScheduleEntry[], tariff: number[]): Metrics {
  const sum = (load: number[]) => ({
    energy_kwh: round2(load.reduce((a, l) => a + l * 0.25, 0)),
    variable_cost_usd: round2(load.reduce((a, l, s) => a + l * 0.25 * tariff[s], 0)),
    peak_kw: round2(Math.max(...load)),
  })
  const load = loadBySlot(schedule)
  const missed = schedule.filter((e) => {
    const t = SAMPLE_TASKS.find((x) => x.id === e.task_id)!
    return e.start_slot + e.duration_slots > t.deadline_slot
  }).length
  return {
    ...sum(load),
    missed_deadlines: missed,
    capacity_violations: load.filter((l) => l > CAPACITY_KW + 1e-6).length,
    tasks_completed: schedule.length - missed,
    tasks_total: SAMPLE_TASKS.length,
    per_home: Object.fromEntries(
      SAMPLE_HOMES.map((h) => [h.id, sum(loadBySlot(schedule, h.id))]),
    ),
  }
}

export const SAMPLE_STATE: NeighborhoodState = {
  revision: 0,
  generation: 0,
  requirements_version: 0,
  scenario_id: 'sample',
  horizon_start: '2026-07-15T18:00:00-04:00',
  slot_minutes: 15,
  capacity_kw: CAPACITY_KW,
  activity: null,
  tariff_mode: 'tou',
  tariff_label: 'Illustrative time-of-use tariff',
  homes: SAMPLE_HOMES,
  tasks: SAMPLE_TASKS,
  tariff_usd_per_kwh: SAMPLE_TARIFF_TOU,
  background_kw_by_home: { A: BACKGROUND_KW, B: BACKGROUND_KW, C: BACKGROUND_KW },
  baseline_schedule: baseline,
  independent_schedule: independent,
  coordinated_schedule: null,
  metrics: {
    baseline: metricsFor(baseline, SAMPLE_TARIFF_TOU),
    independent: metricsFor(independent, SAMPLE_TARIFF_TOU),
    coordinated: null,
  },
  metrics_flat_rate: {
    baseline: metricsFor(baseline, SAMPLE_TARIFF_FLAT),
    independent: metricsFor(independent, SAMPLE_TARIFF_FLAT),
    coordinated: null,
  },
  demand_kw: {
    baseline: loadBySlot(baseline),
    independent: loadBySlot(independent),
    coordinated: null,
  },
  coordination: null,
  events: [],
  events_hidden: false,
  pending_changes: [],
  job_status: null,
  data_mode: 'synthetic',
  ai_mode: 'unavailable',
  agent_impl: { interpret: 'stub', coordinate: 'stub' },
}

/** Sample household view: only that home's tasks, schedule entries, and per-home metrics. */
export function sampleHomeState(home: HomeId): NeighborhoodState {
  const s = SAMPLE_STATE
  const own = (xs: ScheduleEntry[]) => xs.filter((e) => e.home_id === home)
  const ownMetrics = (m: Metrics | null | undefined) =>
    m ? { ...m, per_home: { [home]: m.per_home[home] } } : null
  return {
    ...s,
    homes: s.homes.filter((h) => h.id === home),
    tasks: s.tasks.filter((t) => t.home_id === home),
    background_kw_by_home: { [home]: BACKGROUND_KW },
    baseline_schedule: own(s.baseline_schedule),
    independent_schedule: own(s.independent_schedule),
    metrics: {
      baseline: ownMetrics(s.metrics.baseline),
      independent: ownMetrics(s.metrics.independent),
      coordinated: null,
    },
    metrics_flat_rate: {
      baseline: ownMetrics(s.metrics_flat_rate.baseline),
      independent: ownMetrics(s.metrics_flat_rate.independent),
      coordinated: null,
    },
  }
}
