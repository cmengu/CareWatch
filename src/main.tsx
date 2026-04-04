import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { supabase } from './lib/supabase'
import './index.css'
import App from './App.tsx'

void supabase

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
