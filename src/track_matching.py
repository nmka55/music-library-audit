"""Recall-oriented track matching for duplicate and coverage questions.

The audit matcher in matcher.py is deliberately strict: every one of title, artist,
version, duration, tags and eligibility must agree. That is right before declaring a file
safe, but it misses most real duplicates: a "(Remastered)" suffix, "The Beatles" versus
"Beatles", a duration a few seconds off, or a file with no tags at all each defeat it.

This module ranks a candidate file against a track in three tiers and ignores the album
entirely (the same song legitimately sits on singles, "all time hits" compilations and
the original album):

STRICT    passes the audit matcher's automatic gates.
LIKELY    same song title and artist, duration within a few seconds, same kind of recording
          (a live or remixed version never matches a studio one).
POSSIBLE  similar enough that a person should look.

Callers decide what each tier may be used for; only STRICT is deletion-grade.
"""

import re
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

from matcher import score
from normalization import normalize, repair_mojibake, transliterate

STRICT, LIKELY, POSSIBLE = "STRICT", "LIKELY", "POSSIBLE"
TIER_RANK = {STRICT: 0, LIKELY: 1, POSSIBLE: 2}
LOOSE_SECONDS = 10.0

# Different recordings, not just different tags. Remaster/mono/edit differences are tolerated.
HARD_VERSION = re.compile(r"\b(live|acoustic|demo|remix|instrumental|karaoke|extended)\b")
BRACKETS = re.compile(r"[\[(][^\])]*[\])]")
FEATURE_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with)\s+.*$", re.I)
TRACK_PREFIX = re.compile(r"^\s*(?:\d{1,2}-\d{1,3}|\d{1,3})\s*[-._)]?\s+")
DIGITS = re.compile(r"\d+")
DASH = re.compile(r"\s[-–—]\s")
ARTIST_POSTING_CAP = 4000
TOKEN_POSTING_CAP = 1500


def strip_the(value):
    return value[4:] if value.startswith("the ") else value


def clean_core(text):
    text = BRACKETS.sub(" ", str(text or ""))
    return normalize(FEATURE_TAIL.sub("", text))


def core_titles(text):
    """Comparison keys for one title: brackets, feature credits and '- version' tails removed.

    The text is also tried without a leading track number ("07 - Song"), while the original
    is kept so titles that really start with a number ("7 Rings") still match.
    """
    text = str(text or "")
    stripped = TRACK_PREFIX.sub("", text)
    keys = {clean_core(text), clean_core(stripped), clean_core(DASH.split(stripped)[0])}
    keys.discard("")
    return keys


def prepare(row, filename=None):
    """Add matching-only fields. Needs the normalization fields from prepare_apple/offline."""
    title = repair_mojibake(row.get("Title") or row.get("Name") or "")
    stem = repair_mojibake(Path(filename).stem) if filename else ""
    keys = core_titles(title)
    if stem:
        keys |= core_titles(stem)
    row["_keys"] = keys
    row["_artist_latin"] = normalize(transliterate(repair_mojibake(row.get("Artist") or "")))
    row["_hard"] = frozenset(HARD_VERSION.findall(normalize(title or stem)))
    row["_stem_artist"] = None
    if stem:
        # "Artist - Title" filenames: the title part is searchable, the left part is evidence.
        parts = DASH.split(TRACK_PREFIX.sub("", stem), maxsplit=1)
        if len(parts) == 2 and clean_core(parts[1]):
            row["_stem_artist"] = strip_the(normalize(parts[0]))
            keys.add(clean_core(parts[1]))
        parent = [repair_mojibake(p) for p in Path(filename).parent.parts[-4:]]
        row["_folder"] = " " + normalize(" ".join(parent)) + " "
    else:
        row["_folder"] = ""
    return row


def artist_agreement(a, b):
    """Return (score 0-100, basis). The filename or folder can stand in for a missing artist tag."""
    ac, bc = set(a["Credited Artists"]), set(b["Credited Artists"])
    if ac and bc and ac & bc:
        return 100.0, "tag"
    sim = 0.0
    an, bn = strip_the(a["Normalized Artist"]), strip_the(b["Normalized Artist"])
    if an and bn:
        sim = fuzz.ratio(an, bn)
        if fuzz.token_set_ratio(an, bn) == 100:
            sim = max(sim, 92.0)  # "Artist & Guest" against "Artist"
    al, bl = strip_the(a.get("_artist_latin", "")), strip_the(b.get("_artist_latin", ""))
    if sim < 90 and al and bl and (al != an or bl != bn):
        # Apple Music often spells Russian artists in Latin letters; the files use Cyrillic.
        spelled = fuzz.ratio(al, bl)
        if spelled >= 88:
            return 92.0, "transliteration"
        sim = max(sim, spelled)
    if sim < 90 and b.get("_stem_artist") and fuzz.ratio(b["_stem_artist"], an) >= 85:
        return 92.0, "filename"
    folder = b.get("_folder", "")
    if sim < 90 and folder and any(len(c) >= 3 and f" {c} " in folder for c in ac):
        return 90.0, "folder name"
    return sim, "tag"


def title_agreement(a, b):
    best = 0.0
    for va in a["_keys"]:
        for vb in b["_keys"]:
            r = 100.0 if va == vb else fuzz.ratio(va, vb)
            if r >= 85 and DIGITS.findall(va) != DIGITS.findall(vb):
                r = min(r, 80.0)  # "Part 1" is not "Part 2"
            best = max(best, r)
    return best


def compare(a, b, config, loose_seconds=LOOSE_SECONDS):
    """Return a match description, or None when the two are not plausibly the same song."""
    title = title_agreement(a, b)
    if title < 85:
        return None
    artist, basis = artist_agreement(a, b)
    ad, bd = a.get("Duration Seconds"), b.get("Duration")
    diff = abs(ad - bd) if ad and bd else None
    same_kind = a["_hard"] == b["_hard"]
    eligible = b.get("Archive Eligible") is not False
    notes = [f"title {title:.0f}", f"artist {artist:.0f} ({basis})"]
    notes.append(f"duration {diff:.1f}s apart" if diff is not None else "duration unknown")
    if not same_kind:
        notes.append("different kind of recording (live/remix/acoustic/...)")
    if not eligible:
        notes.append("file is unreadable or protected")
    likely = (
        same_kind
        and eligible
        and title >= 94
        and artist >= 90
        and diff is not None
        and diff <= loose_seconds
        and (basis == "tag" or title == 100)
    )
    if likely:
        tier = LIKELY
        s = score(a, b, config)
        if s["safe"] and s["Overall Confidence"] >= config["matched_threshold"]:
            tier = STRICT
    elif artist >= 60:
        tier = POSSIBLE
    else:
        return None
    return {
        "file": b,
        "tier": tier,
        "title": title,
        "artist": artist,
        "basis": basis,
        "diff": diff,
        "evidence": "; ".join(notes),
    }


class LooseIndex:
    """Candidate retrieval by title key, artist credit and rare title words."""

    def __init__(self, rows):
        self.rows = [r for r in rows if r.get("File Type") != "AppleDouble metadata sidecar"]
        self.by_key, self.by_artist, self.by_token = (defaultdict(list) for _ in range(3))
        for i, row in enumerate(self.rows):
            prepare(row, None if row.get("_virtual") else row.get("Full Path"))
            for key in row["_keys"]:
                self.by_key[key].append(i)
                for token in set(key.split()):
                    if len(token) > 2:
                        self.by_token[token].append(i)
            for credit in row["Credited Artists"]:
                self.by_artist[credit].append(i)

    def candidates(self, a):
        ids = set()
        for key in a["_keys"]:
            ids.update(self.by_key.get(key, ()))
        for credit in a["Credited Artists"]:
            posting = self.by_artist.get(credit, ())
            if len(posting) <= ARTIST_POSTING_CAP:
                ids.update(posting)
        tokens = {t for k in a["_keys"] for t in k.split() if t in self.by_token}
        for token in sorted(tokens, key=lambda t: len(self.by_token[t]))[:2]:
            posting = self.by_token[token]
            if len(posting) <= TOKEN_POSTING_CAP:
                ids.update(posting)
        return [self.rows[i] for i in ids]

    def find(self, a, config, loose_seconds=LOOSE_SECONDS):
        """All plausible matches for a prepared track, best first."""
        if not a["_keys"]:
            return []
        found = [m for b in self.candidates(a) if (m := compare(a, b, config, loose_seconds))]
        found.sort(
            key=lambda m: (
                TIER_RANK[m["tier"]],
                m["diff"] if m["diff"] is not None else 999,
                -m["title"],
                -m["artist"],
            )
        )
        return found
