# QualSched

A desktop app for scheduling Qualtrics survey invitations in EMA studies. It replaces
the `qualtrics_util` command-line tool with a GUI that installs without administrator
rights on Windows, macOS and Linux.

> **Note:** this README replaced the original one in this folder, which was overwritten
> when the Tauri scaffold was unpacked here. Restore anything you need from a backup.

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
   in place. A badge shows whether each participant is ready to schedule, and why not
   when they aren't.
4. **Schedule** — computes the full plan, shows every invitation with local and UTC
   times, then sends after you confirm.
5. **Distributions** — invitations already booked, with cancellation for anything still
   in the future.
6. **Import old config** — reads a `config_qualtrics*.yaml` from the CLI and turns it
   into an account plus a survey profile.

## Where your settings live

Settings are stored for you; you don't need to know the path.

| Platform | Location |
| --- | --- |
| Linux | `~/.config/com.lnpi.qualsched/config.json` |
| macOS | `~/Library/Application Support/com.lnpi.qualsched/config.json` |
| Windows | `%APPDATA%\com.lnpi.qualsched\config.json` |

**API tokens are never written to that file.** They go into the operating system's
credential store — Windows Credential Manager, macOS Keychain, or the Secret Service on
Linux (`gnome-keyring` or `kwallet`, which must be running).

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

Participants whose contacts carry `Time1`, `Time2`, … integers instead of a `TimeSlots`
list are supported too, since the Qualtrics web UI cannot author list-valued embedded
data.

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

## Building

Requires [Rust](https://rustup.rs) and Node 18+.

```bash
npm install
npm run tauri dev      # development, with hot reload
npm run tauri build    # production bundles
```

On Linux you also need the WebKit development packages:

```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev pkg-config
```

Run the Rust tests — the scheduling rules above are covered there — with:

```bash
cd src-tauri && cargo test
```

### Packaging

`npm run tauri build` produces a Windows NSIS installer configured for per-user
installation (no administrator prompt), a macOS `.app`/`.dmg`, and Linux AppImage and
`.deb` bundles.

The macOS build is signed ad-hoc, so the first launch needs right-click → Open. For
wider distribution, replace `bundle.macOS.signingIdentity` in
[src-tauri/tauri.conf.json](src-tauri/tauri.conf.json) with a real Developer ID and add
notarization.

## Layout

```
src/                    Svelte 5 frontend
  lib/                  API bindings, shared types, app state, dropdown cache
  screens/              one file per screen
  components/           ApiDropdown, ConfirmDialog
src-tauri/src/
  qualtrics/            HTTP client and one module per API area
  scheduler/            all scheduling rules — pure, no IO, fully unit-tested
  commands/             the Tauri command surface the frontend calls
  config/, keychain.rs  settings persistence and token storage
  import.rs             legacy YAML reader
```

All Qualtrics API calls happen in Rust; the webview never sees the API token.
