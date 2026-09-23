import { useEffect, useState } from 'react'
import { API_URL, SUPABASE_ANON_KEY, SUPABASE_URL } from './lib/supabase'

// Step 1 hello-world: confirms the browser can reach Supabase (anon key) and the FastAPI backend.
async function checkSupabase() {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/health`, {
    headers: { apikey: SUPABASE_ANON_KEY },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return 'connected'
}

async function checkBackend() {
  const res = await fetch(`${API_URL}/health`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const body = await res.json()
  if (body.db !== 'ok') throw new Error(`db ${body.db}`)
  return `connected (postgis ${body.extensions.postgis ?? 'missing'}, pg_cron ${body.extensions.pg_cron ?? 'missing'})`
}

function StatusRow({ label, check }) {
  const [state, setState] = useState({ status: 'checking', text: 'checking…' })

  useEffect(() => {
    check()
      .then((text) => setState({ status: 'ok', text }))
      .catch((e) => setState({ status: 'error', text: e.message }))
  }, [check])

  const color = { checking: 'text-slate-500', ok: 'text-emerald-600', error: 'text-red-600' }[state.status]
  return (
    <li className="flex justify-between gap-4 py-2 border-b border-slate-200 last:border-0">
      <span className="font-medium">{label}</span>
      <span className={color}>{state.text}</span>
    </li>
  )
}

export default function App() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white rounded-xl shadow p-6">
        <h1 className="text-xl font-bold">KainTabe</h1>
        <p className="text-sm text-slate-500 mb-4">Step 1: connection check</p>
        <ul>
          <StatusRow label="Supabase" check={checkSupabase} />
          <StatusRow label="Backend" check={checkBackend} />
        </ul>
      </div>
    </main>
  )
}
