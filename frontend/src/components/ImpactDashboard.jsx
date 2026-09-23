import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useImpact } from '../hooks/useImpact'

const BAR = '#059669' // brand emerald; validated single-series color on the light surface
const INK_MUTED = '#898781'
const GRID = '#e1e0d9'

const nf1 = new Intl.NumberFormat('en-PH', { maximumFractionDigits: 1 })
const nf0 = new Intl.NumberFormat('en-PH', { maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('en-PH', { notation: 'compact', maximumFractionDigits: 1 })

const fmt = (n, digits = 1) => (Number(n) >= 10000 ? compact : digits ? nf1 : nf0).format(Number(n) || 0)

function dayLabel(iso, long = false) {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('en-PH', long ? { weekday: 'long', month: 'short', day: 'numeric' } : { weekday: 'short', day: 'numeric' })
}

function StatTile({ label, value, unit, note }) {
  return (
    <div className="rounded-xl bg-white border border-slate-200 p-4">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">
        {value}
        {unit && <span className="text-base font-medium text-slate-500"> {unit}</span>}
      </p>
      {note && <p className="mt-0.5 text-xs text-slate-500">{note}</p>}
    </div>
  )
}

function DayTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const { day, kg, pickups } = payload[0].payload
  return (
    <div className="rounded-lg bg-white border border-slate-200 shadow-md px-3 py-2 text-sm">
      <p className="font-semibold text-slate-900">{nf1.format(kg)} kg rescued</p>
      <p className="text-slate-500">
        {dayLabel(day, true)} · {pickups} pickup{pickups === 1 ? '' : 's'}
      </p>
    </div>
  )
}

function timeAgo(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  return hrs < 24 ? `${hrs} h ago` : `${Math.round(hrs / 24)} d ago`
}

export default function ImpactDashboard() {
  const { impact, error } = useImpact()
  const [showTable, setShowTable] = useState(false)

  if (error && !impact) {
    return <p className="p-6 text-center text-red-600">Couldn't load impact numbers: {error}</p>
  }
  if (!impact) {
    return <p className="p-6 text-center text-slate-500">Loading impact…</p>
  }

  const daily = impact.daily ?? []
  const weekKg = daily.reduce((s, d) => s + Number(d.kg), 0)

  return (
    <div className="h-full overflow-y-auto bg-slate-50">
      <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-4">
        {/* Hero figure: the one number the page leads with */}
        <section className="rounded-2xl bg-white border border-slate-200 p-6">
          <p className="text-sm font-medium text-emerald-700">Food rescued through KainTabe</p>
          <p className="mt-1 text-5xl md:text-6xl font-bold text-slate-900">
            {fmt(impact.kg_rescued)} <span className="text-3xl md:text-4xl font-semibold text-slate-500">kg</span>
          </p>
          <p className="mt-2 text-slate-600">
            {nf0.format(impact.pickups)} confirmed pickup{impact.pickups === 1 ? '' : 's'} ·{' '}
            {fmt(impact.kg_donated)} kg donated, {fmt(impact.kg_sold)} kg sold at a discount
          </p>
        </section>

        {/* KPI row */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Meals equivalent" value={fmt(impact.meals, 0)} note="≈ 0.4 kg per meal" />
          <StatTile label="CO₂e avoided" value={fmt(impact.co2e_kg)} unit="kg" note="≈ 2.5 kg per kg of food" />
          <StatTile
            label="Median time to claim"
            value={impact.median_minutes_to_claim == null ? '—' : fmt(impact.median_minutes_to_claim)}
            unit={impact.median_minutes_to_claim == null ? '' : 'min'}
            note="from post to a kitchen claiming it"
          />
          <StatTile label="Earned by donors" value={`₱${fmt(impact.pesos_to_donors, 0)}`} note="from discount sales" />
        </section>

        {/* Daily chart (single series: no legend; the title names it) */}
        <section className="rounded-xl bg-white border border-slate-200 p-4">
          <div className="flex items-baseline justify-between gap-2 mb-3">
            <div>
              <h2 className="font-semibold text-slate-900">Food rescued per day</h2>
              <p className="text-sm text-slate-500">Last 7 days · {fmt(weekKg)} kg total</p>
            </div>
            <button
              type="button"
              onClick={() => setShowTable((v) => !v)}
              className="text-sm text-slate-600 underline underline-offset-2 hover:text-slate-900"
            >
              {showTable ? 'Show chart' : 'Show table'}
            </button>
          </div>

          {showTable ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-1.5 font-medium">Day</th>
                  <th className="py-1.5 font-medium text-right">kg rescued</th>
                  <th className="py-1.5 font-medium text-right">Pickups</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {daily.map((d) => (
                  <tr key={d.day} className="border-b border-slate-100 last:border-0">
                    <td className="py-1.5">{dayLabel(d.day, true)}</td>
                    <td className="py-1.5 text-right">{nf1.format(d.kg)}</td>
                    <td className="py-1.5 text-right">{d.pickups}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="h-56" role="img" aria-label={`Food rescued per day, last 7 days, ${fmt(weekKg)} kg total`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={daily} margin={{ top: 4, right: 4, bottom: 0, left: -12 }} barCategoryGap="20%">
                  <CartesianGrid vertical={false} stroke={GRID} strokeWidth={1} />
                  <XAxis
                    dataKey="day"
                    tickFormatter={(d) => dayLabel(d)}
                    tick={{ fill: INK_MUTED, fontSize: 12 }}
                    axisLine={{ stroke: '#c3c2b7' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: INK_MUTED, fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                    unit=" kg"
                    width={56}
                  />
                  <Tooltip content={<DayTooltip />} cursor={{ fill: 'rgba(5,150,105,0.06)' }} />
                  <Bar dataKey="kg" fill={BAR} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        {/* Recent pickups */}
        <section className="rounded-xl bg-white border border-slate-200 p-4">
          <h2 className="font-semibold text-slate-900 mb-2">Latest pickups</h2>
          {impact.recent.length === 0 ? (
            <p className="text-sm text-slate-500">No confirmed pickups yet. They'll appear here live.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {impact.recent.map((r) => (
                <li key={`${r.confirmed_at}-${r.food_type}`} className="py-2 flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-slate-900">{r.food_type}</span>
                    <span className="text-slate-500"> → {r.recipient_name}</span>
                    {r.listing_type === 'sale' && <span className="ml-1 text-xs text-amber-700">🏷️ sold</span>}
                  </span>
                  <span className="shrink-0 text-slate-500 tabular-nums">
                    {nf1.format(r.kg)} kg · {timeAgo(r.confirmed_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <p className="text-xs text-slate-500 px-1">
          Counts confirmed pickups only (donated and sold). Weights are donor or AI estimates. Meals: ~0.4 kg per meal (WRAP
          uses 420 g). CO₂e: ~2.5 kg per kg of food waste avoided (FAO 2013, Food Wastage Footprint: 3.3 Gt CO₂e ÷ 1.3 Gt of
          food wasted). {nf0.format(impact.listings_posted)} listings posted so far, {nf0.format(impact.open_now)} open
          right now.
        </p>
      </div>
    </div>
  )
}
