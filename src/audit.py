import argparse
import logging
import shutil
import sys
from pathlib import Path
from config import load, read_overrides, save
from apple_music_xml import read_xml
from audio_scanner import discover, inventory
from excel_report import write_report


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Read-only music library audit")
    parser.add_argument(
        "--inspect",
        "--dry-run",
        action="store_true",
        dest="inspect",
        help="Validate inputs and discover files without scanning audio",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Build cached inventory and preliminary workbook",
    )
    parser.add_argument(
        "--workspace",
        help="Directory for local settings, cache, and reports (default: project folder)",
    )
    parser.add_argument(
        "--config", help="Local JSON settings path (default: workspace/config.json)"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Ask for XML and music folders, then save settings without scanning",
    )
    parser.add_argument("--xml", help="Use this XML export for this run")
    parser.add_argument(
        "--music-root",
        action="append",
        help="Music folder; repeat for multiple folders (replaces saved list)",
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Persist command-line input paths in local settings",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting if inputs are unconfigured",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Review REVIEW candidates interactively after matching",
    )
    parser.add_argument(
        "--no-review", action="store_true", help="Do not offer interactive review after matching"
    )
    args = parser.parse_args()
    updates = {}
    if args.xml:
        updates["apple_music_xml"] = args.xml
    if args.music_root is not None:
        updates["offline_music_roots"] = args.music_root
    c = load(args.config, args.workspace, updates)
    if args.setup or not c["offline_music_roots"]:
        if args.non_interactive:
            parser.error(
                "Inputs unconfigured. Supply --xml and --music-root, or run --setup interactively."
            )
        if not args.setup and not sys.stdin.isatty():
            parser.error("No music folders configured. Run --setup or supply --music-root.")
        from setup_wizard import configure

        c = configure(c)
        if args.setup:
            return
    elif args.save_config:
        save(c)
    output = Path(c["output_excel"]).parent
    output.mkdir(parents=True, exist_ok=True)
    Path(c["cache_directory"]).mkdir(parents=True, exist_ok=True)
    Path(c["output_excel"]).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=output / "audit.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    if not Path(c["apple_music_xml"]).is_file():
        raise FileNotFoundError("XML unavailable. Restore it, pass --xml, or rerun --setup.")
    for p in c["offline_music_roots"]:
        if not Path(p).is_dir():
            raise FileNotFoundError(
                f"Music folder unavailable: {p}. Connect the drive or rerun --setup."
            )
    overrides = read_overrides(c)
    for tool in ("ffprobe", "ffmpeg"):
        print(f"{tool}: {shutil.which(tool) or 'NOT AVAILABLE'}", flush=True)
        if not shutil.which(tool) and (tool == "ffprobe" or c["deep_integrity_check"]):
            raise RuntimeError(f"{tool} must be installed and on PATH")
    import tempfile

    with tempfile.TemporaryFile(dir=Path(c["output_excel"]).parent) as f:
        f.write(b"writability check")
    apple = read_xml(c["apple_music_xml"])
    files, errors = discover(c["offline_music_roots"])
    if args.inspect:
        print(
            f"Inspection complete: {len(files):,} files; discovery errors: {len(errors)}",
            flush=True,
        )
        return
    offline = inventory(files, c)
    # Save original Apple metadata before comparisons are added.
    write_report(
        output / "Preliminary_Inventory.xlsx",
        {"Apple Music Library": apple, "Offline Library": offline},
    )
    if args.inventory_only:
        return
    from normalization import prepare_apple, prepare_offline
    from matcher import match_all
    from duplicate_detector import duplicates
    from album_audit import audit_albums
    from dashboard import dashboard

    for row in apple:
        prepare_apple(row)
    for row in offline:
        prepare_offline(row)
    print("Matching tracks...", flush=True)
    matches = match_all(apple, offline, c, overrides)
    if args.review or (not args.non_interactive and not args.no_review):
        from review import review_matches

        should_review = args.review
        if not should_review:
            answer = input(
                f"Review the {sum(row.get('Status') == 'REVIEW' for row in matches):,} REVIEW entries now? [yes/no]: "
            )
            should_review = answer.strip().casefold() in {"yes", "y"}
        if should_review:
            matches, overrides = review_matches(
                apple, matches, overrides, c["manual_matches_file"], offline
            )
    print("Checking duplicates...", flush=True)
    dup = duplicates(offline)
    print("Auditing albums...", flush=True)
    albums = audit_albums(offline)
    summary = dashboard(apple, offline, matches, dup, albums, errors)
    write_report(
        c["output_excel"],
        {
            "Dashboard": summary,
            "Apple Music Library": apple,
            "Offline Library": offline,
            "Match Results": matches,
            "Album Audit": albums,
            "Duplicates": dup,
        },
    )
    for row in summary:
        print(f"{row['Metric']}: {row['Value']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Audit failed")
        raise
