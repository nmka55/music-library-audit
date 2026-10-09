# Implementation and design reference

This document describes the code as shipped. It contains no private input paths, library statistics, purchase identifiers, account names, or real-library samples. Start with [README.md](README.md) for execution; use [DEVELOPER_HANDOFF.md](docs/DEVELOPER_HANDOFF.md) before extending the implementation.

## Scope and boundaries

This is a command-line source project, not a web service, Apple integration, GUI, or installed Python console package. `python src/audit.py` is the entry point. `uv` is an optional dependency runner. Python 3.10+ and installed FFmpeg/FFprobe are required for the complete test suite.

The XML and audio are read-only inputs. Runtime writes are constrained to a selected workspace. Configuration resolves relative paths against that workspace and rejects output/cache/settings destinations under a music root, including resolved symlink escapes. The application passes argument lists to subprocesses, without a shell, and FFmpeg decodes to `-f null -`. Windows-only process-window suppression uses a guarded constant and evaluates to zero on other systems. No Windows drive letter, username, `NUL` output target, shell command or account key is built into runtime logic.

This boundary is application policy, not an OS sandbox. Do not concurrently replace directories with symlinks while an audit runs. Tests may create temporary synthetic media in the OS temporary directory; they do not operate on a user's source collection.

## Repository and workspace structure

```text
project/
  README.md, IMPLEMENTATION.md, AGENTS.md
  CONTRIBUTING.md, SECURITY.md, CHANGELOG.md, LICENSE
  pyproject.toml, uv.lock, requirements.txt
  config.example.json, manual_matches.example.json
  src/                         application modules
  tests/                       synthetic unit and integration tests
  scripts/prepare_release.py   public-file allowlist and clean exporter
  docs/                        configuration, FAQ, publication, handoff
  .github/workflows/tests.yml  native OS/Python test matrix
  config.json                  PRIVATE, generated/saved locally
  manual_matches.json          PRIVATE, optional user decisions
  input/                       PRIVATE XML exports
  cache/                       PRIVATE inventory.sqlite3
  output/                      PRIVATE reports, logs and validation.json
  dist/                        generated publication bundles
```

The last five runtime locations are absent from a fresh publication bundle until needed. An optional `--workspace` can put them outside the source tree. Public JSON examples never contain actual machine paths.

## Every source module

| File | Responsibility and reason for separation |
|---|---|
| `src/audit.py` | CLI parser and pipeline coordinator. Applies options, invokes setup, checks inputs/tools, scans, matches and writes reports. It keeps workflow decisions out of matching/scanning internals. |
| `src/config.py` | Public defaults, workspace-relative path resolution, settings validation, safe writes, and manual-override loading. `load` adds internal `_workspace` and `_config_path`; `save` omits internal keys. |
| `src/setup_wizard.py` | Asks for one XML and repeated folders until `done`/That's all. Validates selections, rejects duplicates, saves settings. Injected `ask`/`tell` functions make prompts testable. |
| `src/apple_music_xml.py` | Reads the plist/XML with `plistlib`, preserves track dictionaries and prints actual field coverage. Optional properties are not assumed present. |
| `src/audio_scanner.py` | Discovers extensions; reads tags and artwork across formats; invokes integrity helpers; classifies DRM/source; hashes read-only bytes; manages concurrent scanning and cache checkpoints. AppleDouble sidecars are not music. |
| `src/integrity.py` | Runs FFprobe/FFmpeg with timeouts and captures failures. Separates readable stream probing from optional full decoding; recognized image-only probe errors become artwork warnings. |
| `src/cache.py` | SQLite schema and reuse rules for inventory records. Keeps expensive media reads separate from cheap reruns. Main-thread DB access avoids sharing a SQLite connection across worker threads. |
| `src/normalization.py` | Builds comparison-only titles, artists, credited sets, albums, version descriptors and duration-in-seconds. Original XML values remain alongside them. |
| `src/matcher.py` | Candidate indexes, component scores, automatic safety gates, manual overrides and detailed match rows. Recording evidence is separate from metadata quality. |
| `src/review.py` | Optional post-match interactive review. Presents original track details and candidates, saves confirmed Persistent-ID overrides immediately, and leaves rejected/uncertain rows REVIEW. |
| `src/compare_libraries.py` | Standalone XML-to-XML comparison: Apple Music tracks with no offline copy. Keeps only offline-library entries that are files (`real_files`: drops cloud-only entries, and entries whose file is gone when the files are visible on this computer), wraps them as file-like rows (`as_file_rows`) and searches them with `track_matching.LooseIndex`. Strict and Likely matches count as present, Possible is reported for review, anything else is MISSING. Track ID is never used. Writes an Excel workbook inside the workspace with literal text cells. Also owns `location_to_path` and the XML helpers shared with `reconcile_libraries.py`. It does not use the scanner, cache or audit report. |
| `src/track_matching.py` | Recall-oriented matcher used by `reconcile_libraries.py`. Ignores the album. Builds comparison keys from titles with brackets, feature credits, track numbers and `- version` tails removed, and from filenames (`Artist - Title`). `LooseIndex` retrieves candidates by title key, artist credit and the two rarest title words. `compare` assigns STRICT (the audit matcher's `score` gates pass), LIKELY (title similarity >= 94, artist >= 90 from tags, `Artist - Title` filename or folder name, same kind of recording, duration within the loose window, readable file) or POSSIBLE (title >= 85 and artist >= 60). Live/remix/acoustic/demo/instrumental/karaoke/extended must agree on both sides; differing digits cap the title score. |
| `src/reconcile_libraries.py` | Three-way reconciliation of two XML exports and a downloaded-music folder. Scans the folder with `audio_scanner` using a separate cache and `_skip_hash`, searches it for each purchased and Apple Music track with `track_matching.LooseIndex` (purchased XML tracks are wrapped as file-like rows so one engine searches both sources), and writes three Excel workbooks. A copy is only a REMOVE CANDIDATE if the match is STRICT and the purchased track's `Location` is an existing file whose size equals the XML `Size`; a LIKELY match becomes a review label only; purchased Location paths are excluded from the candidate pool. An Apple Music track is MISSING EVERYWHERE only if neither source has a STRICT or LIKELY match. It performs no deletion, move or tag write. |
| `src/duplicate_detector.py` | Exact SHA-256 groups and conservative metadata-based duplicate pairs. Different-album copies are informational; no deletion. |
| `src/album_audit.py` | Groups album/disc metadata across roots and reports track/disc gaps, repeated numbers, inconsistent counts and unknowns. No external discography is consulted. |
| `src/dashboard.py` | Aggregates match/quality/duplicate/album metrics. Counts AppleDouble sidecars separately so they cannot inflate audio problems. |
| `src/excel_report.py` | Creates sheets, literal text cells, real fills, filters, freeze panes and local URI links. Saves through a temporary workbook and replaces the destination after a successful save. |
| `src/validate_report.py` | Reopens a completed report; checks original fields, row/count consistency, MATCHED invariants, basic formatting, formula absence and current source stats against the cache. Writes private `validation.json`. |

These modules are intentionally imported from the `src` script directory. This release uses `tool.uv.package = false`; `pip install .` and a `music-audit` console command are not provided. A future packaging refactor must update imports, entry points, test paths and publication allowlists together.

## Pipeline and records

1. Load defaults, then local JSON, then explicit CLI overrides. A supplied config file chooses its parent workspace unless `--workspace` overrides it. Explicit XML/root arguments are per-run unless `--save-config` is set. The wizard always saves and `--setup` exits without scanning.
2. Confirm the XML is a file and each root is a directory. Require FFprobe; require FFmpeg when deep checking is enabled. Inspect mode reports availability and discovered counts without hashing.
3. Parse `Tracks` from the plist. Track dictionaries preserve original property names such as `Name`, `Total Time`, `Persistent ID`, `Release Date` and any additional fields.
4. Walk all roots without following file or directory links. Deduplicate identical path entries using OS path semantics. Overlapping roots therefore count a path once; the first encountered root supplies provenance. Hardlinks and different path aliases are not collapsed by inode; duplicate hashing can still identify identical content.
5. For each file, consult SQLite by path, byte size, nanosecond mtime and schema version. Otherwise read metadata and stream facts, artwork and hash. A per-file failure creates an error row rather than aborting all files. Commit cache progress every 100 new rows.
6. Write the preliminary inventories. Add comparison-only fields, match tracks, audit albums/duplicates and write the six-sheet final workbook.

In interactive mode, the coordinator then offers a post-match review. `review.py` processes only rows currently marked REVIEW. Each retained candidate is offered in order; yes writes a manual override atomically and changes that result to MANUAL MATCH/MATCHED, no advances, and quit returns immediately. An entry with no accepted candidate remains REVIEW. The final workbook is written after these decisions, so its dashboard and match rows reflect confirmations. Non-interactive mode skips this offer; `--review` forces it and `--no-review` suppresses the default offer.

Inventory and result records are plain dictionaries with report-friendly field names. Do not silently rename keys consumed by the matcher, dashboard, exporter or validator. Typical inventory fields are `Full Path`, `Library Root`, `Duration`, `Metadata Issues`, `FFprobe OK`, `DRM Status`, `Archive Eligible` and `SHA-256`.

## Metadata, artwork and eligibility

Mutagen reads format-specific ID3/MP4/Vorbis/ASF tags. Copy tag mappings into an ordinary dictionary before checking cross-format keys; some native mappings reject foreign key syntax. Artist values may contain multiple credits. Track/disc totals may be embedded in `n/total` text or MP4 integer pairs. Do not mark a single-disc album broken solely for lacking a disc-number tag.

Artwork comes from ID3 APIC, MP4 `covr`, FLAC pictures, Vorbis picture blocks or ASF pictures. PNG/JPEG dimensions are decoded when practical. Presence/count and dimensions are separate: unrecognized dimensions do not imply absent artwork. A mislabeled embedded image can produce a quality warning while audio remains readable.

FFprobe supplies actual audio-stream codec, duration, bitrate, sample rate and channels. A fast PASS is not a full decode. Deep mode runs FFmpeg to a discarded null output with an audio-stream map and reports PASS/FAIL. Subprocess failures/timeouts are recorded.

Archive eligibility requires detected DRM-free status, readable metadata/audio inspection, and no failed deep check. M4P, encrypted MP4 sample entries and detectable ASF/stream encryption are ineligible. M4A alone is not purchase evidence. Purchase-related tags support only a **Likely iTunes Store Purchase** label, not a provenance/legal guarantee. No DRM removal occurs.

## Normalization and matching, precisely

Normalization case-folds Unicode, decomposes useful diacritics, normalizes punctuation/spacing and extracts featured credits from title annotations and artist separators. Numeric title qualifiers and version descriptors remain meaningful. A stripped base title is used only to judge whether a weak candidate deserves review.

Version comparison preserves descriptors such as live, acoustic, demo, remix, remaster year, radio edit, extended mix, instrumental, karaoke, mono, stereo, edit and version. Selected album-level markers can also force review. Album-level generic `version`/`edit` and remaster labels are excluded from those extra album-marker checks; original album text still contributes to scoring. Untagged live/clean/explicit edits cannot be reliably distinguished without stronger evidence.

The candidate index maps exact normalized titles, title tokens, credited artists and five-second duration buckets to file IDs. Exact title hits are retained; artist/duration intersections and title-token intersections add plausible candidates. Fuzzy scoring is applied to this shortlist rather than the whole Cartesian product. Unusual missing/translated metadata can still produce false negatives.

The score is:

```text
0.46 * title_score
+ 0.32 * artist_score
+ 0.17 * duration_score
+ 0.02 * album_score
+ 1 point for album-artist agreement
+ 1 point for track/disc agreement
+ 1 point for year agreement
```

All component scores are on 0–100 scales. Artist score takes the stronger of credited-set overlap and normalized artist-string similarity. Duration scores are 100 at at most one second difference, 90 within configured tolerance (default three seconds), 45 within five seconds, otherwise zero. Album/year/track fields are supporting evidence, not requirements.

Automatic MATCHED requires the configured total threshold (default 90), title and artist scores each at least 97, known duration within tolerance, compatible version/numeric qualifiers, an actual title tag, archive eligibility, and no Apple video flag. Failure of any gate caps confidence below the MATCHED threshold. A meaningful weaker candidate becomes REVIEW; no meaningful candidate becomes MISSING. Scores are not calibrated probabilities.

Meaningful review evidence normally requires base-title similarity at least 75 and artist similarity at least 65, plus compatible/unknown duration or an especially strong base title. Exact-looking titles without an artist may be retained with close duration. This intentionally allows low-score REVIEW evidence instead of pretending every low score means absence.

Candidates that safely satisfy MATCHED rank ahead of unsafe candidates; then score, eligibility and metadata quality break ties. All retained candidates are recorded. REVIEW alternatives include its leading suggestion; MATCHED alternatives start after the selected file.

Manual overrides use Persistent ID, or `track:<Track ID>` when missing. A present indexed file gives manual identity confidence 100. Eligibility still controls whether it can satisfy the archive requirement. A missing/out-of-collection override target remains REVIEW without choosing another file.

## SHA-256, caching and integrity are different tools

SHA-256 via standard-library `hashlib` groups exact file bytes. It is not encryption or an acoustic fingerprint, and uses no secret. Metadata/artwork changes produce different hashes. Codec changes produce different hashes. Neither a standalone digest nor FFprobe proves correct provenance or perfect sound.

SQLite stores `path`, `size`, `mtime`, `version`, and a JSON inventory record. Unchanged parse failures may be reused; timed-out probes, detected in-scan file changes and specified legacy reader cases are retried. Enabling deep checks invalidates entries without completed deep results. Paths moved to a new OS or drive are new keys. Changes deliberately preserving both size and mtime are invisible to the cache. Deleting a source does not delete its old cache row; only discovered paths feed the report.

The scanner reads hash input in bounded chunks. Hashing is I/O-heavy, especially on USB hard drives. The worker count defaults to four; more threads are not always faster. Candidate matching usually costs much less than the first complete file read.

## Duplicate and album semantics

Exact duplicate groups share SHA-256. Possible same-album pairs also compare artist credits, title, duration, version and track/disc. Same-recording/different-album pairs are metadata-based information, not errors. Unknown duration or conflicting evidence can become possible-duplicate REVIEW. AppleDouble sidecars are excluded from all these categories.

Album keys use normalized album artist (or artist fallback) plus album, then disc. Missing identifying tags fall back to parent-directory groups with UNKNOWN status. Missing disc numbers are treated as disc 1; available disc totals expose possible gaps. Expected track totals, repeated numbers, holes and inconsistent values are all recorded. No claim of authoritative completeness is made.

## Excel, validation and privacy

Imported text is explicitly written as literal cells so `=...` metadata cannot become a formula. Excel cannot represent every arbitrary input string: illegal control characters are removed and cell strings are capped at Excel's 32,767-character limit. The XML source itself remains unchanged. File links encode native paths as file URIs; they work only where that path exists and the spreadsheet viewer permits local links.

Validation compares scalar XML fields and counts, tests automatic-match invariants, checks formatting metadata and detects source stat changes after scanning. It is not a full byte-identity or perceptual validation of an entire real library. Runtime reports/cache/logs contain personal paths and library information by design; keep them private. Publication uses a public-file allowlist and a deterministic ZIP with normalized metadata. See [PUBLISHING.md](docs/PUBLISHING.md).

## Development history and next steps

The initial pipeline was developed in the order input inspection → inventory/cache → preliminary report → normalization/matching → overrides → duplicates/albums → final report. The portable release adds interactive setup, relative workspace paths, synthetic tests, a dependency lock, privacy-safe export and native CI configuration. No original personal baseline data is shipped.

Known next steps and constraints are listed in [DEVELOPER_HANDOFF.md](docs/DEVELOPER_HANDOFF.md), including improved cancellation, formal record schemas, candidate recall, optional acoustic fingerprints, cache policy versioning and cross-platform CI evidence. Changes must preserve read-only inputs and conservative match gates.
