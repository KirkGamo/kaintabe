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

/**
 * Where a listing is in the auto-widen cycle (mirrors widen_unclaimed() in SQL):
 *  { phase: 'widening' | 'escalating' | 'escalated', msUntilNext }
 */
export function reachState(d, config, now) {
  if (d.status === 'escalated') return { phase: 'escalated', msUntilNext: 0 }
  const next = new Date(d.radius_widened_at).getTime() + config.widen_after_minutes * 60000
  const phase = d.search_radius_m >= config.radius_max_m ? 'escalating' : 'widening'
  return { phase, msUntilNext: Math.max(0, next - now) }
}

/**
 * When a listing's reach (search radius) will cover a spot `distM` metres away, mirroring
 * widen_unclaimed(): donations double their radius every widen period up to the max; a sale
 * first becomes a free donation after the sale window, then widens the same way.
 *  { ms: 0 }       already reaches it
 *  { ms: n }       reaches it in about n ms (if nobody claims it first)
 *  { ms: null }    never: farther than the max reach, or not before the food expires
 */
export function reachEta(d, distM, config, now) {
  const max = config.radius_max_m
  let r = d.search_radius_m
  if (d.status === 'escalated' || r >= distM) return { ms: r >= distM ? 0 : null }
  if (distM > max) return { ms: null }
  const W = config.widen_after_minutes * 60000
  const since = new Date(d.radius_widened_at).getTime()
  let t = d.listing_type === 'sale' ? since + config.sale_window_minutes * 60000 + W : since + W
  while (r < distM) {
    r = Math.min(r * 2, max)
    if (r >= distM) break
    t += W
  }
  const expires = new Date(d.expires_at).getTime()
  return { ms: t < expires ? Math.max(0, t - now) : null }
}

/**
 * Sale listings: price now and time until it turns into a free donation.
 * Mirrors decay_sale_prices() in SQL; the server's price is what gets locked on reserve.
 */
export function saleState(d, config, now) {
  const windowMs = config.sale_window_minutes * 60000
  const elapsed = now - new Date(d.radius_widened_at).getTime()
  const original = Number(d.original_price)
  const price = Math.max(1, Math.round(original * (1 - elapsed / windowMs)))
  return { price, original, msUntilFree: Math.max(0, windowMs - elapsed) }
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
