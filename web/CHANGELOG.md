# Changelog

All notable changes to QualSched Web are documented in this file.

## [Unreleased]

### Added
- Public Privacy Policy and Terms of Service pages (`/privacy`, `/terms`) for
  Google OAuth branding. They render without sign-in. Console URLs and “skip the
  logo” note in `deploy/README.md` §4.
- Desktop QualSched logo (`kelvinlim/qualsched` `src-tauri/icons`) on the login
  screen, sidebar, and browser tab.

### Changed
- Researcher Google OAuth is a **dedicated** QualSched Cloud project (External,
  In production, openid/email/profile only). Do not reuse wearable-hub
  `fitbitdata-499001` (Testing 100-user cap + Health scopes). Console steps in
  `deploy/README.md` §4.

## [0.1.0] - 2026-08-28

### Added
- lnpitask deploy files (Podman Quadlets + host nginx snippet + `scripts/deploy.sh`),
  mirroring wearable-hub. Prefix `/qualsched`, host ports 8050/8060 (tictech
  already uses 8030/8040), backend + frontend only. Host checklist in
  `deploy/README.md`. Researcher allowlist is `SUPERADMIN_EMAILS`, `users` rows, and `ALLOWED_EMAIL_DOMAINS`
  (`umn.edu` on lnpitask; not `gmail.com`); see `deploy/README.md` §4b.
- `ALLOWED_EMAIL_DOMAINS` auto-provisions regular researchers on first Google
  login (`umn.edu` on lnpitask; subdomains included). Gmail stays explicit
  (`SUPERADMIN_EMAILS` / `users` row). Do not add `gmail.com`.
- Production frontend image builds with Vite `base: /qualsched/` so the browser
  requests assets and `/api` `/auth` under that prefix. Local vite/compose stay
  at `/`. Host nginx still strips `/qualsched/`.

### Changed
- MariaDB is the intended production/dev database, matching wearable-hub:
  external host `cnc3.med.umn.edu`, new schema/user `qualsched` (not
  `wearable_hub`). Local compose still starts its own MariaDB sidecar (`db`).
  SQLite is tests-only (plus an explicit escape hatch), not the default first-run.
  Alembic owns the schema; `create_all` is not used against MariaDB.

### Added
- Contacts screen talks to the Qualtrics mailing list (list, add, edit, remove, fill
  missing embedded defaults). Participant PHI is proxied live and never stored.
- Missing directory ID, mailing list ID, or API token returns HTTP 400 with a clear
  reason instead of an empty list that looks like "no participants."
- Schedule preview and execute: compute a NumDays × TimeSlots plan in each contact's
  timezone and book one Qualtrics distribution per participant × day × slot. The plan
  is not stored. Missing token, data center, directory, mailing list, survey id, or
  message id returns HTTP 400 rather than an empty plan.
- Distributions list and cancel: live Qualtrics invitations for the profile survey
  (and leftover 0.1.4 clones), filtered by SMS or email. Unsent rows can be cancelled.
  Removing a contact cancels their unsent invitations first and reports the count.

### Notes
- Schedule progress SSE and delete-progress SSE are still no-ops.

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
