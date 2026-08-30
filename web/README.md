# QualSched Web

Hosted researcher UI for scheduling Qualtrics EMA invitations. **Version 0.2.1**.
Lives in the [QualSched monorepo](https://github.com/kelvinlim/qualsched) as `web/`,
sharing Svelte screens with the desktop app via `ui/`.

Imported from the former standalone repo
[kelvinlim/qualsched-web](https://github.com/kelvinlim/qualsched-web) `main` at
`1a2e6e9a814b`. That repo stays published.

## PHI rule (non-negotiable)

Participant PHI — names, phones, emails, time slots, time zones, LogData — **must stay
in Qualtrics**. The app database never stores contact/participant records.

Allowed tables:

| Table | What it holds |
| --- | --- |
| `users` | Researchers (Google allowlist). Not study participants. |
| `qualtrics_accounts` | Data center, directory id, library id, **Fernet-encrypted** API token |
| `survey_profiles` | Survey id, mailing list id, template ids, sender, default settings |

There is no `contacts` table. No participant phone/email/name columns. Contact
list/create/update/delete and schedule preview/execute proxy Qualtrics and discard
the payload after the response. The plan is never stored.

The Qualtrics API token is encrypted at rest. The browser **never** receives it. The
frontend calls `/api/...`; the backend uses httpx against `{dc}.qualtrics.com`.

## How this differs from desktop QualSched

| Desktop (`desktop/`) | This directory (`web/`) |
| --- | --- |
| Tauri + local JSON config + OS keychain | FastAPI + MariaDB + Fernet |
| No researcher login | Google OAuth allowlist (wearable-hub pattern) |
| `invoke` / `listen` from the webview | HTTP (SSE later for schedule progress) |
| Native file dialogs | `<input type="file">` and downloads |
| Ships as a laptop app | Compose locally; Quadlets on lnpitask (`/qualsched`) |

The sidebar and screens are the same files in `ui/`: Accounts, Survey profile,
Contacts, Schedule, Distributions, Import, Export, Guide. The web shell adds
Google / dev login and Legal pages.

**Milestone 1** wires Accounts (save data center + token) and survey-profile CRUD.
Contacts now proxies the Qualtrics mailing list (no local participant table).
Schedule computes a plan and books Qualtrics distributions; the plan is not stored.
Distributions lists booked invitations from Qualtrics and can cancel unsent ones;
removing a contact cancels theirs first.

## How to run (Docker Compose, local MariaDB sidecar)

MariaDB is the intended database. Local compose starts a **sidecar** MariaDB
named `db` (host port **3307**) so you can work offline. That sidecar is not
used on lnpitask — production points at external MariaDB on `cnc3.med.umn.edu`,
same as wearable-hub.

Ports: API **8030**, UI **8040** — they do not collide with wearable-hub
(`8010`/`8020`) or `/qualtrics_dashboard` on `8000`.

```bash
# from the monorepo root
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
cp web/.env.sample web/.env
# paste the key into FERNET_KEY=
# set SUPERADMIN_EMAILS=you@umn.edu
# compose overrides DATABASE_URL / DB_WAIT_* to the sidecar `db` (see docker-compose.yml)

cd web && docker compose up --build
# frontend image is built from the repo root so ui/ is included
```

The backend entrypoint waits for `DB_WAIT_HOST:DB_WAIT_PORT`, runs
`alembic upgrade head`, then uvicorn. Open http://localhost:8040. Sign in with
the SUPERADMIN_EMAILS address (development sign-in, because Google client ids
are empty). Public Privacy / Terms (no login):
http://localhost:8040/privacy and http://localhost:8040/terms. On Accounts: add
an account, paste a Qualtrics API token, save. Reload — the token field stays
empty and says it is stored.

### Tests (in-memory SQLite)

From `web/backend/`: `pytest`. The fixture is in-memory SQLite + `create_all`.
Alembic revision `0001` is what production/compose apply on **MariaDB 11**
(see `backend/tests/test_alembic_mariadb.py`).

SQLite is not the default first-run. An explicit `sqlite:///./qualsched.db` URL
is an escape hatch only (entrypoint skips the network wait for `sqlite*`).

## Environment variables

See [`web/.env.sample`](.env.sample). Summary:

| Variable | Purpose |
| --- | --- |
| `FERNET_KEY` | Encrypts Qualtrics tokens **and** the session cookie |
| `DATABASE_URL` | `mysql+pymysql://…` — compose sidecar `db`, or cnc3 in prod |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | Schema `qualsched` (do not reuse `wearable_hub`) |
| `DB_WAIT_HOST` / `DB_WAIT_PORT` | entrypoint waits here before `alembic upgrade head` |
| `SUPERADMIN_EMAILS` | Comma-separated bootstrap researcher emails (superusers on first login) |
| `ALLOWED_EMAIL_DOMAINS` | Comma-separated domains auto-provisioned as regular researchers (`umn.edu` on lnpitask; do not add `gmail.com`) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Dedicated QualSched OAuth web client (not wearable-hub / `fitbitdata-499001`) |
| `RESEARCHER_OAUTH_REDIRECT_URI` | Must match the Cloud Console redirect (local: `http://localhost:8040/auth/callback`; prod: `https://lnpitask.umn.edu/qualsched/auth/callback`) |
| `PUBLIC_PATH_PREFIX` | Host path prefix (`/qualsched` on lnpitask). Backend routes stay unprefixed; host nginx strips it |
| `ENVIRONMENT` | `dev` allows the documented bypass when Google ids are unset; `prod` on lnpitask |

Google tokens are **not** stored. The grant is only used to prove identity against the
allowlist: a `users` row, `SUPERADMIN_EMAILS`, or `ALLOWED_EMAIL_DOMAINS` (campus
`@umn.edu` on lnpitask). Gmail is not included in the domain list. After changing
`.env`, restart the backend.

## Production (lnpitask.umn.edu)

Same host as wearable-hub: Podman **Quadlets** + host nginx location blocks —
not compose. **Different** schema (`qualsched`, not `wearable_hub`), host ports
**8050** / **8060** (loopback; tictech already uses 8030/8040), path prefix
**`/qualsched`** only. Do not occupy `/wearable`, `/enroll`, `/webhooks`,
`/qualtrics_dashboard`, `/tictech`, or port 8000.

Public URL: **https://lnpitask.umn.edu/qualsched/**

Google OAuth branding pages (no login; paste these in Cloud Console → Branding):

- Home: https://lnpitask.umn.edu/qualsched/
- Privacy: https://lnpitask.umn.edu/qualsched/privacy
- Terms: https://lnpitask.umn.edu/qualsched/terms

Do not upload a consent-screen logo (forces verification). Full Console steps:
[deploy/README.md](deploy/README.md) §4.

Host checklist (do this on lnpitask; full detail in [deploy/README.md](deploy/README.md)):

1. Checkout at `/home/kolim/Projects/qualsched` (or edit the Quadlet `EnvironmentFile` path).
2. `cp web/.env.sample web/.env` and set `FERNET_KEY`, `SUPERADMIN_EMAILS`,
   `DATABASE_URL` → cnc3 `qualsched`, `DB_WAIT_HOST=cnc3.med.umn.edu`,
   `PUBLIC_PATH_PREFIX=/qualsched`, `ALLOWED_EMAIL_DOMAINS=umn.edu`,
   `RESEARCHER_OAUTH_REDIRECT_URI=https://lnpitask.umn.edu/qualsched/auth/callback`,
   `ENVIRONMENT=prod`. Never commit `.env`. Secrets stay in `web/.env`, not the repo root.
3. Provision schema/user `qualsched` on cnc3 (Kelvin). No MariaDB container on lnpitask.
4. Create a **dedicated** GCP OAuth project for QualSched (External, **In
   production**, scopes openid/email/profile only). Do not reuse
   `fitbitdata-499001`. Put the web client id/secret in `web/.env` (see
   [deploy/README.md](deploy/README.md) §4).
5. Copy [deploy/quadlet/](deploy/quadlet/) to `/etc/containers/systemd/`
   (`qualsched.network`, backend, frontend — **no scheduler**).
6. Merge [deploy/nginx/qualsched.conf](deploy/nginx/qualsched.conf) into the
   existing TLS `server { }` (do not add a second listen/ssl block).
   `sudo nginx -t && sudo nginx -s reload`.
7. `web/scripts/deploy.sh` (rebuilds images from the monorepo layout, restarts units, curls
   `localhost:8050/health` and `localhost:8060/`).

Quadlet sources: [deploy/quadlet/](deploy/quadlet/). Logs:
`sudo journalctl -u qualsched-backend.service -f`.
`docker-compose.yml` is local development only.

## License

MIT. Same as QualSched desktop. Copyright (c) 2026 Kelvin O. Lim.
