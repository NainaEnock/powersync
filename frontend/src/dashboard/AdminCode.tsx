// Admin code entry for the projector. Stored locally, sent only as a bearer header, never in the URL.
import { ShieldCheck, ShieldEllipsis } from 'lucide-react'
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
      <button className="icon-btn" onClick={() => onOpenChange(!open)} aria-expanded={open}
        title={has ? 'Admin code set' : 'Enter admin code'} aria-label="Admin code">
        {has ? <ShieldCheck size={17} /> : <ShieldEllipsis size={17} />}
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
            <button type="submit" className="btn btn-primary">Save</button>
            {has && (
              <button type="button" className="btn" onClick={() => { setToken('admin', ''); onOpenChange(false); onSaved() }}>
                Clear
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  )
}
