# Developer and model handoff

## Start here

Read `README.md`, `IMPLEMENTATION.md`, `docs/CONFIGURATION.md` and `AGENTS.md`. The repository is a portable CLI source project, version 0.2.0. Its objective is conservative offline coverage auditing while never modifying source music. No private user dataset, identity, benchmark path, previous transcript or original specification is needed to continue development.

Entry point: `src/audit.py` (plus the standalone `src/compare_libraries.py` and `src/reconcile_libraries.py`). Dependency declarations: `pyproject.toml`. Reproducibility: `uv.lock`, with a generated pip `requirements.txt`. Python >=3.10. Native FFprobe is required to audit; FFmpeg is required for deep checks and format integration tests.

## Completed behavior

- Explicit interactive XML selection and repeated folder entries ending in `done`/That's all.
- Optional post-match one-by-one REVIEW confirmation with immediately persisted manual overrides.
- Saved private settings, per-run CLI overrides, noninteractive mode and configurable workspace.
- XML parser, read-only inventory, SHA-256 cache, format-specific artwork, stream/decode checks and conservative DRM classification.
- Candidate indexes, recording-version/numeric safety checks, manual overrides and three match states.
- Six-sheet Excel report, metadata-based album/disc audit, four duplicate categories and standalone report validation.
- AppleDouble detection and separate accounting, literal Excel text cells, source-change checks during scanning.
- Standalone `src/compare_libraries.py` (covered by `tests/test_compare_libraries.py`): interactive or `--apple`/`--purchased` XML comparison writing a workspace Excel workbook; no iTunes link exists in standard exports, so that column is filled only from store-URL fields when present.
- Standalone `src/reconcile_libraries.py` (covered by `tests/test_reconcile_libraries.py`, including an FFmpeg end-to-end run): downloaded-folder duplicates of purchased tracks as a reviewable plan, plus Apple Music tracks missing from both libraries. Matching lives in `src/track_matching.py` (tests in `tests/test_track_matching.py`); the strict audit matcher in `matcher.py` is unchanged and is only the STRICT tier. Deletion is deliberately not implemented; adding it would require an explicit product decision and a change to the read-only invariant in `AGENTS.md`.
- Public-file allowlist exporter, no personal defaults, synthetic tests, platform CI, documentation and generic project metadata.

## Non-negotiable invariants

Never call tag `.save()`/`.delete()` methods on input music, write media, alter artwork, reorganize roots, or delete duplicates. Keep application writes in a validated workspace outside music roots. Never bypass a version/DRM/eligibility gate just to increase green counts. Original XML properties must remain alongside normalized values. Missing manual targets must stay REVIEW without substitution. Do not publish config, cache, logs, reports, audio, XML, bytecode or personal commit history.

## Validation commands

```text
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python src/audit.py --setup
uv run --locked python src/audit.py --inspect
uv run --locked python src/audit.py
uv run --locked python src/validate_report.py
python scripts/prepare_release.py
```

For private data outside the checkout, pass the same `--workspace` to setup/audit/validation. Public tests run independently with temporary synthetic data. `test_cli.py` exercises setup, multiple roots, a complete workbook, replacing the XML, a zero-rescan cached rerun and validation. `test_scanner.py` covers supported formats, encrypted fixtures and source immutability. `test_config.py` exercises path and settings safety. `test_audit.py` covers matcher/album/duplicate/cache/Excel behavior. `test_release.py` covers export exclusions and privacy checks.

Windows tests are executed in the development environment. Native macOS/Linux evidence must come from the included GitHub Actions jobs; do not claim those jobs ran before they actually run. Some local environments cannot create symlinks; the symlink test explicitly skips there. FFmpeg integration tests skip when tools are absent, so inspect skip counts rather than interpreting any green test command as full media validation.

## Known limitations and worthwhile next work

1. **Metadata cannot prove recording identity.** No acoustic fingerprints or external track-list lookup are used. Add an optional REVIEW resolver behind an interface, with fixtures for live/remix/clean/explicit distinctions. Never make fingerprint tools mandatory without a product decision.
2. **Candidate recall is conservative.** Translated/missing titles, badly tagged artist fields and unusual collaboration names can be missed or over-split. Add bounded candidate indexes and regressions; avoid all-tracks-by-all-files fuzzy scoring.
3. **Album editions can merge.** Identical album/artist tags group together. Missing disc numbers assume disc 1, and incomplete disc-total tags remain uncertain. A separate edition identifier would need careful migration.
4. **Cache policy is basic.** Path/size/time cannot detect preserved-stat edits. Tool versions, timeout policy and some future options are not part of cache keys. Bump/migrate `cache.VERSION` when metadata semantics change; a targeted refresh/clear interface could reduce unnecessary full rehashes. Deep-mode transitions currently rescan entries without completed deep tests, including some non-audio entries.
5. **Cancellation could improve.** Thread-pool work is submitted eagerly. Interrupts may wait for in-flight work; hashing has no independent filesystem timeout. Consider bounded submission and cooperative cancellation while preserving checkpoints.
6. **Records are dictionaries.** Field renames can break consumers. Typed records/schemas would improve maintainability, but must preserve exported data semantics and cache compatibility.
7. **Excel has limits.** Long strings are capped; invalid control characters are removed; large inventories use memory proportional to workbook cells. Consider an optional complete JSON/CSV artifact and streaming export while preserving formatting and literal-string safety.
8. **Portability requires evidence.** `pathlib`, subprocess argument lists, guarded Windows flags and `-f null -` remove major OS dependencies. CI must still exercise real platform codecs, path Unicode/case behavior and file links.
9. **Publication scanning is defense in depth.** An allowlist protects runtime data, but cannot prove arbitrary future source text anonymous. Expand the list intentionally and review all newly exported documents and files.

10. **Locked workbook fallback.** `excel_report.write_report` saves to a temporary sibling and atomically replaces the configured output. If replacement is denied (for example, an open Excel workbook on Windows), it preserves the newly generated workbook as `<stem>_new.xlsx` and returns successfully. The coordinator currently reports this path; a future structured run-result object could expose it to scripts.

11. **Interactive review decisions.** `review.py` is deliberately separate from scoring. It offers the selected candidate followed by up to three alternatives, saves each accepted Persistent-ID mapping immediately, and changes only the in-memory result row to MATCHED/MANUAL MATCH. Rejections and quit are safe: no source file changes and no automatic MISSING conversion. Keep the `--non-interactive` skip behavior for automation.

## Updating dependencies and publishing changes

Edit `pyproject.toml`, run `uv lock`, then regenerate `requirements.txt` with `uv export --format requirements-txt --no-hashes --no-header --output-file requirements.txt`. Run the complete tests with the lock. Keep behavior docs, examples, CLI help, test coverage and `scripts/prepare_release.py`'s allowlist synchronized. Record user-visible changes in `CHANGELOG.md` without private library examples. Use the clean bundle for a new public repository; review native CI before declaring a release verified.
