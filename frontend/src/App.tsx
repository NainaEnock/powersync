import { useMemo } from 'react'
import { createApi } from './api'
import { Dashboard } from './dashboard/Dashboard'
import PhoneApp from './phone/PhoneApp'
import { HOME_IDS, type HomeId } from './types'

/** `/phone?home=A` pins a tab to a home. Null lets PhoneApp use the stored home or show the picker. */
function homeFromQuery(): HomeId | null {
  const q = new URLSearchParams(window.location.search).get('home')?.toUpperCase()
  return HOME_IDS.includes(q as HomeId) ? (q as HomeId) : null
}

// Routes: /phone (A's household app) and /dashboard (projector).
export default function App() {
  const api = useMemo(() => createApi(), [])
  const path = window.location.pathname.replace(/\/+$/, '') || '/'

  if (path === '/dashboard') return <Dashboard api={api} />
  if (path === '/phone') return <PhoneApp homeId={homeFromQuery()} api={api} />

  return (
    <main className="landing">
      <h1>PowerSync</h1>
      <p><a href="/dashboard">Dashboard</a></p>
      <p><a href="/phone">Phone</a></p>
    </main>
  )
}
