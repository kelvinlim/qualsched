# Changelog

All notable changes to QualSched Web are documented in this file.

## [Unreleased]

### Added
- Public Privacy Policy and Terms of Service pages (`/privacy`, `/terms`) for
  Google OAuth branding. Login screen links to both; they render without sign-in.
- Desktop QualSched logo on the login screen, sidebar, and browser tab.

## [0.1.0] - 2026-08-28

### Changed
- Login hint: campus `@umn.edu` (ALLOWED_EMAIL_DOMAINS) plus explicit SUPERADMIN /
  users-row allowlist. Gmail is not campus-wide.
- Production Docker build sets Vite `base: /qualsched/` (Dockerfile `VITE_BASE`).
  Fetches join `import.meta.env.BASE_URL` so prod calls `/qualsched/api/…` and
  `/qualsched/auth/…`. Local `npm run dev` and compose keep `base: /`.
- Contacts no longer shows the milestone-1 "not wired" banner. The page lists
  participants from the Qualtrics mailing list and can add, edit, and remove them.
- Schedule no longer shows the milestone-1 "not wired" banner. Compute plan and
  Send book Qualtrics invitations; the plan is not kept in this app.
- Distributions no longer shows the milestone-1 "not wired" banner. Load lists
  booked Qualtrics invitations; Cancel selected withdraws unsent ones.

## [0.0.1] - 2026-08-27

### Added
- Milestone 1 skeleton: Svelte 5 UI ported from desktop QualSched, FastAPI backend
  patterned on wearable-hub ops (Fernet, Google allowlist, MariaDB).
- Accounts screen stores Qualtrics data-center metadata and a Fernet-encrypted API
  token. The browser never receives the token.
- Survey profile CRUD. Schedule / Distributions are not wired yet; those screens
  stay honest about it.
- Docker Compose: MariaDB + backend `:8030` + frontend `:8040`.
- Documented local dev-login when Google OAuth client ids are unset.
