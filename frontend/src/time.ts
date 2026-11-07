// The one shared slot formatter for the UI (PRD §9.1).
// Slot 0 = 6:00 PM on 2026-07-15 (America/New_York), 15-minute slots.
// Every time a person reads is 12-hour, like "9:45 PM".

export const SLOT_MINUTES = 15
export const SLOTS = 96
const START_MINUTES = 18 * 60 // 6:00 PM

export function slotToTime(slot: number): string {
  const total = (START_MINUTES + slot * SLOT_MINUTES) % (24 * 60)
  const h24 = Math.floor(total / 60)
  const m = total % 60
  const suffix = h24 >= 12 ? 'PM' : 'AM'
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12
  return `${h12}:${m.toString().padStart(2, '0')} ${suffix}`
}

/** Short label for chart axes: "9 PM", "9:45 PM". */
export function slotToTick(slot: number): string {
  return slotToTime(slot).replace(':00 ', ' ')
}
