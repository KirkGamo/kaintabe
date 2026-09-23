import { useEffect, useMemo, useState } from 'react'
import DonationCard from './components/DonationCard'
import MapView from './components/MapView'
import { useClaims } from './hooks/useClaims'
import { useDonations, useRecipients } from './hooks/useDonations'
import { useNow } from './hooks/useNow'
import { claimDonation } from './lib/api'
import { distanceM } from './lib/geo'
import { timeLeft } from './lib/urgency'

const VIEWER_KEY = 'kaintabe.viewer'

function loadViewerId() {
  try {
    return localStorage.getItem(VIEWER_KEY)
  } catch {
    return null
  }
}

/**
 * Split listings from the viewer's point of view:
 *  open — unclaimed, not expired, and its search radius reaches the viewer (nearest first)
 *  out  — unclaimed but its radius doesn't reach the viewer yet (map only)
 *  mine — claimed by the viewer, awaiting pickup
 * Listings claimed by other orgs are hidden.
 */
function classify(donations, claimsByDonation, viewer, now) {
  const open = []
  const out = []
  const mine = []
  if (!viewer) return { open, out, mine }
  for (const d of donations) {
    const distance = distanceM(viewer, d)
    if (d.status === 'claimed') {
      if (claimsByDonation[d.id]?.recipient_id === viewer.id) mine.push({ donation: d, distance, mode: 'mine' })
    } else if (timeLeft(d, now).leftMs > 0) {
      if (distance <= d.search_radius_m) open.push({ donation: d, distance, mode: 'open' })
      else out.push({ donation: d, distance, mode: 'out' })
    }
  }
  open.sort((a, b) => a.distance - b.distance)
  mine.sort((a, b) => a.distance - b.distance)
  return { open, out, mine }
}

export default function App() {
  const now = useNow()
  const { donations, live } = useDonations()
  const { claimsByDonation, addClaim } = useClaims()
  const recipients = useRecipients()
  const [viewerId, setViewerId] = useState(loadViewerId)
  const [selectedId, setSelectedId] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [toast, setToast] = useState(null)

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

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(id)
  }, [toast])

  const viewer = recipients.find((r) => r.id === viewerId)
  const { open, out, mine } = useMemo(
    () => classify(donations, claimsByDonation, viewer, now),
    [donations, claimsByDonation, viewer, now],
  )
  const mapItems = [...out, ...open, ...mine]
  const selected = mapItems.find((i) => i.donation.id === selectedId)?.donation ?? null

  async function handleClaim(d) {
    setBusyId(d.id)
    try {
      const claim = await claimDonation(d.id, viewer.id)
      addClaim(claim)
      setSelectedId(d.id)
      setToast({ kind: 'ok', text: `Claimed ${d.food_type}! The donor has been notified.` })
    } catch (e) {
      setToast({ kind: 'error', text: e.message })
    } finally {
      setBusyId(null)
    }
  }

  const card = ({ donation: d, distance, mode }) => (
    <DonationCard
      key={d.id}
      donation={d}
      mode={mode}
      distance={distance}
      now={now}
      selected={d.id === selectedId}
      onSelect={(x) => setSelectedId(x.id)}
      onClaim={handleClaim}
      busy={busyId === d.id}
    />
  )

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
            items={mapItems}
            recipients={recipients}
            viewer={viewer}
            selected={selected}
            onSelect={(d) => setSelectedId(d.id)}
            now={now}
          />
        </section>

        <aside className="flex-1 md:flex-none md:w-100 min-h-0 overflow-y-auto p-3 space-y-2 border-t md:border-t-0 md:border-l border-slate-200">
          {mine.length > 0 && (
            <>
              <h2 className="text-sm font-semibold text-indigo-700 px-1">Your pickups ({mine.length})</h2>
              {mine.map(card)}
            </>
          )}

          <h2 className="text-sm font-semibold text-slate-600 px-1 pt-1">
            {open.length} listing{open.length === 1 ? '' : 's'} near you
          </h2>
          {open.length === 0 && (
            <div className="text-center text-slate-500 text-sm py-8">
              <div className="text-4xl mb-2">🌱</div>
              Nothing within reach right now.
              <br />
              New listings appear here instantly.
              {out.length > 0 && (
                <p className="mt-2 text-xs">
                  {out.length} listing{out.length === 1 ? ' is' : 's are'} nearby but not reaching you yet (faded
                  pins).
                </p>
              )}
            </div>
          )}
          {open.map(card)}
        </aside>
      </main>

      {toast && (
        <div
          role="status"
          className={`fixed bottom-4 left-1/2 -translate-x-1/2 z-1000 max-w-[90vw] px-4 py-2.5 rounded-xl shadow-lg text-sm font-medium
            ${toast.kind === 'ok' ? 'bg-emerald-600 text-white' : 'bg-red-600 text-white'}`}
        >
          {toast.text}
        </div>
      )}
    </div>
  )
}
