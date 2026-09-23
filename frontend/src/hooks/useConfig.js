import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

const DEFAULTS = { radius_start_m: 2000, radius_max_m: 8000, widen_after_minutes: 10 }

/** Tunables from app_config (re-read every 30 s so demo-mode switches show up without a reload). */
export function useConfig() {
  const [config, setConfig] = useState(DEFAULTS)
  useEffect(() => {
    const load = () =>
      supabase
        .from('app_config')
        .select('key, value')
        .then(({ data, error }) => {
          if (!error) setConfig({ ...DEFAULTS, ...Object.fromEntries(data.map((r) => [r.key, Number(r.value)])) })
        })
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])
  return config
}
