import { directionsUrl, formatDistance } from '../lib/geo'
import { formatLeft, reachState, timeLeft, urgency, URGENCY_COLORS } from '../lib/urgency'

function ReachBadge({ donation: d, config, now }) {
  const km = d.search_radius_m / 1000
  const { phase, msUntilNext } = reachState(d, config, now)
  if (phase === 'escalated') {
    return <span className="px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-semibold">🚨 Urgent: no takers yet · {km} km</span>
  }
  const next = msUntilNext > 0 ? formatLeft(msUntilNext) : 'now'
  return (
    <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 tabular-nums">
      📡 {km} km reach · {phase === 'widening' ? `widens in ${next}` : `max reach, escalates in ${next}`}
    </span>
  )
}

/**
 * mode: 'open'  — in range of the viewer, claimable
 *       'mine'  — claimed by the viewer, awaiting pickup
 */
export default function DonationCard({ donation: d, mode, distance, now, config, selected, onSelect, onClaim, busy }) {
  const { leftMs, fraction } = timeLeft(d, now)
  const mine = mode === 'mine'
  const badge = mine ? 'bg-indigo-100 text-indigo-700' : URGENCY_COLORS[urgency(fraction)].badge
  const safetyChecked = d.safety_checklist && Object.values(d.safety_checklist).every(Boolean)

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
            {d.quantity}
            {d.est_kg ? ` · ~${Number(d.est_kg)} kg` : ''}
          </p>
          <p className="text-xs text-slate-500 truncate">
            from {d.donor_name}
            {distance != null && <> · <span className="font-medium text-slate-700">{formatDistance(distance)} away</span></>}
          </p>
          <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
            {safetyChecked && <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">✅ Safety checked</span>}
            {!mine && <ReachBadge donation={d} config={config} now={now} />}
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
          className="mt-3 w-full rounded-lg bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 disabled:opacity-60
            text-white font-semibold py-2.5 transition"
        >
          {busy ? 'Claiming…' : 'Claim — free pickup'}
        </button>
      )}

      {mine && (
        <div className="mt-3 flex gap-2">
          <span className="flex-1 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-medium py-2 text-center">
            ✔ Claimed by you, pick up soon
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
    </div>
  )
}
