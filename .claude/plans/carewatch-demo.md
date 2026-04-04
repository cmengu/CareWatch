# CareWatch — Phase 0 Demo Implementation Plan

**Overall Progress: `0% (0/11 steps complete)`**
**Readiness Score: 9/10** *(iteration 3 — seed data added, code bugs fixed)*

---

## TLDR

Build a zero-cost, fully functional CareWatch demo using React + Vite (PWA) on Vercel and Supabase as the backend/database/auth layer. Volunteers log in via email magic-link OTP, see their assigned seniors, and submit daily check-ins. When a senior accumulates 3 consecutive no-answer check-ins, the app automatically creates a flag. AAC staff see a live dashboard with coverage stats, an open flag queue they can action, and an XLSX import screen for onboarding seniors. One seeded AAC demonstrates the full multi-tenancy pattern (RLS on every table). No custom backend, no push notifications, no background jobs — enough to demo to stakeholders and onboard the first pilot AAC. The UI follows the Linear/Vercel/Stripe design language: Inter with `font-feature-settings`, negative letter-spacing on headings, gray-900 primary buttons, semantic color used only for status, minimal shadow, generous breathing room.

---

## Decisions Log (Pre-Check Resolved Flaws)

| # | Flaw | Resolution applied |
|---|---|---|
| 1 | `supabase.ts` imported `Database` from `./types` before `types.ts` existed | `types.ts` is now written in Step 2 alongside `supabase.ts` |
| 2 | `autoFlag` used PostgREST upsert with partial unique index — unsupported | Replaced with `SELECT` + conditional `INSERT`/`UPDATE` pattern |
| 3 | `npm create vite .` on non-empty directory hangs for interactive confirm | Step 1 explicitly instructs human to type `y` when prompted |
| 4 | `seniors_aac_unit_idx` unique index buried in Step 9, missing from schema | Moved into `supabase/schema.sql` (Step 3) |
| 5 | `ProtectedRoute` loops on authenticated user with null `profile` | Added explicit `profileError` state — shows error screen, not redirect |
| 6 | Supabase Auth localhost redirect URL never configured — magic links break in dev | Added to Step 2 human gate instructions |
| 7 | PWA icon PNGs referenced in manifest but never created | Added icon generation step in Step 1 |
| 8 | `SeniorsList` join query had ambiguous Supabase TS typing | Replaced with two explicit queries: assignments then seniors |

---

## Architecture Overview

**The problem this plan solves:** No code exists. The repo contains only docs. This plan builds the full demo from scratch.

**The pattern(s) applied:**
- **Supabase as BaaS** — PostgREST handles DB queries, Auth handles auth, RLS enforces tenancy. No custom backend.
- **Role-based routing** — Single React app serves `/volunteer/*` and `/staff/*` by reading `role` from `profiles`.
- **App-level flag trigger** — After each check-in, frontend checks last 3 outcomes for that senior and creates/updates a flag. SELECT + conditional INSERT/UPDATE (not upsert) to avoid partial-index conflict.
- **Adapter-ready import** — XLSX is parsed client-side with SheetJS. Resulting JSON goes to Supabase via upsert on a non-partial unique index `(aac_id, unit_number)`.
- **Linear/Vercel design language** — Inter variable font with `cv11` feature, negative letter-spacing on headings, gray-900 primary buttons, blue only for focus rings and links, `shadow-sm` on cards (never `shadow-md+`), `transition-colors duration-150 ease-out` on all interactive elements.

**What stays unchanged:** Nothing — greenfield project.

**What this plan adds:**

| File | Single responsibility |
|---|---|
| `src/lib/supabase.ts` | Supabase client singleton |
| `src/lib/types.ts` | TypeScript types (written Step 2, before supabase.ts uses it) |
| `src/lib/utils.ts` | `cn()` helper (clsx + tailwind-merge) |
| `src/contexts/AuthContext.tsx` | Session, profile, role, aacId — global |
| `src/components/ProtectedRoute.tsx` | Auth gate with null-profile error state |
| `src/pages/volunteer/*` | Login, seniors list, check-in form |
| `src/pages/staff/*` | Login, dashboard, flag queue, XLSX import |
| `supabase/schema.sql` | Tables, RLS, helper functions, unique indexes, seed |

**Critical decisions:**

| Decision | Alternative | Why rejected |
|---|---|---|
| Supabase direct (no Fastify for demo) | Build Fastify backend | Adds 2–3 weeks; RLS gives same guarantee |
| Email magic-link OTP | Phone OTP (Twilio) | Twilio costs money |
| SELECT + conditional INSERT for flags | PostgREST upsert | Partial indexes not supported by PostgREST upsert |
| Single Vite app, role-based routes | Two Vite apps | Adds Vercel project complexity |
| Inter + gray-900 primary buttons | Generic blue UI | Premium feel; matches Vercel/Linear/Stripe aesthetic |

**Known limitations:**

| Limitation | Why acceptable | Upgrade path |
|---|---|---|
| No phone OTP | Demo only | Phase 1: Twilio OTP via Fastify |
| No push notifications | Not needed to prove concept | Phase 1: FCM + BullMQ |
| App-level flag trigger (not atomic) | Race condition negligible in demo | Phase 1: Postgres DB trigger |
| Single seeded AAC | Demo only | Phase 1: multi-AAC onboarding + RLS already enforced |
| Light mode only | Budget Android phones; dark mode adds complexity | Phase 1: CSS variables already structured for dark mode upgrade |

---

## Clarification Gate

| Unknown | Required | Source | Blocking | Resolved |
|---|---|---|---|---|
| Supabase project URL + anon key | Env vars for `.env.local` | Human creates project, copies credentials | Steps 3–10 | ✅ Step 2 human gate |
| Vercel project name | Input during `vercel deploy` | Human | Step 10 only | ✅ Step 10 |

No unresolved unknowns. Plan proceeds.

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Output full contents of every modified file. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Any Code Changes

```
Run: ls /Users/ngchenmeng/CareWatch
Confirm: Only README.md and .claude/ exist. No src/, package.json, node_modules/.
If any unexpected files exist → STOP and report.

Run: node --version && npm --version
Confirm: Node >= 18, npm >= 9.
If below minimum → STOP and report.

Run: git status
Confirm: Clean working tree.
```

**Baseline Snapshot (agent fills during pre-flight):**
```
Node version:     ____
npm version:      ____
Files in root:    ____
Git status:       ____
```

**Checks (all must pass before Step 1):**
- [ ] `node --version` returns `v18` or higher
- [ ] Working directory is `/Users/ngchenmeng/CareWatch`
- [ ] No `package.json` exists
- [ ] Git status is clean

---

## Git workflow — Steps 1–10

For every step that creates or edits tracked files:

1. Implement the step, then run its **✓ Verification Test** and confirm **Pass**.
2. Only then run that step’s **Git checkpoint** from the repo root: `git add` → `git commit` → **`git push origin main`**.
3. Never `git add` `.env.local` or other secrets (must stay gitignored). Do not commit before verification passes. Do not squash multiple steps into one commit or one push.

---

## STEPS ANALYSIS

```
Step 1  (Scaffold + Design System)    — Non-critical  — verification only   — Idempotent: No
Step 2  (Supabase + env + types.ts)   — Critical      — full code review     — Idempotent: No (human gate)
Step 3  (DB schema + RLS)             — Critical      — full code review     — Idempotent: Yes
Step 3b (Demo seed data)              — Critical      — full code review     — Idempotent: Yes
Step 4  (Auth context + routing)      — Critical      — full code review     — Idempotent: Yes
Step 5  (Volunteer login + list)      — Non-critical  — verification only   — Idempotent: Yes
Step 6  (Check-in form + flag)        — Critical      — full code review     — Idempotent: Yes
Step 7  (Staff dashboard)             — Non-critical  — verification only   — Idempotent: Yes
Step 8  (Flag queue + update)         — Critical      — full code review     — Idempotent: Yes
Step 9  (XLSX import)                 — Critical      — full code review     — Idempotent: Yes
Step 10 (Vercel deploy)               — Non-critical  — verification only   — Idempotent: Yes
```

---

## Tasks

### Phase 1 — Foundation (Steps 1–3)

**Goal:** Running Vite dev server connected to Supabase with full schema, seed data, and premium design tokens loaded.

---

- [ ] 🟥 **Step 1: Scaffold React + Vite + TypeScript + Design System + PWA** — *Non-critical: creates files, no data*

  **Step Architecture Thinking:**

  **Pattern applied:** Design-token-first scaffold. The Tailwind config and CSS variables define the full visual language before any component is written — the same approach used by shadcn/ui, Vercel's Geist, and Stripe Elements.

  **Why this step exists first:** Every subsequent component imports `cn()`, uses Tailwind classes from the extended config, and renders with Inter. None of those contracts can change after Step 4 without touching every file.

  **Alternative rejected:** Adding design tokens incrementally per component — causes inconsistent spacing and typography mid-demo.

  **What breaks if this deviates:** If `font-feature-settings` is not set on `body`, Inter renders with the generic double-story `a`, losing the Apple/Vercel typographic feel. If `tracking` overrides are missing, headings look like Bootstrap.

  ---

  **Idempotent:** No — creates files. If partially run, delete `package.json` and `node_modules/` before re-running.

  **Pre-Read Gate:** Confirm `ls /Users/ngchenmeng/CareWatch` shows no `package.json`. If found → STOP.

  **⚠️ Interactive prompt:** `npm create vite` will ask "Current directory is not empty. Remove existing files and continue?" because `README.md` and `.claude/` exist. **Type `y` and press Enter.** This is the only interactive step.

  ```bash
  cd /Users/ngchenmeng/CareWatch

  # 1. Scaffold (type 'y' when prompted about non-empty directory)
  npm create vite@latest . -- --template react-ts

  # 2. Core dependencies
  npm install

  # 3. Tailwind CSS
  npm install -D tailwindcss postcss autoprefixer
  npx tailwindcss init -p

  # 4. PWA
  npm install -D vite-plugin-pwa

  # 5. Supabase client
  npm install @supabase/supabase-js

  # 6. Routing
  npm install react-router-dom

  # 7. XLSX parsing
  npm install xlsx

  # 8. Forms
  npm install react-hook-form

  # 9. Design system utilities
  npm install @fontsource-variable/inter lucide-react clsx tailwind-merge
  ```

  Delete Vite boilerplate (not needed):
  ```bash
  rm -f src/App.css src/assets/react.svg public/vite.svg
  ```

  Create PWA placeholder icons (required by manifest — replace with real icons before stakeholder demo):
  ```bash
  # Vite projects use "type":"module" in package.json, so require() is unavailable in plain node -e.
  # Use --input-type=commonjs to force CJS mode for this one-liner.
  node --input-type=commonjs -e "
  const fs = require('fs');
  // Minimal 1x1 PNG (blue pixel). Replace with real 192×192 and 512×512 before demo day.
  const png1x1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
  fs.writeFileSync('public/icon-192.png', png1x1);
  fs.writeFileSync('public/icon-512.png', png1x1);
  console.log('Icon placeholders created');
  "
  ```

  **`vite.config.ts`** — full replacement:
  ```typescript
  import { defineConfig } from 'vite'
  import react from '@vitejs/plugin-react'
  import { VitePWA } from 'vite-plugin-pwa'

  export default defineConfig({
    plugins: [
      react(),
      VitePWA({
        registerType: 'autoUpdate',
        manifest: {
          name: 'CareWatch',
          short_name: 'CareWatch',
          description: 'Community eldercare check-in platform',
          theme_color: '#111827',
          background_color: '#ffffff',
          display: 'standalone',
          icons: [
            { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          ],
        },
      }),
    ],
  })
  ```

  **`tailwind.config.js`** — full replacement:
  ```javascript
  // Note: tailwindcss/defaultTheme is CommonJS in Tailwind 3.x. Use require() not ESM import,
  // even though this project is ESM — tailwind.config.js is evaluated in CJS context by the CLI.
  const defaultTheme = require('tailwindcss/defaultTheme')

  /** @type {import('tailwindcss').Config} */
  module.exports = {
    content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
    theme: {
      extend: {
        fontFamily: {
          sans: ['InterVariable', 'Inter', ...defaultTheme.fontFamily.sans],
        },
        fontSize: {
          // Negative letter-spacing baked in — the single change that makes UIs look premium
          'xs':   ['0.75rem',  { lineHeight: '1rem',    letterSpacing: '-0.005em' }],
          'sm':   ['0.875rem', { lineHeight: '1.25rem', letterSpacing: '-0.005em' }],
          'base': ['1rem',     { lineHeight: '1.5rem',  letterSpacing: '-0.005em' }],
          'lg':   ['1.125rem', { lineHeight: '1.75rem', letterSpacing: '-0.01em'  }],
          'xl':   ['1.25rem',  { lineHeight: '1.75rem', letterSpacing: '-0.01em'  }],
          '2xl':  ['1.5rem',   { lineHeight: '2rem',    letterSpacing: '-0.02em'  }],
          '3xl':  ['1.875rem', { lineHeight: '2.25rem', letterSpacing: '-0.02em'  }],
          '4xl':  ['2.25rem',  { lineHeight: '2.5rem',  letterSpacing: '-0.03em'  }],
          '5xl':  ['3rem',     { lineHeight: '1',       letterSpacing: '-0.03em'  }],
        },
        boxShadow: {
          // Vercel/Linear shadow system — almost imperceptible, never heavy
          'card':      '0 1px 3px 0 rgba(0,0,0,0.06), 0 1px 2px -1px rgba(0,0,0,0.04)',
          'card-hover':'0 4px 12px 0 rgba(0,0,0,0.08), 0 2px 4px -1px rgba(0,0,0,0.04)',
          'dropdown':  '0 4px 24px 0 rgba(0,0,0,0.10), 0 1px 4px 0 rgba(0,0,0,0.06)',
        },
        borderRadius: {
          'card': '0.75rem', // 12px — cards (not 16px which is too bubbly)
        },
      },
    },
    plugins: [],
  }
  ```

  **`src/index.css`** — full replacement:
  ```css
  @import '@fontsource-variable/inter';

  @tailwind base;
  @tailwind components;
  @tailwind utilities;

  @layer base {
    :root {
      /* Semantic colour tokens — components use these, not raw Tailwind grays */
      --color-text-primary:    220 9% 7%;    /* gray-900  #111827 */
      --color-text-secondary:  220 9% 46%;   /* gray-500  #6B7280 */
      --color-text-tertiary:   220 9% 62%;   /* gray-400  #9CA3AF */
      --color-surface:         0 0% 100%;    /* white */
      --color-surface-subtle:  220 14% 97%;  /* gray-50  #F9FAFB */
      --color-border:          220 13% 91%;  /* gray-200  #E5E7EB */
      --color-border-strong:   220 13% 82%;  /* gray-300  #D1D5DB */
      --color-brand:           217 100% 50%; /* #0066FF — focus rings and links only */
    }

    *,
    *::before,
    *::after {
      box-sizing: border-box;
    }

    html {
      font-family: 'InterVariable', 'Inter', system-ui, -apple-system, sans-serif;
      /* cv11: alternate single-story 'a' — the detail that makes Inter look like Apple/Vercel */
      font-feature-settings: 'cv11', 'cv02', 'cv03', 'cv04';
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      text-rendering: optimizeLegibility;
    }

    body {
      background-color: #F9FAFB;
      color: #111827;
    }
  }

  /* Reusable component classes */
  @layer components {
    .btn-primary {
      @apply inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50;
    }
    .btn-secondary {
      @apply inline-flex items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors duration-150 hover:bg-gray-50 hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-50;
    }
    .btn-ghost {
      @apply inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 transition-colors duration-150 hover:bg-gray-100 hover:text-gray-900;
    }
    .input {
      @apply w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 transition-colors duration-150 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20;
    }
    .card {
      @apply rounded-xl border border-gray-200 bg-white shadow-card;
    }
    .label {
      @apply block text-sm font-medium text-gray-700;
    }
    .badge {
      @apply inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium;
    }
    .section-label {
      @apply text-xs font-medium uppercase tracking-widest text-gray-400;
    }
  }
  ```

  **`src/lib/utils.ts`** — create:
  ```typescript
  import { type ClassValue, clsx } from 'clsx'
  import { twMerge } from 'tailwind-merge'

  export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
  }
  ```

  **`.env.local`** — create:
  ```
  VITE_SUPABASE_URL=PLACEHOLDER_FILL_IN_STEP_2
  VITE_SUPABASE_ANON_KEY=PLACEHOLDER_FILL_IN_STEP_2
  ```

  **`.gitignore`** — ensure these lines exist (append if missing):
  ```
  .env.local
  .env
  ```

  **Note on postcss config filename:** `npx tailwindcss init -p` creates either `postcss.config.js` or `postcss.config.cjs` depending on whether the project's `package.json` has `"type": "module"`. Vite projects default to `"type": "module"`, so the file may be `postcss.config.cjs`. Accept whichever file was created — both work.

  **✓ Verification Test:**

  **Type:** Integration

  **Action:** `npm run dev` → open `http://localhost:5173` → open browser DevTools → Elements tab

  **Expected:**
  - Dev server starts with no errors
  - `document.body` has `font-family` containing `InterVariable` or `Inter` (inspect computed styles)
  - No TypeScript compile errors in terminal
  - `src/lib/utils.ts` exists and exports `cn`

  **Pass:** Server starts, Inter font is loaded, no errors.

  **Fail:**
  - `Cannot find module '@fontsource-variable/inter'` → `npm install @fontsource-variable/inter` was not run → re-run install step
  - `Module "clsx" not found` → same — re-run install
  - `EPERM: operation not permitted` on icon creation → node script failed → create placeholder PNGs manually

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add -A
  git status   # confirm .env.local does not appear (must stay untracked / gitignored)
  git commit -m "step 1: scaffold Vite + React + TS + design system (Inter, Tailwind tokens, utils)"
  git push origin main
  ```

---

- [ ] 🟥 **Step 2: Supabase project + environment + types.ts** — *Critical: types.ts must exist before supabase.ts imports it*

  **Step Architecture Thinking:**

  **Pattern applied:** Types-first — `types.ts` is written before `supabase.ts` to satisfy the import dependency chain. This is the same pattern used by Supabase's own CLI (`supabase gen types typescript`).

  **Why types.ts is in this step, not Step 3:** `supabase.ts` uses `createClient<Database>()`. If `types.ts` doesn't exist when `supabase.ts` is written, TypeScript errors block the dev server from starting for all subsequent steps.

  **Alternative rejected:** Write `supabase.ts` without the `Database` generic, add it later — causes silent type loss on all Supabase query results.

  **What breaks if this deviates:** If `types.ts` is written after `supabase.ts`, every step from 3 onwards starts with a compile error. The agent would have to backtrack.

  ---

  **Idempotent:** No — human must create a Supabase project. If the project already exists, skip to "copy credentials".

  **Human Gate (Supabase project creation):**

  Output `"[WAITING: Go to https://supabase.com/dashboard → New project. Name: carewatch-demo. Plan: Free. Region: Southeast Asia (Singapore). Once created: Settings → API → copy (1) Project URL, (2) anon/public key. Then: Authentication → URL Configuration → add http://localhost:5173/** to Redirect URLs (required for magic links in dev). Reply with the URL and anon key.]"` as the final line of your response.
  Do not write any code or call any tools after this line.

  ---

  *(Resume after human provides URL and anon key)*

  Update **`.env.local`** with real values:
  ```
  VITE_SUPABASE_URL=<human-provided project URL>
  VITE_SUPABASE_ANON_KEY=<human-provided anon key>
  ```

  Write **`src/lib/types.ts`** — must be created BEFORE `supabase.ts`:
  ```typescript
  // ─────────────────────────────────────────────────────────────
  // Domain types — derived from supabase/schema.sql
  // Written in Step 2 so supabase.ts can import Database below.
  // ─────────────────────────────────────────────────────────────

  export type Role = 'volunteer' | 'staff' | 'admin'
  export type CheckInOutcome = 'ok' | 'no_answer' | 'flagged'
  export type FlagStatus = 'open' | 'reviewed' | 'actioned' | 'escalated'
  export type ConsentStatus = 'pending' | 'given' | 'withdrawn'
  export type EscalationLevel = 'review' | 'urgent' | 'emergency'

  /** Seeded in Step 3 — single demo tenant */
  export const DEMO_AAC_ID = '00000000-0000-0000-0000-000000000001'

  export interface Profile {
    id: string
    aac_id: string
    role: Role
    name: string
    phone_number: string | null
    created_at: string
  }

  export interface Senior {
    id: string
    aac_id: string
    name: string
    unit_number: string
    block: string | null
    preferred_language: string
    mobility_notes: string | null
    consent_status: ConsentStatus
    consent_date: string | null
    aac_notes: string | null
    visible_fields: Record<string, unknown>
    created_at: string
    updated_at: string
  }

  export interface Assignment {
    id: string
    aac_id: string
    volunteer_id: string
    senior_id: string
    assigned_by: string | null
    assigned_at: string
    ended_at: string | null
  }

  export interface CheckIn {
    id: string
    aac_id: string
    volunteer_id: string
    senior_id: string
    outcome: CheckInOutcome
    notes: string | null
    created_at: string
  }

  export interface Flag {
    id: string
    aac_id: string
    checkin_id: string | null
    senior_id: string
    consecutive_count: number
    status: FlagStatus
    actioned_by: string | null
    actioned_at: string | null
    staff_notes: string | null
    created_at: string
  }

  // ─────────────────────────────────────────────────────────────
  // Supabase Database type — used by createClient<Database>()
  // ─────────────────────────────────────────────────────────────
  export interface Database {
    public: {
      Tables: {
        aacs: {
          Row: { id: string; name: string; created_at: string }
          Insert: { id?: string; name: string }
          Update: Partial<{ name: string }>
        }
        profiles: {
          Row: Profile
          Insert: Omit<Profile, 'created_at'>
          Update: Partial<Omit<Profile, 'id'>>
        }
        seniors: {
          Row: Senior
          Insert: Omit<Senior, 'id' | 'created_at' | 'updated_at'>
          Update: Partial<Omit<Senior, 'id' | 'aac_id' | 'created_at' | 'updated_at'>>
        }
        assignments: {
          Row: Assignment
          Insert: Omit<Assignment, 'id' | 'assigned_at'>
          Update: Partial<Omit<Assignment, 'id' | 'aac_id'>>
        }
        checkins: {
          Row: CheckIn
          Insert: Omit<CheckIn, 'id' | 'created_at'>
          Update: Partial<Omit<CheckIn, 'id' | 'aac_id'>>
        }
        flags: {
          Row: Flag
          Insert: Omit<Flag, 'id' | 'created_at'>
          Update: Partial<Omit<Flag, 'id' | 'aac_id'>>
        }
      }
    }
  }
  ```

  Write **`src/lib/supabase.ts`** — after types.ts exists:
  ```typescript
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
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** Add `import { supabase } from './lib/supabase'` to `src/main.tsx` temporarily. Run `npm run dev`. Check browser console.

  **Expected:** No `Missing env variable` error. Supabase client initialises without throwing.

  **Pass:** Dev server starts, no env-variable errors in console.

  **Fail:**
  - `VITE_SUPABASE_URL is not set` → `.env.local` placeholder not replaced → re-check file
  - TypeScript error `Cannot find module './types'` → `types.ts` not created before `supabase.ts` → check file order in this step

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/lib/types.ts src/lib/supabase.ts
  # Do NOT add .env.local — it is gitignored
  git commit -m "step 2: types.ts + Supabase client with typed Database generic"
  git push origin main
  ```

---

- [ ] 🟥 **Step 3: Database schema + RLS policies + seed data** — *Critical: defines data contract for all app logic*

  **Step Architecture Thinking:**

  **Pattern applied:** Schema-first. All tables, RLS policies, helper functions, and unique indexes are in one SQL file, run once. The `seniors_aac_unit_idx` unique index is here (not buried in Step 9 prose) so the upsert in Step 9 works without a separate SQL run.

  **Why the helper functions use `SECURITY DEFINER`:** RLS policies cannot call other functions that are subject to RLS. `get_my_aac_id()` queries `profiles` — which has RLS — from within another RLS policy. `SECURITY DEFINER` makes the function execute as its owner (postgres), bypassing RLS for that internal lookup only. This is the Supabase-recommended pattern.

  **What breaks if this deviates:** If `get_my_aac_id()` is missing or doesn't use `SECURITY DEFINER`, every RLS policy referencing it will silently return no rows for all users.

  ---

  **Idempotent:** Yes — all statements use `IF NOT EXISTS` or `CREATE OR REPLACE`. `DROP POLICY IF EXISTS` before `CREATE POLICY`.

  Write **`supabase/schema.sql`**:

  ```sql
  -- ============================================================
  -- CareWatch Demo Schema
  -- Run in full in the Supabase SQL Editor (SQL → New query → Run)
  -- ============================================================

  -- AACs
  create table if not exists aacs (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz default now()
  );

  -- Profiles: links auth.users → role + aac
  create table if not exists profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    aac_id uuid references aacs(id) not null,
    role text check (role in ('volunteer', 'staff', 'admin')) not null,
    name text not null,
    phone_number text,
    created_at timestamptz default now()
  );

  -- Seniors
  create table if not exists seniors (
    id uuid primary key default gen_random_uuid(),
    aac_id uuid references aacs(id) not null,
    name text not null,
    unit_number text not null,
    block text,
    preferred_language text default 'English',
    mobility_notes text,
    consent_status text default 'pending' check (consent_status in ('pending', 'given', 'withdrawn')),
    consent_date date,
    aac_notes text,
    visible_fields jsonb default '{}',
    created_at timestamptz default now(),
    updated_at timestamptz default now()
  );

  -- Unique: one senior per unit per AAC (enables idempotent XLSX upsert in Step 9)
  create unique index if not exists seniors_aac_unit_idx on seniors (aac_id, unit_number);

  -- Assignments
  create table if not exists assignments (
    id uuid primary key default gen_random_uuid(),
    aac_id uuid references aacs(id) not null,
    volunteer_id uuid references profiles(id) not null,
    senior_id uuid references seniors(id) not null,
    assigned_by uuid references profiles(id),
    assigned_at timestamptz default now(),
    ended_at timestamptz
  );

  -- CheckIns
  create table if not exists checkins (
    id uuid primary key default gen_random_uuid(),
    aac_id uuid references aacs(id) not null,
    volunteer_id uuid references profiles(id) not null,
    senior_id uuid references seniors(id) not null,
    outcome text check (outcome in ('ok', 'no_answer', 'flagged')) not null,
    notes text,
    created_at timestamptz default now()
  );

  -- Flags
  create table if not exists flags (
    id uuid primary key default gen_random_uuid(),
    aac_id uuid references aacs(id) not null,
    checkin_id uuid references checkins(id),
    senior_id uuid references seniors(id) not null,
    consecutive_count int default 1,
    status text check (status in ('open', 'reviewed', 'actioned', 'escalated')) default 'open',
    actioned_by uuid references profiles(id),
    actioned_at timestamptz,
    staff_notes text,
    created_at timestamptz default now()
  );

  -- Escalation Cases
  create table if not exists escalation_cases (
    id uuid primary key default gen_random_uuid(),
    aac_id uuid references aacs(id) not null,
    flag_id uuid references flags(id),
    senior_id uuid references seniors(id) not null,
    level text check (level in ('review', 'urgent', 'emergency')) not null,
    opened_by uuid references profiles(id) not null,
    opened_at timestamptz default now(),
    action_taken text,
    outcome text,
    closed_at timestamptz
  );

  -- Audit Log
  create table if not exists audit_log (
    id uuid primary key default gen_random_uuid(),
    aac_id uuid references aacs(id) not null,
    actor_id uuid references profiles(id),
    actor_role text,
    action text not null,
    entity_type text not null,
    entity_id uuid,
    diff jsonb,
    created_at timestamptz default now()
  );

  -- ============================================================
  -- Enable RLS
  -- ============================================================
  alter table aacs enable row level security;
  alter table profiles enable row level security;
  alter table seniors enable row level security;
  alter table assignments enable row level security;
  alter table checkins enable row level security;
  alter table flags enable row level security;
  alter table escalation_cases enable row level security;
  alter table audit_log enable row level security;

  -- ============================================================
  -- Helper functions (SECURITY DEFINER — bypass RLS for internal lookup)
  -- ============================================================
  create or replace function get_my_aac_id()
  returns uuid language sql stable security definer as $$
    select aac_id from profiles where id = auth.uid()
  $$;

  create or replace function get_my_role()
  returns text language sql stable security definer as $$
    select role from profiles where id = auth.uid()
  $$;

  -- ============================================================
  -- RLS Policies
  -- ============================================================

  -- profiles: own row + staff sees AAC peers
  drop policy if exists "users view own profile" on profiles;
  create policy "users view own profile" on profiles
    for select using (id = auth.uid());

  drop policy if exists "users insert own profile" on profiles;
  create policy "users insert own profile" on profiles
    for insert with check (id = auth.uid());

  drop policy if exists "staff view aac profiles" on profiles;
  create policy "staff view aac profiles" on profiles
    for select using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  -- seniors: volunteers see only assigned; staff see all in AAC
  drop policy if exists "volunteers see assigned seniors" on seniors;
  create policy "volunteers see assigned seniors" on seniors
    for select using (
      get_my_role() = 'volunteer'
      and id in (
        select senior_id from assignments
        where volunteer_id = auth.uid() and ended_at is null
      )
    );

  drop policy if exists "staff manage seniors" on seniors;
  create policy "staff manage seniors" on seniors
    for all using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  -- assignments
  drop policy if exists "volunteers see own assignments" on assignments;
  create policy "volunteers see own assignments" on assignments
    for select using (volunteer_id = auth.uid());

  drop policy if exists "staff manage assignments" on assignments;
  create policy "staff manage assignments" on assignments
    for all using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  -- checkins
  drop policy if exists "volunteers insert checkins" on checkins;
  create policy "volunteers insert checkins" on checkins
    for insert with check (
      volunteer_id = auth.uid() and aac_id = get_my_aac_id()
    );

  drop policy if exists "volunteers see own checkins" on checkins;
  create policy "volunteers see own checkins" on checkins
    for select using (volunteer_id = auth.uid());

  drop policy if exists "staff view checkins" on checkins;
  create policy "staff view checkins" on checkins
    for select using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  -- flags: volunteers can insert (flag logic in app); staff own all
  drop policy if exists "volunteers insert flags" on flags;
  create policy "volunteers insert flags" on flags
    for insert with check (aac_id = get_my_aac_id());

  drop policy if exists "volunteers update own flags" on flags;
  create policy "volunteers update own flags" on flags
    for update using (aac_id = get_my_aac_id() and get_my_role() = 'volunteer');

  drop policy if exists "staff manage flags" on flags;
  create policy "staff manage flags" on flags
    for all using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  -- escalation_cases: staff only
  drop policy if exists "staff manage escalations" on escalation_cases;
  create policy "staff manage escalations" on escalation_cases
    for all using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  -- audit_log: staff read; authenticated insert
  drop policy if exists "staff read audit log" on audit_log;
  create policy "staff read audit log" on audit_log
    for select using (
      get_my_role() in ('staff', 'admin') and aac_id = get_my_aac_id()
    );

  drop policy if exists "authenticated insert audit log" on audit_log;
  create policy "authenticated insert audit log" on audit_log
    for insert with check (aac_id = get_my_aac_id());

  -- ============================================================
  -- Seed: one demo AAC (fixed UUID for DEMO_AAC_ID constant in types.ts)
  -- ============================================================
  insert into aacs (id, name)
  values ('00000000-0000-0000-0000-000000000001', 'Tampines AAC Demo')
  on conflict (id) do nothing;
  ```

  **Human Gate (schema execution):**
  Output `"[WAITING: Open Supabase SQL Editor → New query → paste the full contents of supabase/schema.sql → Run. Once it shows 'Success. No rows returned', reply 'schema done'.]"` as the final line of your response.
  Do not write any code or call any tools after this line.

  **✓ Verification Test:**

  **Type:** Integration (manual in Supabase dashboard)

  **Action:** Go to Supabase → Table Editor

  **Expected:**
  - 8 tables visible: `aacs`, `profiles`, `seniors`, `assignments`, `checkins`, `flags`, `escalation_cases`, `audit_log`
  - `aacs` has 1 row: `Tampines AAC Demo` with id `00000000-0000-0000-0000-000000000001`
  - Supabase → Authentication → Policies shows policies on all 8 tables

  **Pass:** All 8 tables exist, seed row present, policies listed.

  **Fail:**
  - Table missing → SQL did not fully execute → re-run schema.sql
  - `get_my_aac_id function already exists` error → safe to ignore (uses `CREATE OR REPLACE`)
  - `policy already exists` error → SQL uses `DROP POLICY IF EXISTS` first — if this error appears, a prior run was partial → re-run the full SQL

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add supabase/schema.sql
  git commit -m "step 3: database schema — tables, RLS, unique indexes, seed AAC"
  git push origin main
  ```

---

---

- [ ] 🟥 **Step 3b: Demo seed data** — *Critical: without this the demo shows empty states everywhere*

  **Step Architecture Thinking:**

  **Pattern applied:** Pre-loaded realistic data so the demo is immediately compelling — no SQL knowledge required from the person running the demo. Seniors are inserted independently of user accounts. The open flag is pre-seeded so the staff dashboard shows a non-zero flag count the moment staff logs in.

  **Why this is a separate step from Step 3:** Schema SQL runs once and is idempotent against table structure. Seed data runs after test auth accounts exist (the staff and volunteer profile rows reference `auth.users`). Separating them prevents the ordering problem of seeding profiles before users are created.

  **What breaks without this:** Every screen in the demo shows empty state. The volunteer sees "No seniors assigned". The staff dashboard shows 0 across all tiles. The flag queue shows "All clear". A stakeholder watching cannot evaluate the product.

  **Execution order:**
  1. Human creates two auth accounts (Step 3b Human Gate — same Supabase Auth dashboard used in Step 2)
  2. Agent writes and runs `supabase/seed-demo.sql`

  ---

  **Idempotent:** Yes — all inserts use `ON CONFLICT DO NOTHING`.

  **Human Gate (create test accounts):**

  Output `"[WAITING: In Supabase dashboard → Authentication → Users, create two accounts: (1) Volunteer — email: volunteer@demo.carewatch.sg, password: Demo1234! — note down the UUID shown in the users table. (2) Staff — email: staff@demo.carewatch.sg, password: Demo1234! — note down the UUID. Reply with: VOLUNTEER_UUID=<uuid> STAFF_UUID=<uuid>]"` as the final line of your response.
  Do not write any code or call any tools after this line.

  ---

  *(Resume after human provides both UUIDs)*

  Write **`supabase/seed-demo.sql`** — replace `VOLUNTEER_UUID_HERE` and `STAFF_UUID_HERE` with the values provided:

  ```sql
  -- ============================================================
  -- CareWatch Demo Seed Data
  -- Run AFTER schema.sql and AFTER creating test auth accounts.
  -- Replace VOLUNTEER_UUID_HERE and STAFF_UUID_HERE before running.
  -- ============================================================

  -- Volunteer profile
  insert into profiles (id, aac_id, role, name, phone_number)
  values (
    'VOLUNTEER_UUID_HERE',
    '00000000-0000-0000-0000-000000000001',
    'volunteer',
    'Mdm Siti Rahimah',
    '+65 9123 4567'
  ) on conflict (id) do nothing;

  -- Staff profile
  insert into profiles (id, aac_id, role, name)
  values (
    'STAFF_UUID_HERE',
    '00000000-0000-0000-0000-000000000001',
    'staff',
    'James Tan (AAC Coordinator)'
  ) on conflict (id) do nothing;

  -- 10 realistic HDB seniors in Tampines
  insert into seniors (id, aac_id, name, unit_number, block, preferred_language, mobility_notes, consent_status)
  values
    ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Mdm Lim Ah Kow',      '08-112', '473', 'Hokkien',  null,                               'given'),
    ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Mr S Ramasamy',       '04-21',  '471', 'Tamil',    'Uses walking stick',               'given'),
    ('10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Mdm Chen Siu Fong',   '12-05',  '475', 'Mandarin', null,                               'given'),
    ('10000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Mr Abdul Hamid',      '03-88',  '476', 'Malay',    'Hard of hearing — knock loudly',    'given'),
    ('10000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Mdm Tan Bee Lian',    '07-333', '478', 'Hokkien',  null,                               'given'),
    ('10000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'Mr Goh Ah Huat',      '11-201', '479', 'Cantonese','Wheelchair user',                  'given'),
    ('10000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'Mdm Nair Kamala',     '05-66',  '480', 'English',  null,                               'given'),
    ('10000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000001', 'Mr Ong Teck Huat',    '09-14',  '481', 'Teochew',  null,                               'given'),
    ('10000000-0000-0000-0000-000000000009', '00000000-0000-0000-0000-000000000001', 'Mdm Zainab Binte Ali','02-55',  '471', 'Malay',    null,                               'given'),
    ('10000000-0000-0000-0000-000000000010', '00000000-0000-0000-0000-000000000001', 'Mr Lee Chong Wei',    '06-99',  '473', 'Mandarin', 'Recently discharged from hospital', 'given')
  on conflict (aac_id, unit_number) do nothing;

  -- Assign first 4 seniors to the volunteer
  insert into assignments (aac_id, volunteer_id, senior_id, assigned_at)
  values
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000001', now() - interval '14 days'),
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000002', now() - interval '14 days'),
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000003', now() - interval '14 days'),
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000004', now() - interval '14 days')
  on conflict do nothing;

  -- Pre-seed 3 consecutive no-answer check-ins for Mr Abdul Hamid (senior 004)
  -- so the flag queue is non-empty the moment staff logs in
  insert into checkins (id, aac_id, volunteer_id, senior_id, outcome, notes, created_at)
  values
    ('20000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000004', 'no_answer', 'No response', now() - interval '3 days'),
    ('20000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000004', 'no_answer', 'No response again', now() - interval '2 days'),
    ('20000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000004', 'no_answer', 'Still no answer — very unusual', now() - interval '1 day')
  on conflict do nothing;

  -- Also seed some "ok" check-ins for the other seniors so today's stats look realistic
  insert into checkins (aac_id, volunteer_id, senior_id, outcome, created_at)
  values
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000001', 'ok', now() - interval '1 day'),
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000002', 'ok', now() - interval '1 day'),
    ('00000000-0000-0000-0000-000000000001', 'VOLUNTEER_UUID_HERE', '10000000-0000-0000-0000-000000000003', 'ok', now() - interval '1 day')
  on conflict do nothing;

  -- Open flag for Mr Abdul Hamid (triggered by the 3 consecutive no-answers above)
  insert into flags (id, aac_id, checkin_id, senior_id, consecutive_count, status)
  values (
    '30000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004',
    3,
    'open'
  ) on conflict do nothing;
  ```

  **✓ Verification Test:**

  **Type:** Integration (manual in Supabase dashboard)

  **Action:** After running `seed-demo.sql`, go to Supabase → Table Editor

  **Expected:**
  - `seniors` table: 10 rows, names are realistic Singapore HDB seniors
  - `profiles` table: 2 rows — one volunteer, one staff
  - `assignments` table: 4 rows linking the volunteer to seniors 001–004
  - `checkins` table: 6 rows (3 no-answer + 3 ok)
  - `flags` table: 1 row — `senior_id = 10000000-...-004`, `status = 'open'`, `consecutive_count = 3`

  **Pass:** All counts correct. Flag queue will show 1 open flag immediately when staff logs in.

  **Fail:**
  - `foreign key violation` on profiles INSERT → the UUID provided doesn't match an `auth.users` row → re-check the UUID from the Supabase Auth dashboard
  - `unique constraint violation` on assignments → safe to ignore — `on conflict do nothing` handles it; re-run to confirm

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add supabase/seed-demo.sql
  git commit -m "step 3b: demo seed data — 10 seniors, 1 volunteer, 1 staff, assignments, open flag"
  git push origin main
  ```

---

### Phase 2 — Auth + Routing (Step 4)

**Goal:** Routing resolves correctly by role. Null-profile authenticated users get an error screen, not an infinite redirect.

---

- [ ] 🟥 **Step 4: Auth context + role-based routing** — *Critical: gates all protected screens*

  **Step Architecture Thinking:**

  **Pattern applied:** React Context for global session state. `ProtectedRoute` reads role from context — it does NOT redirect if profile is null after auth, it renders an error state. This prevents redirect loops when `fetchProfile` silently fails.

  **Why the error state matters:** Without it, a user with a valid Supabase session but no `profiles` row (e.g., manually created auth user without seeding profiles) gets an infinite redirect to login, with no feedback. The error state shows "Profile not found — contact your administrator," which is debuggable.

  **Alternative rejected:** Re-fetch profile on every protected page — duplicates the DB call on every navigation.

  **What breaks if this deviates:** If `loading` is used without `profileError`, a null profile from a network failure looks identical to "not logged in" — authenticated users can't access the app and don't know why.

  ---

  **Idempotent:** Yes — overwrites scaffold files.

  Write **`src/contexts/AuthContext.tsx`**:
  ```tsx
  import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
  import { Session } from '@supabase/supabase-js'
  import { supabase } from '../lib/supabase'
  import type { Profile, Role } from '../lib/types'

  interface AuthContextValue {
    session: Session | null
    profile: Profile | null
    profileError: string | null   // non-null = authenticated but profile fetch failed
    role: Role | null
    aacId: string | null
    loading: boolean
    signOut: () => Promise<void>
  }

  const AuthContext = createContext<AuthContextValue | null>(null)

  export function AuthProvider({ children }: { children: ReactNode }) {
    const [session, setSession] = useState<Session | null>(null)
    const [profile, setProfile] = useState<Profile | null>(null)
    const [profileError, setProfileError] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)

    async function fetchProfile(userId: string) {
      const { data, error } = await supabase
        .from('profiles')
        .select('*')
        .eq('id', userId)
        .single()

      if (error) {
        // PGRST116 = row not found — user exists in auth but has no profile row
        setProfileError(
          error.code === 'PGRST116'
            ? 'Profile not found. Ask your AAC coordinator to set up your account.'
            : `Could not load profile: ${error.message}`
        )
        setProfile(null)
      } else {
        setProfile(data)
        setProfileError(null)
      }
    }

    useEffect(() => {
      supabase.auth.getSession().then(async ({ data: { session } }) => {
        setSession(session)
        if (session) await fetchProfile(session.user.id)
        setLoading(false)
      })

      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        setSession(session)
        if (session) {
          fetchProfile(session.user.id)
        } else {
          setProfile(null)
          setProfileError(null)
        }
      })

      return () => subscription.unsubscribe()
    }, [])

    async function signOut() {
      await supabase.auth.signOut()
      setProfile(null)
      setSession(null)
      setProfileError(null)
    }

    return (
      <AuthContext.Provider value={{
        session,
        profile,
        profileError,
        role: profile?.role ?? null,
        aacId: profile?.aac_id ?? null,
        loading,
        signOut,
      }}>
        {children}
      </AuthContext.Provider>
    )
  }

  export function useAuth() {
    const ctx = useContext(AuthContext)
    if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
    return ctx
  }
  ```

  Write **`src/components/ProtectedRoute.tsx`**:
  ```tsx
  import { Navigate } from 'react-router-dom'
  import { AlertCircle } from 'lucide-react'
  import { useAuth } from '../contexts/AuthContext'
  import type { Role } from '../lib/types'

  interface Props {
    requiredRole: Role
    children: React.ReactNode
  }

  export function ProtectedRoute({ requiredRole, children }: Props) {
    const { session, role, loading, profileError } = useAuth()

    if (loading) {
      return (
        <div className="flex h-screen items-center justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-200 border-t-gray-900" />
        </div>
      )
    }

    // Authenticated but profile missing or errored — show error, don't redirect loop
    if (session && profileError) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 p-6 text-center">
          <AlertCircle className="h-8 w-8 text-red-500" />
          <p className="text-sm font-medium text-gray-900">Account setup incomplete</p>
          <p className="max-w-xs text-sm text-gray-500">{profileError}</p>
        </div>
      )
    }

    if (!session) {
      return <Navigate to={requiredRole === 'volunteer' ? '/volunteer/login' : '/staff/login'} replace />
    }

    // Role mismatch — redirect to the correct login
    const isStaffRole = role === 'staff' || role === 'admin'
    if (requiredRole === 'volunteer' && role !== 'volunteer') {
      return <Navigate to="/volunteer/login" replace />
    }
    if ((requiredRole === 'staff' || requiredRole === 'admin') && !isStaffRole) {
      return <Navigate to="/staff/login" replace />
    }

    return <>{children}</>
  }
  ```

  Write **`src/App.tsx`** — full replacement of Vite scaffold:
  ```tsx
  import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
  import { AuthProvider } from './contexts/AuthContext'
  import { ProtectedRoute } from './components/ProtectedRoute'

  import { VolunteerLogin } from './pages/volunteer/VolunteerLogin'
  import { SeniorsList } from './pages/volunteer/SeniorsList'
  import { CheckInForm } from './pages/volunteer/CheckInForm'

  import { StaffLogin } from './pages/staff/StaffLogin'
  import { Dashboard } from './pages/staff/Dashboard'
  import { FlagQueue } from './pages/staff/FlagQueue'
  import { ImportSeniors } from './pages/staff/ImportSeniors'

  export default function App() {
    return (
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Navigate to="/volunteer/login" replace />} />

            <Route path="/volunteer/login" element={<VolunteerLogin />} />
            <Route path="/volunteer/seniors" element={
              <ProtectedRoute requiredRole="volunteer"><SeniorsList /></ProtectedRoute>
            } />
            <Route path="/volunteer/seniors/:seniorId/checkin" element={
              <ProtectedRoute requiredRole="volunteer"><CheckInForm /></ProtectedRoute>
            } />

            <Route path="/staff/login" element={<StaffLogin />} />
            <Route path="/staff/dashboard" element={
              <ProtectedRoute requiredRole="staff"><Dashboard /></ProtectedRoute>
            } />
            <Route path="/staff/flags" element={
              <ProtectedRoute requiredRole="staff"><FlagQueue /></ProtectedRoute>
            } />
            <Route path="/staff/import" element={
              <ProtectedRoute requiredRole="staff"><ImportSeniors /></ProtectedRoute>
            } />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    )
  }
  ```

  Update **`src/main.tsx`** — full replacement:
  ```tsx
  import { StrictMode } from 'react'
  import { createRoot } from 'react-dom/client'
  import './index.css'
  import App from './App.tsx'

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
  ```

  Create page stubs (exact export names must match App.tsx imports):
  ```bash
  mkdir -p src/pages/volunteer src/pages/staff
  ```

  **`src/pages/volunteer/VolunteerLogin.tsx`** (stub — replaced Step 5):
  ```tsx
  export function VolunteerLogin() { return <div>Volunteer Login</div> }
  ```
  **`src/pages/volunteer/SeniorsList.tsx`** (stub — replaced Step 5):
  ```tsx
  export function SeniorsList() { return <div>Seniors List</div> }
  ```
  **`src/pages/volunteer/CheckInForm.tsx`** (stub — replaced Step 6):
  ```tsx
  export function CheckInForm() { return <div>Check-In Form</div> }
  ```
  **`src/pages/staff/StaffLogin.tsx`** (stub — replaced Step 7):
  ```tsx
  export function StaffLogin() { return <div>Staff Login</div> }
  ```
  **`src/pages/staff/Dashboard.tsx`** (stub — replaced Step 7):
  ```tsx
  export function Dashboard() { return <div>Dashboard</div> }
  ```
  **`src/pages/staff/FlagQueue.tsx`** (stub — replaced Step 8):
  ```tsx
  export function FlagQueue() { return <div>Flag Queue</div> }
  ```
  **`src/pages/staff/ImportSeniors.tsx`** (stub — replaced Step 9):
  ```tsx
  export function ImportSeniors() { return <div>Import Seniors</div> }
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:** `npm run dev` → navigate to `http://localhost:5173`

  **Expected:**
  - Redirects to `/volunteer/login` (shows "Volunteer Login" stub)
  - Navigate to `/volunteer/seniors` → redirects to `/volunteer/login`
  - Navigate to `/staff/login` → shows "Staff Login" stub
  - No TypeScript errors in terminal
  - No `useAuth must be used outside AuthProvider` errors

  **Pass:** Routing and redirects work. Zero compile errors.

  **Fail:**
  - `Cannot find module './pages/volunteer/VolunteerLogin'` → stub files not created or export name wrong → check exact export name matches `VolunteerLogin`
  - `useAuth must be used inside AuthProvider` → `ProtectedRoute` is outside the `AuthProvider` wrapper in `App.tsx` → check nesting

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/App.tsx src/main.tsx src/contexts/AuthContext.tsx \
    src/components/ProtectedRoute.tsx src/pages/
  git commit -m "step 4: auth context with profileError state, protected routes, page stubs"
  git push origin main
  ```

---

### Phase 3 — Volunteer Flow (Steps 5–6)

**Goal:** Volunteer can log in with email magic link, see assigned seniors, and submit check-ins. Flags auto-created after 3 consecutive no-answers.

---

- [ ] 🟥 **Step 5: Volunteer login + assigned seniors list** — *Non-critical: read-only UI*

  **Step Architecture Thinking:**

  **Pattern applied:** Linear/Vercel auth form aesthetic — centered, minimal, single-purpose. No hero images, no gradients. Typography carries the brand. The OTP "sent" state uses generous whitespace and a single clear message.

  **SeniorsList query fix (pre-check flaw 8):** Uses two separate queries — first get `senior_id`s from assignments, then fetch those seniors directly. This avoids the Supabase JS type ambiguity from PostgREST FK joins (`Senior | Senior[] | null`).

  **What breaks if this deviates:** If the join query is used instead, TypeScript may infer `senior` as `Senior | null` or `Senior[]` depending on the Supabase JS version, causing runtime map errors.

  ---

  **Idempotent:** Yes — replaces stubs.

  Replace **`src/pages/volunteer/VolunteerLogin.tsx`**:
  ```tsx
  import { useState } from 'react'
  import { supabase } from '../../lib/supabase'

  export function VolunteerLogin() {
    const [email, setEmail] = useState('')
    const [sent, setSent] = useState(false)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    async function handleSubmit(e: React.FormEvent) {
      e.preventDefault()
      setLoading(true)
      setError(null)
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          // Magic link lands the user on the seniors list after auth
          emailRedirectTo: `${window.location.origin}/volunteer/seniors`,
        },
      })
      if (error) setError(error.message)
      else setSent(true)
      setLoading(false)
    }

    if (sent) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-6">
          <div className="w-full max-w-sm text-center">
            <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 mx-auto">
              <svg className="h-5 w-5 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 0 1-2.25 2.25h-15a2.25 2.25 0 0 1-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25m19.5 0v.243a2.25 2.25 0 0 1-1.07 1.916l-7.5 4.615a2.25 2.25 0 0 1-2.36 0L3.32 8.91a2.25 2.25 0 0 1-1.07-1.916V6.75" />
              </svg>
            </div>
            <h1 className="text-xl font-semibold text-gray-900">Check your email</h1>
            <p className="mt-2 text-sm text-gray-500">
              We sent a login link to <span className="font-medium text-gray-900">{email}</span>
            </p>
            <p className="mt-1 text-sm text-gray-400">Click the link in your email to sign in.</p>
            <button
              onClick={() => setSent(false)}
              className="mt-8 text-sm text-gray-500 underline underline-offset-4 hover:text-gray-700 transition-colors"
            >
              Use a different email
            </button>
          </div>
        </div>
      )
    }

    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-6">
        <div className="w-full max-w-sm">
          {/* Wordmark */}
          <div className="mb-10 text-center">
            <h1 className="text-2xl font-semibold tracking-tight text-gray-900">CareWatch</h1>
            <p className="mt-1.5 text-sm text-gray-500">Volunteer sign in</p>
          </div>

          <div className="card p-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="label mb-1.5">Email address</label>
                <input
                  id="email"
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  className="input"
                  placeholder="you@example.com"
                />
              </div>

              {error && (
                <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
              )}

              <button type="submit" disabled={loading} className="btn-primary w-full">
                {loading ? (
                  <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />Sending…</>
                ) : 'Send login link'}
              </button>
            </form>
          </div>

          <p className="mt-6 text-center text-sm text-gray-500">
            AAC staff?{' '}
            <a href="/staff/login" className="font-medium text-gray-900 underline underline-offset-4 hover:text-gray-700 transition-colors">
              Sign in here
            </a>
          </p>
        </div>
      </div>
    )
  }
  ```

  Replace **`src/pages/volunteer/SeniorsList.tsx`**:
  ```tsx
  import { useEffect, useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { LogOut, ChevronRight, AlertCircle } from 'lucide-react'
  import { supabase } from '../../lib/supabase'
  import { useAuth } from '../../contexts/AuthContext'
  import type { Senior } from '../../lib/types'

  export function SeniorsList() {
    const { profile, signOut } = useAuth()
    const [seniors, setSeniors] = useState<Senior[]>([])
    const [loading, setLoading] = useState(true)
    const navigate = useNavigate()

    useEffect(() => {
      async function load() {
        // Step 1: Get senior_ids from active assignments for this volunteer
        const { data: assignments, error: aErr } = await supabase
          .from('assignments')
          .select('senior_id')
          .is('ended_at', null)

        if (aErr || !assignments || assignments.length === 0) {
          setSeniors([])
          setLoading(false)
          return
        }

        // Step 2: Fetch those seniors explicitly (avoids Supabase JS join type ambiguity)
        const seniorIds = assignments.map(a => a.senior_id)
        const { data: seniorData } = await supabase
          .from('seniors')
          .select('id, name, unit_number, block, mobility_notes')
          .in('id', seniorIds)

        setSeniors((seniorData as Pick<Senior, 'id' | 'name' | 'unit_number' | 'block' | 'mobility_notes'>[]) ?? [])
        setLoading(false)
      }
      load()
    }, [])

    const today = new Date().toLocaleDateString('en-SG', {
      weekday: 'long', day: 'numeric', month: 'long',
    })

    if (loading) {
      return (
        <div className="flex h-screen items-center justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-200 border-t-gray-900" />
        </div>
      )
    }

    return (
      <div className="min-h-screen bg-gray-50">
        {/* Header */}
        <header className="border-b border-gray-200 bg-white px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-base font-semibold text-gray-900">CareWatch</h1>
              <p className="text-xs text-gray-500">{profile?.name}</p>
            </div>
            <button onClick={signOut} className="btn-ghost px-2.5 py-1.5">
              <LogOut className="h-4 w-4" />
              <span className="sr-only">Sign out</span>
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-lg px-4 py-6">
          {/* Date heading */}
          <div className="mb-5">
            <p className="section-label mb-0.5">Today</p>
            <h2 className="text-lg font-semibold text-gray-900">{today}</h2>
          </div>

          {seniors.length === 0 ? (
            <div className="card flex flex-col items-center gap-2 p-8 text-center">
              <AlertCircle className="h-8 w-8 text-gray-300" />
              <p className="text-sm font-medium text-gray-600">No seniors assigned</p>
              <p className="text-sm text-gray-400">Contact your AAC coordinator to get started.</p>
            </div>
          ) : (
            <ul className="space-y-2">
              {seniors.map(senior => (
                <li key={senior.id}>
                  <button
                    onClick={() => navigate(`/volunteer/seniors/${senior.id}/checkin`)}
                    className="card w-full p-5 text-left transition-all duration-150 hover:shadow-card-hover hover:border-gray-300"
                  >
                    <div className="flex items-center justify-between">
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-gray-900">{senior.name}</p>
                        <p className="mt-0.5 text-sm text-gray-500">
                          Blk {senior.block} · #{senior.unit_number}
                        </p>
                        {senior.mobility_notes && (
                          <p className="mt-1.5 text-xs text-amber-700 bg-amber-50 inline-block rounded px-1.5 py-0.5">
                            {senior.mobility_notes}
                          </p>
                        )}
                      </div>
                      <ChevronRight className="h-4 w-4 flex-shrink-0 text-gray-400 ml-3" />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </main>
      </div>
    )
  }
  ```

  **✓ Verification Test:**

  **Type:** E2E (manual)

  **Action:** In Supabase Auth dashboard → Users, create a test user (email). In Supabase SQL editor, run:
  ```sql
  insert into profiles (id, aac_id, role, name)
  select id, '00000000-0000-0000-0000-000000000001', 'volunteer', 'Test Volunteer'
  from auth.users where email = 'YOUR_TEST_EMAIL'
  on conflict do nothing;
  ```
  Go to `/volunteer/login`. Enter email. Check inbox. Click magic link.

  **Expected:** Redirected to `/volunteer/seniors`. Page renders with Inter font (check DevTools Elements → computed font-family). List shows "No seniors assigned" (no assignments yet — expected).

  **Pass:** Login works, redirect fires, page loads, no console errors, Inter font confirmed.

  **Fail:**
  - Magic link redirects to wrong URL → Supabase Auth redirect URL not configured for `localhost:5173` → Step 2 human gate instructions: add `http://localhost:5173/**` to Redirect URLs
  - Empty seniors list — expected at this point (no assignments seeded yet)
  - `Cannot read properties of null (reading 'map')` → `seniorData` null → `(seniorData ?? [])` handles it; re-check the null coalescing

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/pages/volunteer/VolunteerLogin.tsx src/pages/volunteer/SeniorsList.tsx
  git commit -m "step 5: volunteer login (email OTP) and seniors list — premium UI"
  git push origin main
  ```

---

- [ ] 🟥 **Step 6: Check-in form + auto-flag logic** — *Critical: core mutation; flag logic uses SELECT + conditional INSERT/UPDATE*

  **Step Architecture Thinking:**

  **Pattern applied:** SELECT + conditional INSERT/UPDATE for flag creation. This replaces the original plan's PostgREST upsert, which fails on partial unique indexes. The SELECT is cheap (one row, indexed); the conditional branch is explicit and readable.

  **Why not upsert:** PostgREST's `/rest/v1/table?on_conflict=column` requires a full non-partial unique constraint on that column. The original plan used `onConflict: 'senior_id'` with a partial index `WHERE status='open'` — PostgREST cannot use partial indexes for conflict resolution. Result: either a PostgREST error or silent duplicate insertion.

  **Design:** Outcome selector uses a minimal radio-card pattern with a semantic left-border indicator (not colored backgrounds). This avoids the "traffic-light widget" look that makes AI-generated UIs obvious.

  **What breaks if this deviates:** If upsert is re-introduced without a non-partial unique constraint on `senior_id`, the demo will create duplicate open flags for the same senior after repeated no-answers, corrupting the flag queue.

  ---

  **Idempotent:** Yes — replaces stub.

  Replace **`src/pages/volunteer/CheckInForm.tsx`**:
  ```tsx
  import { useEffect, useState } from 'react'
  import { useNavigate, useParams } from 'react-router-dom'
  import { useForm } from 'react-hook-form'
  import { ArrowLeft, Check } from 'lucide-react'
  import { supabase } from '../../lib/supabase'
  import { useAuth } from '../../contexts/AuthContext'
  import { cn } from '../../lib/utils'
  import type { CheckInOutcome, Senior } from '../../lib/types'

  interface FormValues {
    outcome: CheckInOutcome
    notes: string
  }

  const OUTCOMES: {
    value: CheckInOutcome
    label: string
    description: string
    borderColor: string
  }[] = [
    { value: 'ok',        label: 'All good',    description: 'Senior answered and is well',    borderColor: 'border-l-green-500'  },
    { value: 'no_answer', label: 'No answer',   description: 'No response after knocking',     borderColor: 'border-l-amber-500'  },
    { value: 'flagged',   label: 'Concern',     description: 'Something needs staff attention', borderColor: 'border-l-red-500'    },
  ]

  export function CheckInForm() {
    const { seniorId } = useParams<{ seniorId: string }>()
    const { profile, aacId } = useAuth()
    const navigate = useNavigate()
    const [senior, setSenior] = useState<Pick<Senior, 'name' | 'unit_number' | 'block'> | null>(null)
    const [submitting, setSubmitting] = useState(false)
    const [submitError, setSubmitError] = useState<string | null>(null)

    const { register, handleSubmit, watch } = useForm<FormValues>({
      defaultValues: { outcome: 'ok', notes: '' },
    })
    const selectedOutcome = watch('outcome')

    useEffect(() => {
      if (!seniorId) return
      supabase
        .from('seniors')
        .select('name, unit_number, block')
        .eq('id', seniorId)
        .single()
        .then(({ data }) => setSenior(data))
    }, [seniorId])

    async function onSubmit(values: FormValues) {
      if (!profile || !aacId || !seniorId) return
      setSubmitting(true)
      setSubmitError(null)

      // 1. Insert check-in
      const { data: checkin, error: checkinError } = await supabase
        .from('checkins')
        .insert({
          aac_id: aacId,
          volunteer_id: profile.id,
          senior_id: seniorId,
          outcome: values.outcome,
          notes: values.notes.trim() || null,
        })
        .select('id')
        .single()

      if (checkinError || !checkin) {
        setSubmitError(checkinError?.message ?? 'Failed to submit. Try again.')
        setSubmitting(false)
        return
      }

      // 2. Auto-flag: query last 3 outcomes for this senior (SELECT + conditional INSERT/UPDATE)
      //    Uses explicit branching — not upsert — because PostgREST upsert cannot use partial indexes.
      if (values.outcome === 'no_answer') {
        await handleAutoFlag(seniorId, checkin.id, aacId)
      }

      navigate('/volunteer/seniors')
    }

    async function handleAutoFlag(seniorId: string, checkinId: string, aacId: string) {
      // A. Get last 3 check-in outcomes for this senior
      const { data: recent } = await supabase
        .from('checkins')
        .select('outcome')
        .eq('senior_id', seniorId)
        .eq('aac_id', aacId)
        .order('created_at', { ascending: false })
        .limit(3)

      // Need exactly 3 results, all no_answer
      if (!recent || recent.length < 3) return
      if (!recent.every(c => c.outcome === 'no_answer')) return

      // B. Check if an open flag already exists for this senior.
      //    Use maybeSingle() — returns { data: null, error: null } on 0 rows.
      //    .single() would throw PGRST116 when no flag exists (the common case on first no-answer).
      const { data: existingFlag } = await supabase
        .from('flags')
        .select('id')
        .eq('senior_id', seniorId)
        .eq('aac_id', aacId)
        .eq('status', 'open')
        .maybeSingle()

      if (existingFlag) {
        // C-i. Update the existing flag's consecutive count and latest checkin_id
        await supabase
          .from('flags')
          .update({ consecutive_count: 3, checkin_id: checkinId })
          .eq('id', existingFlag.id)
      } else {
        // C-ii. Create a new open flag
        await supabase
          .from('flags')
          .insert({
            aac_id: aacId,
            checkin_id: checkinId,
            senior_id: seniorId,
            consecutive_count: 3,
            status: 'open',
          })
      }
    }

    return (
      <div className="min-h-screen bg-gray-50">
        {/* Header */}
        <header className="border-b border-gray-200 bg-white px-4 py-4">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate(-1)} className="btn-ghost -ml-1 px-2 py-1.5">
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div>
              <h1 className="text-base font-semibold text-gray-900">
                {senior?.name ?? 'Check-in'}
              </h1>
              {senior && (
                <p className="text-xs text-gray-500">Blk {senior.block} · #{senior.unit_number}</p>
              )}
            </div>
          </div>
        </header>

        <form onSubmit={handleSubmit(onSubmit)} className="mx-auto max-w-lg px-4 py-6 space-y-6">
          {/* Outcome selector */}
          <div>
            <p className="label mb-3">How did the visit go?</p>
            <div className="space-y-2">
              {OUTCOMES.map(o => (
                <label
                  key={o.value}
                  className={cn(
                    'flex cursor-pointer items-center gap-4 rounded-xl border border-gray-200 bg-white p-4 transition-all duration-150',
                    'border-l-4',
                    // Left border colour indicates outcome type
                    selectedOutcome === o.value ? o.borderColor : 'border-l-gray-200',
                    selectedOutcome === o.value ? 'shadow-card' : 'hover:border-gray-300',
                  )}
                >
                  <input
                    type="radio"
                    value={o.value}
                    {...register('outcome', { required: true })}
                    className="sr-only"
                  />
                  {/* Custom radio indicator */}
                  <div className={cn(
                    'flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border-2 transition-colors duration-150',
                    selectedOutcome === o.value
                      ? 'border-gray-900 bg-gray-900'
                      : 'border-gray-300',
                  )}>
                    {selectedOutcome === o.value && (
                      <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />
                    )}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">{o.label}</p>
                    <p className="text-xs text-gray-500">{o.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="notes" className="label mb-1.5">
              Notes <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <textarea
              id="notes"
              {...register('notes')}
              rows={3}
              placeholder="Any observations…"
              className="input resize-none"
            />
          </div>

          {submitError && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{submitError}</p>
          )}

          <button type="submit" disabled={submitting} className="btn-primary w-full py-3 text-base">
            {submitting ? (
              <><span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />Submitting…</>
            ) : 'Submit check-in'}
          </button>
        </form>
      </div>
    )
  }
  ```

  **✓ Verification Test:**

  **Type:** E2E (manual)

  **Action:** Seed a senior and an active assignment for the test volunteer in Supabase SQL:
  ```sql
  -- Insert a test senior
  insert into seniors (aac_id, name, unit_number, block)
  values ('00000000-0000-0000-0000-000000000001', 'Mdm Tan', '04-21', '123');

  -- Assign to the test volunteer (replace YOUR_VOLUNTEER_ID)
  insert into assignments (aac_id, volunteer_id, senior_id)
  select '00000000-0000-0000-0000-000000000001', id, (select id from seniors where name = 'Mdm Tan')
  from profiles where role = 'volunteer' limit 1;
  ```
  Log in as volunteer → navigate to `/volunteer/seniors` → tap "Mdm Tan" → submit `no_answer` 3 times.

  **Expected:**
  - Each submission redirects back to seniors list
  - `checkins` table has 3 rows for Mdm Tan with `outcome='no_answer'`
  - After the 3rd no_answer, `flags` table has 1 row: `status='open'`, `consecutive_count=3`
  - Submitting a 4th no_answer: flag row `consecutive_count` updates to 3 (stays 3, not 4 — the query always takes last 3)

  **Pass:** 3 check-in rows, 1 flag row with status='open'.

  **Fail:**
  - No flag created → `handleAutoFlag` not finding 3 consecutive no-answers → add `console.log(recent)` to debug the outcomes query
  - RLS error on checkins INSERT → `aac_id` mismatch → check profile `aac_id` matches `00000000-0000-0000-0000-000000000001`
  - `PGRST116` on flag SELECT → expected if no existing flag — the `.single()` call returns error when row not found → this is handled by the `if (existingFlag)` check; confirm code uses the `existingFlag?.id` pattern

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/pages/volunteer/CheckInForm.tsx
  git commit -m "step 6: check-in form with SELECT+INSERT/UPDATE flag logic (no partial-index upsert)"
  git push origin main
  ```

---

### Phase 4 — Staff Dashboard (Steps 7–8)

**Goal:** Staff can log in, see live coverage stats, and action flags from a clean queue.

---

- [ ] 🟥 **Step 7: Staff login + dashboard overview** — *Non-critical: read-only UI*

  **Step Architecture Thinking:**

  **Pattern applied:** Stripe dashboard stat tile pattern — large number in `text-4xl font-bold tracking-tight`, label in `text-xs font-medium uppercase tracking-widest text-gray-500` below. Semantic colour only for the flag count when non-zero.

  **What breaks if this deviates:** If colour is used on all stat tiles (blue seniors, purple volunteers, green checkins), the dashboard looks like a Bootstrap template. Premium = monochrome chrome with colour only for the actionable metric (open flags).

  ---

  **Idempotent:** Yes — replaces stubs.

  Replace **`src/pages/staff/StaffLogin.tsx`**:
  ```tsx
  import { useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { supabase } from '../../lib/supabase'

  export function StaffLogin() {
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const navigate = useNavigate()

    async function handleSubmit(e: React.FormEvent) {
      e.preventDefault()
      setLoading(true)
      setError(null)
      const { error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) { setError(error.message); setLoading(false); return }
      navigate('/staff/dashboard')
    }

    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-6">
        <div className="w-full max-w-sm">
          <div className="mb-10 text-center">
            <h1 className="text-2xl font-semibold tracking-tight text-gray-900">CareWatch</h1>
            <p className="mt-1.5 text-sm text-gray-500">Staff sign in</p>
          </div>

          <div className="card p-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="label mb-1.5">Email</label>
                <input id="email" type="email" required autoComplete="email"
                  value={email} onChange={e => setEmail(e.target.value)}
                  className="input" placeholder="you@tampinesaac.sg"
                />
              </div>
              <div>
                <label htmlFor="password" className="label mb-1.5">Password</label>
                <input id="password" type="password" required autoComplete="current-password"
                  value={password} onChange={e => setPassword(e.target.value)}
                  className="input"
                />
              </div>
              {error && (
                <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
              )}
              <button type="submit" disabled={loading} className="btn-primary w-full">
                {loading ? (
                  <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />Signing in…</>
                ) : 'Sign in'}
              </button>
            </form>
          </div>

          <p className="mt-6 text-center text-sm text-gray-500">
            Volunteer?{' '}
            <a href="/volunteer/login" className="font-medium text-gray-900 underline underline-offset-4 hover:text-gray-700 transition-colors">
              Sign in here
            </a>
          </p>
        </div>
      </div>
    )
  }
  ```

  Replace **`src/pages/staff/Dashboard.tsx`**:
  ```tsx
  import { useEffect, useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { LogOut, Flag, Upload } from 'lucide-react'
  import { supabase } from '../../lib/supabase'
  import { useAuth } from '../../contexts/AuthContext'
  import { cn } from '../../lib/utils'

  interface Stats {
    totalSeniors: number
    totalVolunteers: number
    checkinsToday: number
    openFlags: number
  }

  export function Dashboard() {
    const { profile, signOut } = useAuth()
    const [stats, setStats] = useState<Stats | null>(null)
    const navigate = useNavigate()

    useEffect(() => {
      async function load() {
        const today = new Date().toISOString().split('T')[0]
        const [seniors, volunteers, checkins, flags] = await Promise.all([
          supabase.from('seniors').select('id', { count: 'exact', head: true }),
          supabase.from('profiles').select('id', { count: 'exact', head: true }).eq('role', 'volunteer'),
          supabase.from('checkins').select('id', { count: 'exact', head: true }).gte('created_at', today),
          supabase.from('flags').select('id', { count: 'exact', head: true }).eq('status', 'open'),
        ])
        setStats({
          totalSeniors:    seniors.count   ?? 0,
          totalVolunteers: volunteers.count ?? 0,
          checkinsToday:   checkins.count  ?? 0,
          openFlags:       flags.count     ?? 0,
        })
      }
      load()
    }, [])

    const statTiles = stats ? [
      { label: 'Seniors',          value: stats.totalSeniors,    flagged: false },
      { label: 'Volunteers',       value: stats.totalVolunteers,  flagged: false },
      { label: "Check-ins today",  value: stats.checkinsToday,    flagged: false },
      { label: 'Open flags',       value: stats.openFlags,        flagged: stats.openFlags > 0 },
    ] : []

    return (
      <div className="min-h-screen bg-gray-50">
        {/* Header */}
        <header className="border-b border-gray-200 bg-white px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-base font-semibold text-gray-900">CareWatch</h1>
              <p className="text-xs text-gray-500">{profile?.name} · Staff</p>
            </div>
            <button onClick={signOut} className="btn-ghost px-2.5 py-1.5">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-2xl px-4 py-6 space-y-6">
          {/* Stat grid — Stripe dashboard pattern */}
          <div>
            <p className="section-label mb-3">Overview</p>
            <div className="grid grid-cols-2 gap-3">
              {stats === null
                ? Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="card h-24 animate-pulse bg-gray-100" />
                  ))
                : statTiles.map(t => (
                    <div
                      key={t.label}
                      className={cn(
                        'card p-5',
                        t.flagged && 'border-red-200 bg-red-50',
                      )}
                    >
                      <p className={cn(
                        'text-4xl font-bold tracking-tight',
                        t.flagged ? 'text-red-700' : 'text-gray-900',
                      )}>
                        {t.value}
                      </p>
                      <p className={cn(
                        'mt-1.5 text-xs font-medium uppercase tracking-widest',
                        t.flagged ? 'text-red-500' : 'text-gray-400',
                      )}>
                        {t.label}
                      </p>
                    </div>
                  ))
              }
            </div>
          </div>

          {/* Quick actions */}
          <div>
            <p className="section-label mb-3">Actions</p>
            <div className="space-y-2">
              <button
                onClick={() => navigate('/staff/flags')}
                className="card w-full p-5 text-left transition-all duration-150 hover:shadow-card-hover hover:border-gray-300 flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100">
                    <Flag className="h-4 w-4 text-gray-600" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">Flag queue</p>
                    <p className="text-xs text-gray-500">Review and action open flags</p>
                  </div>
                </div>
                {stats && stats.openFlags > 0 && (
                  <span className="badge bg-red-100 text-red-700">{stats.openFlags}</span>
                )}
              </button>

              <button
                onClick={() => navigate('/staff/import')}
                className="card w-full p-5 text-left transition-all duration-150 hover:shadow-card-hover hover:border-gray-300 flex items-center gap-3"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100">
                  <Upload className="h-4 w-4 text-gray-600" />
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-900">Import seniors</p>
                  <p className="text-xs text-gray-500">Upload XLSX spreadsheet</p>
                </div>
              </button>
            </div>
          </div>
        </main>
      </div>
    )
  }
  ```

  **✓ Verification Test:**

  **Type:** E2E (manual)

  **Action:** Create a staff user in Supabase Auth (email + password). Insert profile:
  ```sql
  insert into profiles (id, aac_id, role, name)
  select id, '00000000-0000-0000-0000-000000000001', 'staff', 'AAC Coordinator'
  from auth.users where email = 'YOUR_STAFF_EMAIL'
  on conflict do nothing;
  ```
  Log in at `/staff/login`.

  **Expected:**
  - Redirects to `/staff/dashboard`
  - 4 stat tiles render: Seniors, Volunteers, Check-ins today, Open flags
  - Values match actual DB counts
  - Flag tile turns red if `openFlags > 0`
  - Loading skeleton (pulse animation) visible briefly

  **Pass:** Login works, stats match DB, conditional flag colour correct.

  **Fail:**
  - All stats show 0 → RLS denying queries → confirm profile row has `role='staff'` → call `select get_my_role()` in Supabase SQL editor while logged in as staff to verify
  - Redirect to `/staff/login` after sign-in → `ProtectedRoute` role check → confirm profile inserted correctly

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/pages/staff/StaffLogin.tsx src/pages/staff/Dashboard.tsx
  git commit -m "step 7: staff login and dashboard with Stripe-style stat tiles"
  git push origin main
  ```

---

- [ ] 🟥 **Step 8: Flag queue + flag status update** — *Critical: staff data mutation*

  **Step Architecture Thinking:**

  **Pattern applied:** Optimistic UI update (local state updated immediately, reverted on error). Stripe table aesthetic: uppercase column labels, row-level hover, semantic badge colours at low opacity (not full saturation).

  **What breaks if this deviates:** If the status update uses `PATCH` without `eq('id')` scoping, it could update all flags. Always scope updates to the specific flag ID.

  ---

  **Idempotent:** Yes — replaces stub.

  Replace **`src/pages/staff/FlagQueue.tsx`**:
  ```tsx
  import { useEffect, useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { ArrowLeft, CheckCircle } from 'lucide-react'
  import { supabase } from '../../lib/supabase'
  import { useAuth } from '../../contexts/AuthContext'
  import { cn } from '../../lib/utils'
  import type { Flag, FlagStatus } from '../../lib/types'

  interface FlagRow extends Flag {
    senior_name: string
    senior_unit: string
    senior_block: string | null
  }

  const STATUS_META: Record<FlagStatus, { label: string; className: string }> = {
    open:      { label: 'Open',      className: 'bg-red-50 text-red-700'     },
    reviewed:  { label: 'Reviewed',  className: 'bg-amber-50 text-amber-700'  },
    actioned:  { label: 'Actioned',  className: 'bg-green-50 text-green-700'  },
    escalated: { label: 'Escalated', className: 'bg-purple-50 text-purple-700' },
  }

  const NEXT_ACTIONS: { from: FlagStatus; to: FlagStatus; label: string }[] = [
    { from: 'open',      to: 'reviewed',  label: 'Mark reviewed'  },
    { from: 'open',      to: 'escalated', label: 'Escalate'       },
    { from: 'reviewed',  to: 'actioned',  label: 'Mark actioned'  },
    { from: 'reviewed',  to: 'escalated', label: 'Escalate'       },
    { from: 'escalated', to: 'actioned',  label: 'Mark resolved'  },
  ]

  export function FlagQueue() {
    const { profile } = useAuth()
    const navigate = useNavigate()
    const [flags, setFlags] = useState<FlagRow[]>([])
    const [loading, setLoading] = useState(true)
    const [expandedId, setExpandedId] = useState<string | null>(null)
    const [notes, setNotes] = useState<Record<string, string>>({})

    useEffect(() => {
      async function load() {
        const { data } = await supabase
          .from('flags')
          .select('*, senior:senior_id(name, unit_number, block)')
          .order('created_at', { ascending: false })

        const rows: FlagRow[] = (data ?? []).map((f: any) => ({
          ...f,
          senior_name:  f.senior?.name        ?? 'Unknown',
          senior_unit:  f.senior?.unit_number  ?? '',
          senior_block: f.senior?.block        ?? null,
        }))
        setFlags(rows)
        setLoading(false)
      }
      load()
    }, [])

    async function updateStatus(flagId: string, newStatus: FlagStatus) {
      const staffNotes = notes[flagId] ?? ''
      // Optimistic update
      setFlags(prev =>
        prev.map(f =>
          f.id === flagId
            ? { ...f, status: newStatus, staff_notes: staffNotes, actioned_by: profile?.id ?? null, actioned_at: new Date().toISOString() }
            : f
        )
      )
      setExpandedId(null)

      const { error } = await supabase
        .from('flags')
        .update({
          status: newStatus,
          staff_notes: staffNotes || null,
          actioned_by: profile?.id,
          actioned_at: new Date().toISOString(),
        })
        .eq('id', flagId)

      if (error) {
        // Revert
        setFlags(prev =>
          prev.map(f => f.id === flagId ? { ...f, status: f.status } : f)
        )
        alert(`Update failed: ${error.message}`)
      }
    }

    if (loading) {
      return (
        <div className="flex h-screen items-center justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-200 border-t-gray-900" />
        </div>
      )
    }

    return (
      <div className="min-h-screen bg-gray-50">
        <header className="border-b border-gray-200 bg-white px-4 py-4">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/staff/dashboard')} className="btn-ghost -ml-1 px-2 py-1.5">
              <ArrowLeft className="h-4 w-4" />
            </button>
            <h1 className="text-base font-semibold text-gray-900">Flag queue</h1>
          </div>
        </header>

        <main className="mx-auto max-w-2xl px-4 py-6">
          {flags.length === 0 ? (
            <div className="card flex flex-col items-center gap-2 p-10 text-center">
              <CheckCircle className="h-8 w-8 text-green-400" />
              <p className="text-sm font-medium text-gray-700">All clear</p>
              <p className="text-sm text-gray-400">No open flags at the moment.</p>
            </div>
          ) : (
            /* Stripe-style table */
            <div className="card overflow-hidden">
              {/* Table header */}
              <div className="grid grid-cols-[1fr_auto_auto] border-b border-gray-100 px-5 py-3">
                <span className="section-label">Senior</span>
                <span className="section-label mr-8">Flags</span>
                <span className="section-label">Status</span>
              </div>

              <ul className="divide-y divide-gray-100">
                {flags.map(flag => {
                  const isExpanded = expandedId === flag.id
                  const actions = NEXT_ACTIONS.filter(a => a.from === flag.status)
                  return (
                    <li key={flag.id}>
                      {/* Row */}
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : flag.id)}
                        className="grid w-full grid-cols-[1fr_auto_auto] items-center px-5 py-4 text-left transition-colors duration-150 hover:bg-gray-50"
                      >
                        <div>
                          <p className="text-sm font-medium text-gray-900">{flag.senior_name}</p>
                          <p className="text-xs text-gray-500">
                            Blk {flag.senior_block} · #{flag.senior_unit} · {new Date(flag.created_at).toLocaleDateString('en-SG')}
                          </p>
                        </div>
                        <span className="mr-8 text-sm font-medium text-gray-700">
                          {flag.consecutive_count}×
                        </span>
                        <span className={cn('badge', STATUS_META[flag.status].className)}>
                          {STATUS_META[flag.status].label}
                        </span>
                      </button>

                      {/* Expanded action panel */}
                      {isExpanded && (
                        <div className="border-t border-gray-100 bg-gray-50 px-5 py-4 space-y-3">
                          <div>
                            <label className="label mb-1.5 text-xs">Staff notes</label>
                            <textarea
                              value={notes[flag.id] ?? flag.staff_notes ?? ''}
                              onChange={e => setNotes(n => ({ ...n, [flag.id]: e.target.value }))}
                              rows={2}
                              placeholder="Add notes…"
                              className="input text-sm resize-none"
                            />
                          </div>
                          {actions.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {actions.map(a => (
                                <button
                                  key={a.to}
                                  onClick={() => updateStatus(flag.id, a.to)}
                                  className={cn(
                                    'btn-secondary text-xs py-1.5',
                                    a.to === 'escalated' && 'border-red-200 text-red-700 hover:bg-red-50',
                                  )}
                                >
                                  {a.label}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </main>
      </div>
    )
  }
  ```

  **✓ Verification Test:**

  **Type:** E2E (manual)

  **Action:** Log in as staff. Navigate to Flag queue. If a flag from Step 6 exists, click the row, add a note, click "Mark reviewed".

  **Expected:**
  - Flag row updates badge to "Reviewed" immediately (optimistic)
  - `flags` table in Supabase shows `status='reviewed'` and `staff_notes` populated
  - `actioned_by` = staff user's UUID

  **Pass:** UI updates instantly, DB row reflects change.

  **Fail:**
  - Badge reverts after update → Supabase returned an error → check browser console for the revert `alert()` message
  - RLS error → confirm staff profile `role='staff'` and `aac_id` matches flag's `aac_id`

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/pages/staff/FlagQueue.tsx
  git commit -m "step 8: flag queue with Stripe table aesthetic and optimistic status update"
  git push origin main
  ```

---

### Phase 5 — XLSX Import (Step 9)

**Goal:** Staff can upload any XLSX/CSV, map columns to senior fields, and safely import to the database.

---

- [ ] 🟥 **Step 9: XLSX import screen** — *Critical: bulk data insert using non-partial unique index*

  **Step Architecture Thinking:**

  **Pattern applied:** Three-step wizard (Upload → Map → Preview + Import). Each step is gated on the previous. The Supabase upsert uses `onConflict: 'aac_id,unit_number'` — this is the `seniors_aac_unit_idx` unique index added to `schema.sql` in Step 3, not a separate migration.

  **Why the unique index is non-partial:** PostgREST requires a full (not partial) unique constraint for conflict resolution. `(aac_id, unit_number)` is a full constraint — safe to use with `.upsert({ onConflict: 'aac_id,unit_number' })`.

  **What breaks if this deviates:** If the `seniors_aac_unit_idx` was never created in Step 3 (e.g., partial SQL run), the upsert will throw a "no unique or exclusion constraint" error. Verify the index exists before proceeding.

  ---

  **Idempotent:** Yes — replaces stub. Import itself is idempotent (upsert).

  **Pre-Read Gate:** In Supabase SQL editor, run:
  ```sql
  select indexname from pg_indexes where tablename = 'seniors' and indexname = 'seniors_aac_unit_idx';
  ```
  Must return 1 row. If 0 rows → re-run `schema.sql` Step 3 before continuing.

  Replace **`src/pages/staff/ImportSeniors.tsx`**:
  ```tsx
  import { useRef, useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import * as XLSX from 'xlsx'
  import { ArrowLeft, Upload, CheckCircle } from 'lucide-react'
  import { supabase } from '../../lib/supabase'
  import { useAuth } from '../../contexts/AuthContext'
  import { cn } from '../../lib/utils'

  type RawRow = Record<string, string>

  interface ColMap {
    name: string
    unit_number: string
    block: string
    preferred_language: string
  }

  interface ImportResult {
    upserted: number
    skipped: number
  }

  const FIELD_CONFIG: { key: keyof ColMap; label: string; required: boolean }[] = [
    { key: 'name',               label: 'Senior name',         required: true  },
    { key: 'unit_number',        label: 'Unit number',          required: true  },
    { key: 'block',              label: 'Block',                required: false },
    { key: 'preferred_language', label: 'Preferred language',   required: false },
  ]

  export function ImportSeniors() {
    const { aacId } = useAuth()
    const navigate = useNavigate()
    const fileRef = useRef<HTMLInputElement>(null)

    const [step, setStep] = useState<'upload' | 'map' | 'preview'>('upload')
    const [headers, setHeaders] = useState<string[]>([])
    const [rows, setRows] = useState<RawRow[]>([])
    const [colMap, setColMap] = useState<ColMap>({ name: '', unit_number: '', block: '', preferred_language: '' })
    const [result, setResult] = useState<ImportResult | null>(null)
    const [importing, setImporting] = useState(false)
    const [parseError, setParseError] = useState<string | null>(null)
    const [importError, setImportError] = useState<string | null>(null)

    function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
      const file = e.target.files?.[0]
      if (!file) return
      setParseError(null)

      const reader = new FileReader()
      reader.onload = evt => {
        try {
          const wb = XLSX.read(evt.target?.result, { type: 'binary' })
          const ws = wb.Sheets[wb.SheetNames[0]]
          const data = XLSX.utils.sheet_to_json<RawRow>(ws, { defval: '' })

          if (data.length === 0) {
            setParseError('The spreadsheet appears empty. Check that it has a header row and at least one data row.')
            return
          }

          setHeaders(Object.keys(data[0]))
          setRows(data)
          setStep('map')
        } catch {
          setParseError('Could not read the file. Make sure it is a valid XLSX, XLS, or CSV file.')
        }
      }
      reader.readAsBinaryString(file)
    }

    function handleMapContinue() {
      const missing = FIELD_CONFIG.filter(f => f.required && !colMap[f.key]).map(f => f.label)
      if (missing.length > 0) {
        setParseError(`Map required fields first: ${missing.join(', ')}`)
        return
      }
      setParseError(null)
      setStep('preview')
    }

    async function handleImport() {
      if (!aacId) return
      setImporting(true)
      setImportError(null)

      const validRows = rows
        .map(row => ({
          aac_id:             aacId,
          name:               String(row[colMap.name]               ?? '').trim(),
          unit_number:        String(row[colMap.unit_number]         ?? '').trim(),
          block:              colMap.block               ? String(row[colMap.block] ?? '').trim() || null : null,
          preferred_language: colMap.preferred_language  ? String(row[colMap.preferred_language] ?? '').trim() || 'English' : 'English',
        }))
        .filter(r => r.name && r.unit_number)

      const skipped = rows.length - validRows.length

      const { data, error } = await supabase
        .from('seniors')
        .upsert(validRows, { onConflict: 'aac_id,unit_number' })
        .select('id')

      setImporting(false)

      if (error) {
        setImportError(error.message)
        return
      }

      setResult({ upserted: data?.length ?? 0, skipped })
    }

    // Success screen
    if (result) {
      return (
        <div className="min-h-screen bg-gray-50">
          <header className="border-b border-gray-200 bg-white px-4 py-4">
            <div className="flex items-center gap-3">
              <button onClick={() => navigate('/staff/dashboard')} className="btn-ghost -ml-1 px-2 py-1.5">
                <ArrowLeft className="h-4 w-4" />
              </button>
              <h1 className="text-base font-semibold text-gray-900">Import complete</h1>
            </div>
          </header>
          <main className="mx-auto max-w-lg px-4 py-12 text-center">
            <CheckCircle className="mx-auto mb-4 h-10 w-10 text-green-500" />
            <h2 className="text-xl font-semibold text-gray-900 mb-6">Import summary</h2>
            <div className="card p-6 text-left space-y-3">
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Added / updated</span>
                <span className="text-sm font-semibold text-gray-900">{result.upserted}</span>
              </div>
              <div className="flex justify-between border-t border-gray-100 pt-3">
                <span className="text-sm text-gray-600">Skipped (missing name or unit)</span>
                <span className="text-sm font-semibold text-gray-500">{result.skipped}</span>
              </div>
            </div>
            <button
              onClick={() => { setResult(null); setRows([]); setHeaders([]); setColMap({ name: '', unit_number: '', block: '', preferred_language: '' }); setStep('upload') }}
              className="btn-secondary mt-6"
            >
              Import another file
            </button>
          </main>
        </div>
      )
    }

    return (
      <div className="min-h-screen bg-gray-50">
        <header className="border-b border-gray-200 bg-white px-4 py-4">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/staff/dashboard')} className="btn-ghost -ml-1 px-2 py-1.5">
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div>
              <h1 className="text-base font-semibold text-gray-900">Import seniors</h1>
              <p className="text-xs text-gray-500 capitalize">{step === 'upload' ? 'Step 1 of 3' : step === 'map' ? 'Step 2 of 3' : 'Step 3 of 3'}</p>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-lg px-4 py-6 space-y-5">
          {/* Step 1: Upload */}
          {step === 'upload' && (
            <div className="card p-6">
              <h2 className="text-sm font-semibold text-gray-900 mb-4">Upload spreadsheet</h2>
              <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleFile} className="sr-only" />
              <button
                onClick={() => fileRef.current?.click()}
                className={cn(
                  'flex w-full flex-col items-center gap-3 rounded-xl border-2 border-dashed border-gray-200 p-8 text-center',
                  'transition-colors duration-150 hover:border-gray-400 hover:bg-gray-50',
                )}
              >
                <Upload className="h-6 w-6 text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-700">Click to choose file</p>
                  <p className="text-xs text-gray-400 mt-0.5">XLSX, XLS, or CSV</p>
                </div>
              </button>
              {parseError && (
                <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{parseError}</p>
              )}
            </div>
          )}

          {/* Step 2: Map columns */}
          {step === 'map' && (
            <div className="card p-6">
              <h2 className="text-sm font-semibold text-gray-900 mb-1">Map columns</h2>
              <p className="text-xs text-gray-500 mb-4">{rows.length} rows loaded from spreadsheet</p>
              <div className="space-y-3">
                {FIELD_CONFIG.map(field => (
                  <div key={field.key} className="flex items-center gap-3">
                    <label className="w-40 flex-shrink-0 text-sm text-gray-700">
                      {field.label}
                      {field.required && <span className="text-red-500 ml-0.5">*</span>}
                    </label>
                    <select
                      value={colMap[field.key]}
                      onChange={e => setColMap(m => ({ ...m, [field.key]: e.target.value }))}
                      className="input flex-1"
                    >
                      <option value="">— skip —</option>
                      {headers.map(h => <option key={h} value={h}>{h}</option>)}
                    </select>
                  </div>
                ))}
              </div>
              {parseError && (
                <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{parseError}</p>
              )}
              <div className="mt-5 flex gap-2">
                <button onClick={() => setStep('upload')} className="btn-secondary flex-1">Back</button>
                <button onClick={handleMapContinue} className="btn-primary flex-1">Continue</button>
              </div>
            </div>
          )}

          {/* Step 3: Preview + import */}
          {step === 'preview' && (
            <div className="space-y-4">
              <div className="card overflow-hidden">
                <div className="border-b border-gray-100 px-5 py-3">
                  <span className="section-label">Preview (first 5 rows)</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-100">
                        {FIELD_CONFIG.filter(f => colMap[f.key]).map(f => (
                          <th key={f.key} className="px-4 py-2.5 text-left font-medium text-gray-500">{f.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {rows.slice(0, 5).map((row, i) => (
                        <tr key={i} className="hover:bg-gray-50 transition-colors">
                          {FIELD_CONFIG.filter(f => colMap[f.key]).map(f => (
                            <td key={f.key} className="px-4 py-2.5 text-gray-700">{row[colMap[f.key]]}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {importError && (
                <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{importError}</p>
              )}

              <div className="flex gap-2">
                <button onClick={() => setStep('map')} className="btn-secondary flex-1">Back</button>
                <button onClick={handleImport} disabled={importing} className="btn-primary flex-1">
                  {importing ? (
                    <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />Importing…</>
                  ) : `Import ${rows.length} rows`}
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    )
  }
  ```

  **✓ Verification Test:**

  **Type:** E2E (manual)

  **Action:** Create a CSV file:
  ```
  FullName,UnitNo,Block,Language
  Mdm Lim,03-11,456,Hokkien
  Mr Rajan,07-05,789,English
  ```
  Log in as staff → Import seniors → upload CSV → map `FullName → name`, `UnitNo → unit_number`, `Block → block` → import.

  **Expected:**
  - Step 2 shows 2 rows loaded
  - Preview shows both seniors correctly
  - Import summary: 2 added / updated
  - `seniors` table shows both rows with `aac_id` set

  **Pass:** Both seniors in DB, re-import is idempotent (same count, no duplicates).

  **Fail:**
  - `no unique or exclusion constraint` error → `seniors_aac_unit_idx` not created → re-run Step 3 schema SQL, then re-check with the Pre-Read Gate SQL
  - RLS error on INSERT → staff `aac_id` null or wrong → check profile row

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add src/pages/staff/ImportSeniors.tsx
  git commit -m "step 9: XLSX import wizard with SheetJS and non-partial unique upsert"
  git push origin main
  ```

---

### Phase 6 — Deploy (Step 10)

**Goal:** App live on Vercel. All routes work. PWA installable on Android Chrome.

---

- [ ] 🟥 **Step 10: Vercel deployment** — *Non-critical: config + deploy*

  **Step Architecture Thinking:**

  **Pattern applied:** SPA rewrite rule in `vercel.json` — all paths serve `index.html`. Without this, direct navigation to `/volunteer/login` returns Vercel's 404.

  **What breaks if this deviates:** Any bookmarked or shared URL to a non-root path (e.g., a magic link redirecting to `/volunteer/seniors`) returns 404.

  ---

  **Idempotent:** Yes.

  Write **`vercel.json`**:
  ```json
  {
    "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
  }
  ```

  Deploy:
  ```bash
  # Install Vercel CLI if not present
  npm install -g vercel

  # Deploy (follow prompts: link to account, project name: carewatch-demo)
  vercel deploy --prod
  ```

  After the first deploy completes and the Vercel URL is known (e.g., `https://carewatch-demo.vercel.app`):

  ```bash
  # Set env vars for production build
  vercel env add VITE_SUPABASE_URL production
  # paste Supabase project URL

  vercel env add VITE_SUPABASE_ANON_KEY production
  # paste anon key

  # Redeploy to pick up env vars
  vercel deploy --prod
  ```

  Update Supabase Auth settings:
  - Supabase dashboard → Authentication → URL Configuration
  - Site URL: `https://carewatch-demo.vercel.app`
  - Redirect URLs: add `https://carewatch-demo.vercel.app/**`

  **✓ Verification Test:**

  **Type:** E2E

  **Action:** Open Vercel deployment URL in Android Chrome.

  **Expected:**
  - App loads at `/volunteer/login`
  - Direct navigation to `/staff/login` does not 404
  - Android Chrome shows "Add to Home Screen" install prompt (PWA manifest detected)
  - Magic link in email redirects to the Vercel URL (not localhost)

  **Pass:** App live, routes work, PWA installable.

  **Fail:**
  - 404 on direct URL → `vercel.json` rewrite not applied → confirm file is in repo root and was committed → redeploy
  - Magic link goes to localhost → Supabase Site URL not updated to Vercel URL → update in Supabase Auth settings
  - Env var errors → check Vercel → Project Settings → Environment Variables → confirm both `VITE_` vars are set for Production

  **Git checkpoint (after verification passes):**
  ```bash
  cd /Users/ngchenmeng/CareWatch
  git add vercel.json
  git commit -m "step 10: vercel.json SPA rewrite for client-side routing"
  git push origin main
  ```

---

## Regression Guard

No existing system to regress — greenfield.

---

## Rollback Procedure

```bash
git log --oneline            # find commit hash for the step to revert
git revert <commit-hash>     # creates a new revert commit, does not alter history

# For database changes: drop tables and re-run schema.sql
# Only needed if schema was applied incorrectly (partial run)
```

---

## Pre-Flight Checklist

| Phase | Check | How to Confirm | Status |
|---|---|---|---|
| **Pre-flight** | Node >= 18 | `node --version` | ⬜ |
| | No `package.json` exists | `ls /Users/ngchenmeng/CareWatch` | ⬜ |
| | Git clean | `git status` | ⬜ |
| **Step 1** | Dev server starts | `npm run dev` — no errors | ⬜ |
| | Inter font loaded | DevTools → Elements → `body` computed `font-family` | ⬜ |
| | `cn()` utility exists | `ls src/lib/utils.ts` | ⬜ |
| **Step 2** | `types.ts` created before `supabase.ts` | Both files exist: `ls src/lib/` | ⬜ |
| | Supabase client initialises | No env-var error in browser console | ⬜ |
| | Localhost redirect URL added | Supabase Auth → URL Configuration | ⬜ |
| **Step 3** | All 8 tables exist | Supabase Table Editor | ⬜ |
| | Seed AAC present | `select * from aacs` returns 1 row | ⬜ |
| | `seniors_aac_unit_idx` exists | `select indexname from pg_indexes where indexname='seniors_aac_unit_idx'` | ⬜ |
| **Step 3b** | 10 seniors in `seniors` | Table Editor → seniors row count | ⬜ |
| | 2 profiles (volunteer + staff) | `select role, name from profiles` | ⬜ |
| | 1 open flag pre-seeded | `select status from flags` returns `open` | ⬜ |
| | 4 assignments for volunteer | `select count(*) from assignments` = 4 | ⬜ |
| **Step 4** | Routes work | Unauthenticated `/volunteer/seniors` redirects | ⬜ |
| | Profile error state renders | Manually test with a user with no profile row | ⬜ |
| **Step 5** | Login + magic link works | Email received, click redirects to `/volunteer/seniors` | ⬜ |
| | Two-query senior fetch works | Seniors list loads (or shows "no seniors" correctly) | ⬜ |
| **Step 6** | Check-in inserts | Row in `checkins` table | ⬜ |
| | Auto-flag triggers on 3rd no-answer | Row in `flags` with `status='open'` | ⬜ |
| | 4th no-answer updates (not duplicates) | Still only 1 flag row for the senior | ⬜ |
| **Step 7** | Staff login works | Redirect to `/staff/dashboard` | ⬜ |
| | Stats tiles match DB | Counts match Supabase table counts | ⬜ |
| **Step 8** | Flag update persists | DB row reflects new status | ⬜ |
| | Optimistic revert fires on error | (manually break the update to test) | ⬜ |
| **Step 9** | `seniors_aac_unit_idx` confirmed | Pre-read gate SQL returns 1 row | ⬜ |
| | Import inserts rows | Seniors appear in `seniors` table | ⬜ |
| | Re-import is idempotent | No duplicate rows on second import | ⬜ |
| **Step 10** | App live | Vercel URL loads in browser | ⬜ |
| | PWA installable | "Add to Home Screen" prompt on Android | ⬜ |
| | Direct URL navigation | `/staff/login` does not 404 | ⬜ |

---

## Risk Heatmap

| Step | Risk | What Could Go Wrong | Early Detection | Idempotent |
|---|---|---|---|---|
| 1 — Scaffold | 🟢 Low | `npm create vite` non-empty directory prompt | Type `y` when prompted | No |
| 2 — Supabase | 🟡 Medium | Wrong env var values; localhost not in redirect URLs | Check browser console; test magic link in dev | No |
| 3 — Schema | 🟡 Medium | Partial SQL run leaves missing index or policy | Run pre-read gate SQL to confirm index | Yes |
| 4 — Auth routing | 🟢 Low | Export name mismatch in stubs | TypeScript errors at `npm run dev` | Yes |
| 5 — Volunteer UI | 🟢 Low | Magic link redirects to wrong URL | Check `emailRedirectTo` = `window.location.origin + /volunteer/seniors` | Yes |
| 6 — Check-in + flag | 🟢 Low | Auto-flag SELECT behaviour on 0 rows | Fixed: uses `.maybeSingle()` — returns `{ data: null }` when no open flag exists | Yes |
| 7 — Dashboard | 🟢 Low | RLS denying count queries | `select get_my_role()` in SQL editor as the staff user | Yes |
| 8 — Flag update | 🟡 Medium | Optimistic update reverts (RLS) | Browser console shows revert alert | Yes |
| 9 — XLSX import | 🟡 Medium | Unique index missing from schema | Pre-read gate SQL query | Yes |
| 10 — Deploy | 🟢 Low | 404 on direct URL; magic links go to localhost | Test immediately after deploy | Yes |

**✅ Step 6 flag SELECT:** Uses `.maybeSingle()` — safe on 0 rows. `if (existingFlag)` branch handles both the "first flag" and "update existing flag" cases correctly.

---

## Demo Script — Stakeholder Walkthrough

> Run this after all 11 steps are complete. Use two devices or two browser profiles (one for volunteer, one for staff).

### Setup (2 min before the demo)
- Open incognito tab A → `https://carewatch-demo.vercel.app/volunteer/login` → log in as `volunteer@demo.carewatch.sg`
- Open incognito tab B → `https://carewatch-demo.vercel.app/staff/login` → log in as `staff@demo.carewatch.sg`

### Demo Flow (8–10 min)

**Act 1 — Volunteer experience (3 min)**

1. Show tab A on mobile or resized browser (375px width to simulate Android)
2. Point out: "No app install — works in the browser. This runs on any Android phone from 2018."
3. Seniors list shows: Mdm Lim Ah Kow, Mr Ramasamy, Mdm Chen, Mr Abdul Hamid
4. Tap **Mr Abdul Hamid** → note mobility note "Hard of hearing — knock loudly" in the header
5. Select **No answer** → submit → back to list
   - This is the 4th consecutive no-answer. The flag's `consecutive_count` stays at 3 (already open).
6. Tap **Mdm Lim Ah Kow** → select **All good** → submit
7. Show: "Check-in recorded. Mdm Lim's streak continues."

**Act 2 — Staff dashboard (3 min)**

1. Switch to tab B (staff dashboard)
2. Show the 4 stat tiles: **10 seniors**, **1 volunteer**, check-ins today, **1 open flag** (red)
3. Click **Flag queue**
4. Show Mr Abdul Hamid's flag — "3 consecutive no-answers over 3 days. Unusual for him."
5. Click the row → expand the action panel → type staff note: "Called family, they will check on him"
6. Click **Mark reviewed**
7. Badge updates immediately → "This is the audit trail AAC coordinators need."

**Act 3 — XLSX import (2 min)**

1. Back to dashboard → **Import seniors**
2. Upload a CSV with 5 new seniors
3. Map columns → preview → import
4. "Staff uploads their spreadsheet once. No IT department, no API keys, no phone calls."

**Act 4 — Multi-tenancy point (1 min)**

1. Pull up the Supabase Table Editor (screen share)
2. Show `aac_id` on every row in seniors, checkins, flags
3. "20 AACs could run on this today. Bishan AAC staff can never see Tampines data — the database refuses to return it, not just the app."

### Demo Reset (after the demo)
```sql
-- Reset the flag back to open so the demo is repeatable
update flags set status = 'open', actioned_by = null, actioned_at = null, staff_notes = null
where id = '30000000-0000-0000-0000-000000000001';

-- Remove today's check-ins (keep the pre-seeded ones)
delete from checkins where created_at > now() - interval '5 minutes';
```

---

## Success Criteria

| Feature | Target | Verification |
|---|---|---|
| Volunteer login | Email magic link signs in on Android Chrome | Send link → open on phone → session active |
| Seniors list | 4 assigned seniors visible (RLS enforced) | Volunteer sees only their 4 — not all 10 |
| Check-in submission | Row inserted with correct `aac_id`, `volunteer_id`, `senior_id` | Check Supabase `checkins` table |
| Auto-flagging | Flag created after exactly 3 consecutive no-answers (not 2) | Submit 2 → no new flag. Submit 3rd → flag row appears |
| Staff dashboard | 4 stat tiles show live counts; flag tile turns red | Numbers match DB; 1 open flag = red tile |
| Flag queue | Pre-seeded flag for Mr Abdul Hamid visible on login | No SQL needed — data pre-loaded in Step 3b |
| Flag action | Staff can action a flag; change persists + is optimistic | Update status → badge changes instantly, DB reflects it |
| XLSX import | 50-row file imports cleanly; re-import is idempotent | 50 rows in `seniors`; second import same count |
| PWA installable | "Add to Home Screen" on Android Chrome | Open Vercel URL on Android → install prompt appears |
| Typography | Inter with `cv11` loaded | DevTools → `body` computed `font-feature-settings` includes `cv11` |
| Premium aesthetic | Gray-900 primary buttons, no coloured card backgrounds | Visual QA: headings tight, buttons dark, no Bootstrap colours |
| Demo reset | Flag can be reset to `open` in 1 SQL command | Run reset SQL above — flag back to open state |

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not proceed past a Human Gate without explicit human input.**
⚠️ **If blocked, mark 🟨 In Progress and output the State Manifest before stopping.**
⚠️ **Do not batch multiple steps into one git commit or push.**
⚠️ **Step 6 flag logic: use SELECT + conditional INSERT/UPDATE — never upsert with a partial index.**
⚠️ **Step 9 upsert: confirm `seniors_aac_unit_idx` exists (pre-read gate) before importing.**
✅ **Step 6 flag SELECT uses `.maybeSingle()` — no action needed.**
