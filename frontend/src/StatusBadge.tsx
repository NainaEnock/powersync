// Header badge shown on both phone and dashboard (PRD §4 P0-15, §17).
// Shows: data mode, backend connection, auth mode, and AI model.
import { Cpu, Database, Plug, PlugZap, Shield, ShieldCheck, ShieldOff } from 'lucide-react'
import type { Api, Polled } from './api'
import type { Health } from './types'

export function StatusBadge({ api, health }: { api: Api; health: Polled<Health> }) {
  const h = health.data
  const connected = !!h && !health.error
  const AuthIcon = h?.auth_mode === 'enforced' ? ShieldCheck : h?.auth_mode === 'partial' ? Shield : ShieldOff
  const live = h?.agent_impl?.coordinate === 'live'

  return (
    <div className="status-badge" role="status" aria-live="polite">
      <span className={`pill ${api.mode === 'sample' ? 'pill-warn' : 'pill-ok'}`}>
        <Database size={13} /> {api.mode === 'sample' ? 'Sample data' : 'Live data'}
      </span>
      <span className={`pill ${connected ? 'pill-ok' : 'pill-bad'}`}>
        {connected ? <PlugZap size={13} /> : <Plug size={13} />}
        {connected ? 'Backend connected' : (health.error?.message ?? 'Connecting…')}
      </span>
      {connected && h && (
        <span className={`pill ${h.auth_mode === 'enforced' ? 'pill-ok' : 'pill-warn'}`}>
          <AuthIcon size={13} /> {h.auth_mode}
        </span>
      )}
      {connected && h && (
        <span className={`pill ${h.openrouter_configured && live ? '' : 'pill-warn'}`} title="AI model from /api/health">
          <Cpu size={13} />
          {!h.openrouter_configured ? 'AI not configured' : (h.model ?? 'model not set')}
          {h.openrouter_configured && !live ? ' · stub agent' : ''}
        </span>
      )}
    </div>
  )
}
