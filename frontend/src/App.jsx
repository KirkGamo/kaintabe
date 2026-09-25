import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import BottomSheet from './components/BottomSheet'
import DonationCard from './components/DonationCard'
import MapView from './components/MapView'
import { useConfig } from './hooks/useConfig'
import { useDonations, useRecipients } from './hooks/useDonations'
import { useNow } from './hooks/useNow'
import { useTelegramIdentity } from './hooks/useTelegramIdentity'
import { claimDonation, confirmPickup, withdrawListing } from './lib/api'
import { distanceM } from './lib/geo'
import { reachEta, timeLeft } from './lib/urgency'

// Charts are heavy; load them only when the Impact tab is opened
const ImpactDashboard = lazy(() => import('./components/ImpactDashboard'))

const alive = (d, now) => d.status !== 'claimed' && timeLeft(d, now).leftMs > 0

/**
 * What this viewer sees. Everyone gets the public feed (approximate areas, no names/photos);
 * exact rows come only from /api/map for the viewer's own roles:
 *  open   — org: listings within its reach (exact, claimable)
 *           individual: listings by distance, flagged in/out of their pickup range ('person')
 *           otherwise: public areas (read-only)
 *  out    — org: public areas of listings whose reach doesn't cover it yet, with an ETA
 *  mine   — org/individual: their claims awaiting pickup (exact)
 *  own    — donor: their own listings (exact, Take down, who claimed them)
 *  reach  — the viewer's own pickup area (org / individual), drawn instead of every listing's circle
 *  hidden — donor-only viewer: how many other listings are hidden (they see just their own by default)
 */
function buildView(publicListings, identity, now, config, showOthers) {
  const exact = new Set([...identity.inRange, ...identity.myPickups, ...identity.myListings].map((d) => d.id))
  const mine = identity.myPickups.map((d) => ({ donation: d, distance: null, mode: 'mine' }))
  const own = identity.myListings.map((d) => ({ donation: d, distance: null, mode: 'own' }))
  const others = publicListings.filter((d) => !exact.has(d.id) && alive(d, now))
  const { org, individual } = identity

  if (org) {
    const open = identity.inRange
      .filter((d) => alive(d, now))
      .map((d) => ({ donation: d, distance: d.distance_m, mode: 'open' }))
    const out = others
      .map((d) => {
        const distance = distanceM(org, d)
        return { donation: d, distance, mode: 'out', eta: reachEta(d, distance, config, now).ms }
      })
      .sort((a, b) => (a.eta ?? Infinity) - (b.eta ?? Infinity) || a.distance - b.distance)
    const reach = { lat: org.lat, lng: org.lng, radius: org.service_radius_m }
    return { open, out, mine, own, reach, hidden: 0 }
  }
  if (individual) {
    const radius = individual.radius_m ?? 3000
    // Flash offers they got: what the Telegram offer already told them (donor, food, exact distance)
    // on top of the approximate public listing; the exact spot comes once they claim it
    const offers = new Map(identity.flashOffers.map((o) => [o.id, o]))
    const open = others
      .map((d) => {
        const offer = offers.get(d.id)
        if (offer) return { donation: { ...d, ...offer }, distance: offer.distance_m, mode: 'person', inReach: true, offer: true }
        const distance = distanceM(individual, d)
        return { donation: d, distance, mode: 'person', inReach: distance <= radius }
      })
      .sort((a, b) => (b.offer ? 1 : 0) - (a.offer ? 1 : 0) || a.distance - b.distance)
    return { open, out: [], mine, own, reach: { lat: individual.lat, lng: individual.lng, radius }, hidden: 0 }
  }
  const open = others
    .sort((a, b) => new Date(a.expires_at) - new Date(b.expires_at))
    .map((d) => ({ donation: d, distance: null, mode: 'public' }))
  // A donor mainly wants their own food; other donors' listings are one tap away
  if (identity.donor && !showOthers) return { open: [], out: [], mine, own, reach: null, hidden: open.length }
  return { open, out: [], mine, own, reach: null, hidden: 0 }
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

// Phones get a full-screen map with a swipe-up sheet; wider screens keep the side panel
function useIsDesktop() {
  const query = '(min-width: 768px)'
  const [desktop, setDesktop] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setDesktop(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return desktop
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
      className={`inline-flex items-center min-h-10 px-3 py-1.5 rounded-lg text-sm font-medium transition
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
  const isDesktop = useIsDesktop()
  const [sheet, setSheet] = useState('peek')
  // donor-only view: show other donors' listings too (remembered on this device)
  const [showOthers, setShowOthers] = useState(() => {
    try {
      return localStorage.getItem('kt.showOthers') === '1'
    } catch {
      return false
    }
  })
  function toggleOthers() {
    setShowOthers((v) => {
      try {
        localStorage.setItem('kt.showOthers', v ? '0' : '1')
      } catch {
        /* private mode: still toggles for this visit */
      }
      return !v
    })
  }

  // Selecting a pin shows its card: open the sheet (phones) and scroll the card into view
  function select(d) {
    setSelectedId(d.id)
    if (!isDesktop && sheet === 'peek') setSheet('half')
    setTimeout(
      () => document.getElementById(`card-${d.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }),
      250,
    )
  }

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(id)
  }, [toast])

  // The acting org is proven by Telegram (Mini App); nobody can pick an org by hand
  const viewer = identity.org
  const { open, out, mine, own, reach, hidden } = useMemo(
    () => buildView(donations, identity, now, config, showOthers),
    [donations, identity, now, config, showOthers],
  )
  const donorOnly = Boolean(identity.donor && !identity.org && !identity.individual)
  const mapItems = [...out, ...open, ...own, ...mine]
  // Donor view: kitchens whose own pickup area covers the donor's spot (kitchen locations are public)
  const donor = identity.donor
  const kitchensInReach = useMemo(
    () => (donor ? recipients.filter((r) => distanceM(r, donor) <= (r.service_radius_m ?? 0)) : []),
    [recipients, donor],
  )
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
      // an org claims in its reach; an individual claims a flash offer (who is acting comes from Telegram)
      const claim = await claimDonation(d.id, viewer?.id)
      setSelectedId(d.id)
      setToast({
        kind: 'ok',
        text:
          claim.reserved_price != null
            ? `Reserved ${d.food_type} for ₱${Number(claim.reserved_price)}. Pay the donor at pickup.`
            : viewer
              ? `Claimed ${d.food_type}! The donor has been notified.`
              : `It's yours! ${d.food_type} is under Your pickups, with directions.`,
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

  const card = ({ donation: d, distance, mode, eta, inReach, offer }) => (
    <div key={d.id} id={`card-${d.id}`}>
      <DonationCard
        donation={d}
        mode={mode}
        distance={distance}
        eta={eta}
        inReach={inReach}
        offer={offer}
        reachKm={reach ? reach.radius / 1000 : null}
        now={now}
        config={config}
        selected={d.id === selectedId}
        onSelect={select}
        onClaim={handleClaim}
        onConfirm={handleConfirm}
        onTakeDown={handleTakeDown}
        busy={busyId === d.id}
        botUrl={identity.botUrl}
        inTelegram={identity.inTelegram}
      />
    </div>
  )

  const inPersonReach = open.filter((i) => i.inReach).length
  const summary = (
    <>
      {mine.length ? `${mine.length} pickup${mine.length === 1 ? '' : 's'} · ` : ''}
      {donorOnly
        ? `${own.length} of your listing${own.length === 1 ? '' : 's'}${showOthers ? ` · ${open.length} other${open.length === 1 ? '' : 's'}` : ''}`
        : identity.individual && !viewer
          ? `${inPersonReach} listing${inPersonReach === 1 ? '' : 's'} within your ${reach.radius / 1000} km`
          : `${open.length} listing${open.length === 1 ? '' : 's'} ${viewer ? 'in your reach' : 'live now'}`}
      {!viewer && !donorOnly && <span className="font-normal text-slate-400"> · approximate areas</span>}
    </>
  )
  const listing = (
    <>
      {mine.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-indigo-700 px-1">Your pickups ({mine.length})</h2>
          {mine.map(card)}
        </>
      )}

      {donor && (
        <p className="text-xs text-slate-600 bg-teal-50 rounded-lg px-3 py-2">
          🏠 <strong>{kitchensInReach.length}</strong> partner kitchen{kitchensInReach.length === 1 ? '' : 's'} can
          reach your spot · 🙋 <strong>{donor.neighbors_nearby ?? 0}</strong> neighbor
          {donor.neighbors_nearby === 1 ? '' : 's'} on the flash-offer list nearby
        </p>
      )}
      {own.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-teal-700 px-1 pt-1">Food you posted ({own.length})</h2>
          {own.map(card)}
        </>
      )}

      {/* phones show this in the sheet's handle already */}
      {isDesktop && <h2 className="text-sm font-semibold text-slate-600 px-1 pt-1">{summary}</h2>}
      {donorOnly && own.length === 0 && (
        <div className="text-center text-slate-500 text-sm py-6">
          <div className="text-4xl mb-2">📸</div>
          No food posted right now. Send a photo in the bot to share food.
        </div>
      )}
      {donorOnly && (
        <button
          type="button"
          onClick={toggleOthers}
          className="w-full rounded-lg border border-slate-300 hover:bg-slate-50 text-sm font-medium text-slate-700 py-2 min-h-11"
        >
          {showOthers ? '🙈 Hide other listings' : `👀 Show other listings (${hidden})`}
        </button>
      )}
      {donorOnly && showOthers && open.length > 0 && (
        <h2 className="text-sm font-semibold text-slate-500 px-1 pt-1">Other listings (approximate areas)</h2>
      )}
      {!donorOnly && open.length === 0 && (
        <div className="text-center text-slate-500 text-sm py-8">
          <div className="text-4xl mb-2">🌱</div>
          {viewer ? 'Nothing within reach right now.' : 'No surplus food listed right now.'}
          <br />
          New listings appear here instantly.
        </div>
      )}
      {open.map(card)}

      {out.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-slate-500 px-1 pt-2">Not in your reach yet ({out.length})</h2>
          {out.map(card)}
        </>
      )}
    </>
  )

  return (
    // Inside Telegram, --tg-viewport-stable-height excludes Telegram's own chrome; elsewhere it's the full screen
    <div
      className="flex flex-col bg-slate-50 text-slate-900 overflow-hidden"
      style={{ height: 'var(--tg-viewport-stable-height, 100dvh)' }}
    >
      <header className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-3 sm:px-4 py-1.5 sm:py-2 bg-white border-b border-slate-200 z-10">
        <div className="flex items-center gap-2">
          <span className="text-xl sm:text-2xl">🍱</span>
          <div>
            <h1 className="font-bold leading-tight">KainTabe</h1>
            <p className="hidden sm:block text-xs text-slate-500 leading-tight">
              Surplus food, matched before it spoils
            </p>
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
        <main className="flex-1 min-h-0 relative md:flex md:flex-row">
          {/* isolate: Leaflet's panes and controls (z-index up to 1000) stay inside the map, under the sheet */}
          <section className="absolute inset-0 isolate md:static md:flex-1">
            <MapView
              items={mapItems}
              recipients={recipients}
              viewer={viewer}
              home={home}
              reach={reach}
              kitchensInReach={kitchensInReach}
              compact={!isDesktop}
              selected={selected}
              onSelect={select}
              now={now}
            />
          </section>

          {isDesktop ? (
            <aside className="md:w-100 min-h-0 overflow-y-auto p-3 space-y-2 border-l border-slate-200">
              {listing}
            </aside>
          ) : (
            <BottomSheet snap={sheet} onSnap={setSheet} summary={summary}>
              {listing}
            </BottomSheet>
          )}
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
