import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

export const ACTIVE_STATUSES = ['posted', 'escalated', 'claimed']

const COLUMNS =
  'id, donor_name, photo_url, food_type, quantity, est_kg, lat, lng, listing_type, current_price, ' +
  'expires_at, search_radius_m, radius_widened_at, status, created_at, safety_checklist'

/**
 * Active listings kept in sync via Supabase Realtime.
 * Returns { donations, live } where live = realtime channel is subscribed.
 */
export function useDonations() {
  const [byId, setById] = useState({})
  const [live, setLive] = useState(false)

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
      .channel('donations-feed')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'donations' }, (payload) => {
        if (payload.eventType === 'DELETE') {
          setById((prev) => {
            const next = { ...prev }
            delete next[payload.old.id]
            return next
          })
        } else {
          upsert(payload.new)
        }
      })
      .subscribe((status) => setLive(status === 'SUBSCRIBED'))

    supabase
      .from('donations')
      .select(COLUMNS)
      .in('status', ACTIVE_STATUSES)
      .gt('expires_at', new Date().toISOString())
      .order('created_at', { ascending: false })
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) {
          console.error('load donations failed', error)
          return
        }
        setById((prev) => ({ ...Object.fromEntries(data.map((d) => [d.id, d])), ...prev }))
      })

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [])

  return { donations: Object.values(byId), live }
}

export function useRecipients() {
  const [recipients, setRecipients] = useState([])
  useEffect(() => {
    supabase
      .from('recipients')
      .select('id, name, type, lat, lng, capacity, hours')
      .eq('type', 'partner_org')
      .order('name')
      .then(({ data, error }) => {
        if (error) console.error('load recipients failed', error)
        else setRecipients(data)
      })
  }, [])
  return recipients
}
