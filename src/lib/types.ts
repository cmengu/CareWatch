// Domain types — aligned with supabase/schema.sql (Step 3). Needed before supabase.ts.

export type Role = 'volunteer' | 'staff' | 'admin'
export type CheckInOutcome = 'ok' | 'no_answer' | 'flagged'
export type FlagStatus = 'open' | 'reviewed' | 'actioned' | 'escalated'
export type ConsentStatus = 'pending' | 'given' | 'withdrawn'
export type EscalationLevel = 'review' | 'urgent' | 'emergency'

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
