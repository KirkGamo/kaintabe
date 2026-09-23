import { formatLeft, timeLeft, urgency, URGENCY_COLORS } from '../lib/urgency'

export default function DonationCard({ donation: d, now, selected, onSelect }) {
  const { leftMs, fraction } = timeLeft(d, now)
  const claimed = d.status === 'claimed'
  const level = urgency(fraction)
  const badge = claimed ? 'bg-slate-200 text-slate-600' : URGENCY_COLORS[level].badge
  const safetyChecked = d.safety_checklist && Object.values(d.safety_checklist).every(Boolean)

  return (
    <button
      type="button"
      onClick={() => onSelect(d)}
      className={`w-full text-left flex gap-3 p-3 rounded-xl bg-white border transition
        ${selected ? 'border-indigo-500 ring-2 ring-indigo-200' : 'border-slate-200 hover:border-slate-300'}
        ${claimed ? 'opacity-60' : ''}`}
    >
      {d.photo_url ? (
        <img src={d.photo_url} alt={d.food_type} className="w-20 h-20 rounded-lg object-cover shrink-0 bg-slate-100" />
      ) : (
        <div className="w-20 h-20 rounded-lg bg-slate-100 flex items-center justify-center text-3xl shrink-0">🍱</div>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold leading-tight truncate">{d.food_type}</h3>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap tabular-nums ${badge}`}>
            {claimed ? 'Claimed' : `⏱ ${formatLeft(leftMs)}`}
          </span>
        </div>
        <p className="text-sm text-slate-600">
          {d.quantity}
          {d.est_kg ? ` · ~${Number(d.est_kg)} kg` : ''}
        </p>
        <p className="text-xs text-slate-500 truncate">from {d.donor_name}</p>
        <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
          {safetyChecked && <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">✅ Safety checked</span>}
          {!claimed && (
            <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
              📡 {d.search_radius_m / 1000} km reach
            </span>
          )}
        </div>
      </div>
    </button>
  )
}
