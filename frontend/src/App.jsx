import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import DonationCard from './components/DonationCard'
import MapView from './components/MapView'
import { useClaims } from './hooks/useClaims'
import { useConfig } from './hooks/useConfig'
import { useDonations, useRecipients } from './hooks/useDonations'
import { useNow } from './hooks/useNow'
import { useTelegramIdentity } from './hooks/useTelegramIdentity'
import { claimDonation, confirmPickup } from './lib/api'
import { distanceM } from './lib/geo'
import { timeLeft } from './lib/urgency'

// Charts are heavy; load them only when the Impact tab is opened
const ImpactDashboard = lazy(() => import('./components/ImpactDashboard'))

/**
 * Split listings from the viewer's point of view:
 *  open   — unclaimed, not expired, and its search radius reaches the viewer (nearest first)
 *  out    — unclaimed but its radius doesn't reach the viewer yet (map only)
 *  mine   — claimed by the viewer, awaiting pickup
 *  public — no org identity (normal browser, or a non-org in Telegram): every live listing, read-only
 * Listings claimed by other orgs are hidden.
 */
function classify(donations, claimsByDonation, viewer, now) {
  const open = []
  const out = []
  const mine = []
  if (!viewer) {
    for (const d of donations) {
      if (d.status !== 'claimed' && timeLeft(d, now).leftMs > 0) open.push({ donation: d, distance: null, mode: 'public' })
    }
    open.sort((a, b) => new Date(a.donation.expires_at) - new Date(b.donation.expires_at))
    return { open, out, mine }
  }
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

// #impact opens the dashboard directly (handy as the demo's closing screen)
function useHashView() {
  const read = () => (window.location.hash === '#impact' ? 'impact' : 'map')
  const [view, setView] = useState(read)
  useEffect(() => {
    const onHash = () => setView(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return view
}

/** Header identity: the org acting (inside Telegram), or a read-only public view. */
function WhoAmI({ identity }) {
  if (identity.loading) return <span className="text-sm text-slate-400">Checking…</span>
  if (identity.org) {
    const pending = identity.org.review_status === 'pending_review'
    return (
      <span className="text-sm flex items-center gap-1.5 min-w-0">
        <span className="font-semibold truncate max-w-48">🏢 {identity.org.name}</span>
        {pending && (
          <span className="shrink-0 text-[11px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
            Pending review
          </span>
        )}
      </span>
    )
  }
  return (
    <span className="text-sm text-slate-500" title="Partner organizations claim food inside the KainTabe Telegram bot">
      👀 Public view{identity.inTelegram && identity.firstName ? ` · ${identity.firstName}` : ''}
    </span>
  )
}

function Tab({ href, active, children }) {
  return (
    <a
      href={href}
      aria-current={active ? 'page' : undefined}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition
        ${active ? 'bg-emerald-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
    >
      {children}
    </a>
  )
}

export default function App() {
  const view = useHashView()
  const now = useNow()
  const { donations, live } = useDonations()
  const { claimsByDonation, addClaim } = useClaims()
  const recipients = useRecipients()
  const config = useConfig()
  const identity = useTelegramIdentity()
  const [selectedId, setSelectedId] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(id)
  }, [toast])

  // The acting org is proven by Telegram (Mini App); nobody can pick an org by hand any more
  const viewer = identity.org
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
      const text =
        claim.reserved_price != null
          ? `Reserved ${d.food_type} for ₱${Number(claim.reserved_price)}. Pay the donor at pickup.`
          : `Claimed ${d.food_type}! The donor has been notified.`
      setToast({ kind: 'ok', text })
    } catch (e) {
      setToast({ kind: 'error', text: e.message })
    } finally {
      setBusyId(null)
    }
  }

  async function handleConfirm(d, file) {
    const claim = claimsByDonation[d.id]
    try {
      const done = await confirmPickup(claim.id, viewer.id, file)
      addClaim({ ...claim, confirmed_at: done.confirmed_at, confirmation_photo_url: done.confirmation_photo_url })
      const n = d.est_kg ? Math.max(1, Math.round(Number(d.est_kg) / 0.4)) : 0
      const meals = n ? ` ~${n} meal${n === 1 ? '' : 's'} rescued.` : ''
      setToast({ kind: 'ok', text: `Pickup confirmed, thank you!${meals} The donor has been notified.` })
    } catch (e) {
      setToast({ kind: 'error', text: e.message })
      throw e
    }
  }

  const card = ({ donation: d, distance, mode }) => (
    <DonationCard
      key={d.id}
      donation={d}
      mode={mode}
      distance={distance}
      now={now}
      config={config}
      claim={claimsByDonation[d.id]}
      selected={d.id === selectedId}
      onSelect={(x) => setSelectedId(x.id)}
      onClaim={handleClaim}
      onConfirm={handleConfirm}
      busy={busyId === d.id}
      botUrl={identity.botUrl}
      inTelegram={identity.inTelegram}
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
        <nav className="flex items-center gap-1 order-last sm:order-0 w-full sm:w-auto">
          <Tab href="#map" active={view === 'map'}>
            🗺️ Map
          </Tab>
          <Tab href="#impact" active={view === 'impact'}>
            📊 Impact
          </Tab>
        </nav>
        <div className="flex items-center gap-3">
          <WhoAmI identity={identity} />
          <span
            className={`text-xs font-medium flex items-center gap-1 ${live ? 'text-emerald-600' : 'text-slate-400'}`}
            title={live ? 'Receiving live updates' : 'Connecting…'}
          >
            <span className={`w-2 h-2 rounded-full ${live ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
            {live ? 'Live' : '…'}
          </span>
        </div>
      </header>

      {view === 'impact' ? (
        <main className="flex-1 min-h-0">
          <Suspense fallback={<p className="p-6 text-center text-slate-500">Loading impact…</p>}>
            <ImpactDashboard />
          </Suspense>
        </main>
      ) : (
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
              {open.length} listing{open.length === 1 ? '' : 's'} {viewer ? 'near you' : 'live now'}
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
      )}

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
