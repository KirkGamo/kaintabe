import { Fragment, useEffect } from 'react'
import L from 'leaflet'
import { Circle, MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { timeLeft, urgency, URGENCY_COLORS, formatLeft } from '../lib/urgency'

const ILOILO = [10.7102, 122.5553]

// Emoji-in-a-circle pins: no image assets to break under the bundler
function pinIcon({ color, emoji, size = 34, ring = false, faded = false }) {
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
    html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${color};
      display:flex;align-items:center;justify-content:center;font-size:${size * 0.5}px;
      border:3px solid white;opacity:${faded ? 0.55 : 1};box-shadow:0 1px 4px rgba(0,0,0,.35);
      ${ring ? `outline:3px solid ${color};outline-offset:2px;` : ''}">${emoji}</div>`,
  })
}

function FlyTo({ target }) {
  const map = useMap()
  useEffect(() => {
    if (target) map.flyTo([target.lat, target.lng], Math.max(map.getZoom(), 15), { duration: 0.6 })
  }, [target, map])
  return null
}

// Public/approximate locations are grid-cell centers; draw them as an area, never a precise pin
const APPROX_AREA_M = 300

/**
 * items: [{ donation, mode }]
 *   exact:       'open' (in the org's reach) · 'mine' (claimed by this viewer) · 'own' (the donor's listing)
 *   approximate: 'public' (no identity) · 'out' (outside the org's reach) — location is a ~500 m cell
 * home: the viewer's own spot (org / donor / individual), if known
 */
export default function MapView({ items, recipients, viewer, home, selected, onSelect, now }) {
  return (
    <MapContainer center={ILOILO} zoom={14} className="h-full w-full" zoomControl={false}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FlyTo target={selected} />

      {recipients.map((r) => (
        <Marker
          key={r.id}
          position={[r.lat, r.lng]}
          icon={pinIcon({ color: r.id === viewer?.id ? '#4f46e5' : '#64748b', emoji: '🏠', size: 30 })}
          zIndexOffset={-100}
        >
          <Popup>
            <strong>{r.name}</strong>
            {r.review_status === 'pending_review' && (
              <>
                <br />
                <span style={{ color: '#b45309' }}>🕓 Pending review (self-declared)</span>
              </>
            )}
            <br />
            {[r.capacity, r.hours].filter(Boolean).join(' · ')}
          </Popup>
        </Marker>
      ))}

      {home && (
        <Marker position={[home.lat, home.lng]} icon={pinIcon({ color: '#0f766e', emoji: '📍', size: 28 })} zIndexOffset={-200}>
          <Popup>{home.label}</Popup>
        </Marker>
      )}

      {items.map(({ donation: d, mode }) => {
        const { leftMs, fraction } = timeLeft(d, now)
        const approx = mode === 'public' || mode === 'out'
        const color = approx && mode === 'out' ? '#94a3b8' : URGENCY_COLORS[urgency(fraction)].hex
        const isSelected = selected?.id === d.id
        if (approx) {
          return (
            <Circle
              key={d.id}
              center={[d.lat, d.lng]}
              radius={APPROX_AREA_M}
              pathOptions={{ color, weight: isSelected ? 3 : 1.5, fillColor: color, fillOpacity: isSelected ? 0.35 : 0.2 }}
              eventHandlers={{ click: () => onSelect(d) }}
            >
              <Popup>
                <strong>{d.food_type}</strong>
                {d.listing_type === 'sale' ? ' · 🏷️ for sale' : ''}
                <br />
                {formatLeft(leftMs)} left · approximate area
                {mode === 'out' && (
                  <>
                    <br />
                    <em>Not in your area yet: its reach doesn't cover you</em>
                  </>
                )}
              </Popup>
            </Circle>
          )
        }
        const mine = mode === 'mine'
        const pinColor = mine ? '#4f46e5' : mode === 'own' ? '#0f766e' : color
        return (
          <Fragment key={d.id}>
            {/* Outline-only reach circles so overlapping listings stay readable; fill the selected one */}
            {!mine && (
              <Circle
                center={[d.lat, d.lng]}
                radius={d.search_radius_m}
                pathOptions={{
                  color: pinColor,
                  weight: isSelected ? 2 : 1,
                  opacity: isSelected ? 0.9 : 0.5,
                  fillOpacity: isSelected ? 0.12 : 0,
                  dashArray: '4 6',
                }}
              />
            )}
            <Marker
              position={[d.lat, d.lng]}
              icon={pinIcon({
                color: pinColor,
                emoji: mine ? '✔️' : mode === 'own' ? '📦' : d.listing_type === 'sale' ? '🏷️' : '🍱',
                ring: isSelected,
              })}
              zIndexOffset={isSelected ? 1000 : 0}
              eventHandlers={{ click: () => onSelect(d) }}
            >
              <Popup>
                <strong>{d.food_type}</strong> · {d.quantity}
                <br />
                {mine ? 'Claimed by you' : mode === 'own' ? 'Your listing' : `${formatLeft(leftMs)} left`}
              </Popup>
            </Marker>
          </Fragment>
        )
      })}
    </MapContainer>
  )
}
