import { useEffect, useMemo, useState } from 'react'
import DonationCard from './components/DonationCard'
import MapView from './components/MapView'
import { useDonations, useRecipients } from './hooks/useDonations'
import { useNow } from './hooks/useNow'
import { timeLeft } from './lib/urgency'

const VIEWER_KEY = 'kaintabe.viewer'

function loadViewerId() {
  try {
    return localStorage.getItem(VIEWER_KEY)
  } catch {
    return null
  }
}

export default function App() {
  const now = useNow()
  const { donations, live } = useDonations()
  const recipients = useRecipients()
  const [viewerId, setViewerId] = useState(loadViewerId)
  const [selectedId, setSelectedId] = useState(null)

  // Default to the first partner org once loaded
  useEffect(() => {
    if (recipients.length && !recipients.some((r) => r.id === viewerId)) setViewerId(recipients[0].id)
  }, [recipients, viewerId])

  useEffect(() => {
    try {
      if (viewerId) localStorage.setItem(VIEWER_KEY, viewerId)
    } catch {
      /* storage unavailable: selection just won't persist */
    }
  }, [viewerId])

  const viewer = recipients.find((r) => r.id === viewerId)

  // Open listings first (most urgent on top), claimed ones after; hide ones that ran out
  const visible = useMemo(
    () =>
      donations
        .filter((d) => d.status === 'claimed' || timeLeft(d, now).leftMs > 0)
        .sort((a, b) => {
          const ca = a.status === 'claimed'
          const cb = b.status === 'claimed'
          if (ca !== cb) return ca ? 1 : -1
          return new Date(a.expires_at) - new Date(b.expires_at)
        }),
    [donations, now],
  )
  const selected = visible.find((d) => d.id === selectedId) ?? null
  const openCount = visible.filter((d) => d.status !== 'claimed').length

  return (
    <div className="h-dvh flex flex-col bg-slate-50 text-slate-900">
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 bg-white border-b border-slate-200 z-10">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🍱</span>
          <div>
            <h1 className="font-bold leading-tight">KainTabe</h1>
            <p className="text-xs text-slate-500 leading-tight">Surplus food, matched before it spoils</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm flex items-center gap-2">
            <span className="text-slate-500 hidden sm:inline">Viewing as</span>
            <select
              value={viewerId ?? ''}
              onChange={(e) => setViewerId(e.target.value)}
              className="border border-slate-300 rounded-lg px-2 py-1 bg-white text-sm max-w-48"
            >
              {recipients.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <span
            className={`text-xs font-medium flex items-center gap-1 ${live ? 'text-emerald-600' : 'text-slate-400'}`}
            title={live ? 'Receiving live updates' : 'Connecting…'}
          >
            <span className={`w-2 h-2 rounded-full ${live ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
            {live ? 'Live' : '…'}
          </span>
        </div>
      </header>

      <main className="flex-1 min-h-0 flex flex-col md:flex-row">
        <section className="h-[45dvh] md:h-auto md:flex-1 relative">
          <MapView
            donations={visible}
            recipients={recipients}
            viewer={viewer}
            selected={selected}
            onSelect={(d) => setSelectedId(d.id)}
            now={now}
          />
        </section>

        <aside className="flex-1 md:flex-none md:w-100 min-h-0 overflow-y-auto p-3 space-y-2 border-t md:border-t-0 md:border-l border-slate-200">
          <h2 className="text-sm font-semibold text-slate-600 px-1">
            {openCount} open listing{openCount === 1 ? '' : 's'}
          </h2>
          {visible.length === 0 && (
            <div className="text-center text-slate-500 text-sm py-10">
              <div className="text-4xl mb-2">🌱</div>
              No surplus food right now.
              <br />
              New listings from the Telegram bot appear here instantly.
            </div>
          )}
          {visible.map((d) => (
            <DonationCard
              key={d.id}
              donation={d}
              now={now}
              selected={d.id === selectedId}
              onSelect={(x) => setSelectedId(x.id)}
            />
          ))}
        </aside>
      </main>
    </div>
  )
}
