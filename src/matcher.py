import os
import re
from collections import defaultdict
from pathlib import Path
from rapidfuzz import fuzz
from normalization import normalize


class CandidateIndex:
    def __init__(self, rows):
        self.rows = rows
        self.titles = defaultdict(set)
        self.tokens = defaultdict(set)
        self.artists = defaultdict(set)
        self.durations = defaultdict(set)
        for i, r in enumerate(rows):
            if r.get("File Type") == "AppleDouble metadata sidecar":
                continue
            self.titles[r["Normalized Title"]].add(i)
            title = r["Normalized Title"] or normalize(Path(r["Full Path"]).stem)
            for token in title.split():
                if len(token) > 1:
                    self.tokens[token].add(i)
            for artist in r["Credited Artists"]:
                self.artists[artist].add(i)
            if r.get("Duration"):
                self.durations[int(r["Duration"] // 5)].add(i)

    def candidates(self, a):
        ids = set(self.titles.get(a["Normalized Title"], ())) if a["Normalized Title"] else set()
        artists = set().union(*(self.artists.get(x, set()) for x in a["Credited Artists"]))
        duration = set()
        if a.get("Duration Seconds"):
            b = int(a["Duration Seconds"] // 5)
            duration = set().union(*(self.durations.get(x, set()) for x in range(b - 2, b + 3)))
        token_ids = set().union(
            *(self.tokens.get(t, set()) for t in a["Normalized Title"].split() if len(t) > 1)
        )
        ids |= (artists & duration) | (token_ids & (artists | duration))
        return [self.rows[i] for i in sorted(ids)]


def score(a, b, c):
    fallback = not bool(b.get("Title"))
    title = fuzz.ratio(
        a["Normalized Title"],
        b["Normalized Title"] or normalize(re.sub(r"^\d+[ ._-]*", "", Path(b["Full Path"]).stem)),
    )
    ac, bc = set(a["Credited Artists"]), set(b["Credited Artists"])
    artist = 100.0 if ac and ac == bc else (100 * len(ac & bc) / len(ac | bc) if ac and bc else 0)
    if a["Normalized Artist"] and b["Normalized Artist"]:
        artist = max(artist, fuzz.ratio(a["Normalized Artist"], b["Normalized Artist"]))
    ad, bd = a.get("Duration Seconds"), b.get("Duration")
    diff = abs(ad - bd) if ad and bd else None
    duration = (
        100
        if diff is not None and diff <= 1
        else 90
        if diff is not None and diff <= c["duration_tolerance_seconds"]
        else 45
        if diff is not None and diff <= 5
        else 0
    )
    album = (
        fuzz.ratio(a["Normalized Album"], b["Normalized Album"])
        if a["Normalized Album"] and b["Normalized Album"]
        else 0
    )
    numeric_conflict = re.findall(r"\b\d+\b", a["Normalized Title"]) != re.findall(
        r"\b\d+\b", b["Normalized Title"]
    )
    conflict = (
        a["Version Markers"] != b["Version Markers"]
        or a.get("Album Version Markers", []) != b.get("Album Version Markers", [])
        or numeric_conflict
    )
    album_artist = bool(
        a.get("Album Artist") and normalize(a["Album Artist"]) == normalize(b.get("Album Artist"))
    )
    track = bool(
        a.get("Track Number")
        and a.get("Track Number") == b.get("Track Number")
        and (a.get("Disc Number") or 1) == (b.get("Disc Number") or 1)
    )
    year = bool(a.get("Year") and a.get("Year") == b.get("Year"))
    confidence = (
        0.46 * title + 0.32 * artist + 0.17 * duration + 0.02 * album + album_artist + track + year
    )
    reasons = [
        f"title {title:.1f}; artist {artist:.1f}; duration "
        + (f"{diff:.3f}s" if diff is not None else "unknown")
    ]
    safe = (
        title >= 97
        and artist >= 97
        and diff is not None
        and diff <= c["duration_tolerance_seconds"]
        and not conflict
        and not fallback
        and b.get("Archive Eligible") is True
        and not a.get("Has Video")
    )
    if a.get("Has Video"):
        reasons.append("Apple item includes video; an audio copy requires review")
    if conflict:
        reasons.append("Version descriptors differ; human review required")
    if fallback:
        reasons.append("Filename fallback; title tag missing")
    if not b.get("Archive Eligible"):
        reasons.append(
            "File is not archive eligible: "
            + b.get("DRM Status", "Unknown")
            + "; "
            + b.get("Integrity", "unknown integrity")
        )
    if diff is None or diff > c["duration_tolerance_seconds"]:
        reasons.append("Duration missing or outside safe tolerance")
    if title < 97:
        reasons.append("Title agreement below automatic-match requirement (97)")
    if artist < 97:
        reasons.append("Artist agreement below automatic-match requirement (97)")
    if not safe:
        confidence = min(confidence, c["matched_threshold"] - 1)
    basic = fuzz.ratio(
        a.get("Normalized Base Title", a["Normalized Title"]),
        b.get("Normalized Base Title", b["Normalized Title"]),
    )
    meaningful = (basic >= 75 and artist >= 65 and (diff is None or diff <= 5 or basic >= 90)) or (
        title >= 95 and not b.get("Artist") and diff is not None and diff <= 5
    )
    return {
        "file": b,
        "Overall Confidence": round(confidence, 2),
        "Title Score": round(title, 2),
        "Artist Score": round(artist, 2),
        "Duration Difference": round(diff, 3) if diff is not None else None,
        "Album Score": round(album, 2),
        "Version Conflict": conflict,
        "safe": safe,
        "meaningful": meaningful,
        "Match Reason": "; ".join(reasons),
    }


def match_all(apple, offline, config, overrides):
    index = CandidateIndex(offline)
    paths = {os.path.normcase(os.path.abspath(r["Full Path"])): r for r in offline}
    results = []
    for a in apple:
        r = {
            "Status": "MISSING",
            "Match Type": "AUTOMATIC",
            "Apple Persistent ID": a.get("Persistent ID"),
            "Apple Title": a.get("Name"),
            "Apple Artist": a.get("Artist"),
            "Apple Album": a.get("Album"),
            "Apple Duration": a.get("Duration Seconds"),
            "Apple Release Date": a.get("Release Date"),
            "Matched Offline Title": None,
            "Matched Offline Artist": None,
            "Matched Offline Album": None,
            "Offline Duration": None,
            "Matched File Path": None,
            "Library Root": None,
            "Overall Confidence": 0,
            "Title Score": None,
            "Artist Score": None,
            "Duration Difference": None,
            "Album Score": None,
            "Version Conflict": None,
            "Archive Eligible": False,
            "Integrity": None,
            "Metadata Quality": None,
            "Artwork": None,
            "Alternative Candidate 1": None,
            "Alternative Candidate 1 Score": None,
            "Alternative Candidate 2": None,
            "Alternative Candidate 2 Score": None,
            "Alternative Candidate 3": None,
            "Alternative Candidate 3 Score": None,
            "Match Reason": "No meaningful candidate found",
            "Review Notes": "",
            "All Relevant Copies": [],
        }
        key = a.get("Persistent ID") or "track:" + str(a.get("Track ID"))
        candidates = []
        selected = None
        if key in overrides:
            target = overrides[key]
            r["Match Type"] = "MANUAL MATCH"
            if not isinstance(target, str):
                r.update(
                    Status="REVIEW",
                    **{"Match Reason": "Invalid manual override: expected path string"},
                )
            else:
                b = paths.get(os.path.normcase(os.path.abspath(target)))
                r["Matched File Path"] = target
                if b and Path(target).is_file():
                    selected = score(a, b, config)
                    selected["Overall Confidence"] = 100
                    selected["Match Reason"] = (
                        "MANUAL MATCH: user-specified recording; archive eligibility checked separately"
                    )
                    r["Status"] = "MATCHED" if b.get("Archive Eligible") else "REVIEW"
                    if not b.get("Archive Eligible"):
                        r["Review Notes"] = (
                            "Manual identity confirmed, but this file cannot satisfy the offline archive requirement"
                        )
                else:
                    r.update(
                        Status="REVIEW",
                        **{
                            "Match Reason": "Manual override file is missing or outside the scanned collection; no substitute selected"
                        },
                    )
        else:
            candidates = [score(a, b, config) for b in index.candidates(a)]
            candidates = [s for s in candidates if s["meaningful"]]
            candidates.sort(
                key=lambda s: (
                    s["safe"] and s["Overall Confidence"] >= config["matched_threshold"],
                    s["Overall Confidence"],
                    s["file"].get("Archive Eligible", False),
                    not bool(s["file"].get("Metadata Issues")),
                ),
                reverse=True,
            )
            if candidates:
                selected = candidates[0]
                r["Status"] = (
                    "MATCHED"
                    if selected["safe"]
                    and selected["Overall Confidence"] >= config["matched_threshold"]
                    else "REVIEW"
                )
                if selected["Overall Confidence"] < config["review_threshold"]:
                    r["Review Notes"] = (
                        "Below review threshold, retained because meaningful evidence exists"
                    )
                # REVIEW exposes the best three candidates including its leading suggestion.
                alternatives = candidates[:3] if r["Status"] == "REVIEW" else candidates[1:4]
                for i, s in enumerate(alternatives, 1):
                    r[f"Alternative Candidate {i}"] = s["file"]["Full Path"]
                    r[f"Alternative Candidate {i} Score"] = s["Overall Confidence"]
                r["All Relevant Copies"] = [s["file"]["Full Path"] for s in candidates]
        if selected:
            b = selected["file"]
            r.update({k: v for k, v in selected.items() if k not in ("file", "safe", "meaningful")})
            r.update(
                {
                    "Matched Offline Title": b.get("Title"),
                    "Matched Offline Artist": b.get("Artist"),
                    "Matched Offline Album": b.get("Album"),
                    "Offline Duration": b.get("Duration"),
                    "Matched File Path": b["Full Path"],
                    "Library Root": b["Library Root"],
                    "Archive Eligible": b.get("Archive Eligible", False),
                    "Integrity": b.get("Integrity"),
                    "Metadata Quality": b.get("Metadata Issues") or "GOOD",
                    "Artwork": b.get("Artwork Present", False),
                }
            )
        results.append(r)
    return results
