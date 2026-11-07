// Admin code entry for the projector. Stored locally, sent only as a bearer header, never in the URL.
import { KeyRound } from 'lucide-react'
import { useState } from 'react'
import { getToken, setToken } from '../api'

export function AdminCode({ open, onOpenChange, onSaved }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onSaved: () => void
}) {
  const [value, setValue] = useState('')
  const has = !!getToken('admin')

  return (
    <div className="admin-wrap">
      <button onClick={() => onOpenChange(!open)} aria-expanded={open} title="Admin code">
        <KeyRound size={16} /> {has ? 'Admin code set' : 'Admin code'}
      </button>
      {open && (
        <form
          className="popover"
          onSubmit={(e) => {
            e.preventDefault()
            setToken('admin', value.trim())
            setValue('')
            onOpenChange(false)
            onSaved()
          }}
        >
          <label>
            Admin code
            <input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
          </label>
          <div className="popover-row">
            <button type="submit">Save</button>
            {has && (
              <button type="button" onClick={() => { setToken('admin', ''); onOpenChange(false); onSaved() }}>
                Clear
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  )
}
