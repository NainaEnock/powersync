// Money arrives with 4 decimals (contract §3). Always show 2.
export const usd = (n: number) => `${n < 0 ? '−' : ''}$${Math.abs(n).toFixed(2)}`

/** "+$0.12", "−$0.97", "no change" */
export function usdDelta(after: number, before: number): string {
  const d = Math.round((after - before) * 100) / 100
  if (d === 0) return 'no change'
  return `${d > 0 ? '+' : '−'}$${Math.abs(d).toFixed(2)}`
}

export const kw = (n: number) => `${n.toFixed(1)} kW`
export const kwh = (n: number) => `${n.toFixed(2)} kWh`
