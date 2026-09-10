# Configuration reference

Settings are local to a workspace. Read [README.md](../README.md) for setup and reruns. Neither `config.json` nor `manual_matches.json` belongs in a public repository.

Precedence is built-in defaults → selected JSON file → explicit `--xml`/`--music-root` options. CLI paths are temporary unless `--save-config` is present. Setup saves immediately but does not scan when explicitly invoked with `--setup`.

| Setting | Default | Meaning |
|---|---|---|
| `apple_music_xml` | `input/Library.xml` | Export to parse on every run |
| `offline_music_roots` | `[]` | One or more folders; setup fills this list |
| `output_excel` | `output/Music_Library_Audit.xlsx` | Final workbook; must use `.xlsx` in a workspace subdirectory |
| `cache_directory` | `cache` | Workspace subdirectory for SQLite |
| `manual_matches_file` | `manual_matches.json` | Optional private override object |
| `duration_tolerance_seconds` | `3` | Automatic-match duration gate, allowed range 0–5 |
| `deep_integrity_check` | `false` | Full FFmpeg decode instead of probe-only testing |
| `matched_threshold` | `90` | Total score needed in addition to all safety gates |
| `review_threshold` | `70` | Distinguishes normal review evidence from weaker meaningful candidates |
| `workers` | `4` | Concurrent scanning threads; integer 1–32 |
| `probe_timeout_seconds` | `45` | FFprobe subprocess time limit |
| `deep_timeout_seconds` | `600` | FFmpeg decode time limit per file |

Thresholds must satisfy `0 <= review_threshold < matched_threshold <= 100`. Booleans must be JSON `true`/`false`, not quoted strings. Unknown settings are rejected to catch spelling mistakes. Raising duration tolerance does not disable title, artist, version or eligibility gates. The excellent-duration tier is at most one second; the explicit tolerance still controls automatic safety even if configured below one second.

Paths are native to the operating system. `pathlib` resolves them, including `~`; relative paths use the workspace. A path valid on one OS may not exist on another. In JSON on Windows, either escape backslashes or use forward slashes. The wizard avoids manual JSON escaping. Paths typed into CLI arguments should be quoted if they contain spaces.

The default workspace is the project directory. `--config "profile/config.json"` uses that file's parent unless `--workspace` is also supplied. The settings file, overrides, output and cache must stay under the resulting workspace. Output/cache cannot contain the input XML. Resolved write destinations cannot fall inside a music root.

Missing music drives stop the audit rather than silently declaring the collection missing. To intentionally remove a root, run setup and enter the remaining roots. Existing configuration with invalid paths is not silently overwritten. Use corrected CLI arguments or edit the private JSON before rerunning.

Example public template:

```json
{
  "apple_music_xml": "input/Library.xml",
  "offline_music_roots": ["music-one", "music-two"],
  "output_excel": "output/Music_Library_Audit.xlsx",
  "cache_directory": "cache",
  "manual_matches_file": "manual_matches.json",
  "deep_integrity_check": false
}
```

Omitted keys use defaults. These folder names are illustrative, not paths shipped for any individual.

Manual overrides map the exact Persistent ID string to a path. Case matters for IDs. Relative override paths use the workspace; absolute paths can point to selected external roots. The target must exist in the current scanned inventory. Moving files can require editing overrides; the program does not silently follow missing targets by title.

The log, preliminary workbook and `validation.json` use the final workbook's parent directory. A custom `--workspace` must also be supplied to `src/validate_report.py`. If an audit used unsaved per-run input overrides, save that configuration before using the standalone validator so it compares the same inputs.
