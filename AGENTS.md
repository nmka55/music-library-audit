# Instructions for coding agents

Read README.md, IMPLEMENTATION.md and docs/DEVELOPER_HANDOFF.md before substantive changes.

- Keep music roots and XML strictly read-only. No tag saves, conversions, artwork edits, moves or duplicate deletion.
- Preserve conservative automatic-match gates, original XML fields and explicit uncertainty. Missing manual targets must not select substitutes.
- Resolve paths through config.py; keep runtime writes within the chosen workspace and outside music roots.
- Use temporary synthetic fixtures. Never require or publish a real library, account information, absolute personal paths or private scan statistics.
- Public export is an explicit file allowlist in scripts/prepare_release.py. Add new public files deliberately; never include runtime artifacts or Git history.
- Keep README, implementation details, handoff, CLI help, config examples and tests aligned.
- Run tests appropriate to the change. Full verification uses Python unittest with FFmpeg/FFprobe installed; do not claim native macOS/Linux validation until those CI jobs run.
- Do not upload data, create remote repositories or push commits without user authorization. Preparing a clean local publication bundle is supported.
