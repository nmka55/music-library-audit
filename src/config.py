"""Portable settings, path resolution, and write-boundary validation."""

import copy
import json
import math
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
EXTENSIONS = {".mp3", ".m4a", ".m4p", ".flac", ".aac", ".wav", ".ogg", ".opus", ".wma"}
DEFAULTS = {
    "apple_music_xml": "input/Library.xml",
    "offline_music_roots": [],
    "output_excel": "output/Music_Library_Audit.xlsx",
    "cache_directory": "cache",
    "manual_matches_file": "manual_matches.json",
    "duration_tolerance_seconds": 3,
    "deep_integrity_check": False,
    "matched_threshold": 90,
    "review_threshold": 70,
    "workers": 4,
    "probe_timeout_seconds": 45,
    "deep_timeout_seconds": 600,
}
PATH_KEYS = ("apple_music_xml", "output_excel", "cache_directory", "manual_matches_file")


def resolve_path(value, workspace):
    """Relative paths belong to the workspace, never an incidental shell cwd."""
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ValueError("Paths must be nonempty strings")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else workspace / path).resolve()


def validate(c):
    for key in (
        "matched_threshold",
        "review_threshold",
        "duration_tolerance_seconds",
        "probe_timeout_seconds",
        "deep_timeout_seconds",
    ):
        value = c[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{key} must be a finite number")
    if not 0 <= c["review_threshold"] < c["matched_threshold"] <= 100:
        raise ValueError("Require 0 <= review_threshold < matched_threshold <= 100")
    if not 0 <= c["duration_tolerance_seconds"] <= 5:
        raise ValueError("Duration tolerance must be between 0 and 5 seconds")
    if type(c["workers"]) is not int or not 1 <= c["workers"] <= 32:
        raise ValueError("workers must be an integer between 1 and 32")
    if not isinstance(c["deep_integrity_check"], bool):
        raise ValueError("deep_integrity_check must be a JSON boolean")
    if any(c[k] <= 0 for k in ("probe_timeout_seconds", "deep_timeout_seconds")):
        raise ValueError("Subprocess timeouts must be positive")
    workspace = Path(c["_workspace"])
    output = Path(c["output_excel"])
    if output.suffix.lower() != ".xlsx":
        raise ValueError("output_excel must end in .xlsx")
    writes = [
        output.parent,
        Path(c["cache_directory"]),
        Path(c["manual_matches_file"]),
        Path(c["_config_path"]),
    ]
    for target in writes:
        if not target.is_relative_to(workspace):
            raise ValueError(
                "All generated files and local settings must stay inside the workspace"
            )
        if any(target.is_relative_to(Path(root)) for root in c["offline_music_roots"]):
            raise ValueError("A write destination overlaps a read-only music folder")
    if output.parent == workspace:
        raise ValueError("Place the workbook in a dedicated output subdirectory")
    if Path(c["cache_directory"]) == workspace:
        raise ValueError("Use a dedicated cache subdirectory")
    xml = Path(c["apple_music_xml"])
    if xml.is_relative_to(output.parent) or xml.is_relative_to(Path(c["cache_directory"])):
        raise ValueError("Keep the source XML outside the output and cache directories")
    if xml in (Path(c["_config_path"]), Path(c["manual_matches_file"])):
        raise ValueError("The source XML cannot also be a settings or overrides file")
    return c


def load(config_path=None, workspace=None, updates=None):
    explicit = Path(config_path).expanduser().resolve() if config_path else None
    workspace = (
        Path(workspace).expanduser().resolve()
        if workspace
        else (explicit.parent if explicit else BASE)
    )
    config_path = explicit or workspace / "config.json"
    c = copy.deepcopy(DEFAULTS)
    if config_path.is_file():
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a JSON object")
        unknown = set(data) - set(DEFAULTS)
        if unknown:
            raise ValueError("Unknown configuration keys: " + ", ".join(sorted(unknown)))
        c.update(data)
    c.update(updates or {})
    roots = c["offline_music_roots"]
    if not isinstance(roots, list) or any(not isinstance(p, str) for p in roots):
        raise ValueError("offline_music_roots must be a list of folder paths")
    c["offline_music_roots"] = list(dict.fromkeys(str(resolve_path(p, workspace)) for p in roots))
    for key in PATH_KEYS:
        c[key] = str(resolve_path(c[key], workspace))
    c["_workspace"], c["_config_path"] = str(workspace), str(config_path)
    return validate(c)


def save(c):
    """Save only machine-local configuration, never an exportable template."""
    validate(c)
    workspace = Path(c["_workspace"])
    data = {key: c[key] for key in DEFAULTS}
    for key in PATH_KEYS:
        path = Path(data[key])
        if path.is_relative_to(workspace):
            data[key] = path.relative_to(workspace).as_posix()
    target = Path(c["_config_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def read_overrides(c):
    path = Path(c["manual_matches_file"])
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict) or any(not isinstance(v, str) for v in result.values()):
        raise ValueError("Manual matches must map track identifiers to path strings")
    return {k: str(resolve_path(v, Path(c["_workspace"]))) for k, v in result.items()}
