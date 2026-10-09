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
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from compare_libraries import (
    COLUMNS,
    as_file_rows,
    choose_xml,
    duration_text,
    link_for,
    location_to_path,
    output_path,
    read_tracks,
    write_xlsx,
)
from config import load, resolve_path
from normalization import normalize, prepare_apple, prepare_offline
from track_matching import (
    LOOSE_SECONDS,
    STRICT,
    LIKELY,
    POSSIBLE as WEAK,
    TIER_RANK,
    LooseIndex,
    prepare as prepare_query,
)

REMOVE = "REMOVE CANDIDATE"
LIKELY_DUP = "LIKELY DUPLICATE: review, then remove"
KEEP_REMOTE = "KEEP: purchased copy not downloaded"
KEEP_GONE = "KEEP: purchased file not found on this computer"
REVIEW_CHANGED = "REVIEW: purchased file differs from the XML"
REVIEW_WEAK = "REVIEW: possible match, not confident"
MISSING = "MISSING EVERYWHERE"
POSSIBLE = "POSSIBLE MATCH"

PLAN_COLUMNS = (
    "Recommendation",
    "Match Type",
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
    "Duration Difference (s)",
    "Album Tracks In This Folder",
    "Evidence",
)
ALBUM_COLUMNS = (
    "Album",
    "Album Artist",
    "Purchased Tracks",
    "With Internet Copy",
    "Purchased File On Disk",
    "Internet Files To Remove",
    "Likely Duplicates To Review",
    "Best Internet Folder",
    "Tracks In That Folder",
)
MISSING_COLUMNS = COLUMNS[:6] + ("Status", "Closest Match", "Reason")
TIER_LABEL = {STRICT: "Strict", LIKELY: "Likely", WEAK: "Possible"}
# Lower is better when one downloaded file matches several purchased tracks.
STATE_RANK = {"OK": 0, "CHANGED": 1, "MISSING_LOCAL": 2, "NOT_DOWNLOADED": 3}
STATE_RECOMMENDATION = {
    "OK": {STRICT: REMOVE, LIKELY: LIKELY_DUP},
    "CHANGED": {STRICT: REVIEW_CHANGED, LIKELY: REVIEW_CHANGED},
    "MISSING_LOCAL": {STRICT: KEEP_GONE, LIKELY: KEEP_GONE},
    "NOT_DOWNLOADED": {STRICT: KEEP_REMOTE, LIKELY: KEEP_REMOTE},
}
STATE_REASON = {
    "OK": "the purchased copy exists on this computer",
    "CHANGED": "purchased file size no longer equals the XML size; check it before removing",
    "MISSING_LOCAL": "XML lists the purchased file, but it is not at that path now",
    "NOT_DOWNLOADED": "the purchased track is cloud-only; download it in iTunes first",
}


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


def plan_internet_copies(purchased, finder, config, state_of, loose_seconds):
    """One row per downloaded file that matches (or may match) a purchased track."""
    found = {}
    for track in purchased:
        state = None
        for m in finder.find(track, config, loose_seconds):
            if state is None:
                state = state_of(track)
            rank = (TIER_RANK[m["tier"]], STATE_RANK[state[0]], m["diff"] or 0)
            path = m["file"]["Full Path"]
            if path not in found or rank < found[path]["rank"]:
                found[path] = {"rank": rank, "match": m, "track": track, "state": state}
    folder_tracks = defaultdict(set)
    album_sizes = defaultdict(int)
    for track in purchased:
        album_sizes[album_key(track)] += 1
    for path, hit in found.items():
        if hit["match"]["tier"] != WEAK:
            folder_tracks[(album_key(hit["track"]), os.path.dirname(path))].add(id(hit["track"]))
    rows = []
    for path, hit in found.items():
        m, track = hit["match"], hit["track"]
        b, tier = m["file"], m["tier"]
        state, purchased_path = hit["state"]
        key = album_key(track)
        together = len(folder_tracks.get((key, os.path.dirname(path)), ()))
        evidence = m["evidence"]
        if tier != WEAK:
            evidence += "; " + STATE_REASON[state]
        rows.append(
            {
                "Recommendation": REVIEW_WEAK
                if tier == WEAK
                else STATE_RECOMMENDATION[state][tier],
                "Match Type": TIER_LABEL[tier],
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
                "Duration Difference (s)": round(m["diff"], 1) if m["diff"] is not None else "",
                "Album Tracks In This Folder": f"{together} of {album_sizes[key]}"
                if together
                else "",
                "Evidence": evidence,
                "_album": key,
                "_track": id(track),
                "_folder": os.path.dirname(path),
                "_tier": tier,
            }
        )
    order = {
        REMOVE: 0,
        LIKELY_DUP: 1,
        REVIEW_CHANGED: 2,
        REVIEW_WEAK: 3,
        KEEP_GONE: 4,
        KEEP_REMOTE: 5,
    }
    rows.sort(
        key=lambda r: (
            order[r["Recommendation"]],
            r["Purchased Artist"].casefold(),
            r["Purchased Album"].casefold(),
            r["Internet File"].casefold(),
        )
    )
    return rows


def album_summary(purchased, plan, state_of):
    albums = defaultdict(
        lambda: {"tracks": 0, "disk": 0, "internet": set(), "remove": 0, "likely": 0, "folders": {}}
    )
    samples = {}
    for track in purchased:
        key = album_key(track)
        samples.setdefault(key, track)
        entry = albums[key]
        entry["tracks"] += 1
        entry["disk"] += state_of(track)[0] == "OK"
    for row in plan:
        if row["_tier"] == WEAK:
            continue
        entry = albums[row["_album"]]
        entry["internet"].add(row["_track"])
        entry["remove"] += row["Recommendation"] == REMOVE
        entry["likely"] += row["Recommendation"] == LIKELY_DUP
        entry["folders"].setdefault(row["_folder"], set()).add(row["_track"])
    rows = []
    for key, entry in albums.items():
        if not entry["internet"]:
            continue
        sample = samples[key]
        folder, tracks = max(entry["folders"].items(), key=lambda kv: len(kv[1]))
        rows.append(
            {
                "Album": sample.get("Album", ""),
                "Album Artist": sample.get("Album Artist") or sample.get("Artist", ""),
                "Purchased Tracks": entry["tracks"],
                "With Internet Copy": len(entry["internet"]),
                "Purchased File On Disk": entry["disk"],
                "Internet Files To Remove": entry["remove"],
                "Likely Duplicates To Review": entry["likely"],
                "Best Internet Folder": folder,
                "Tracks In That Folder": len(tracks),
            }
        )
    rows.sort(
        key=lambda r: (
            -(r["Internet Files To Remove"] + r["Likely Duplicates To Review"]),
            -r["With Internet Copy"],
            r["Album Artist"].casefold(),
        )
    )
    return rows


def missing_everywhere(apple, purchased_finder, internet_finder, config, loose_seconds):
    """Apple Music tracks that neither the purchased XML nor the downloaded folder holds."""
    rows = []
    for track in apple:
        in_purchased = purchased_finder.find(track, config, loose_seconds)
        in_folder = internet_finder.find(track, config, loose_seconds)
        if any(m["tier"] != WEAK for m in in_purchased + in_folder):
            continue
        status, closest, reason = (
            MISSING,
            "",
            "not in the purchased library or the downloaded folder",
        )
        weak = [("Purchased", m) for m in in_purchased] + [("Downloaded", m) for m in in_folder]
        if weak:
            where, m = min(
                weak, key=lambda w: (-(w[1]["title"] + w[1]["artist"]), w[1]["diff"] or 999)
            )
            b = m["file"]
            status, reason = POSSIBLE, f"{where.lower()}: {m['evidence']}"
            closest = (
                f"Purchased: {b.get('Title', '')} - {b.get('Artist', '')} ({b.get('Album', '')})"
                if where == "Purchased"
                else f"Downloaded: {b['Full Path']}"
            )
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


def reconcile(
    apple_tracks,
    purchased_tracks,
    offline,
    config,
    state_of=purchased_state,
    loose_seconds=LOOSE_SECONDS,
):
    """Pure comparison step: dictionaries in, three lists of Excel rows out."""
    apple = [dict(t) for t in apple_tracks]
    purchased = [dict(t) for t in purchased_tracks]
    for row in apple + purchased:
        prepare_apple(row)
        prepare_query(row)
    for row in offline:
        prepare_offline(row)
    # The purchased files themselves must never be offered as removable copies.
    protected = {
        key_of(location_to_path(t["Location"])) for t in purchased_tracks if t.get("Location")
    }
    candidates = [r for r in offline if key_of(r["Full Path"]) not in protected]
    internet_finder = LooseIndex(candidates)
    purchased_rows = as_file_rows(purchased_tracks)
    for row in purchased_rows:
        prepare_offline(row)
    purchased_finder = LooseIndex(purchased_rows)
    states = {}

    def cached_state(track):
        if id(track) not in states:
            states[id(track)] = state_of(track)
        return states[id(track)]

    plan = plan_internet_copies(purchased, internet_finder, config, cached_state, loose_seconds)
    albums = album_summary(purchased, plan, cached_state)
    missing = missing_everywhere(apple, purchased_finder, internet_finder, config, loose_seconds)
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
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=LOOSE_SECONDS,
        help="Largest duration difference still treated as the same song (default: %(default)s)",
    )
    parser.add_argument("--workspace", help="Workspace directory (default: project folder)")
    parser.add_argument(
        "--config", help="Local JSON settings path (default: workspace/config.json)"
    )
    args = parser.parse_args(argv)
    if not 0 <= args.duration_seconds <= 30:
        parser.error("--duration-seconds must be between 0 and 30")
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
    plan, albums, missing, protected = reconcile(
        apple_tracks, purchased_tracks, offline, c, loose_seconds=args.duration_seconds
    )
    write_xlsx(plan, outputs["Internet_Duplicates_Of_Purchased.xlsx"], PLAN_COLUMNS)
    write_xlsx(albums, outputs["Purchased_Albums_In_Internet_Collection.xlsx"], ALBUM_COLUMNS)
    write_xlsx(missing, outputs["Apple_Music_Missing_Everywhere.xlsx"], MISSING_COLUMNS)

    def count(rows, column, value):
        return sum(r[column] == value for r in rows)

    megabytes = sum(
        r["Internet Size (MB)"] for r in plan if r["Recommendation"] in (REMOVE, LIKELY_DUP)
    )
    tell("\nDownloaded files that duplicate purchased tracks:")
    for label in (REMOVE, LIKELY_DUP, KEEP_REMOTE, KEEP_GONE, REVIEW_CHANGED, REVIEW_WEAK):
        tell(f"  {label}: {count(plan, 'Recommendation', label):,}")
    tell(f"  Space held by REMOVE CANDIDATE and LIKELY DUPLICATE files: {megabytes / 1000:,.1f} GB")
    tell("\nApple Music tracks not in the purchased library or the downloaded folder:")
    tell(f"  {MISSING}: {count(missing, 'Status', MISSING):,}")
    tell(f"  {POSSIBLE}: {count(missing, 'Status', POSSIBLE):,}  (check by hand)")
    if errors:
        tell(
            f"\n{len(errors)} folder(s) could not be fully read; those files are not in the results."
        )
    tell("\nNothing was deleted or changed. Review the Excel files, then remove files yourself:")
    for path in outputs.values():
        tell(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
