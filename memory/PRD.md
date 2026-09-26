# IronCore Gym Management System — MVP PRD

## Original problem statement
Replace Excel-based member, fee, and membership-expiry tracking for a small/medium-sized gym with a reliable, mobile-first web dashboard. The MVP must provide secure admin access, relationally related member/membership/payment data, deterministic INR calculations, Asia/Kolkata date handling, expiry alerts, reports, settings, realistic development demo data, and an architecture ready for later WhatsApp, attendance, online payments, staff roles, member portal, and AI assistant features.

## Architecture decisions
- React 19 frontend with FastAPI backend.
- SQLite relational database for the MVP, with foreign keys and indexes on search, expiry, and payment fields.
- JWT bearer authentication with bcrypt password hashes, eight-hour expiry, development-only seeded admin, and server-side JTI revocation on logout.
- Deterministic server-side membership status, expiry, totals, pending balance, dashboard, and report calculations using Asia/Kolkata.
- REST API boundaries leave room for future notifications, AI queries, payments, attendance, and role expansion.

## User personas
- Gym owner: checks daily health, follows up expiring members, and monitors collections from an Android phone.
- Front-desk staff: quickly adds members, assigns plans, records payments, and searches records.

## Core requirements (static)
Admin login/logout, protected dashboard, members, membership plans, historical memberships, multiple payments, payment history, pending-fee calculation, automatic status, expiry filters, reports, INR formatting, settings, responsive mobile-first UI, validation, and demo data.

## Implemented — 2026-09-22
- Built SQLite schema for users, members, plans, memberships, payments, activity logs, revoked tokens, and settings.
- Added seeded development admin and 15 realistic demo members across active, expiring, expired, and pending-payment states.
- Added dashboard, member directory/search/create flow, payment collection view, expiry watchlist, reports, settings, and mobile navigation.
- Added JWT auth with bcrypt, protected endpoints, server-side logout revocation, and secure input validation for payments and membership dates.
- Independently regression-tested backend and mobile flows; no mocked APIs are used.

## Implemented — 2026-09-25
- Extended "Add Member" form: plan dropdown (from DB), auto-prefilled fee (editable), auto-calculated expiry using calendar month math (editable override), optional initial "Paid now" + method (Cash/UPI/Card/Bank Transfer/Other).
- Backend `POST /api/members` now creates member + membership + optional payment atomically inside a transaction with server-side validation (plan active, expiry ≥ joining, paid_now ≤ total fee).
- Switched membership expiry calculation to calendar-accurate `add_months` on both create-member and add-membership endpoints.
- Added Member Detail page: tap any row to view full profile, current plan/duration, fee summary (total/paid/pending), status badge, expiry, and complete payment history. Includes Edit member (modal → PUT), Delete member (confirm dialog → archive), and Record Payment. Mobile-friendly layout.
- Record Payment upgraded to a smart three-in-one flow: Case 1 (pending only) posts to `/payments`; Cases 2 & 3 (expired / expiring soon, with or without pending) go through new atomic `POST /api/members/{id}/renew` that optionally settles the old membership, creates a new membership row, and optionally applies an initial payment on it. Address field added to Add Member.

## Prioritized backlog
- P0: Keep production secrets and admin credentials outside committed development configuration.
- P1: Add member edit/detail screen with complete payment history and membership renewal actions.
- P1: Add plan edit/archive controls and date-range filters/CSV exports for reports.
- P2: Add explicit configured CORS origins if moving to credentialed cookie sessions.
- P2: Add WhatsApp/SMS notifications, staff roles, attendance, online payments, member portal, and AI assistant.

## Next tasks
1. Complete member profile, edit, renewal, and payment-history workflows.
2. Add report date-range filtering and CSV export.
3. Add role-based permissions for additional staff accounts.
4. Integrate notifications and AI only after the core operations workflow is extended.