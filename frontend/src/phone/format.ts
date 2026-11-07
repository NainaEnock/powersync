// One 12-hour formatter for every time the phone shows (PRD §9.1).
// Slots stay integers internally; people only ever see "9:45 PM".

const DEFAULT_START_MINUTES = 18 * 60; // 6:00 PM

/** Minutes after midnight of the horizon start, read from an ISO string like 2026-07-15T18:00:00-04:00. */
export function horizonStartMinutes(horizonStart?: string | null): number {
  if (!horizonStart) return DEFAULT_START_MINUTES;
  const m = /T(\d{2}):(\d{2})/.exec(horizonStart);
  if (!m) return DEFAULT_START_MINUTES;
  return Number(m[1]) * 60 + Number(m[2]);
}

export function formatClock(totalMinutes: number): string {
  const mins = ((Math.round(totalMinutes) % 1440) + 1440) % 1440;
  const h24 = Math.floor(mins / 60);
  const mm = mins % 60;
  const suffix = h24 < 12 ? 'AM' : 'PM';
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${h12}:${mm.toString().padStart(2, '0')} ${suffix}`;
}

export function slotToTime(slot: number, horizonStart?: string | null, slotMinutes = 15): string {
  return formatClock(horizonStartMinutes(horizonStart) + slot * slotMinutes);
}

export function formatUsd(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `$${v.toFixed(2)}`;
}

export function formatKwh(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v.toFixed(2)} kWh`;
}

export function formatKw(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v.toFixed(1)} kW`;
}

/** Friendly appliance name used in sentences ("your car"). */
export function applianceNoun(taskName: string): string {
  const n = taskName.toLowerCase();
  if (n.includes('ev') || n.includes('car')) return 'car';
  if (n.includes('dryer')) return 'dryer';
  if (n.includes('dish')) return 'dishwasher';
  return n;
}

export function editFieldPhrase(field: string): string {
  switch (field) {
    case 'deadline_slot':
      return 'finish time';
    case 'earliest_slot':
      return 'earliest start';
    case 'preferred_start_slot':
      return 'preferred start';
    default:
      return 'time';
  }
}

export function newRequestId(home: string): string {
  const uuid =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `phone-${home.toLowerCase()}-${uuid}`;
}
