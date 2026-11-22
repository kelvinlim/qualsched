# Acquisition heatmap

Both desktop and web QualSched share the Acquisition screen in `ui/`. It shows one
row per mailing-list participant, a block per local day, and a completed/expected
count. The block's number is completed surveys. The fraction beside the row is the
sum for the days on screen (last 7 local days, or the study window). **To date**
sums only prompts whose send time has already passed.

Inactive is a display flag. It does not cancel invitations, delete responses, or
change scheduler eligibility.

## What is counted

**Completed** means a Qualtrics response that is finished (`finished` 1/true) and
whose status is a real response:

| Status | Meaning | Counted |
| --- | --- | --- |
| 0 | IP Address (normal) | yes |
| 4 | Imported | yes |
| 16 | Offline app | yes |
| 1, 17 | Preview | no |
| 2 | Test | no |
| 256 | Synthetic | no |
| 6, 8, 9, 12 | Spam (legacy) | no |
| anything else, or missing | | no |

In-progress responses are not requested (`exportResponsesInProgress` is false; that
flag's true value means "only incomplete"). A partial that Qualtrics has already
closed and marked finished is counted, because that is Qualtrics' finished bit.

**Expected** is an invitation Qualtrics still lists for that participant (email and
SMS list endpoints), placed on the calendar day of its `sendDate` in the
participant's `TimeZone`. An empty `TimeZone` uses the survey profile timezone and
the row says so. An unreadable timezone makes the row unknown rather than guessing.
Prompts with `sendDate` still in the future are drawn as not-yet-due and are not in
the denominator, including later prompts on the current local day. A completion
that names that invitation still counts it as due.

The scheduler is not run again. Random windows and later edits show up only as the
send time Qualtrics stored. A cancelled invitation that is no longer listed is not
in the denominator. If `SurveysScheduled` is set but nothing is listed, the expected
count stays at the listed invitations (possibly zero) and the screen says so.

`NumDays` is clamped before any date is allocated. A corrupt value cannot walk
millions of days; the screen keeps at most about a year and says the window was
shortened. A 404 from the SMS invitation list does not hide email invitations.
The screen says the SMS list was missing. Any other SMS error still fails the load.

Days differ on purpose:

- **ratio**, including 0/n — invitations were due and this many were completed
- **future** — invitations exist but none are due yet
- **none** — inside the known study window, nothing was listed
- **non-study** — outside `StartDate` + `NumDays`, and nothing was listed
- **unknown** — the denominator cannot be computed honestly

An invitation outside the study window is still shown. The booked record wins over
`StartDate`.

## How a response is matched

Qualtrics' response export can carry names, email, IP, location, and every answer.
This feature does not use those as join keys.

A completion is applied only when `RecipientID` or `contactId` (also accepted as
`recipientId` / `ContactID`) **exactly** equals that participant's directory
`contactId` (`CID_…`) or mailing-list `contactLookupId` (`CGC_…`). Name, email,
phone, and external data reference are ignored, even if they happen to match.

The create-export call does not send `embeddedDataIds`. That parameter has to
name embedded-data fields that exist on the survey; requesting `RecipientID`
or `Q_DL` when they are not those fields makes Qualtrics return HTTP 400 for
the whole request (`invalid columns`). Recipient id is read from whatever
embedded fields the export actually contains. `questionIds: []` asks for no
answer columns. If Qualtrics rejects a filtered body, the next body drops that
filter. The last body is only `format: json` and `compress: true`. A `GRP_1` response is not one of those body rejections: Qualtrics uses that code when the call reached the wrong datacenter, and the sentence names the host the API user belongs to. The client retries that host once and does not keep the sentence. JSON and
NDJSON exports are not sent `useLabels`, `breakoutSets`, `timeZone`, or the
other parameters the Start Response Export page says are rejected even when
false. Answers, if a broader file is required, are discarded while parsing.

The browser repeats a short request. Qualtrics export progress is asynchronous, and the web proxy stops reading after 60 seconds, so the server runs the export on a background thread in this process and each request only reads that in-memory progress. The page shows a short status line (contacts loaded, which survey is exporting, download, counting) plus the elapsed timer. A new attempt, including switching profile, drops that memory. Desktop polls inside one command and emits the same status lines. A failure says which stage it reached (`start`, `poll`, `download`, `parse`), the HTTP status when the HTTP call itself failed, a Qualtrics machine `errorCode` when that code matches a short token such as `RTE_2`, or the exception type when the failure never left this process. The Qualtrics sentence, column names, exception text, and file bytes are not included.

The first body requests those metadata columns and `questionIds: []`. Names,
email, IP, location, and external reference are not in that list. A broader file,
when the filter is rejected, is read **in memory**, reduced to the completion
fields, and discarded. The screen says when that fallback happened. Answers are
never returned to the UI.

Linking a response to one invitation:

1. Same `responseId` twice counts once.
2. An explicit distribution id, or a `Q_DL` value that is exactly a listed
   distribution id or starts with `{that id}_`, attributes the completion to that
   invitation — including a late completion after the link expired.
3. If the recipient and the distribution id name different participants, the
   response is a conflict and is applied to neither row.
4. With no distribution pointer, the response is applied only when exactly one
   unmatched invitation for that person has already been sent and, if it has an
   expiration, still contains the completion time.
5. If none do, and exactly one unmatched invitation was sent before the completion,
   that late completion is applied. Several candidates are left unmatched.
6. Anything else is not added to a day. The row is marked provisional ("at least")
   when that happens, when any finished response had no recipient id (it could
   belong to anyone), or when a listed invitation could not be tied to a participant.

Anonymous, preview, test, and unmatched responses are counted in the exclusion
totals. They are not silently given to a row.

**Prerequisite.** Qualtrics adds `RecipientID` for invitations sent to directory
contacts, as embedded data on the response. If a survey's export has no such field,
completions stay unmatched. This app will not fall back to name or email. The
screen states that rule whenever counts are not definitive.

`Q_DL` is used only when it identifies one listed distribution. An opaque token
that does not is treated as an unreadable pointer, not as a guess.

## Manual status

`QsMonitor` on the contact's embedded data is `active` (or absent) or `inactive`.
Both apps read and write that field, so the flag is the same on desktop and web
without a local file of participant ids. The write does not seed other embedded
defaults, does not change `SurveysScheduled`, and does not call the distribution
delete API. Eligibility ignores `QsMonitor`. **Active only** is a checkbox in
memory; the server still returns inactive rows.

## Desktop retention

Nothing this feature creates is written to disk.

- Response export bytes are downloaded into a `Vec`, unzipped in memory (stored or
  deflate), reduced to the fields above, then overwritten with zeros before the
  buffer is freed. That overwrite does **not** clear copies the allocator or the
  HTTP stack already made, pages the OS has swapped out, or a crash dump taken
  while the buffer was live. QualSched cannot promise those are gone.
- The command returns aggregate counts plus the display name Contacts already
  shows. It does not return answers, emails, phones, response ids, or raw export
  text. Errors from the export path are a static sentence and an HTTP status, not
  the file body.
- The webview holds the report in component state. It is cleared when the account
  or survey profile changes and when the screen is left. It is not put in
  `localStorage`, `sessionStorage`, IndexedDB, or the lookup cache. The only
  `localStorage` key in the desktop shell is `qualsched.lastSeenVersion`.
- Tauri has no HTTP cache of Qualtrics calls: the webview does not call Qualtrics.
  `reqwest` is not configured with a disk cache.
- Config remains `config.json` in the OS app-config directory (accounts, survey
  profiles, sender addresses). API tokens stay in the OS keychain. This feature
  does not rewrite that file and does not delete tokens.
- No temp file, download path, or log line is added for the export.

### Preexisting risks (not introduced here)

- Contacts and Distributions already return names, phones, and emails to the
  webview for the signed-in researcher. Those responses are not written by this
  feature, but they are in process memory while those screens are open.
- The Qualtrics JSON client, on non-export errors, can include up to 300 characters
  of the error body in the message shown to the researcher. The acquisition export
  path does not. Other screens still can.
- A user-chosen **Export Config** writes the survey profile YAML (settings and the
  researcher's sender address), not participant rows.
- `LogData` on the Qualtrics contact can gain one entry `{action: qs_monitor}` when
  the flag is toggled. That lives in Qualtrics, not on the computer.

## Web retention

- The browser calls `/api/.../acquisition`. The Qualtrics token stays on the server.
  Another researcher's account id returns 404 and does not call Qualtrics.
- The server downloads the export with `get_bytes`, which does not put the body in
  the error text. Parsing uses `BytesIO` / `zipfile` and never extracts to a path.
  Buffers are overwritten after parse. Same OS limit as desktop: swap and crash
  dumps can still contain process memory.
- The JSON response is the same aggregate the desktop command returns. FastAPI
  models forbid extra fields. `Cache-Control: no-store` is set, and the browser
  fetch uses `cache: "no-store"`.
- MariaDB is unchanged: `users`, `qualtrics_accounts`, `survey_profiles` only.
  Tokens stay Fernet ciphertext. There is still no contacts table.
- The status write is a Qualtrics contact update of `QsMonitor` only.

## Tests

Desktop: `cargo test --lib acquisition` (parser wipe, exclusion, exact-id refusal,
dedup/late/current-day, ambiguous overlap, DST, unknown timezone, eligibility
unchanged by `QsMonitor`).

Web: `pytest tests/test_acquisition.py` (the same rules, plus auth isolation, the
status round-trip not deleting invitations, error text that does not echo the
export, and no `open()` during parse or `load_report`).

UI: `ui/lib/acquisition-view.test.ts` (labels for 0/n vs none vs future vs
non-study vs unknown, active-only filter without mutating the list, no storage
APIs in the module).
