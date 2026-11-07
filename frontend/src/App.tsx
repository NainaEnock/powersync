import { useMemo } from 'react'
import { createApi } from './api'
import { Dashboard } from './dashboard/Dashboard'
import { HOME_IDS, type HomeId } from './types'

// Routes: /phone (A's household app) and /dashboard (projector).
export default function App() {
  const api = useMemo(() => createApi(), [])
  const path = window.location.pathname.replace(/\/+$/, '') || '/'

  if (path === '/dashboard') return <Dashboard api={api} />
  if (path === '/phone') return <PhoneRoute />

  return (
    <main className="landing">
      <h1>PowerSync</h1>
      <p><a href="/dashboard">Dashboard</a></p>
      <p><a href="/phone">Phone</a></p>
    </main>
  )
}

/** Placeholder until A's PhoneApp lands in src/phone/. `/phone?home=A` pins a tab to a home. */
function PhoneRoute() {
  const q = new URLSearchParams(window.location.search).get('home')?.toUpperCase()
  const homeId = HOME_IDS.includes(q as HomeId) ? (q as HomeId) : null
  return (
    <main className="landing">
      <h1>PowerSync phone</h1>
      <p>{homeId ? `Pinned to Home ${homeId}.` : 'No home chosen.'} The phone app (A) plugs in here.</p>
    </main>
  )
}
