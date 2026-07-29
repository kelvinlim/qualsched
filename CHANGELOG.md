# Changelog

All notable changes to QualSched are documented in this file.

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
