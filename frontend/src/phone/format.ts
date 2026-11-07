// Phone-only wording helpers. Times always go through slotToTime() in src/time.ts.

export function formatUsd(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `$${v.toFixed(2)}`;
}

export function formatKwh(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v.toFixed(2)} kWh`;
}

/** Friendly appliance name used in sentences ("your car"). */
export function applianceNoun(taskName: string): string {
  const n = taskName.toLowerCase();
  if (/\bev\b/.test(n) || n.includes('car')) return 'car';
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
