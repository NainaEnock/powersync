// "My appliances": the resident adds a schedulable appliance from the catalog or removes one of their own.
// Every change goes through POST /api/appliances; the plan clears and the street replans on the next
// coordination. Cooking appliances aren't offered because they run when people eat.
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, type Api } from '../api'
import { slotToTime } from '../time'
import type { ApplianceCatalog, HomeId, NeighborhoodState } from '../types'
import { errorText } from './usePhoneFlow'

const hours = (slots: number) => {
  const m = slots * 15
  return m % 60 === 0 ? `${m / 60} h` : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`
}

export function AppliancesCard({ homeId, api, state, busy, onChanged }: {
  homeId: HomeId
  api: Api
  state: NeighborhoodState
  busy: boolean
  onChanged: () => void
}) {
  const [catalog, setCatalog] = useState<ApplianceCatalog | null>(null)
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('')
  const [deadline, setDeadline] = useState<number | null>(null)
  const [working, setWorking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Removing replans the whole street, so it takes a second tap.
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)

  // Load the catalog; if the backend was unreachable, try again on the next state update.
  const haveCatalog = catalog !== null
  useEffect(() => {
    if (haveCatalog) return
    let cancelled = false
    api.applianceCatalog().then((c) => { if (!cancelled) setCatalog(c) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [api, haveCatalog, state.revision])

  const own = state.tasks.filter((t) => t.home_id === homeId)
  const spec = catalog?.schedulable.find((a) => a.kind === kind) ?? null
  const full = catalog ? own.length >= catalog.max_per_home : false
  const planning = state.job_status === 'running'
  const disabled = busy || planning || working !== null || api.mode === 'sample'

  // Finish-by choices: every 30 minutes from the earliest possible finish to 6:00 AM (slot 48).
  const finishOptions = useMemo(() => {
    if (!spec) return []
    const first = Math.ceil(spec.duration_slots / 2) * 2
    const out: number[] = []
    for (let s = first; s <= 48; s += 2) out.push(s)
    if (!out.includes(spec.deadline_slot) && spec.deadline_slot <= 96) out.push(spec.deadline_slot)
    return out.sort((a, b) => a - b)
  }, [spec])

  const pick = (k: string) => {
    setKind(k)
    setDeadline(catalog?.schedulable.find((a) => a.kind === k)?.deadline_slot ?? null)
  }

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setError(null)
    setWorking(label)
    try {
      await fn()
      onChanged()
      return true
    } catch (e) {
      setError(e instanceof ApiError ? errorText(e) : 'Something went wrong. Try again.')
      return false
    } finally {
      setWorking(null)
    }
  }

  const add = async () => {
    if (!spec) return
    if (await run('add', () => api.addAppliance(homeId, spec.kind, deadline ?? undefined))) {
      setOpen(false)
      setKind('')
    }
  }

  return (
    <section className="ps-card">
      <div className="ps-card-head">
        <h2>My appliances</h2>
        {!open && (
          <button className="ps-btn ps-small" onClick={() => setOpen(true)} disabled={disabled || full || !catalog}>
            <Plus aria-hidden /> Add
          </button>
        )}
      </div>
      <p className="ps-muted">Appliances your agent can schedule. Changing them replans the street.</p>

      <ul className="ps-appliances">
        {own.map((t) => (
          <li key={t.id}>
            <div>
              <div className="ps-plan-name">{t.name}</div>
              <div className="ps-muted ps-small-text">
                {t.power_kw} kW · {hours(t.duration_slots)} · done by {slotToTime(t.deadline_slot)}
              </div>
            </div>
            {confirmRemove === t.id ? (
              <div className="ps-remove-confirm">
                <button
                  className="ps-btn ps-small ps-danger"
                  disabled={disabled}
                  onClick={async () => {
                    await run(t.id, () => api.removeAppliance(homeId, t.id))
                    setConfirmRemove(null)
                  }}
                >
                  {working === t.id ? <Loader2 className="ps-spin" aria-hidden /> : null} Remove
                </button>
                <button className="ps-btn ps-small" disabled={working === t.id} onClick={() => setConfirmRemove(null)}>
                  Keep
                </button>
              </div>
            ) : (
              <button
                className="ps-icon-btn"
                aria-label={`Remove ${t.name}`}
                disabled={disabled || own.length <= 1}
                onClick={() => { setError(null); setConfirmRemove(t.id) }}
              >
                <Trash2 aria-hidden />
              </button>
            )}
          </li>
        ))}
      </ul>

      {open && catalog && (
        <div className="ps-add">
          <label className="ps-field">
            Appliance
            <select className="ps-input" value={kind} onChange={(e) => pick(e.target.value)}>
              <option value="">Choose…</option>
              {catalog.schedulable.map((a) => (
                <option key={a.kind} value={a.kind}>
                  {a.name} ({a.power_kw} kW, {hours(a.duration_slots)})
                </option>
              ))}
            </select>
          </label>
          {spec && (
            <>
              <p className="ps-muted ps-small-text">{spec.note}</p>
              <label className="ps-field">
                Done by
                <select className="ps-input" value={deadline ?? ''} onChange={(e) => setDeadline(Number(e.target.value))}>
                  {finishOptions.map((s) => (
                    <option key={s} value={s}>{slotToTime(s)}</option>
                  ))}
                </select>
              </label>
            </>
          )}
          <div className="ps-row">
            <button className="ps-btn ps-primary" onClick={add} disabled={!spec || disabled}>
              {working === 'add' ? <Loader2 className="ps-spin" aria-hidden /> : <Plus aria-hidden />} Add appliance
            </button>
            <button className="ps-btn" onClick={() => { setOpen(false); setKind(''); setError(null) }}>Cancel</button>
          </div>
          <p className="ps-muted ps-small-text">
            Not offered: {catalog.not_schedulable.map((n) => `${n.name} (${n.why.charAt(0).toLowerCase()}${n.why.slice(1, -1)})`).join('; ')}.
          </p>
        </div>
      )}

      {planning && <p className="ps-muted ps-small-text">Planning is running. You can change appliances when it finishes.</p>}
      {full && <p className="ps-muted ps-small-text">Up to {catalog?.max_per_home} appliances per home.</p>}
      {error && <p className="ps-error" role="alert">{error}</p>}
    </section>
  )
}
