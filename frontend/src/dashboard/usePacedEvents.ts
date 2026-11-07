// Reveal new conversation events one at a time, like a text thread, so the audience can read each one.
// Every event shown is a real stored event in its real order; only the moment it appears is delayed.
// History already present when the page loads is shown at once (never replayed).
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AgentEvent } from '../types'

/** Reading time per message: tool calls flash by, plan announcements get longer. */
export function revealDelayMs(e: AgentEvent): number {
  if (e.type === 'tool_call' || e.type === 'tool_result') return 450
  if (e.type === 'validation' || e.type === 'commit') return 1400
  return Math.min(3200, Math.max(1300, 900 + e.text.length * 9))
}

export interface Paced {
  shown: AgentEvent[]
  /** The next real event waiting to appear (drives the "…" bubble). */
  next: AgentEvent | null
  queued: number
  skip: () => void
}

export function usePacedEvents(events: AgentEvent[] | undefined, generation: number | undefined): Paced {
  const sorted = useMemo(() => [...(events ?? [])].sort((a, b) => a.sequence - b.sequence), [events])
  const [count, setCount] = useState<number | null>(null) // null until the first load
  const [gen, setGen] = useState(generation)

  // First load, or a reset: show what's there without replaying it.
  useEffect(() => {
    if (events === undefined) return
    if (count === null || generation !== gen || sorted.length < count) {
      setCount(sorted.length)
      setGen(generation)
    }
  }, [events, sorted.length, count, generation, gen])

  const shownCount = Math.min(count ?? 0, sorted.length)
  const next = shownCount < sorted.length ? sorted[shownCount] : null

  // Key the timer on the event id: polling returns fresh objects every second, and
  // depending on the object itself would restart the timer before it ever fired.
  const nextId = next?.id ?? null
  const nextDelay = next ? revealDelayMs(next) : 0
  useEffect(() => {
    if (!nextId) return
    const t = window.setTimeout(() => setCount((c) => (c ?? 0) + 1), nextDelay)
    return () => window.clearTimeout(t)
  }, [nextId, nextDelay])

  const skip = useCallback(() => setCount(sorted.length), [sorted.length])

  return { shown: sorted.slice(0, shownCount), next, queued: sorted.length - shownCount, skip }
}
