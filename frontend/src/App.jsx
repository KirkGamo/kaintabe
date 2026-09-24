import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import DonationCard from './components/DonationCard'
import MapView from './components/MapView'
import { useConfig } from './hooks/useConfig'
import { useDonations, useRecipients } from './hooks/useDonations'
import { useNow } from './hooks/useNow'
import { useTelegramIdentity } from './hooks/useTelegramIdentity'
import { claimDonation, confirmPickup, withdrawListing } from './lib/api'
import { timeLeft } from './lib/urgency'

// Charts are heavy; load them only when the Impact tab is opened
const ImpactDashboard = lazy(() => import('./components/ImpactDashboard'))

const alive = (d, now) => d.status !== 'claimed' && timeLeft(d, now).leftMs > 0

/**
 * What this viewer sees. Everyone gets the public feed (approximate areas, no names/photos);
 * exact rows come only from /api/map for the viewer's own roles:
 *  open — org: listings within its reach (exact, claimable) · otherwise: public areas (read-only)
 *  out  — org: public areas of listings its reach doesn't cover yet
 *  mine — org/individual: their claims awaiting pickup (exact)
 *  own  — donor: their own listings (exact, Take down)
 */
function buildView(publicListings, identity, now) {
  const exact = new Set([...identity.inRange, ...identity.myPickups, ...identity.myListings].map((d) => d.id))
  const mine = identity.myPickups.map((d) => ({ donation: d, distance: null, mode: 'mine' }))
  const own = identity.myListings.map((d) => ({ donation: d, distance: null, mode: 'own' }))
  const others = publicListings.filter((d) => !exact.has(d.id) && alive(d, now))

  if (identity.org) {
    const open = identity.inRange
      .filter((d) => alive(d, now))
      .map((d) => ({ donation: d, distance: d.distance_m, mode: 'open' }))
    return { open, out: others.map((d) => ({ donation: d, distance: null, mode: 'out' })), mine, own }
  }
  const open = others
    .sort((a, b) => new Date(a.expires_at) - new Date(b.expires_at))
    .map((d) => ({ donation: d, distance: null, mode: 'public' }))
  return { open, out: [], mine, own }
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

/** Header identity: which roles this Telegram user holds, or the read-only public view. */
function WhoAmI({ identity }) {
  if (identity.loading) return <span className="text-sm text-slate-400">Checking…</span>
  const { org, donor, individual } = identity
  if (!org && !donor && !individual) {
    return (
      <span className="text-sm text-slate-500" title="Exact locations are shown only to the people who need them">
        👀 Public view{identity.inTelegram && identity.firstName ? ` · ${identity.firstName}` : ''}
      </span>
    )
  }
  return (
    <span className="text-sm flex items-center gap-1.5 min-w-0">
      <span className="font-semibold truncate max-w-48">
        {org ? `🏢 ${org.name}` : donor ? `🍱 ${donor.name}` : `🙋 ${identity.firstName ?? 'You'}`}
      </span>
      {org?.review_status === 'pending_review' && (
        <span className="shrink-0 text-[11px] font-semibold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
          Pending review
        </span>
      )}
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
  const { donations, live, changedAt } = useDonations()
  const recipients = useRecipients()
  const config = useConfig()
  const identity = useTelegramIdentity(changedAt)
  const [selectedId, setSelectedId] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(id)
  }, [toast])

  // The acting org is proven by Telegram (Mini App); nobody can pick an org by hand
  const viewer = identity.org
  const { open, out, mine, own } = useMemo(() => buildView(donations, identity, now), [donations, identity, now])
  const mapItems = [...out, ...open, ...own, ...mine]
  const selected = mapItems.find((i) => i.donation.id === selectedId)?.donation ?? null
  const home = viewer
    ? { lat: viewer.lat, lng: viewer.lng, label: viewer.name }
    : identity.donor
      ? { lat: identity.donor.lat, lng: identity.donor.lng, label: 'Your pickup spot' }
      : identity.individual
        ? { lat: identity.individual.lat, lng: identity.individual.lng, label: 'Your spot' }
        : null

  async function run(d, action) {
    setBusyId(d.id)
    try {
      await action()
      await identity.refresh()
    } catch (e) {
      setToast({ kind: 'error', text: e.message })
      throw e
    } finally {
      setBusyId(null)
    }
  }

  const handleClaim = (d) =>
    run(d, async () => {
      const claim = await claimDonation(d.id, viewer.id)
      setSelectedId(d.id)
      setToast({
        kind: 'ok',
        text:
          claim.reserved_price != null
            ? `Reserved ${d.food_type} for ₱${Number(claim.reserved_price)}. Pay the donor at pickup.`
            : `Claimed ${d.food_type}! The donor has been notified.`,
      })
    }).catch(() => {})

  const handleConfirm = (d, file) =>
    run(d, async () => {
      await confirmPickup(d.claim_id, viewer?.id, file)
      const n = d.est_kg ? Math.max(1, Math.round(Number(d.est_kg) / 0.4)) : 0
      const meals = n ? ` ~${n} meal${n === 1 ? '' : 's'} rescued.` : ''
      setToast({ kind: 'ok', text: `Pickup confirmed, thank you!${meals} The donor has been notified.` })
    })

  const handleTakeDown = (d) =>
    run(d, async () => {
      await withdrawListing(d.id)
      setToast({ kind: 'ok', text: `Taken down: ${d.food_type}` })
    }).catch(() => {})

  const card = ({ donation: d, distance, mode }) => (
    <DonationCard
      key={d.id}
      donation={d}
      mode={mode}
      distance={distance}
      now={now}
      config={config}
      selected={d.id === selectedId}
      onSelect={(x) => setSelectedId(x.id)}
      onClaim={handleClaim}
      onConfirm={handleConfirm}
      onTakeDown={handleTakeDown}
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
              home={home}
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

            {own.length > 0 && (
              <>
                <h2 className="text-sm font-semibold text-teal-700 px-1 pt-1">Food you posted ({own.length})</h2>
                {own.map(card)}
              </>
            )}

            <h2 className="text-sm font-semibold text-slate-600 px-1 pt-1">
              {open.length} listing{open.length === 1 ? '' : 's'} {viewer ? 'near you' : 'live now'}
              {!viewer && <span className="font-normal text-slate-400"> · approximate areas</span>}
            </h2>
            {open.length === 0 && (
              <div className="text-center text-slate-500 text-sm py-8">
                <div className="text-4xl mb-2">🌱</div>
                {viewer ? 'Nothing within reach right now.' : 'No surplus food listed right now.'}
                <br />
                New listings appear here instantly.
                {out.length > 0 && (
                  <p className="mt-2 text-xs">
                    {out.length} listing{out.length === 1 ? ' is' : 's are'} nearby but not reaching you yet (grey
                    areas).
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
