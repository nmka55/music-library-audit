# How and why

## What does this program actually do?

It compares metadata from a library export with metadata and stream facts from local files. It records evidence and uncertainty in Excel. It does not download tracks, fix files, remove duplicates, change tags, reorganize folders, or access a music account. Use the Match Results sheet first, then inspect REVIEW explanations and quality warnings.

## How do I rerun after updating the XML?

Put the new export at the saved path, reconnect the music drives, close the workbook, and rerun `uv run --locked python src/audit.py`. No setup is needed if paths are unchanged. Use `--xml` for a different export or `--setup` for a different saved folder list. The XML is reparsed every time; unchanged audio scans are cached.

## Why not compare filenames?

Filenames are frequently shortened, numbered or inconsistent. A song may appear on multiple albums or have collaborators stored in different fields. Title, credited artists and duration provide stronger evidence. Filename fallback remains review-only, and album/year/track metadata can support a decision without being mandatory.

## Why REVIEW instead of calling a near match good?

A studio, live, acoustic, remix or remastered track can look similar. A false claim of offline coverage is more costly than a review request. The score and the automatic safety gates are separate; a score near 100 is not permission to ignore a version or eligibility conflict. The score is not a statistical confidence probability.

## What do SHA-256 and cryptographic libraries have to do with music?

Only exact bytes. SHA-256 converts the entire file into a 256-bit digest, commonly displayed as 64 hexadecimal characters. Matching digests are strong practical evidence of identical files, even under different filenames. The audit uses Python's built-in `hashlib`; it does not need a separate `cryptography` library or any secret key.

It is not encryption: nothing is encrypted or decrypted and no password is used. It is not an acoustic fingerprint: an MP3 and a FLAC of the same song differ, as do files with different artwork. A digest calculated from a damaged file is still a valid digest of that damaged file; a trusted earlier digest would be needed to use hashing as a change/integrity reference. FFprobe and optional FFmpeg decoding examine readability separately.

Synthetic encrypted-media tests generate throwaway random keys solely to confirm encrypted M4A is rejected. Those are not account credentials, are not embedded in published code, and are not used by the real audit.

## Why was uv introduced?

It makes dependency setup and repeatable execution convenient. It creates/uses an isolated `.venv`, resolves project dependencies and runs Python with them. It can also run temporary development tools. The application does not invoke uv internally. During development, uv may be used for tooling such as reading a specification; those tools are not runtime audit dependencies.

`uv sync --locked` installs the resolved environment; `uv run --locked ...` prepares it and runs a command. `pyproject.toml` is the declaration; `uv.lock` is the resolved set; `requirements.txt` is the pip-compatible export. You can use standard venv/pip instead. [Official uv project guide](https://docs.astral.sh/uv/guides/projects/).

## Why can the first run be slow?

Hashing must read all audio bytes. Random access and external-drive throughput can dominate even when CPU usage is low. Multiple readers are configurable but more is not always faster. Future runs still discover/stat files, but skip unchanged metadata, hash and probe work. Deep mode additionally decodes audio and can take much longer.

## Why does the cache not notice every possible edit?

Its inexpensive change detector is path + size + nanosecond modification timestamp. An edit deliberately preserving those properties can evade it. Moving to a different path is treated as a new file. Cache schema/version changes may deliberately force new scans. There is not yet a selective cache-management CLI.

## Does PASS mean my archive is perfect?

No. Fast PASS means metadata and stream inspection succeeded. Full decoding is listed separately and is off by default. Even a successful full decode does not prove the recording/version is correct, tags are accurate, artwork is right, or the file has a particular origin. Album completeness is based on the files' own tags.

## Why are some M4A files not marked as purchases?

M4A is a container/extension, not proof of a store purchase. Purchase-related metadata supports only a likely-purchase classification. Generic DRM-free AAC is still potentially eligible. Detected protected files do not satisfy permanent offline coverage; no DRM-removal feature is provided.

## Why are `._` files in the inventory?

Some disks contain macOS AppleDouble metadata sidecars with audio-looking extensions. Their binary header distinguishes them from songs. They remain visible for accounting but do not count as audio, duplicate songs or incomplete albums.

## Can I publish the report or cache with the code?

They are private outputs: they contain paths, track IDs, library metadata and possibly purchase-related information. Publish only the clean exporter bundle. The project has no telemetry or online matching, but dependency installers access public package sources. GitHub account/commit identity is separate from code content. Read [PUBLISHING.md](PUBLISHING.md).

## What happens when I choose to review matches interactively?

After matching, an interactive run asks whether to review the remaining REVIEW entries. For each one it shows the original title/artist/album/duration, the reason, and the retained candidates. `yes` confirms the current candidate and immediately saves a Persistent-ID manual override; `no` rejects only that candidate and advances; `quit` stops while retaining earlier choices. Rejecting every candidate leaves the row REVIEW. This pass never changes a music file and never silently marks a rejected candidate MISSING.

## What if a future model changes the project?

Provide [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md), [IMPLEMENTATION.md](../IMPLEMENTATION.md), [AGENTS.md](../AGENTS.md) and the synthetic tests. Do not send private XML/cache/reports unless intentionally sharing them. The handoff lists invariants, limitations and validation commands without requiring the original conversation.
