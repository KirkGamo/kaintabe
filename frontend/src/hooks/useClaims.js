import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

/** All claims keyed by donation_id, kept live via Realtime. addClaim() applies an API result immediately. */
export function useClaims() {
  const [byDonation, setByDonation] = useState({})

  const addClaim = useCallback((claim) => setByDonation((prev) => ({ ...prev, [claim.donation_id]: claim })), [])

  useEffect(() => {
    let cancelled = false
    const channel = supabase
      .channel('claims-feed')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'claims' }, (payload) => {
        if (payload.eventType === 'DELETE') {
          setByDonation((prev) => {
            const next = { ...prev }
            for (const [k, c] of Object.entries(next)) if (c.id === payload.old.id) delete next[k]
            return next
          })
        } else {
          addClaim(payload.new)
        }
      })
      .subscribe()

    supabase
      .from('claims')
      .select('id, donation_id, recipient_id, claimed_at, confirmed_at, confirmation_photo_url, reserved_price')
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) console.error('load claims failed', error)
        else setByDonation((prev) => ({ ...Object.fromEntries(data.map((c) => [c.donation_id, c])), ...prev }))
      })

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [addClaim])

  return { claimsByDonation: byDonation, addClaim }
}
