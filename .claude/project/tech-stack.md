CareWatch — Software Engineering Game Plan

Decisions Locked In
QuestionDecisionWho buildsIn-house dev teamVolunteer devicesOld budget Android phones — assume low storage, slow CPUsExisting AAC systemsUnknown for now — design for import-first, integration laterScale20+ AACs, thousands of seniors — multi-tenant from day oneBudgetWell-funded for production. Zero cost for demo.Check-in verificationTrust-based — no geo or photo enforcementSenior importXLSX upload button — any staff can do itHostingVendor-hosted but fully portable — no lock-in

Tech Stack
Demo (Zero Cost)
LayerChoiceWhyVolunteer interfacePWA (React + Vite) hosted on VercelNo app store, no install, runs in browser on any AndroidAAC dashboardSame React app, different route, hosted on VercelOne codebase, free tierBackend + DBSupabase free tierPostgreSQL + auth + REST API + row-level security out of the boxAuthSupabase Auth — OTP via email for demoTwilio costs money; email OTP is free for demoXLSX importSheetJS in the browser — parse client-side, POST to SupabaseZero backend costPush notificationsSkip for demoNot needed to prove the concept
Demo is live, functional, and costs nothing. Same codebase graduates to production.
Production
LayerChoiceWhyVolunteer interfacePWA (React + Vite)Old budget phones cannot be assumed to have storage for a native app. PWA runs in the browser — no install, no app store approval, works on Android 8+. Web Push handles notifications on Android.AAC dashboardReact + Vite, separate deploymentInternal tool — no need for a framework. Fast to build and maintain.BackendNode.js + FastifyLightweight, fast, strong ecosystem. In-house team can move quickly.DatabasePostgreSQL on AWS RDS (Singapore region)Relational model suits assignments + check-ins + audit logs. Row-level security handles multi-tenancy cleanly. Singapore region for PDPA.Multi-tenancyEvery table has an aac_id column. RLS policies enforce it.Simplest approach that scales — no schema-per-tenant complexity.AuthJWT. Volunteers: OTP via Twilio. Staff: email + password.Phone OTP removes friction for less tech-savvy volunteers.XLSX importSheetJS on frontend, normalised POST to backendStaff or anyone can upload a spreadsheet. No CLI tools, no IT involvement.Existing system integrationAdapter pattern — build a generic import API nowYou don't know what the AAC systems are yet. Design the import endpoint to accept normalised JSON. XLSX parser is the first adapter. Future connectors (SocialServiceNet, custom CRM) plug into the same interface without changing the core.Push notificationsFirebase Cloud Messaging (Web Push for PWA)Free generous tier. Works on Android Chrome. iOS support improving from iOS 16.4+.Background jobsBullMQ + Redis (AWS ElastiCache)Daily reminder notifications. Auto-escalation after 3 consecutive no-answers.HostingAWS ap-southeast-1. ECS Fargate (backend), RDS (database), S3 + CloudFront (frontend).Singapore region. No vendor lock-in — Docker containers can move anywhere.PortabilityDocker + Prisma migrations + Terraform IaCFull infrastructure as code. Vendor can hand over and someone else picks it up.MonitoringAWS CloudWatch + Sentry for errorsStandard, cost-effective.

Architecture Overview
Volunteers (PWA on Android browser)
        │
        ▼
  Vercel / CloudFront  ◄──── React + Vite frontend
        │
        ▼
   Fastify REST API  (ECS Fargate, Docker)
        │
   ┌────┴────────────────────┐
   ▼                         ▼
PostgreSQL (RDS)         Redis (ElastiCache)
  - aac_id on every row    - BullMQ job queues
  - RLS enforced           - Session cache
        │
   ┌────┴────────────────────┐
   ▼                         ▼
XLSX Import Adapter    Future: SocialServiceNet
(SheetJS → normalised       adapter, CRM adapter,
 JSON → POST /import)       all plug into same API

Multi-Tenancy Design
Every core table carries aac_id. PostgreSQL Row Level Security policies enforce that queries only return rows matching the authenticated user's AAC. A Volunteer from Tampines AAC can never see a senior from Bishan AAC — not because the app filters it, but because the database refuses to return it.
Staff and Admin roles are scoped to their aac_id at the JWT level. A super-admin role (for your central team) can query across all AACs for reporting.

Import System Design
The XLSX import button does this:

Staff uploads a spreadsheet (any format — you handle mapping in the UI)
Browser parses it with SheetJS, shows a column-mapping screen ("which column is the senior's name? which is their unit?")
Staff confirms, frontend sends normalised JSON to POST /aac/:aacId/seniors/import
Backend validates, checks for duplicates, inserts, returns a summary ("48 added, 2 skipped — duplicate unit numbers")
Audit log records who imported what and when

This same endpoint is what future system integrations will call. The XLSX UI is just the first adapter.

Data Models
Seniors
id, aac_id, name, unit_number, block_id, preferred_language,
mobility_notes, consent_status, consent_date, aac_notes,
visible_fields (JSONB), created_at, updated_at
Volunteers
id, aac_id, phone_number, name, block_id, verified,
active, joined_at, last_active_at
Assignments
id, aac_id, volunteer_id, senior_id, assigned_by,
assigned_at, ended_at
CheckIns
id, aac_id, volunteer_id, senior_id,
outcome (ok | no_answer | flagged), notes,
created_at
Flags
id, aac_id, checkin_id, senior_id, consecutive_count,
status (open | reviewed | actioned | escalated),
actioned_by, actioned_at, staff_notes
EscalationCases
id, aac_id, flag_id, senior_id, level (review | urgent | emergency),
opened_by, opened_at, action_taken, outcome, closed_at
AuditLog
id, aac_id, actor_id, actor_role, action, entity_type,
entity_id, diff (JSONB), created_at

Key API Endpoints
MethodEndpointRolePurposePOST/auth/otp/requestPublicRequest OTP to phonePOST/auth/otp/verifyPublicVerify OTP, return JWTGET/me/seniorsVolunteerAssigned seniors onlyGET/seniors/:idVolunteer / StaffProfile (field-filtered by role)POST/seniors/:id/checkinsVolunteerSubmit check-inPOST/aac/:id/seniors/importStaff / AdminBulk import from XLSXGET/dashboard/overviewStaffStats across all blocksGET/dashboard/flagsStaffOpen flag queuePATCH/flags/:idStaffUpdate flag statusPOST/escalationsStaffOpen escalation caseGET/volunteersStaffVolunteer list + activityPOST/assignmentsAdminAssign volunteer to seniorPATCH/seniors/:id/visibilityAdminControl what volunteers seePATCH/seniors/:id/consentAdminUpdate consent statusGET/reports/coverageSuper AdminCross-AAC coverage report

Build Phases
Phase 0 — Demo (now, zero cost, 2–3 weeks)
PWA in Vercel + Supabase. Volunteer check-in flow, AAC dashboard overview, XLSX import, flagging. Enough to show stakeholders and onboard the first pilot AAC. No push notifications, no background jobs.
Phase 1 — Production MVP (6–8 weeks)
Migrate to AWS Singapore. Multi-AAC with RLS. OTP via Twilio. Push notifications via FCM. Background jobs for reminders and auto-escalation. Full audit log. Volunteer and senior management for AAC admins.
Phase 2 — Integration Layer (4 weeks after Phase 1 stable)
Build the existing-system adapter once you know what systems the AACs are using. The import API is already there — you're just writing a new adapter on top. Add cross-AAC reporting for your central team.
Phase 3 — Scale & Insights (ongoing)
Volunteer fatigue analytics. Coverage trend reports. Escalation outcome tracking. Senior wellbeing longitudinal data. Potential SingPass or Corppass integration for volunteer verification if required.

Portability Guarantee
Everything is containerised with Docker. Database schema is managed through Prisma migrations — full history, rollback capable. Infrastructure defined in Terraform. At any point you can hand a vendor the repo and the Terraform state and they can redeploy the entire system from scratch on any cloud. No proprietary services that cannot be swapped out.