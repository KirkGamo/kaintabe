// Great-circle distance in metres. Mirrors the PostGIS range check for instant UI filtering;
// the server (claim_donation) remains the source of truth when claiming.
export function distanceM(a, b) {
  const R = 6371000
  const rad = (x) => (x * Math.PI) / 180
  const dLat = rad(b.lat - a.lat)
  const dLng = rad(b.lng - a.lng)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function formatDistance(m) {
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`
}

export function directionsUrl({ lat, lng }) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`
}
