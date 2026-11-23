# Acquisition heatmap

Both desktop and web QualSched share the Acquisition screen in `ui/`. Opening the
screen or switching account or survey profile clears any in-memory report and waits
for the researcher to click **Load** (shown as **Refresh** once a report is on
screen).

It shows one row per mailing-list participant, a block per local day, and a
completed/expected fraction beside each row for **On screen** and **To date** (summing
only prompts whose send time has already passed).

Inactive is a display flag. It does not cancel invitations, delete responses, or
change scheduler eligibility.

## What is counted

**Completed** comes from Qualtrics' per-invitation `stats.finished` on each SMS or
email distribution listed for the survey and profile mailing list. No Qualtrics
response export is started, and no survey answers, respondent IP/location metadata,
or response ids are downloaded. A response that Qualtrics auto-closed after expiry is
marked finished by Qualtrics (`stats.finished > 0`) and counted as completed.

**Expected** is an invitation Qualtrics still lists for that participant on the
profile's mailing list (`distributions?mailingListId=...&surveyId=...&distributionRequestType=Invite`
and `distributions/sms?surveyId=...`), placed on the calendar day of its `sendDate`
in the participant's `TimeZone`.

- `distributions/sms?surveyId=...` returns invitations across all mailing lists that
  share the survey id; entries whose `recipients.mailingListId` is set to another
  mailing list are ignored rather than treated as missing contacts.
- An empty participant `TimeZone` falls back to the survey profile timezone and the
  row says so. An unreadable timezone makes the row `unknown` rather than guessing.
- Prompts with `sendDate` still in the future are drawn as `future` (or counted in
  `later` on the current day) and omitted from the expected denominator until due.
- An invitation missing `stats` marks that day (and the row's definitive flag)
  `unknown` rather than guessing `0`.

The scheduler is not run again. Random windows and later edits show up only as the
send time Qualtrics stored. A cancelled invitation that is no longer listed is not
in the denominator. If `SurveysScheduled` is set but nothing is listed, the expected
count stays at the listed invitations (possibly zero) and the screen says so.

`NumDays` is clamped (`MAX_SPAN_DAYS = 370`) before any date range is built so a
corrupt value cannot walk millions of days; when shortened, the screen notes it. A
404 from the SMS invitation list does not hide email invitations; the screen notes
that the SMS list returned not found. Any other SMS error fails the load.

Days differ on purpose:

- **ratio**, including `0/n` — invitations were due and this many were completed
- **future** — invitations exist for that day but none are due yet (`later > 0`)
- **none** — inside the known study window, nothing was listed
- **nonStudy** — outside `StartDate` + `NumDays`, and nothing was listed
- **unknown** — timezone, mailing-list join, or invitation `stats` prevent computing
  the denominator honestly

An invitation outside the study window is still shown. In **Entire study** view,
trailing/unrelated `nonStudy` days are trimmed when the row has study days.

## Weekly layout and day detail

Day boxes in both **Last 7 days** and **Entire study** are grouped into 7-column
**Monday–Sunday** week rows (`groupByWeeks`, header `M T W T F S S`) stacked vertically
so weekdays and weekends (`S`, `S`, highlighted) align down columns. Each row shows
the Monday short date (with year included when a row spans multiple years), and blank
gap weeks with no days are omitted.

Hovering or focusing a day box opens a viewport-clamped popover showing:

- Full local date (`Weekday, Mon D, YYYY`) and a **Weekend** badge on Saturday/Sunday
- Completion summary (`x of y completed (z%)`, plus any later same-day prompts) or the
  day state message (`future`, `none`, `nonStudy`, `unknown`)
- Every prompt scheduled on that local day in chronological order: local send time
  (`HH:MM`), method (`SMS` or `Email`), and status (`Completed`, `Started (not finished)`,
  `Sent (no response)`, `Delivery failed`, `Scheduled (not yet due)`, or `Status unknown`)

## How invitations are matched

Invitations are attached to a mailing-list row only when `recipients.contactId`
**exactly** matches that participant's `contactLookupId` (`CGC_…`) or directory
`contactId` (`CID_…`). Name, email, phone, and external data reference are never used
as join keys.

- An invitation with no distribution id or recipient contact id is counted in
  `excluded.unjoinedInvitations`, reported in a limitation note, and marks rows missing
  a lookup id provisional/unknown.
- An invitation on the profile's mailing list whose contact was later removed from the
  mailing list is still counted in `excluded.unjoinedInvitations` and reported in a
  separate limitation note, without downgrading active participants on the list to
  provisional.

## Manual status

`QsMonitor` on the contact's embedded data is `active` (or absent) or `inactive`.
Both apps read and write that field, so the flag is the same on desktop and web
without a local file of participant ids. The write does not seed other embedded
defaults, does not change `SurveysScheduled`, and does not call the distribution
delete API. Eligibility ignores `QsMonitor`. **Active only** is a checkbox in
memory; the server still returns inactive rows.

## Desktop retention

Nothing this feature creates is written to disk.

- Acquisition reads only mailing-list contacts and distribution records in memory; no
  response export files or survey answers are fetched.
- The command returns aggregate counts, per-prompt schedule/status metadata
  (`sendLocal`, `method`, `status`), and the display name and external reference
  Contacts already shows. It does not return answers, emails, phones, or response ids.
- The webview holds the report in component state. It is cleared when the account
  or survey profile changes and when the screen is left. It is not put in
  `localStorage`, `sessionStorage`, IndexedDB, or the lookup cache. The only
  `localStorage` keys in the desktop shell are `qualsched.lastSeenVersion` and
  `qualsched.hidePhi` (a boolean UI preference).
- Tauri has no HTTP cache of Qualtrics calls: the webview does not call Qualtrics.
  `reqwest` is not configured with a disk cache.
- Config remains `config.json` in the OS app-config directory (accounts, survey
  profiles, sender addresses). API tokens stay in the OS keychain. This feature
  does not rewrite that file and does not delete tokens.
- No temp file, download path, or log line is added for acquisition.

### Preexisting risks (not introduced here)

- Contacts and Distributions already return names, phones, and emails to the
  webview for the signed-in researcher. Those responses are not written by this
  feature, but they are in process memory while those screens are open.
- The Qualtrics JSON client, on errors, can include up to 300 characters of the
  error body in the message shown to the researcher.
- A user-chosen **Export Config** writes the survey profile YAML (settings and the
  researcher's sender address), not participant rows.
- `LogData` on the Qualtrics contact can gain one entry `{action: qs_monitor}` when
  the flag is toggled. That lives in Qualtrics, not on the computer.

## Web retention

- The browser calls `/api/.../acquisition` (which starts/polls an in-process worker)
  when the researcher clicks **Load** or **Refresh**. The Qualtrics token stays on
  the server. Another researcher's account id returns 404 and does not call Qualtrics.
- Acquisition does not download response exports or write temp files to disk.
- The JSON response is the same aggregate the desktop command returns. FastAPI
  models forbid extra fields (`extra="forbid"`). `Cache-Control: no-store` is set,
  and the browser fetch uses `cache: "no-store"`.
- MariaDB is unchanged: `users`, `qualtrics_accounts`, `survey_profiles` only.
  Tokens stay Fernet ciphertext. There is still no contacts table.
- The status write is a Qualtrics contact update of `QsMonitor` only.

## Tests

Desktop: `cargo test --lib acquisition` (distribution-stats counting, prompt status
classification, missing stats, mailing-list filtering, removed contacts vs unowned
invitations, DST/timezone handling, clamped window, `QsMonitor` not mutating eligibility).

Web: `pytest tests/test_acquisition.py` (the same rules, plus auth isolation, no
external requests opened by opening the screen alone, status round-trip not deleting
invitations, and `open()` not called during `load_report`).

UI: `ui/lib/acquisition-view.test.ts` (Mon–Sun weekday headers, `isoWeekday` / date
formatters, stacked weekly `groupByWeeks` padding and gap omission, study tail-trimming,
`promptStatusLabel` & `dayDetail`, labels for `0/n` vs `none` vs `future` vs `nonStudy` vs
`unknown`, active-only filter without mutating the list, no storage APIs in the module).
