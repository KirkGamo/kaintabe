import { directionsUrl, formatDistance } from '../lib/geo'
import ConfirmPickup from './ConfirmPickup'
import { formatLeft, reachState, saleState, timeLeft, urgency, URGENCY_COLORS } from '../lib/urgency'

function ReachBadge({ donation: d, config, now }) {
  const km = d.search_radius_m / 1000
  if (d.listing_type === 'sale') {
    const { msUntilFree } = saleState(d, config, now)
    return (
      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 tabular-nums">
        📡 {km} km · free in {msUntilFree > 0 ? formatLeft(msUntilFree) : 'now'} if unsold
      </span>
    )
  }
  const { phase, msUntilNext } = reachState(d, config, now)
  if (phase === 'escalated') {
    const offered = d.flash_offer_count ?? 0
    return (
      <>
        <span className="px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-semibold">🚨 Urgent: no takers yet · {km} km</span>
        {offered > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-violet-100 text-violet-800 font-semibold">
            📣 Offered to {offered} {offered === 1 ? 'person' : 'people'} nearby
          </span>
        )}
      </>
    )
  }
  const next = msUntilNext > 0 ? formatLeft(msUntilNext) : 'now'
  return (
    <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 tabular-nums">
      📡 {km} km reach · {phase === 'widening' ? `widens in ${next}` : `max reach, escalates in ${next}`}
    </span>
  )
}

/**
 * mode: 'open'   — in range of the signed-in org, claimable
 *       'mine'   — claimed by that org, awaiting pickup
 *       'public' — no org identity: read-only, approximate, points people to the Telegram bot
 *       'own'    — the signed-in donor's own listing: Take down (or who claimed it)
 */
export default function DonationCard({
  donation: d, mode, distance, now, config, claim, selected, onSelect, onClaim, onConfirm, onTakeDown, busy, botUrl,
  inTelegram,
}) {
  const { leftMs, fraction } = timeLeft(d, now)
  const mine = mode === 'mine'
  const forSale = d.listing_type === 'sale' && !mine
  const sale = forSale ? saleState(d, config, now) : null
  // claimed listings carry their reservation (from /api/map); older callers may still pass `claim`
  const reserved = d.reserved_price ?? claim?.reserved_price
  const reservedPrice = mine && reserved != null ? Number(reserved) : null
  const own = mode === 'own'
  const badge = mine ? 'bg-indigo-100 text-indigo-700' : URGENCY_COLORS[urgency(fraction)].badge
  const safetyChecked = d.safety_checked ?? (d.safety_checklist && Object.values(d.safety_checklist).every(Boolean))

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(d)}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(d)}
      className={`w-full text-left p-3 rounded-xl bg-white border transition cursor-pointer
        ${selected ? 'border-indigo-500 ring-2 ring-indigo-200' : 'border-slate-200 hover:border-slate-300'}`}
    >
      <div className="flex gap-3">
        {d.photo_url ? (
          <img src={d.photo_url} alt={d.food_type} className="w-20 h-20 rounded-lg object-cover shrink-0 bg-slate-100" />
        ) : (
          <div className="w-20 h-20 rounded-lg bg-slate-100 flex items-center justify-center text-3xl shrink-0">🍱</div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold leading-tight truncate">{d.food_type}</h3>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap tabular-nums ${badge}`}>
              ⏱ {formatLeft(leftMs)}
            </span>
          </div>
          <p className="text-sm text-slate-600">
            {d.quantity ?? 'Surplus food'}
            {d.est_kg ? ` · ~${Number(d.est_kg)} kg` : ''}
          </p>
          {sale && (
            <p className="text-sm">
              <span className="font-bold text-amber-700 tabular-nums">🏷️ ₱{sale.price}</span>{' '}
              <span className="text-slate-400 line-through">₱{sale.original}</span>{' '}
              <span className="text-xs text-slate-500">price drops until free</span>
            </p>
          )}
          <p className="text-xs text-slate-500 truncate">
            {d.donor_name ? `from ${d.donor_name}` : own ? 'your listing' : 'from a donor nearby (approximate area)'}
            {distance != null && <> · <span className="font-medium text-slate-700">{formatDistance(distance)} away</span></>}
          </p>
          <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
            {safetyChecked && <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">✅ Safety checked</span>}
            {d.allergens?.length > 0 && (
              <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-800">⚠️ May contain {d.allergens.join(', ')}</span>
            )}
            {d.ai_assisted && <span className="px-1.5 py-0.5 rounded bg-violet-50 text-violet-700">🤖 AI-read photo</span>}
            {!mine && d.status !== 'claimed' && <ReachBadge donation={d} config={config} now={now} />}
          </div>
        </div>
      </div>

      {mode === 'open' && (
        <button
          type="button"
          disabled={busy}
          onClick={(e) => {
            e.stopPropagation()
            onClaim(d)
          }}
          className={`mt-3 w-full rounded-lg disabled:opacity-60 text-white font-semibold py-2.5 transition
            ${forSale ? 'bg-amber-600 hover:bg-amber-700 active:bg-amber-800' : 'bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800'}`}
        >
          {busy ? (forSale ? 'Reserving…' : 'Claiming…') : forSale ? `Reserve — pay ₱${sale.price} at pickup` : 'Claim — free pickup'}
        </button>
      )}

      {mode === 'public' &&
        (inTelegram ? (
          <p className="mt-3 text-center text-sm text-slate-500">
            Partner kitchens claim here. Register yours with /start in the bot.
          </p>
        ) : (
          <a
            href={botUrl ?? undefined}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="mt-3 block w-full rounded-lg border border-sky-300 bg-sky-50 hover:bg-sky-100 text-sky-800
              font-semibold py-2.5 text-center transition"
          >
            ✈️ Claim in Telegram
          </a>
        ))}

      {mine && (
        <div className="mt-3 flex gap-2">
          <span className="flex-1 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-medium py-2 text-center">
            {reservedPrice != null ? `✔ Reserved: pay ₱${reservedPrice} at pickup` : '✔ Claimed by you, pick up soon'}
          </span>
          <a
            href={directionsUrl(d)}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="rounded-lg border border-slate-300 hover:bg-slate-50 text-sm font-medium px-3 py-2"
          >
            🧭 Directions
          </a>
        </div>
      )}
      {mine && leftMs <= 0 && (
        <p className="mt-2 text-xs text-amber-800 bg-amber-50 rounded-lg px-3 py-2">
          ⏰ Past its safe time. Confirm only if you picked it up in time (within the hour); otherwise it closes
          automatically.
        </p>
      )}
      {mine && <ConfirmPickup onConfirm={(file) => onConfirm(d, file)} />}

      {own &&
        (d.status === 'claimed' ? (
          leftMs > 0 ? (
            <p className="mt-3 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-medium py-2 text-center">
              ✔️ Claimed by {d.claimer_name ?? 'someone'}, they're coming
            </p>
          ) : (
            <p className="mt-3 rounded-lg bg-slate-100 text-slate-600 text-sm py-2 px-3 text-center">
              ⌛ Pickup window over. If {d.claimer_name ?? 'they'} didn't collect it, this closes automatically within
              the hour.
            </p>
          )
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation()
              onTakeDown(d)
            }}
            className="mt-3 w-full rounded-lg border border-slate-300 hover:bg-slate-50 disabled:opacity-60
              text-slate-700 font-semibold py-2.5 transition"
          >
            {busy ? 'Taking down…' : `🗑️ Take down: already gone`}
          </button>
        ))}
    </div>
  )
}
