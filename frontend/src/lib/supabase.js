import { createClient } from '@supabase/supabase-js'

const trimSlash = (url) => (url ?? '').replace(/\/+$/, '')

export const SUPABASE_URL = trimSlash(import.meta.env.VITE_SUPABASE_URL)
export const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY
export const API_URL = trimSlash(import.meta.env.VITE_API_URL)

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
