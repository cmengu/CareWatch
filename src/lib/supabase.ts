import { createClient } from '@supabase/supabase-js'
import type { Database } from './types'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

if (!supabaseUrl || supabaseUrl === 'PLACEHOLDER_FILL_IN_STEP_2') {
  throw new Error('VITE_SUPABASE_URL is not set. Update .env.local with your Supabase project URL.')
}
if (!supabaseAnonKey || supabaseAnonKey === 'PLACEHOLDER_FILL_IN_STEP_2') {
  throw new Error('VITE_SUPABASE_ANON_KEY is not set. Update .env.local with your Supabase anon key.')
}

export const supabase = createClient<Database>(supabaseUrl, supabaseAnonKey)
