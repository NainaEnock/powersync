import { RotateCcw, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useHealth, usePoll, type Api } from '../api'
import { StatusBadge } from '../StatusBadge'
import { AdminCode } from './AdminCode'
import { ConversationPanel } from './ConversationPanel'
import { DemandChart } from './DemandChart'
import { HomeCards } from './HomeCards'
import { MetricTiles } from './MetricTiles'
import './dashboard.css'

export function Dashboard({ api }: { api: Api }) {
  const health = useHealth(api)
  const state = usePoll((signal) => api.state(undefined, signal), [api])
  const s = state.data
  const needsCode = state.error?.code === 'UNAUTHORIZED' || state.error?.code === 'FORBIDDEN'
  const [codeOpen, setCodeOpen] = useState(false)
  useEffect(() => {
    if (needsCode) setCodeOpen(true)
  }, [needsCode])

  return (
    <div className="dash">
      <header className="dash-top">
        <h1>PowerSync</h1>
        <StatusBadge api={api} health={health} />
        <div className="dash-top-right">
          {s && <span className="muted">Revision {s.revision}</span>}
          <button disabled title="Coming in B8"><Users size={16} /> Coordinate neighborhood</button>
          <button disabled title="Coming in B8"><RotateCcw size={16} /> Reset</button>
          <AdminCode open={codeOpen} onOpenChange={setCodeOpen} onSaved={state.refresh} />
        </div>
      </header>

      {api.mode === 'sample' && (
        <div className="banner-sample">Sample data. These numbers come from the PRD scenario, not the live backend.</div>
      )}
      {needsCode ? (
        <div className="banner-error">
          {state.error?.code === 'FORBIDDEN' ? 'That admin code is wrong.' : 'Enter the admin code to view the dashboard.'}
        </div>
      ) : (
        state.error && <div className="banner-error">{state.error.message}</div>
      )}
      {s?.coordination?.status === 'stale_tariff' && (
        <div className="banner-sample">{s.coordination.reasons[0] ?? 'Plan priced under the previous tariff. Coordinate again.'}</div>
      )}

      <div className="dash-main">
        <div className="dash-left">
          {s && (
            <>
              <MetricTiles state={s} />
              <DemandChart state={s} />
              <HomeCards state={s} />
            </>
          )}
        </div>
        <ConversationPanel state={s} needsCode={needsCode} />
      </div>
    </div>
  )
}
