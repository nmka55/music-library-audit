"""Create a fresh, allowlisted public source tree and metadata-normalized ZIP."""

import hashlib
import json
from pathlib import Path
import re
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
# Intentionally explicit. A new source/doc/test file needs publication review.
PUBLIC_FILES = (
    ".gitignore",
    ".gitattributes",
    ".github/workflows/tests.yml",
    "README.md",
    "IMPLEMENTATION.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "config.example.json",
    "manual_matches.example.json",
    "docs/CONFIGURATION.md",
    "docs/FAQ.md",
    "docs/DEVELOPER_HANDOFF.md",
    "docs/PUBLISHING.md",
    "src/audit.py",
    "src/config.py",
    "src/review.py",
    "src/setup_wizard.py",
    "src/apple_music_xml.py",
    "src/audio_scanner.py",
    "src/integrity.py",
    "src/cache.py",
    "src/normalization.py",
    "src/matcher.py",
    "src/duplicate_detector.py",
    "src/album_audit.py",
    "src/dashboard.py",
    "src/excel_report.py",
    "src/validate_report.py",
    "tests/test_audit.py",
    "tests/test_scanner.py",
    "tests/test_config.py",
    "tests/test_cli.py",
    "tests/test_release.py",
    "tests/test_review.py",
    "scripts/prepare_release.py",
)


def privacy_issues(text, project=PROJECT):
    """Defense in depth; not a general proof that arbitrary prose is anonymous."""
    issues = []
    home = Path.home()
    for path in (home, Path(project).resolve()):
        for spelling in {str(path), str(path).replace("\\", "/"), str(path).replace("\\", "\\\\")}:
            if len(spelling) > 3 and spelling.casefold() in text.casefold():
                issues.append("Literal local home/workspace path")
    username = home.name
    if len(username) >= 4 and username.casefold() not in {
        "root",
        "user",
        "users",
        "runner",
        "runneradmin",
        "admin",
        "administrator",
    }:
        if re.search(r"(?<![\w-])" + re.escape(username) + r"(?![\w-])", text, re.I):
            issues.append("Local account name")
    patterns = {
        "Absolute home path": r"(?:[A-Za-z]:[\\/]+Users[\\/]+|/(?:home|Users)/)[A-Za-z0-9_.-]+",
        "Private key block": r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
        "Credential-shaped token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text):
            issues.append(label)
    return sorted(set(issues))


def prepare(project=PROJECT):
    project = Path(project).resolve()
    payload = {}
    errors = []
    for relative in PUBLIC_FILES:
        source = project / relative
        if source.is_symlink() or not source.resolve().is_relative_to(project):
            raise ValueError("Public source path escapes project: " + relative)
        # Decode/re-encode public text, so editor newline conventions do not vary ZIP bytes.
        text = source.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        findings = privacy_issues(text, project)
        if findings:
            errors.append(relative + ": " + ", ".join(findings))
        payload[relative] = text.encode("utf-8")
    if errors:
        raise ValueError("Publication review required:\n" + "\n".join(errors))
    manifest = {
        "format": 1,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())},
    }
    payload["PUBLIC_MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    dist = project / "dist"
    if dist.is_symlink() or not dist.resolve().is_relative_to(project):
        raise ValueError("dist must be a real directory inside this project")
    dist.mkdir(exist_ok=True)
    index = 1
    while True:
        name = "music-library-audit" + (f"-{index}" if index > 1 else "")
        target, archive = dist / name, dist / (name + ".zip")
        if not target.exists() and not archive.exists():
            break
        index += 1
    target.mkdir()
    for relative, data in payload.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
        for relative, data in sorted(payload.items()):
            info = zipfile.ZipInfo(
                "music-library-audit/" + relative, date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, data)
    print(f"Public source: {target}")
    print(f"Public ZIP: {archive}")
    print(f"Public files: {len(payload)}; private runtime data excluded; privacy patterns passed")
    return target, archive


if __name__ == "__main__":
    prepare()
