# Changelog

## Unreleased

- New `src/compare_libraries.py`: choose an Apple Music XML and a purchased-music XML, then write a multi-column Excel (.xlsx) workbook of Apple Music tracks that are not confidently in the purchased library (title, artist, album, year, duration, iTunes link when the XML has one, status, closest purchased track, reason).

- New `src/reconcile_libraries.py`: compares an Apple Music XML, a purchased-music XML and a downloaded-music folder. Writes a reviewable plan of downloaded files that duplicate purchased tracks (REMOVE CANDIDATE only when the purchased file exists unchanged on this computer), an album summary, and the Apple Music tracks missing from both libraries. Read-only; nothing is deleted.
- New `src/check_mp3_integrity.py`: read-only MP3 damage report (cut-out chunks, truncated files, files shorter than their own header, optional FFmpeg decode errors and a duration cross-check against an iTunes/Apple Music XML). `ask_folders` moved to `compare_libraries.py`.
- Matching reads text that was saved as Windows-1251 Cyrillic but displayed as Latin-1 (`Ñòîï!` for `Стоп!`) via `normalization.repair_mojibake`, and compares Cyrillic artist names with Apple Music's Latin spellings via `transliterate`. Both affect comparison fields only; original tags and XML values are never changed.
- `src/compare_libraries.py` now takes an Apple Music XML and an offline-library XML (`--offline`, `--purchased` still accepted), uses the tiered matcher, ignores cloud-only and vanished entries, adds `--duration-seconds`, an `Offline File` column and the default output `Apple_Music_Missing_From_Offline.xlsx`.
- New `src/track_matching.py`: tiered Strict/Likely/Possible matching on title, artist and duration that ignores the album and tolerates remaster/explicit/single-version suffixes, artist spelling differences, duration drift and untagged files named `Artist - Title`. `reconcile_libraries.py` uses it, adds `--duration-seconds`, a `LIKELY DUPLICATE` review label and per-folder album evidence. Only Strict matches can be `REMOVE CANDIDATE`.
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
