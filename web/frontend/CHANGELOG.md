# Changelog

All notable changes to QualSched Web are documented in this file.

## [Unreleased]

## [0.2.6] - 2026-11-22

### Added
- **Acquisition** participant search input above the table (name, reference, phone, email; respects **Hide PHI** by searching only `extRef` and `contactId`) and compact heatmap legend.

### Changed
- **Acquisition** partial day boxes (`1%–99%`) use warm amber fills while `100%` completed days use solid emerald green, multi-year week labels are widened to prevent overlap, and **Active only** keeps participants who are not `Inactive` and have survey invitations during the current Monday–Sunday week.

## [0.2.5] - 2026-11-22

### Fixed
- Fixed Acquisition zero counts and cross-mailing-list unjoined invitations by counting per-invitation Qualtrics `stats.finished` (SMS filtered by `recipients.mailingListId` + email distributions) without downloading survey response exports, and separating removed-contact invitations cleanly from unowned invitations.

### Changed
- Acquisition waits for an explicit **Load** / **Refresh** click instead of auto-downloading on open or profile switch, and arranges day boxes into vertically stacked Monday–Sunday 7-day rows with weekend column styling and week-start labels.

### Added
- Hover/focus day-detail popover on Acquisition day boxes showing the full local date, weekend badge, completion summary, and per-prompt local send time, method, and status.

## [0.2.4] - 2026-11-22

### Fixed
- Acquisition export follows the datacenter host Qualtrics names with error code GRP_1, or in a proxy notice, and retries that host once. The sentence itself is not shown or logged.
- Acquisition export no longer fails before it reaches Qualtrics. A per-call deadline was passed into the HTTP client's send method, which rejected it, so the request became an internal error and the page only showed its own 50 second timeout. The page now shows the stage and the error type.
- The Contacts screen was reloading the mailing list on every pass. Opening it produced a continuous stream of contact requests. It now loads once per selected profile.
- Acquisition shows a short live status line (connecting, contacts, invitations, which survey is exporting, download, counting) while the timer runs. The web request returns as soon as that status is known; the Qualtrics calls continue in the server process. The page keeps reading that status past the server's export deadline, and a newer load stops the previous one before the next Qualtrics call.
- Acquisition loading no longer restarts on every tick. The screen's load effect was reading the operation counter it incremented, so Svelte aborted the request and reset the elapsed timer to 0:00. A request that does not answer, or that stays pending past the poll budget, now shows a banner instead of spinning.
- Acquisition no longer holds one browser request open while Qualtrics builds the response file. Each request performs one progress check. The proxy in front of the app stops at 60 seconds, which cut off a slow export before. A failure now names the stage, the HTTP status, and a machine error code, without the Qualtrics sentence.
- Loading buttons and status lines show an indeterminate spinner and a cumulative elapsed time. The time starts with the operation, keeps running through retries, and resets when a new operation starts.
- Acquisition no longer fails with "Qualtrics response export failed (HTTP 400)"
  when the survey has no embedded field named RecipientID. The export request
  no longer guesses those field names, and a rejected filter falls through to
  an unfiltered JSON export that is reduced to completion fields in memory.

### Added
- **Hide PHI** checkbox in the top bar across Contacts, Contact editor, Schedule, Distributions, and Acquisition: replaces participant names with `extRef` (falling back to Qualtrics contact ID), masks phone numbers, email addresses, and destinations, and locks/masks identity fields while editing. Defaults off and persists in `localStorage`.
- **Acquisition** screen, shared with desktop: completed surveys versus invitations
  still listed. The browser receives aggregate counts only. Response exports stay
  on the server and are not stored.

## [0.2.3] - 2026-08-30

### Changed
- Shared version bump with desktop. What's new download still opens the GitHub
  release page on web (desktop now offers this computer's installer).

## [0.2.2] - 2026-08-30

### Added
- Accounts: Load from Qualtrics picker for Message library ID (GR_/UR_), same as
  Contact directory.

### Changed
- All Load from Qualtrics lists sort by name (case-insensitive); unnamed items last.
- Sidebar: Survey profile and Import Config stay disabled until a usable account
  is selected (non-empty data center). A blank New account draft does not count.

### Fixed
- Survey profile: + Add profile actually opens a blank form you can type into
  and Save (the new profile is added to the account). Existing profiles auto-open
  if none was selected.

## [0.2.1] - 2026-08-30

### Fixed
- Production Vite builds resolve `@qualsched/changelog?raw` and `@qualsched/guide?raw`
  (regex aliases).
- "What's new" only treats a GitHub release as an update when its semver is newer
  than the running version.

### Changed
- Import Config defaults "Import into" to the currently selected account after
  Read config. Create a new account remains an option.

### Added
- GitHub Actions CI: `npm ci`, check, desktop + web frontend builds, and ui tests.

## [0.2.0] - 2026-08-30

### Added
- Public Privacy Policy and Terms of Service pages (`/privacy`, `/terms`) for
  Google OAuth branding. Login screen links to both; they render without sign-in.
- Desktop QualSched logo on the login screen, sidebar, and browser tab.

### Changed
- First monorepo release with desktop QualSched. Shared `ui/`, desktop, and
  web now use the same version. Web was 0.1.0.

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
