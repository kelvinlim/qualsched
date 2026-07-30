# Changelog

All notable changes to QualSched are documented in this file.

## [Unreleased]

### Added
- Import can add a survey profile to an account you already have, instead of
  always creating a new one. That account's API token, data center, contact
  directory and message library are left untouched, and the wizard warns when the
  file disagrees with the account or duplicates a profile already in it.
- Imported profiles are named after the file they came from rather than all
  arriving as "Imported project".
- A search box on Contacts and Distributions, filtering by name, phone number or
  email. Punctuation in phone numbers is ignored on both sides, so `612-555-1234`
  and `6125551234` find the same person.
- Distributions shows each recipient's phone and email.
- A breadcrumb at the top of every screen showing the account and survey profile in
  use, each linking to its screen. It replaces the context block that sat at the
  bottom of the sidebar.

### Fixed
- Bulk actions no longer touch rows a filter is hiding. Selecting every row, then
  ticking "Not yet sent only", previously cancelled the hidden ones too while the
  button and the confirmation dialog both reported a different number.

## [0.1.5] - 2026-07-30

### Changed
- Survey copies are no longer created or sent through. The 0.1.4 workaround for
  Qualtrics' one-invitation-a-day limit did not work in the field, so every slot
  of the day is booked against the profile's own survey again.
- A plan with more than one invitation a day now carries a warning on the
  Schedule screen and in the send confirmation, stating what Qualtrics will
  actually deliver.

### Fixed
- A profile with more time slots a day than it had survey copies scheduled only
  one invitation a day under 0.1.4; the whole plan is booked again.
- Sending with no survey selected POSTed an empty survey id instead of stopping.
- Distribution listing survives a survey copy the user has deleted in Qualtrics.
  One such copy previously emptied the whole Distributions screen and broke
  participant removal, which cancels pending invitations first.

### Notes for upgraders
- Copies created by 0.1.4 stay recorded so their pending invitations remain
  cancellable, and appear on the profile screen as "Leftover survey copies" with
  a **Forget these copies** button. Cancel anything still scheduled against them
  before deleting those surveys in Qualtrics.

## [0.1.4] - 2026-07-29

### Added
- Survey copies: a profile can create clones of its survey on demand from the
  profile screen, named after the original with `-c` suffixes.

### Fixed
- Multiple daily administrations now actually deliver. Qualtrics silently drops
  every invitation after the first for the same survey to the same contact each
  day, so slot *k* of each day now sends through survey copy *k*. A slot with no
  survey copy left is skipped with a reason rather than folded onto one already
  used.
- Distribution listing and cancellation span the survey copies, since a copy's
  invitation cannot be cancelled against the original's survey id.

## [0.1.3] - 2026-07-29

### Added
- User guide (`docs/USER_GUIDE.md`).
- macOS builds are signed and notarized in CI.

### Fixed
- The profile's time zone setting is now actually applied.

## [0.1.2] - 2026-07-29

### Added
- Apple Silicon macOS release built alongside the Windows installer in CI.
- Contact columns are sortable, with phone and email split into separate
  columns.

## [0.1.1] - 2026-07-29

### Added
- Local send times shown alongside scheduled distributions.

### Fixed
- Qualtrics contact writes no longer send fields the API rejects.

## [0.1.0] - 2026-07-29

### Added
- Initial release: QualSched desktop app for scheduling Qualtrics survey
  invitations by email or SMS, ported from the `qualtrics_util` Python CLI.
- Per-participant scheduling via Qualtrics embedded data, preview/execute
  contract, DST- and midnight-safe time windows, and YAML study-config import.
