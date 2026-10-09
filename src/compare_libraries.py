"""Compare an Apple Music XML export with a purchased-music XML export.

Writes a multi-column Excel file of Apple Music tracks that are NOT confidently present in
the purchased library. Both XML files are read-only inputs; the workbook is written inside
the workspace output directory.
"""

import argparse
import os
import plistlib
import sys
from pathlib import Path
from config import load, resolve_path
from normalization import comparison

# Store-link fields are not guaranteed to exist; any of these that hold a URL are used.
LINK_FIELDS = ("Store URL", "iTunes URL", "Apple Music URL", "URL", "Track URL", "Album URL")
COLUMNS = (
    "Title",
    "Artist",
    "Album",
    "Year",
    "Duration",
    "iTunes Link",
    "Status",
    "Closest Purchased Track",
    "Reason",
)
MATCHED, POSSIBLE, NOT_FOUND = "MATCHED", "POSSIBLE MATCH", "NOT IN PURCHASED"


def read_tracks(path):
    with open(path, "rb") as f:
        document = plistlib.load(f)
    tracks = document.get("Tracks") if isinstance(document, dict) else None
    if not isinstance(tracks, dict):
        raise ValueError(f"{path} is not an iTunes/Apple Music library XML with a Tracks section")
    return list(tracks.values())


def prepare(track):
    """Comparison-only keys; the original track dictionary is left untouched."""
    c = comparison(track.get("Name", ""), track.get("Artist", ""), track.get("Album", ""))
    return {
        "track": track,
        "title": c["Normalized Title"],
        "base": c["Normalized Base Title"],
        "versions": tuple(c["Version Markers"]),
        "artists": frozenset(c["Credited Artists"]),
        "seconds": (track.get("Total Time") or 0) / 1000 or None,
        "video": bool(track.get("Has Video") or track.get("Music Video")),
        "persistent": track.get("Persistent ID"),
    }


def index(rows):
    by_persistent, by_exact, by_base = {}, {}, {}
    for r in rows:
        if r["persistent"]:
            by_persistent.setdefault(r["persistent"], []).append(r)
        by_exact.setdefault((r["title"], r["versions"], r["artists"]), []).append(r)
        by_base.setdefault(r["base"], []).append(r)
    return by_persistent, by_exact, by_base


def describe(row):
    t = row["track"]
    return f"{t.get('Name', '')} - {t.get('Artist', '')} ({t.get('Album', '')})"


def closest(row, candidates):
    """Prefer the candidate whose duration is nearest; unknown durations sort last."""
    if row["seconds"] is None:
        return candidates[0]
    return min(
        candidates,
        key=lambda c: abs(c["seconds"] - row["seconds"]) if c["seconds"] else float("inf"),
    )


def classify(row, indexes, tolerance):
    """Return (status, purchased row or None, reason). Conservative: doubt is never a match."""
    by_persistent, by_exact, by_base = indexes
    if row["persistent"] in by_persistent:
        return MATCHED, by_persistent[row["persistent"]][0], "same Persistent ID"
    exact = by_exact.get((row["title"], row["versions"], row["artists"]), [])
    near = [
        c
        for c in exact
        if row["seconds"] is not None
        and c["seconds"] is not None
        and abs(c["seconds"] - row["seconds"]) <= tolerance
        and c["video"] == row["video"]
    ]
    if near:
        return MATCHED, closest(row, near), "title, artist, version and duration agree"
    if exact:
        pick = closest(row, exact)
        if row["video"] != pick["video"]:
            why = "title and artist agree but one is a video"
        elif row["seconds"] is None or pick["seconds"] is None:
            why = "title and artist agree but a duration is missing"
        else:
            why = f"title and artist agree but duration differs by {abs(pick['seconds'] - row['seconds']):.0f}s"
        return POSSIBLE, pick, why
    similar = [c for c in by_base.get(row["base"], []) if c["artists"] & row["artists"]]
    if similar:
        pick = closest(row, similar)
        if pick["versions"] != row["versions"]:
            return POSSIBLE, pick, "same song and artist but a different version/edit"
        return POSSIBLE, pick, "same song but the artist credits differ"
    return NOT_FOUND, None, "no purchased track with this title and artist"


def link_for(track):
    for field in LINK_FIELDS:
        value = track.get(field)
        if isinstance(value, str) and value.startswith(("http://", "https://", "itms")):
            return value
    return ""


def duration_text(track):
    ms = track.get("Total Time")
    return f"{int(ms // 60000)}:{int(ms // 1000 % 60):02d}" if ms else ""


def compare(apple_tracks, purchased_tracks, tolerance=3, include_matched=False):
    """Return row dictionaries for Apple Music tracks, sorted for browsing."""
    indexes = index([prepare(t) for t in purchased_tracks])
    results = []
    for track in apple_tracks:
        status, other, reason = classify(prepare(track), indexes, tolerance)
        if status == MATCHED and not include_matched:
            continue
        results.append(
            {
                "Title": track.get("Name", ""),
                "Artist": track.get("Artist", ""),
                "Album": track.get("Album", ""),
                "Year": track.get("Year", ""),
                "Duration": duration_text(track),
                "iTunes Link": link_for(track),
                "Status": status,
                "Closest Purchased Track": describe(other) if other else "",
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
    results.sort(key=lambda r: r["_sort"])
    return results


def write_xlsx(rows, destination, columns=COLUMNS):
    """Write the table as a workbook: every column is its own cell, text stays literal."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(list(columns))
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column, "")
            if isinstance(value, str):
                value = ILLEGAL_CHARACTERS_RE.sub("", value)[:32767]
            values.append(value)
        ws.append(values)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"  # literal text, never a formula
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for index_, column in enumerate(columns, 1):
        longest = max([len(str(column))] + [len(str(r.get(column, ""))) for r in rows[:500]])
        ws.column_dimensions[ws.cell(1, index_).column_letter].width = min(max(longest + 2, 10), 60)
    temporary = destination.with_name(destination.stem + ".tmp.xlsx")
    wb.save(temporary)
    os.replace(temporary, destination)


def candidate_xmls(workspace):
    found = []
    for folder in (Path.cwd(), workspace, workspace / "input"):
        if folder.is_dir():
            for path in sorted(folder.glob("*.xml")):
                if path.resolve() not in found:
                    found.append(path.resolve())
    return found


def choose_xml(label, workspace, ask=input, tell=print, exclude=None):
    """Pick from XML files found nearby, or type/drag in a path."""
    options = [p for p in candidate_xmls(workspace) if p != exclude]
    tell(f"\nChoose the {label} XML.")
    for number, path in enumerate(options, 1):
        tell(f"  {number}. {path}")
    while True:
        hint = "number or path" if options else "path"
        raw = ask(f"{label} XML ({hint}): ").strip().strip('"').strip("'")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw:
            path = resolve_path(raw, workspace)
            if path.is_file():
                return path
        tell("That is not an existing file. Try again.")


def output_path(c, requested=None, default_name="Apple_Music_Not_In_Purchased.xlsx"):
    """Workbook destination: inside the workspace output folder, never over an input or music root."""
    workspace = Path(c["_workspace"])
    default = Path(c["output_excel"]).parent / default_name
    path = resolve_path(requested, workspace) if requested else default
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Output must end in .xlsx")
    if not path.is_relative_to(workspace):
        raise ValueError("The workbook must be written inside the workspace")
    if any(path.is_relative_to(Path(root)) for root in c["offline_music_roots"]):
        raise ValueError("The workbook cannot be written inside a read-only music folder")
    return path


def main(argv=None, ask=input, tell=print):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Compare an Apple Music library XML with a purchased-music library XML "
        "and write an Excel file of Apple Music tracks missing from the purchased library"
    )
    parser.add_argument("--apple", help="Apple Music library XML (asked for if omitted)")
    parser.add_argument("--purchased", help="Purchased music library XML (asked for if omitted)")
    parser.add_argument(
        "--output", help="Excel .xlsx path inside the workspace (default: output/*.xlsx)"
    )
    parser.add_argument("--workspace", help="Workspace directory (default: project folder)")
    parser.add_argument(
        "--config", help="Local JSON settings path (default: workspace/config.json)"
    )
    parser.add_argument(
        "--include-matched",
        action="store_true",
        help="Also list tracks found in the purchased library (Status = MATCHED)",
    )
    args = parser.parse_args(argv)
    c = load(args.config, args.workspace)
    workspace = Path(c["_workspace"])
    interactive = args.apple is None or args.purchased is None
    if interactive and not sys.stdin.isatty() and ask is input:
        parser.error("Supply --apple and --purchased when not running in a terminal.")
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
    for path in (apple, purchased):
        if not path.is_file():
            parser.error(f"XML file not found: {path}")
    if apple == purchased:
        parser.error("Choose two different XML files.")
    destination = output_path(c, args.output)
    if destination in (apple, purchased):
        parser.error("The workbook cannot overwrite an input XML.")
    apple_tracks, purchased_tracks = read_tracks(apple), read_tracks(purchased)
    rows = compare(
        apple_tracks,
        purchased_tracks,
        c["duration_tolerance_seconds"],
        args.include_matched,
    )
    write_xlsx(rows, destination)
    counts = {s: sum(r["Status"] == s for r in rows) for s in (MATCHED, POSSIBLE, NOT_FOUND)}
    tell(f"\nApple Music tracks:    {len(apple_tracks):,}")
    tell(f"Purchased tracks:      {len(purchased_tracks):,}")
    if args.include_matched:
        tell(f"Matched:               {counts[MATCHED]:,}")
    else:
        tell(f"Matched (not listed):  {len(apple_tracks) - len(rows):,}")
    tell(f"Possible match:        {counts[POSSIBLE]:,}  (check these by hand)")
    tell(f"Not in purchased:      {counts[NOT_FOUND]:,}")
    if not any(r["iTunes Link"] for r in rows):
        tell("No iTunes/store link fields exist in this XML, so that column is empty.")
    tell(f"Excel file written: {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
