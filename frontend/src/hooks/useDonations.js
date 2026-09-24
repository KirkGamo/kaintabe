import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

export const ACTIVE_STATUSES = ['posted', 'escalated', 'claimed']

// public_listings: every listing with an APPROXIMATE location (~500 m grid cell), no donor name,
// no photo. This is all the browser's public key can read; exact details come from /api/map.
const COLUMNS =
  'id, status, listing_type, food_type, est_kg, original_price, current_price, allergens, ai_assisted, ' +
  'safety_checked, expires_at, created_at, search_radius_m, radius_widened_at, flash_offer_count, lat, lng'

/**
 * Live public listings via Supabase Realtime.
 * Returns { donations, live, changedAt } — changedAt bumps on every change (used to refresh role views).
 */
export function useDonations() {
  const [byId, setById] = useState({})
  const [live, setLive] = useState(false)
  const [changedAt, setChangedAt] = useState(0)

  useEffect(() => {
    let cancelled = false

    const upsert = (row) =>
      setById((prev) => {
        const next = { ...prev }
        if (ACTIVE_STATUSES.includes(row.status)) next[row.id] = row
        else delete next[row.id]
        return next
      })

    // Subscribe first, then load, so nothing posted in between is missed
    const channel = supabase
      .channel('public-listings-feed')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'public_listings' }, (payload) => {
        if (payload.eventType === 'DELETE') {
          setById((prev) => {
            const next = { ...prev }
            delete next[payload.old.id]
            return next
          })
        } else {
          upsert(payload.new)
        }
        setChangedAt(Date.now())
      })
      .subscribe((status) => setLive(status === 'SUBSCRIBED'))

    supabase
      .from('public_listings')
      .select(COLUMNS)
      .in('status', ACTIVE_STATUSES)
      .gt('expires_at', new Date(Date.now() - 24 * 3600 * 1000).toISOString())
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) {
          console.error('load listings failed', error)
          return
        }
        setById((prev) => ({ ...Object.fromEntries(data.map((d) => [d.id, d])), ...prev }))
      })

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [])

  return { donations: Object.values(byId), live, changedAt }
}

export function useRecipients() {
  const [recipients, setRecipients] = useState([])
  useEffect(() => {
    supabase
      .from('recipients')
      .select('id, name, type, lat, lng, capacity, hours, org_kind, review_status')
      .eq('type', 'partner_org')
      .order('name')
      .then(({ data, error }) => {
        if (error) console.error('load recipients failed', error)
        else setRecipients(data)
      })
  }, [])
  return recipients
}
