# Security and privacy

The audit runs locally and has no account authentication, telemetry, upload endpoint or network matching. Dependency installation and GitHub publication are separate network operations. FFmpeg/FFprobe and Mutagen parse supplied media; keep those tools current and do not treat this application as a security sandbox for malicious files.

Music and XML are read-only inputs. Writes are confined to a configured workspace, with resolved path checks preventing writes inside music roots. Spreadsheet text is emitted as literal values to avoid imported formulas. Runtime reports/cache/logs contain private metadata and paths; Git ignores the default runtime locations and the publication exporter uses an explicit public-file allowlist.

Do not post credentials, original library exports, full private logs, media or personal filesystem paths in public issues. Use synthetic reproductions. If the hosting repository enables GitHub private vulnerability reporting, use its Security tab for sensitive reports; otherwise request a private reporting route without disclosing the issue details publicly. No personal email address is embedded in this project.

Automated export checks cannot guarantee every form of identifying information is absent. Review new source/docs, Git author/email settings and the destination account. `.gitignore` does not remove files already tracked in an existing Git history. Start publication from the clean exported directory as described in [PUBLISHING.md](docs/PUBLISHING.md).
