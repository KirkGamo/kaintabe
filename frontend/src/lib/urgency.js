// Countdown maths shared by the map pins and the cards.

export function timeLeft(donation, now) {
  const expires = new Date(donation.expires_at).getTime()
  const created = new Date(donation.created_at).getTime()
  const leftMs = Math.max(0, expires - now)
  const fraction = expires > created ? leftMs / (expires - created) : 0
  return { leftMs, fraction }
}

// green while more than half the shelf life remains, amber until 20%, then red
export function urgency(fraction) {
  if (fraction > 0.5) return 'fresh'
  if (fraction > 0.2) return 'soon'
  return 'urgent'
}

export const URGENCY_COLORS = {
  fresh: { hex: '#059669', badge: 'bg-emerald-100 text-emerald-800' },
  soon: { hex: '#d97706', badge: 'bg-amber-100 text-amber-800' },
  urgent: { hex: '#dc2626', badge: 'bg-red-100 text-red-700' },
}

export function formatLeft(ms) {
  if (ms <= 0) return 'expired'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}h ${pad(m)}m` : `${m}:${pad(sec)}`
}
