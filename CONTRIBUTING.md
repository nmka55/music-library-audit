# Contributing

Read [IMPLEMENTATION.md](IMPLEMENTATION.md) and the [developer handoff](docs/DEVELOPER_HANDOFF.md). Changes should preserve read-only inputs, conservative matching and local-only data handling.

Create a small branch and describe the concrete behavior change, why it is needed and how it was tested. Use synthetic titles/artists and generated short audio for regressions. Never attach a real XML library, cached inventory, log containing personal paths, purchased audio or screenshots showing a private collection.

Run `uv run --locked python -m unittest discover -s tests -v` with FFmpeg and FFprobe installed. The native CI matrix should pass. When changing parsing, cover relevant formats; when changing matching, include false-positive cases. Avoid tests that simply repeat an implementation formula without checking observable behavior.

Update documentation, config examples and publication allowlist when adding modules or options. Dependency changes belong in `pyproject.toml`, `uv.lock` and the exported `requirements.txt`. Do not regenerate private test baselines from someone's collection. See [PUBLISHING.md](docs/PUBLISHING.md) before releasing.
