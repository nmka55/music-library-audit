"""Reconcile an Apple Music XML, a purchased-music XML and a folder of downloaded music.

Answers two questions without changing any file:

1. Which downloaded files are copies of purchased tracks? The result is a reviewable
   plan. A file is only a REMOVE CANDIDATE when the purchased track also exists as a
   real, unchanged file on this computer; nothing is ever deleted by this program.
2. Which Apple Music tracks are in neither the purchased library nor the downloaded
   folder?

The downloaded folder is read with the existing tag/FFprobe scanner and conservative
matcher (without SHA-256, so each file is not read in full). Results are Excel files in
the workspace output directory.
"""

import argparse
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

from compare_libraries import (
    COLUMNS,
    MATCHED,
    NOT_FOUND,
    POSSIBLE,
    choose_xml,
    classify,
    duration_text,
    index,
    link_for,
    output_path,
    prepare,
    read_tracks,
    write_xlsx,
)
from config import load, resolve_path
from matcher import CandidateIndex, score
from normalization import normalize, prepare_apple, prepare_offline

REMOVE = "REMOVE CANDIDATE"
KEEP_REMOTE = "KEEP: purchased copy not downloaded"
KEEP_GONE = "KEEP: purchased file not found on this computer"
REVIEW_CHANGED = "REVIEW: purchased file differs from the XML"
REVIEW_WEAK = "REVIEW: possible match, not confident"
MISSING = "MISSING EVERYWHERE"

PLAN_COLUMNS = (
    "Recommendation",
    "Internet File",
    "Internet Title",
    "Internet Artist",
    "Internet Album",
    "Internet Format",
    "Internet Bitrate (kbps)",
    "Internet Size (MB)",
    "Purchased Title",
    "Purchased Artist",
    "Purchased Album",
    "Purchased File",
    "Purchased Format",
    "Match Confidence",
    "Reason",
)
ALBUM_COLUMNS = (
    "Album",
    "Album Artist",
    "Purchased Tracks",
    "With Internet Copy",
    "Purchased File On Disk",
    "Internet Files To Remove",
)
MISSING_COLUMNS = COLUMNS[:6] + ("Status", "Closest Match", "Reason")
# Lower is better when one downloaded file matches several purchased tracks.
STATE_RANK = {"OK": 0, "CHANGED": 1, "MISSING_LOCAL": 2, "NOT_DOWNLOADED": 3}
STATE_RECOMMENDATION = {
    "OK": REMOVE,
    "CHANGED": REVIEW_CHANGED,
    "MISSING_LOCAL": KEEP_GONE,
    "NOT_DOWNLOADED": KEEP_REMOTE,
}
STATE_REASON = {
    "OK": "same recording as a purchased file that exists on this computer",
    "CHANGED": "purchased file size no longer equals the XML size; check it before removing",
    "MISSING_LOCAL": "XML lists the purchased file, but it is not at that path now",
    "NOT_DOWNLOADED": "the purchased track is cloud-only; download it in iTunes first",
}


def location_to_path(url):
    """Turn an iTunes file URL into a native path (Windows drive and UNC forms included)."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", path):
        return path[1:]
    if parsed.netloc not in ("", "localhost"):
        return "//" + parsed.netloc + path
    return path


def purchased_state(track):
    """Return (state, path): is the purchased copy a real, unchanged file right now?"""
    location = track.get("Location")
    if not location:
        return "NOT_DOWNLOADED", None
    path = location_to_path(location)
    if not os.path.isfile(path):
        return "MISSING_LOCAL", path
    expected = track.get("Size")
    if expected and os.path.getsize(path) != expected:
        return "CHANGED", path
    return "OK", path


def key_of(path):
    return os.path.normcase(os.path.abspath(path))


def codec_text(row):
    return (row.get("Codec") or row.get("Extension", "").lstrip(".") or "").upper()


def kbps(row):
    try:
        return round(float(row.get("Bitrate")) / 1000)
    except (TypeError, ValueError):
        return ""


def album_key(track):
    return (
        normalize(track.get("Album Artist") or track.get("Artist")),
        normalize(track.get("Album")),
    )


def scored_candidates(track, finder, config):
    return [score(track, row, config) for row in finder.candidates(track)]


def is_confident(s, config):
    return s["safe"] and s["Overall Confidence"] >= config["matched_threshold"]


def plan_internet_copies(purchased, finder, config, state_of):
    """One row per downloaded file that matches (or may match) a purchased track."""
    found = {}
    for track in purchased:
        state = None
        for s in scored_candidates(track, finder, config):
            confident = is_confident(s, config)
            if not confident and not (
                s["meaningful"] and s["Overall Confidence"] >= config["review_threshold"]
            ):
                continue
            if state is None:
                state = state_of(track)
            rank = (0 if confident else 1, STATE_RANK[state[0]], -s["Overall Confidence"])
            path = s["file"]["Full Path"]
            if path not in found or rank < found[path]["rank"]:
                found[path] = {
                    "rank": rank,
                    "score": s,
                    "track": track,
                    "state": state,
                    "confident": confident,
                }
    rows = []
    for path, hit in found.items():
        b, track, s = hit["score"]["file"], hit["track"], hit["score"]
        state, purchased_path = hit["state"]
        rows.append(
            {
                "Recommendation": STATE_RECOMMENDATION[state] if hit["confident"] else REVIEW_WEAK,
                "Internet File": path,
                "Internet Title": b.get("Title", ""),
                "Internet Artist": b.get("Artist", ""),
                "Internet Album": b.get("Album", ""),
                "Internet Format": codec_text(b),
                "Internet Bitrate (kbps)": kbps(b),
                "Internet Size (MB)": round((b.get("File Size") or 0) / 1_000_000, 1),
                "Purchased Title": track.get("Name", ""),
                "Purchased Artist": track.get("Artist", ""),
                "Purchased Album": track.get("Album", ""),
                "Purchased File": purchased_path or "",
                "Purchased Format": f"{track.get('Bit Rate', '')} kbps"
                if track.get("Bit Rate")
                else "",
                "Match Confidence": s["Overall Confidence"],
                "Reason": STATE_REASON[state] if hit["confident"] else s["Match Reason"],
                "_album": album_key(track),
                "_track": id(track),
            }
        )
    order = {REMOVE: 0, REVIEW_CHANGED: 1, REVIEW_WEAK: 2, KEEP_GONE: 3, KEEP_REMOTE: 4}
    rows.sort(key=lambda r: (order[r["Recommendation"]], r["Internet File"].casefold()))
    return rows


def album_summary(purchased, plan, state_of):
    albums = defaultdict(lambda: {"tracks": 0, "disk": 0, "internet": set(), "remove": set()})
    for track in purchased:
        entry = albums[album_key(track)]
        entry["tracks"] += 1
        entry["disk"] += state_of(track)[0] == "OK"
    by_track = {id(t): t for t in purchased}
    for row in plan:
        if row["Recommendation"] == REVIEW_WEAK:
            continue
        entry = albums[row["_album"]]
        entry["internet"].add(row["_track"])
        if row["Recommendation"] == REMOVE:
            entry["remove"].add(row["Internet File"])
    rows = []
    for key, entry in albums.items():
        if not entry["internet"] and not entry["remove"]:
            continue
        sample = next(t for t in by_track.values() if album_key(t) == key)
        rows.append(
            {
                "Album": sample.get("Album", ""),
                "Album Artist": sample.get("Album Artist") or sample.get("Artist", ""),
                "Purchased Tracks": entry["tracks"],
                "With Internet Copy": len(entry["internet"]),
                "Purchased File On Disk": entry["disk"],
                "Internet Files To Remove": len(entry["remove"]),
            }
        )
    rows.sort(key=lambda r: (-r["Internet Files To Remove"], r["Album Artist"].casefold()))
    return rows


def missing_everywhere(apple, purchased_index, finder, config):
    """Apple Music tracks found in neither the purchased XML nor the downloaded folder."""
    rows = []
    tolerance = config["duration_tolerance_seconds"]
    for track in apple:
        status, other, reason = classify(prepare(track), purchased_index, tolerance)
        if status == MATCHED:
            continue
        closest = (
            f"Purchased: {other['track'].get('Name', '')} - {other['track'].get('Artist', '')}"
            if other
            else ""
        )
        found = scored_candidates(track, finder, config)
        if any(is_confident(s, config) for s in found):
            continue
        weak = sorted(
            (s for s in found if s["meaningful"]),
            key=lambda s: -s["Overall Confidence"],
        )
        if weak and status == NOT_FOUND:
            status, reason = POSSIBLE, "downloaded folder: " + weak[0]["Match Reason"]
            closest = "Downloaded: " + weak[0]["file"]["Full Path"]
        elif status == POSSIBLE:
            reason = "purchased library: " + reason
        else:
            status, reason = MISSING, "not in the purchased library or the downloaded folder"
        rows.append(
            {
                "Title": track.get("Name", ""),
                "Artist": track.get("Artist", ""),
                "Album": track.get("Album", ""),
                "Year": track.get("Year", ""),
                "Duration": duration_text(track),
                "iTunes Link": link_for(track),
                "Status": status,
                "Closest Match": closest,
                "Reason": reason,
                "_sort": (
                    str(track.get("Artist", "")).casefold(),
                    str(track.get("Album", "")).casefold(),
                    track.get("Disc Number", 0),
                    track.get("Track Number", 0),
                    str(track.get("Name", "")).casefold(),
                ),
            }
        )
    rows.sort(key=lambda r: (r["Status"] != MISSING, r["_sort"]))
    return rows


def reconcile(apple_tracks, purchased_tracks, offline, config, state_of=purchased_state):
    """Pure comparison step: dictionaries in, three lists of Excel rows out."""
    apple = [dict(t) for t in apple_tracks]
    purchased = [dict(t) for t in purchased_tracks]
    for row in apple + purchased:
        prepare_apple(row)
    for row in offline:
        prepare_offline(row)
    # The purchased files themselves must never be offered as removable copies.
    protected = {
        key_of(location_to_path(t["Location"])) for t in purchased_tracks if t.get("Location")
    }
    candidates = [r for r in offline if key_of(r["Full Path"]) not in protected]
    finder = CandidateIndex(candidates)
    states = {}

    def cached_state(track):
        if id(track) not in states:
            states[id(track)] = state_of(track)
        return states[id(track)]

    plan = plan_internet_copies(purchased, finder, config, cached_state)
    albums = album_summary(purchased, plan, cached_state)
    purchased_index = index([prepare(t) for t in purchased_tracks])
    missing = missing_everywhere(apple, purchased_index, finder, config)
    return plan, albums, missing, len(offline) - len(candidates)


def ask_folders(ask=input, tell=print):
    tell("\nEnter the downloaded-music folder, one per answer. Enter done when finished.")
    folders = []
    while True:
        raw = ask(f"Music folder {len(folders) + 1}, or done: ").strip().strip('"').strip("'")
        if raw.casefold() in ("done", "") and folders:
            return folders
        if raw and Path(raw).expanduser().is_dir():
            folders.append(str(Path(raw).expanduser()))
        else:
            tell("That folder does not exist. Try again." if raw else "Add at least one folder.")


def main(argv=None, ask=input, tell=print):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Find downloaded music that duplicates purchased tracks (reviewable plan, "
        "nothing is deleted) and Apple Music tracks missing from both libraries"
    )
    parser.add_argument("--apple", help="Apple Music library XML (asked for if omitted)")
    parser.add_argument("--purchased", help="Purchased music library XML (asked for if omitted)")
    parser.add_argument(
        "--music-root",
        action="append",
        help="Downloaded-music folder; repeat for several (default: saved folders, else asked)",
    )
    parser.add_argument("--workspace", help="Workspace directory (default: project folder)")
    parser.add_argument(
        "--config", help="Local JSON settings path (default: workspace/config.json)"
    )
    args = parser.parse_args(argv)
    c = load(args.config, args.workspace)
    workspace = Path(c["_workspace"])
    if (
        not args.apple or not args.purchased or not (args.music_root or c["offline_music_roots"])
    ) and (not sys.stdin.isatty() and ask is input):
        parser.error("Supply --apple, --purchased and --music-root when not running in a terminal.")
    apple = (
        resolve_path(args.apple, workspace)
        if args.apple
        else choose_xml("Apple Music library", workspace, ask, tell)
    )
    purchased = (
        resolve_path(args.purchased, workspace)
        if args.purchased
        else choose_xml("purchased music library", workspace, ask, tell, exclude=apple)
    )
    roots = args.music_root or c["offline_music_roots"] or ask_folders(ask, tell)
    c = load(args.config, args.workspace, {"offline_music_roots": roots})
    for path in (apple, purchased):
        if not path.is_file():
            parser.error(f"XML file not found: {path}")
    if apple == purchased:
        parser.error("Choose two different XML files.")
    for root in c["offline_music_roots"]:
        if not Path(root).is_dir():
            parser.error(f"Music folder unavailable: {root}. Connect the drive and retry.")
    if not shutil.which("ffprobe"):
        parser.error("ffprobe must be installed and on PATH.")
    outputs = {
        name: output_path(c, None, name)
        for name in (
            "Internet_Duplicates_Of_Purchased.xlsx",
            "Purchased_Albums_In_Internet_Collection.xlsx",
            "Apple_Music_Missing_Everywhere.xlsx",
        )
    }
    cache = Path(c["cache_directory"]) / "reconcile"
    cache.mkdir(parents=True, exist_ok=True)
    scan_config = dict(c, cache_directory=str(cache), _skip_hash=True)

    from audio_scanner import discover, inventory

    apple_tracks, purchased_tracks = read_tracks(apple), read_tracks(purchased)
    files, errors = discover(c["offline_music_roots"])
    tell(f"Apple Music tracks: {len(apple_tracks):,}; purchased tracks: {len(purchased_tracks):,}")
    tell(f"Downloaded files found: {len(files):,}. Reading tags (first run can take a while)...")
    offline = [
        r
        for r in inventory(files, scan_config)
        if r.get("File Type") != "AppleDouble metadata sidecar"
    ]
    plan, albums, missing, protected = reconcile(apple_tracks, purchased_tracks, offline, c)
    write_xlsx(plan, outputs["Internet_Duplicates_Of_Purchased.xlsx"], PLAN_COLUMNS)
    write_xlsx(albums, outputs["Purchased_Albums_In_Internet_Collection.xlsx"], ALBUM_COLUMNS)
    write_xlsx(missing, outputs["Apple_Music_Missing_Everywhere.xlsx"], MISSING_COLUMNS)

    def count(rows, column, value):
        return sum(r[column] == value for r in rows)

    megabytes = sum(r["Internet Size (MB)"] for r in plan if r["Recommendation"] == REMOVE)
    tell("\nDownloaded files that duplicate purchased tracks:")
    for label in (REMOVE, KEEP_REMOTE, KEEP_GONE, REVIEW_CHANGED, REVIEW_WEAK):
        tell(f"  {label}: {count(plan, 'Recommendation', label):,}")
    tell(f"  Space held by REMOVE CANDIDATE files: {megabytes / 1000:,.1f} GB")
    tell("\nApple Music tracks not in the purchased library or the downloaded folder:")
    tell(f"  {MISSING}: {count(missing, 'Status', MISSING):,}")
    tell(f"  {POSSIBLE}: {count(missing, 'Status', POSSIBLE):,}  (check by hand)")
    if errors:
        tell(f"\n{len(errors)} folder(s) could not be fully read; those files are not in the results.")
    tell("\nNothing was deleted or changed. Review the Excel files, then remove files yourself:")
    for path in outputs.values():
        tell(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
