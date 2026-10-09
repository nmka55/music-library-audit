# Changelog

## Unreleased

- New `src/compare_libraries.py`: choose an Apple Music XML and a purchased-music XML, then write a multi-column Excel (.xlsx) workbook of Apple Music tracks that are not confidently in the purchased library (title, artist, album, year, duration, iTunes link when the XML has one, status, closest purchased track, reason).

- New `src/reconcile_libraries.py`: compares an Apple Music XML, a purchased-music XML and a downloaded-music folder. Writes a reviewable plan of downloaded files that duplicate purchased tracks (REMOVE CANDIDATE only when the purchased file exists unchanged on this computer), an album summary, and the Apple Music tracks missing from both libraries. Read-only; nothing is deleted.
- The scanner skips SHA-256 when the internal `_skip_hash` setting is present, so the reconcile script does not read every file in full.

## 0.2.0

- Portable workspace-relative configuration for Windows, macOS and Linux.
- Interactive XML selection and any number of offline roots, ending with `done`/That's all.
- Explicit CLI paths, persistent settings, noninteractive mode and validation workspace options.
- Synthetic end-to-end setup, updated-XML and cache-reuse tests.
- Anonymous public templates, dependency lock, clean allowlist export and native CI matrix.
- User instructions, algorithm/source reference, privacy guide and developer/model handoff.
- Optional post-match interactive review: confirm candidates one by one, save confirmed manual overrides, or leave uncertain entries as REVIEW.

## 0.1.0

- Initial read-only inventory, cache, conservative matching, manual overrides, artwork/integrity auditing, duplicate/album checks and six-sheet Excel report.
