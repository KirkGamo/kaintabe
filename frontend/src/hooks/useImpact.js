import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

/** impact_summary() from the database, re-fetched whenever a listing or claim changes. */
export function useImpact() {
  const [impact, setImpact] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    let timer = null

    const load = () =>
      supabase.rpc('impact_summary').then(({ data, error }) => {
        if (cancelled) return
        if (error) setError(error.message)
        else {
          setImpact(data)
          setError(null)
        }
      })

    // Pickups arrive as bursts of donation + claim updates; refetch once per burst
    const refetchSoon = () => {
      clearTimeout(timer)
      timer = setTimeout(load, 800)
    }

    const channel = supabase
      .channel('impact-feed')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'claims' }, refetchSoon)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'donations' }, refetchSoon)
      .subscribe()
    load()

    return () => {
      cancelled = true
      clearTimeout(timer)
      supabase.removeChannel(channel)
    }
  }, [])

  return { impact, error }
}
