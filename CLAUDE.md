# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

`cargo` is **not on the PATH** by default in this environment. Run `. "$HOME/.cargo/env"` first or every Tauri command fails with `Rust: not found`.

```bash
npm run tauri dev                        # run with frontend hot reload
npm run tauri build                      # production bundles for the current OS
npm run check                            # svelte-check over the frontend
cd src-tauri && cargo test               # all Rust tests
cd src-tauri && cargo test midnight      # one test, by substring of its name
```

Linux builds need the WebKit dev packages listed in the README.

## Where the reference implementation lives

This app is a port of a Python CLI, and the code it ports is **not** in the `lnpi_qualtrics/` symlink in this repo. That folder is a response-export tool containing no scheduling or distribution code at all.

The authoritative source is the sibling repo `../qualtrics_util/`:

- `qualtrics_util.py` — the monolith that actually ships. Behavior questions are settled here.
- `src/qualtrics_util/` — an incomplete refactor. Good for structure, not for behavior; several paths are unfinished or broken.
- `config/*.yaml` — 27 real study configs, useful as importer test inputs.

Consult `lnpi_qualtrics/LNPIQualtrics.py` only for survey and mailing-list enumeration.

## Architecture

**Rust owns every Qualtrics API call.** The webview never sees the API token and no HTTP plugin is enabled. Adding a frontend `fetch` to Qualtrics would break that; add a `#[tauri::command]` instead.

**`scheduler/` is pure.** No IO, no globals, and both the clock and the RNG are injected as parameters. This is what makes DST, midnight-crossing, and past-slot behavior testable, so keep new scheduling rules there rather than in the command layer.

**Preview and execute are a contract.** `preview_schedule` resolves random time windows and returns the concrete plan; `execute_schedule` sends *that* plan. Re-drawing times at send would mean the user approved something different from what went out.

**Failures are collected, never fatal.** A bad participant record yields a `Skipped` with a human-readable reason; a failed send is recorded and the batch continues. Nothing in the send path should return early on a single item's failure.

**`SurveysScheduled` is the idempotency guard.** It is written once per participant after their sends complete, and a non-zero value makes them ineligible. If that write fails the app reports it prominently, because a re-run would otherwise double-schedule. Treat it accordingly.

**Eligibility has one implementation.** `contact_cmds::to_view` runs `scheduler::contact_eligibility` so the Contacts badge cannot disagree with what the scheduler will actually do. Don't add a second rule set for display.

## Deliberate deviations from the Python

These look like bugs against the reference and are not. Do not "restore" them:

| Behavior | Why |
| --- | --- |
| Past send times are skipped | The CLI posted them; Qualtrics accepts them and they never fire |
| A failed send doesn't abort the run | The CLI called `sys.exit`, stranding half-scheduled participants |
| `ExpireMinutes` is read | The CLI read `MINUTES_EXP`, which no config writes, so expiry always fell back to 60 |
| Windows crossing midnight work | `[2350,0010]` produced a nonsense time |
| Email sender fields are per-project | They were hardcoded to a UMN address |
| `TimeSlots` is parsed, not `eval`'d | `eval` accepted participant-editable text and impossible times like `2366` |

## Qualtrics API behavior encoded in the code

- The contact `PUT` echoes back the whole record, but Qualtrics rejects `contactId`, `contactLookupId`, and `mailingListUnsubscribed` on the way in. A null `email` must be omitted entirely rather than sent as null.
- Distributions are addressed by `contactLookupId` (`CGC_…`), not `contactId`. The mailing-list response usually carries it; only fall back to the directory-contact request when it doesn't.
- Message text is fetched and inlined with a random suffix rather than sent by `messageId`. Qualtrics refuses a second invitation with identical content on the same day.
- Writes are paced by `client::WRITE_PACING` to stay under rate limits.
- `verify_tls: false` exists for the VA's `gov1` data center, which sits behind TLS interception.

## Data model and storage

Accounts hold connection settings and one or more survey profiles; profiles hold a survey, mailing list, templates, and embedded-data defaults. Settings persist as JSON in the OS config directory; **tokens go to the OS keychain only** and must never be written into that file. The backend is the source of truth — config-mutating commands return the whole updated `AppConfig` and the frontend replaces its copy.

Per-participant scheduling lives in Qualtrics embedded data (`StartDate`, `NumDays`, `TimeSlots`, `TimeZone`, `ContactMethod`, `ExpireMinutes`, `SurveysScheduled`), not in local config. Project defaults only seed keys a contact is missing; existing per-participant values are never overwritten.

## Testing

Scheduling rules are covered in `src-tauri/src/scheduler/tests.rs` with a seeded RNG and a fixed clock — DST spring-forward and fall-back, midnight-crossing windows, past-slot skipping, slot parsing, and the eligibility matrix. Extend that suite when changing scheduling behavior.

The contact-creation and contact-removal paths have **not** been exercised against live Qualtrics; the Python tool had no equivalent, so no known quirks could be mirrored.
