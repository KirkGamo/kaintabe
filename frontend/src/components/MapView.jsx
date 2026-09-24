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

// items: [{ donation, mode: "open" | "out" | "mine" }] — "out" = listing whose reach doesn't cover the viewer
export default function MapView({ items, recipients, viewer, selected, onSelect, now }) {
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

      {items.map(({ donation: d, mode }) => {
        const { leftMs, fraction } = timeLeft(d, now)
        const mine = mode === 'mine'
        const out = mode === 'out'
        const color = mine ? '#4f46e5' : out ? '#94a3b8' : URGENCY_COLORS[urgency(fraction)].hex
        const isSelected = selected?.id === d.id
        return (
          <Fragment key={d.id}>
            {/* Outline-only reach circles so overlapping listings stay readable; fill the selected one */}
            {!mine && (
              <Circle
                center={[d.lat, d.lng]}
                radius={d.search_radius_m}
                pathOptions={{
                  color,
                  weight: isSelected ? 2 : 1,
                  opacity: isSelected ? 0.9 : out ? 0.35 : 0.5,
                  fillOpacity: isSelected ? 0.12 : 0,
                  dashArray: '4 6',
                }}
              />
            )}
            <Marker
              position={[d.lat, d.lng]}
              icon={pinIcon({ color, emoji: mine ? '✔️' : d.listing_type === 'sale' ? '🏷️' : '🍱', ring: isSelected, faded: out })}
              zIndexOffset={isSelected ? 1000 : out ? -50 : 0}
              eventHandlers={{ click: () => onSelect(d) }}
            >
              <Popup>
                <strong>{d.food_type}</strong> · {d.quantity}
                <br />
                {mine ? 'Claimed by you' : `${formatLeft(leftMs)} left`}
                {out && (
                  <>
                    <br />
                    <em>Not in your area yet: its reach doesn't cover you</em>
                  </>
                )}
              </Popup>
            </Marker>
          </Fragment>
        )
      })}
    </MapContainer>
  )
}
