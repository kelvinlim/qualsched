# QualSched

A researcher UI for scheduling Qualtrics survey invitations in EMA studies. This
repository is a **monorepo**: one shared Svelte UI, a Tauri desktop app, and
QualSched Web.

**Running a study?** Start with the [User Guide](desktop/docs/USER_GUIDE.md)
(also embedded in both apps). The rest of this file is for people building or
deploying the apps.

QualSched is free and open source under the [MIT License](LICENSE).

## Layout

```
ui/                  shared Svelte screens, components, types, filter/sort/state/cache, app.css
desktop/             Tauri desktop app (v0.2.3): App shell, lib/api.ts (invoke), src-tauri/
web/                 QualSched Web: FastAPI + MariaDB, frontend shell (login/legal), deploy/
```

Adding or refining a screen (Contacts, Schedule, …) is **one change** in `ui/`
that both apps pick up. Each app keeps its own `lib/api.ts` — desktop uses Tauri
`invoke`, web uses `fetch` + `withBase()` — with the same exported function names
and types.

QualSched Web was imported from [kelvinlim/qualsched-web](https://github.com/kelvinlim/qualsched-web)
`main` at `1a2e6e9a814b`. That repo stays published; do not delete it.

## Installing the desktop app

Download the installer for your platform from the
[Releases page](https://github.com/kelvinlim/qualsched/releases) — a Windows NSIS `.exe`
or `.msi`, a macOS `.dmg`, or a Linux AppImage or `.deb`. The NSIS `.exe`, and the
macOS and Linux packages, install without administrator rights. The MSI is a
per-machine install and will ask for administrator approval. Neither Windows installer
is code-signed yet.

On macOS the build is signed ad-hoc, so the first launch needs right-click → **Open**.

## What it does

Qualtrics has no built-in recurring scheduler for this workflow, so invitations are
booked one at a time: for each participant, `NumDays × TimeSlots` individual
distributions are created, each at a specific moment in that participant's own time
zone. QualSched computes those moments, shows you the full plan, and sends it.

Once sent, nothing needs to keep running — Qualtrics holds each invitation until its
send time arrives.

Screens, in the order you use them:

1. **Accounts** — one per Qualtrics login: API token, data center, contact directory,
   message library. You can keep several (for example UMN and VA) and switch freely.
2. **Survey profile** — one per study: survey, mailing list, SMS and email templates,
   email sender details, and the default scheduling values for new participants.
   Dropdowns fill themselves from the Qualtrics API.
3. **Contacts** — the mailing list with each participant's scheduling fields, editable
   in place, searchable by name, phone or email. A badge shows whether each participant
   is ready to schedule, and why not when they aren't.
4. **Schedule** — computes the full plan, shows every invitation with local and UTC
   times, then sends after you confirm.
5. **Distributions** — invitations already booked, searchable the same way, with
   cancellation for anything still in the future.
6. **Import Config** — reads a `config_qualtrics*.yaml` from the CLI, or one this app
   exported, and turns it into a survey profile, either in a new account or in one you
   already have.
7. **Export Config** — writes the selected survey profile back out as a
   `config_qualtrics*.yaml` for another machine to import, or for the CLI to read. The
   API token is never included.
8. **User guide** — the full guide, embedded in the app and readable offline.

Step-by-step instructions for each screen, written for study coordinators, are in the
[User Guide](desktop/docs/USER_GUIDE.md).

## Desktop vs web

| | Desktop | Web |
| --- | --- | --- |
| Shell | Tauri window, no login | Google / dev login, Privacy & Terms |
| API | Rust `invoke`; token in OS keychain | FastAPI `fetch`; token Fernet-encrypted in MariaDB |
| Scheduler | Pure Rust `desktop/src-tauri/src/scheduler/` | Pure Python `web/backend/app/scheduler.py` |
| Install / host | NSIS / MSI / DMG / AppImage / deb, auto-update | Compose locally; Quadlets on lnpitask at `/qualsched` |

Eligibility skip-reason strings and plan JSON shapes stay aligned across the two
schedulers. Participant PHI stays in Qualtrics on both sides.

## Running locally

Requires [Node 18+](https://nodejs.org) (workspaces) and, for desktop,
[Rust](https://rustup.rs).

```bash
npm install                 # installs ui, desktop, and web/frontend
npm run check               # svelte-check on ui + both shells
```

### Desktop

```bash
npm run dev:desktop         # Tauri + Vite on :1420
npm run tauri -- build      # production bundles
cd desktop/src-tauri && cargo test
```

On Linux you also need the WebKit development packages:

```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev pkg-config
```

Settings live in the OS config directory; **API tokens go to the OS credential
store** (Windows Credential Manager, macOS Keychain, or Secret Service on Linux).

| Platform | Config file |
| --- | --- |
| Linux | `~/.config/com.lnpi.qualsched/config.json` |
| macOS | `~/Library/Application Support/com.lnpi.qualsched/config.json` |
| Windows | `%APPDATA%\com.lnpi.qualsched\config.json` |

### Web

Local compose starts a sidecar MariaDB and serves the API on **8030** and the UI
on **8040** (no collision with wearable-hub on 8010/8020). Vite `base` stays `/`
locally; the production image uses `/qualsched/`.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
cp web/.env.sample web/.env
# paste the key into FERNET_KEY= and set SUPERADMIN_EMAILS=you@umn.edu

cd web && docker compose up --build
# UI: http://localhost:8040   API: http://localhost:8030
# or without Docker: npm run dev:web  (from repo root) plus the FastAPI backend

cd web/backend && pytest
```

`.env` is **`web/.env`** so desktop secrets never sit in the same file.

Full web PHI rules, OAuth, and environment variables: [web/README.md](web/README.md).

## Production (lnpitask)

Checkout is **`/home/kolim/Projects/qualsched`**. Secrets live at
`/home/kolim/Projects/qualsched/web/.env`. Quadlet `EnvironmentFile=` paths
point there.

Public URL: **https://lnpitask.umn.edu/qualsched/**

| | QualSched Web | wearable-hub (do not reuse) |
| --- | --- | --- |
| Path prefix | `/qualsched` only | `/wearable` |
| Host ports (loopback) | **8050** backend, **8060** frontend | 8010 / 8020 |
| Local compose ports | **8030** / **8040** | — |
| MariaDB | External `cnc3`, schema `qualsched` | `wearable_hub` |

tictech already uses 8030/8040 on the host, which is why production Quadlets
publish 8050/8060. Local compose keeps 8030/8040.

See [web/deploy/README.md](web/deploy/README.md) and `web/scripts/deploy.sh`.
This repository does not deploy itself.

## Scheduling rules

A participant is scheduled when `SurveysScheduled` is 0, `NumDays` is above 0, and a
delivery method is set — `ContactMethod` of `sms`/`email`, or the older `UseSMS: 1`.

`TimeSlots` holds times of day in 24-hour HHMM form:

```
800,1200,1600,2000        four fixed times
[800,900],[2000,2100]     a random moment inside each window
800,[1200,1300],2000      mixed
```

Random windows guard against participants habituating to a fixed schedule. Windows may
cross midnight (`[2350,0010]`), which rolls the invitation onto the next day.

Times are interpreted in the participant's `TimeZone`, falling back to the profile's.
Daylight-saving transitions are handled: a time that occurs twice uses the earlier
instant, and a time that does not exist moves forward to the first valid minute.

The same rules without the jargon, plus every skip reason and what to do about it, are in
[the guide](desktop/docs/USER_GUIDE.md#reference-the-scheduling-fields).

### Differences from the command-line tool

Behavior is otherwise a faithful port, but six things were deliberately changed:

- **Past times are skipped.** The CLI posted invitations for moments that had already
  passed; they were accepted by Qualtrics and never delivered. These are now dropped and
  listed with a reason in the preview.
- **A failed send no longer aborts the run.** The CLI called `sys.exit` on the first
  failure, leaving a participant half-scheduled. Every remaining invitation now goes out
  and failures are reported together.
- **`ExpireMinutes` is honored.** The CLI read a key name (`MINUTES_EXP`) that no config
  file writes, so link expiry silently fell back to 60 minutes.
- **Midnight-crossing windows work.** `[2350,0010]` previously produced a nonsense time.
- **Email sender details are settings.** They were hardcoded to a UMN address.
- **Time slots are parsed, not `eval`'d.** Malformed values like `2366` are now rejected
  with an explanation instead of crashing mid-run.

`SurveysScheduled` is written once per participant after their invitations are sent. If
that write fails the app says so prominently — until it's corrected, a later run would
schedule that participant a second time.

## Desktop packaging

`npm run tauri -- build` produces a Windows NSIS installer configured for per-user
installation (no administrator prompt), a Windows MSI (per-machine; administrator
prompt), a macOS `.app`/`.dmg`, and Linux AppImage and `.deb` bundles.

The tagged-release workflow is [`.github/workflows/release-windows.yml`](.github/workflows/release-windows.yml)
(Linux + macOS + Windows). It reads versions from `desktop/package.json`,
`desktop/src-tauri/tauri.conf.json`, and `desktop/src-tauri/Cargo.toml`, and
uploads bundles from `desktop/src-tauri/target/release/bundle/…`.

The macOS build is signed ad-hoc, so the first launch needs right-click → Open. For
wider distribution, replace `bundle.macOS.signingIdentity` in
[desktop/src-tauri/tauri.conf.json](desktop/src-tauri/tauri.conf.json) with a real
Developer ID and add notarization.

## License

MIT — see [LICENSE](LICENSE). QualSched is developed by
[OmniKog LLC](https://omnikog.com/qualsched).
