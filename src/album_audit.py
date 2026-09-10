from collections import defaultdict, Counter
from pathlib import Path
from normalization import normalize


def audit_albums(rows):
    groups = defaultdict(list)
    for r in rows:
        if r.get("File Type") == "AppleDouble metadata sidecar":
            continue
        artist = normalize(r.get("Album Artist") or r.get("Artist"))
        album = r["Normalized Album"]
        key = (artist, album) if artist and album else ("UNKNOWN", str(Path(r["Full Path"]).parent))
        groups[key].append(r)
    result = []
    for key, album_files in groups.items():
        discs = defaultdict(list)
        for r in album_files:
            discs[r.get("Disc Number") or 1].append(r)
        disc_totals = {r["Disc Total"] for r in album_files if r.get("Disc Total")}
        missing_discs = (
            sorted(set(range(1, min(max(disc_totals), 1000) + 1)) - set(discs))
            if disc_totals
            else []
        )
        for disc, files in sorted(discs.items()):
            totals = {r["Track Total"] for r in files if r.get("Track Total")}
            numbers = Counter(r["Track Number"] for r in files if r.get("Track Number"))
            expected = max(totals) if totals else None
            missing = (
                sorted(set(range(1, min(expected, 10000) + 1)) - set(numbers)) if expected else []
            )
            repeated = sorted(n for n, count in numbers.items() if count > 1)
            invalid = bool(expected and any(n > expected for n in numbers)) or bool(
                expected and expected > 10000
            )
            inconsistent = len(totals) > 1 or len(disc_totals) > 1 or invalid
            status = (
                "INCONSISTENT TAGS"
                if inconsistent
                else "POSSIBLY INCOMPLETE"
                if missing or missing_discs
                else "UNKNOWN"
                if not expected
                or any(not r.get("Track Number") or not r.get("Track Total") for r in files)
                or key[0] == "UNKNOWN"
                else "COMPLETE ACCORDING TO TAGS"
            )
            result.append(
                {
                    "Album Artist": files[0].get("Album Artist") or files[0].get("Artist"),
                    "Album": files[0].get("Album"),
                    "Disc Number": disc,
                    "Status": status,
                    "Files Found": len(files),
                    "Expected Track Count": expected,
                    "Track Count Values": sorted(totals),
                    "Actual Track Numbers": sorted(numbers),
                    "Duplicate Track Numbers": repeated,
                    "Missing Track Numbers": missing,
                    "Expected Disc Counts": sorted(disc_totals),
                    "Missing Disc Numbers": missing_discs,
                    "Disc Completeness": "POSSIBLY INCOMPLETE"
                    if missing_discs
                    else "COMPLETE ACCORDING TO TAGS"
                    if disc_totals
                    else "UNKNOWN",
                    "Library Roots": sorted({r["Library Root"] for r in files}),
                    "Notes": "Metadata-based only; duplicate copies across roots can repeat track numbers. Missing disc tags assumed disc 1.",
                    "Files": [r["Full Path"] for r in files],
                }
            )
    return result
