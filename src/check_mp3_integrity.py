"""Find MP3 files that are damaged: skipped chunks, truncated downloads, decoder errors.

Read-only: files are only opened for reading and nothing is repaired, moved or deleted.
Every MP3 gets a structure scan in pure Python (no FFmpeg needed) that walks the MPEG
frames and reports

* places where bytes were cut out or replaced (a "lost sync" gap between frames),
* a final frame that is cut off,
* a file with fewer frames or bytes than its own Xing/Info/VBRI header says it should have
  (the telltale sign of an incomplete download or dropped data),
* an ID3 length tag (TLEN) longer than the audio that is actually there.

With --decode each file is also decoded with FFmpeg to a discarded output. That catches
damage the structure scan cannot, for example whole frames removed from a stream.

Results are written to an Excel workbook inside the workspace output directory.
"""

import argparse
import mmap
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from compare_libraries import as_file_rows, ask_folders, output_path, read_tracks, write_xlsx
from config import load
from normalization import prepare_apple, prepare_offline
from track_matching import LooseIndex
from track_matching import prepare as prepare_query

OK, SUSPECT, CORRUPT, UNREADABLE = "OK", "SUSPECT", "CORRUPT", "UNREADABLE"
VERDICT_ORDER = {CORRUPT: 0, UNREADABLE: 1, SUSPECT: 2, OK: 3}
COLUMNS = (
    "Verdict",
    "File",
    "Issues",
    "Duration (s)",
    "Library Duration (s)",
    "Library Track",
    "First Problem At (s)",
    "Frames Found",
    "Frames Expected",
    "Frames Missing",
    "Gaps Found",
    "Bytes Skipped",
    "Ends Mid-Frame",
    "Decoder Errors",
    "First Decoder Error",
    "Bitrate (kbps)",
    "Size (MB)",
)

# Verdict thresholds. Tolerances absorb the small differences real encoders produce.
FRAME_TOLERANCE = 2  # frames the Xing header may disagree by
BYTES_TOLERANCE = 0.01  # fraction of the audio bytes the Xing header may disagree by
GAP_CORRUPT_BYTES = 128  # bytes lost between frames: a real chunk, not stray padding
GAP_CORRUPT_COUNT = 2  # or this many separate gaps
DECODER_CORRUPT_ERRORS = 3
LENGTH_TAG_TOLERANCE = 0.03  # fraction, with a 3 second floor
SHORTFALL_SECONDS = 2  # a library track this much longer than the audio is suspicious
SHORTFALL_FRACTION = 0.01

BITRATES = {
    (1, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def parse_header(data, pos):
    """Return (length, samples, rate, kbps, version, layer, mono, has_crc) or None."""
    if pos + 4 > len(data) or data[pos] != 0xFF:
        return None
    b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
    version, layer = (b1 >> 3) & 3, 4 - ((b1 >> 1) & 3)
    if (b1 & 0xE0) != 0xE0 or version == 1 or layer == 4:
        return None
    bitrate_index, rate_index = b2 >> 4, (b2 >> 2) & 3
    if bitrate_index in (0, 15) or rate_index == 3:
        return None
    family = 1 if version == 3 else 2
    kbps = BITRATES[(family, layer)][bitrate_index]
    rate = SAMPLE_RATES[version][rate_index]
    padding = (b2 >> 1) & 1
    if layer == 1:
        length, samples = (12 * kbps * 1000 // rate + padding) * 4, 384
    elif layer == 2 or family == 1:
        length, samples = 144 * kbps * 1000 // rate + padding, 1152
    else:
        length, samples = 72 * kbps * 1000 // rate + padding, 576
    return length, samples, rate, kbps, version, layer, (b3 >> 6) == 3, not (b1 & 1)


def find_sync(data, pos, end):
    """Next offset where three consecutive frames with matching parameters start."""
    while True:
        pos = data.find(b"\xff", pos, end)
        if pos < 0:
            return None
        head = parse_header(data, pos)
        if head and pos + head[0] <= end:
            ok, follow = True, pos + head[0]
            for _ in range(2):
                if follow >= end:
                    break
                nxt = parse_header(data, follow)
                if not nxt or nxt[2:3] != head[2:3] or nxt[4:6] != head[4:6]:
                    ok = False
                    break
                follow += nxt[0]
            if ok:
                return pos
        pos += 1


def id3v2_end(data):
    """Offset just past any ID3v2 tag(s) at the start of the file."""
    pos = 0
    while data[pos : pos + 3] == b"ID3" and len(data) >= pos + 10:
        size = 0
        for byte in data[pos + 6 : pos + 10]:
            size = (size << 7) | (byte & 0x7F)
        pos += 10 + size + (10 if data[pos + 5] & 0x10 else 0)
    return pos


def audio_end(data):
    """Offset where the audio stops: before a trailing ID3v1 or APEv2 tag."""
    end = len(data)
    if end >= 128 and data[end - 128 : end - 125] == b"TAG":
        end -= 128
    if end >= 32 and data[end - 32 : end - 24] == b"APETAGEX":
        size = int.from_bytes(data[end - 20 : end - 16], "little")
        flags = int.from_bytes(data[end - 12 : end - 8], "little")
        end -= size + (32 if flags & (1 << 31) else 0)
    return max(end, 0)


def read_info_header(data, pos, head):
    """Expected (frames, bytes) from a Xing/Info/VBRI frame, or None if this is a normal frame."""
    length, _, _, _, version, _, mono, has_crc = head
    side = (17 if mono else 32) if version == 3 else (9 if mono else 17)
    tag = pos + 4 + (2 if has_crc else 0) + side
    if data[tag : tag + 4] in (b"Xing", b"Info"):
        flags = int.from_bytes(data[tag + 4 : tag + 8], "big")
        cursor, frames, size = tag + 8, None, None
        if flags & 1:
            frames, cursor = int.from_bytes(data[cursor : cursor + 4], "big"), cursor + 4
        if flags & 2:
            size = int.from_bytes(data[cursor : cursor + 4], "big")
        return frames, size
    if data[pos + 36 : pos + 40] == b"VBRI":
        return (
            int.from_bytes(data[pos + 46 : pos + 50], "big"),
            int.from_bytes(data[pos + 42 : pos + 46], "big"),
        )
    return None


def length_tag_seconds(path):
    """The ID3 TLEN value in seconds, if the tag exists and mutagen is installed."""
    try:
        from mutagen.id3 import ID3

        frame = ID3(path).get("TLEN")
        return int(str(frame.text[0])) / 1000 if frame else None
    except Exception:
        return None


def scan(path):
    """Structure scan of one MP3. Returns a result dictionary (never raises for bad files)."""
    result = {
        "path": str(path),
        "frames": 0,
        "expected_frames": None,
        "expected_bytes": None,
        "gaps": [],  # (offset, bytes lost, seconds into the file)
        "partial_tail": 0,
        "trailing_junk": 0,
        "param_changes": 0,
        "seconds": 0.0,
        "kbps": None,
        "size": 0,
        "problem": None,
    }
    try:
        with open(path, "rb") as handle:
            result["size"] = size = Path(path).stat().st_size
            if size == 0:
                result["problem"] = "empty file"
                return result
            data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                _scan_frames(data, result)
            finally:
                data.close()
    except (OSError, ValueError) as error:
        result["problem"] = f"cannot read file: {error}"
    return result


def _scan_frames(data, result):
    end = audio_end(data)
    start = id3v2_end(data)
    pos = find_sync(data, start, end)
    if pos is None:
        result["problem"] = (
            "looks like an MP4/M4A file renamed to .mp3"
            if data[4:8] == b"ftyp"
            else "no MP3 audio frames found"
        )
        return
    first, samples_total, previous = pos, 0, None
    bitrates = set()
    while pos < end:
        head = parse_header(data, pos)
        if head:
            length = head[0]
            if pos + length > end:
                result["partial_tail"] = end - pos
                break
            result["rate"] = head[2]
            params = head[2:3] + head[4:6]
            if previous is not None and params != previous:
                result["param_changes"] += 1
            previous = params
            if pos == first:
                info = read_info_header(data, pos, head)
                if info:
                    result["expected_frames"], result["expected_bytes"] = info
                    pos += length
                    continue
            result["frames"] += 1
            bitrates.add(head[3])
            samples_total += head[1]
            pos += length
            continue
        resumed = find_sync(data, pos + 1, end)
        at = samples_total / result.get("rate", 44100)
        if resumed is None:
            leftover = bytes(data[pos:end])
            if leftover.strip(b"\0"):
                result["trailing_junk"] = len(leftover)
            break
        result["gaps"].append((pos, resumed - pos, at))
        pos = resumed
    rate = result.get("rate", 44100)
    result["seconds"] = samples_total / rate
    result["audio_bytes"] = end - first
    result["kbps"] = bitrates.pop() if len(bitrates) == 1 else None
    if result["frames"] == 0:
        result["problem"] = "no complete MP3 frames"


def decode_errors(path, timeout=600):
    """Decode with FFmpeg to nowhere. Returns (error count, first error line)."""
    try:
        run = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, f"could not run FFmpeg: {error}"
    lines = [
        line
        for line in run.stderr.decode("utf-8", "replace").splitlines()
        if line.strip() and not re.match(r"^\[(png|mjpeg|jpeg2000|bmp|gif|webp) @", line)
    ]
    return len(lines), (lines[0][:200] if lines else "")


def library_shortfall(path, seconds, reference, config):
    """Compare with the same song in a library: (library seconds, label) if this file is much shorter.

    Dropped frames in a file with no length header leave nothing inside the file to see, but
    the audio ends up shorter than the real track. A shorter edit also looks like this, so the
    result is only ever a SUSPECT note.
    """
    try:
        from mutagen import File

        tags = File(path, easy=True) or {}
        title, artist = tags["title"][0], tags["artist"][0]
    except Exception:
        return None
    query = {
        "Name": title,
        "Artist": artist,
        "Album": (tags.get("album") or [""])[0],
        "Total Time": seconds * 1000,
    }
    prepare_apple(query)
    prepare_query(query)
    same = [
        m
        for m in reference.find(query, config, loose_seconds=1e9)
        if m["same_kind"] and m["title"] >= 94 and m["artist"] >= 90
    ]
    lengths = [(m["file"].get("Duration") or 0, m["file"]) for m in same]
    lengths = [(d, f) for d, f in lengths if d]
    if not lengths:
        return None
    if any(abs(d - seconds) <= max(SHORTFALL_SECONDS, d * SHORTFALL_FRACTION) for d, _ in lengths):
        return None
    longest, track = min(lengths, key=lambda item: item[0])  # the closest of the longer ones
    if all(d > seconds for d, _ in lengths):
        return longest, f"{track.get('Title', '')} - {track.get('Artist', '')}"
    return None


def judge(result, decode=None, length_tag=None, shortfall=None):
    """Turn scan facts into (verdict, [issues]). Thresholds are the constants above."""
    if result["problem"]:
        return UNREADABLE, [result["problem"]]
    issues, corrupt, suspect = [], False, False
    per_frame = result["seconds"] / result["frames"] if result["frames"] else 0.026
    expected = result["expected_frames"]
    if expected is not None:
        missing = expected - result["frames"]
        # Encoders disagree on whether the header counts its own frame; allow for that.
        if missing > FRAME_TOLERANCE:
            corrupt = True
            issues.append(
                f"{missing} frames missing (about {missing * per_frame:.1f} s): the file has "
                f"fewer frames than its own header says"
            )
    wanted = result["expected_bytes"]
    if wanted and result["audio_bytes"] < wanted * (1 - BYTES_TOLERANCE):
        corrupt = True
        issues.append(
            f"file is {(wanted - result['audio_bytes']) / 1024:.0f} KB shorter than its header says"
        )
    gaps = result["gaps"]
    lost = sum(g[1] for g in gaps)
    if gaps:
        text = f"{len(gaps)} gap(s) where data was cut out ({lost} bytes lost), first at {gaps[0][2]:.1f} s"
        issues.append(text)
        if lost >= GAP_CORRUPT_BYTES or len(gaps) >= GAP_CORRUPT_COUNT:
            corrupt = True
        else:
            suspect = True
    if result["partial_tail"]:
        suspect = True
        issues.append(f"ends in the middle of a frame ({result['partial_tail']} bytes): cut off")
    if result["trailing_junk"] >= 1:
        suspect = True
        issues.append(f"{result['trailing_junk']} bytes of unrecognised data after the audio")
    if result["param_changes"]:
        suspect = True
        issues.append(f"sample rate or format changes {result['param_changes']} time(s) mid-file")
    if length_tag and result["seconds"] < length_tag - max(3.0, length_tag * LENGTH_TAG_TOLERANCE):
        suspect = True
        issues.append(
            f"length tag says {length_tag:.0f} s but the audio is only {result['seconds']:.0f} s"
        )
    if shortfall:
        suspect = True
        issues.append(
            f"audio is {shortfall[0] - result['seconds']:.0f} s shorter than '{shortfall[1]}' in "
            f"your library ({shortfall[0]:.0f} s): cut off, or a shorter edit"
        )
    if decode is not None and decode[0]:
        if decode[0] >= DECODER_CORRUPT_ERRORS:
            corrupt = True
        else:
            suspect = True
        issues.append(f"FFmpeg reported {decode[0]} decoder error(s)")
    return (CORRUPT if corrupt else SUSPECT if suspect else OK), issues


def check_file(path, root, decode, timeout, reference=None, config=None):
    result = scan(path)
    errors = decode_errors(path, timeout) if decode and not result["problem"] else None
    ok = not result["problem"]
    shortfall = (
        library_shortfall(path, result["seconds"], reference, config) if reference and ok else None
    )
    verdict, issues = judge(result, errors, length_tag_seconds(path) if ok else None, shortfall)
    gaps = result["gaps"]
    expected = result["expected_frames"]
    missing = max(0, expected - result["frames"]) if expected is not None else ""
    return {
        "Verdict": verdict,
        "File": str(Path(path).relative_to(root)),
        "Issues": "; ".join(issues),
        "Duration (s)": round(result["seconds"], 1) if result["frames"] else "",
        "Library Duration (s)": round(shortfall[0], 1) if shortfall else "",
        "Library Track": shortfall[1] if shortfall else "",
        "First Problem At (s)": round(gaps[0][2], 1) if gaps else "",
        "Frames Found": result["frames"],
        "Frames Expected": expected if expected is not None else "",
        "Frames Missing": missing,
        "Gaps Found": len(gaps),
        "Bytes Skipped": sum(g[1] for g in gaps),
        "Ends Mid-Frame": "yes" if result["partial_tail"] else "",
        "Decoder Errors": errors[0] if errors else "",
        "First Decoder Error": errors[1] if errors else "",
        "Bitrate (kbps)": result["kbps"] or "",
        "Size (MB)": round(result["size"] / 1_000_000, 2),
    }


def find_mp3s(roots):
    files = []
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            if path.suffix.lower() == ".mp3" and path.is_file() and not path.is_symlink():
                if not path.name.startswith("._"):
                    files.append((Path(root), path))
    return files


def main(argv=None, ask=input, tell=print):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Check MP3 files for damage such as skipped chunks, truncation and "
        "decoder errors (read-only; writes an Excel report)"
    )
    parser.add_argument(
        "--music-root",
        action="append",
        help="Folder to check; repeat for several (default: saved folders, else asked)",
    )
    parser.add_argument(
        "--decode",
        action="store_true",
        help="Also decode every file with FFmpeg (slower; finds damage the scan cannot)",
    )
    parser.add_argument(
        "--library",
        action="append",
        help="iTunes/Apple Music XML to compare durations with (repeat for several); flags "
        "files much shorter than the same song in the library",
    )
    parser.add_argument("--all", action="store_true", help="List healthy files too")
    parser.add_argument("--output", help="Excel .xlsx path inside the workspace")
    parser.add_argument("--workspace", help="Workspace directory (default: project folder)")
    parser.add_argument(
        "--config", help="Local JSON settings path (default: workspace/config.json)"
    )
    args = parser.parse_args(argv)
    c = load(args.config, args.workspace)
    if (
        not (args.music_root or c["offline_music_roots"])
        and not sys.stdin.isatty()
        and ask is input
    ):
        parser.error("Supply --music-root when not running in a terminal.")
    roots = args.music_root or c["offline_music_roots"] or ask_folders(ask, tell)
    c = load(args.config, args.workspace, {"offline_music_roots": roots})
    for root in c["offline_music_roots"]:
        if not Path(root).is_dir():
            parser.error(f"Music folder unavailable: {root}. Connect the drive and retry.")
    if args.decode and not shutil.which("ffmpeg"):
        parser.error("--decode needs ffmpeg installed and on PATH.")
    destination = output_path(c, args.output, "MP3_Integrity_Report.xlsx")
    reference = None
    if args.library:
        library_rows = []
        for xml in args.library:
            if not Path(xml).expanduser().is_file():
                parser.error(f"Library XML not found: {xml}")
            library_rows += as_file_rows(read_tracks(Path(xml).expanduser()))
        for row in library_rows:
            prepare_offline(row)
        reference = LooseIndex(library_rows)
        tell(f"Library tracks for duration cross-check: {len(library_rows):,}")
    files = find_mp3s(c["offline_music_roots"])
    tell(f"MP3 files found: {len(files):,}" + (" (scan + FFmpeg decode)" if args.decode else ""))

    def work(item):
        root, path = item
        try:
            return check_file(path, root, args.decode, c["deep_timeout_seconds"], reference, c)
        except Exception as error:  # one bad file must not stop the run
            return {
                "Verdict": UNREADABLE,
                "File": str(path.relative_to(root)),
                "Issues": str(error),
            }

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    def progress(items):
        return tqdm(items, total=len(files), desc="Checking", mininterval=5) if tqdm else items

    with ThreadPoolExecutor(max_workers=c["workers"]) as pool:
        rows = list(progress(pool.map(work, files)))
    counts = {v: sum(r["Verdict"] == v for r in rows) for v in (OK, SUSPECT, CORRUPT, UNREADABLE)}
    shown = rows if args.all else [r for r in rows if r["Verdict"] != OK]
    shown.sort(key=lambda r: (VERDICT_ORDER[r["Verdict"]], r["File"].casefold()))
    write_xlsx(shown, destination, COLUMNS)
    tell(f"\nCORRUPT:    {counts[CORRUPT]:,}  (data missing or cut out; replace these)")
    tell(f"SUSPECT:    {counts[SUSPECT]:,}  (minor signs of damage; listen to them)")
    tell(f"UNREADABLE: {counts[UNREADABLE]:,}  (not a usable MP3)")
    tell(f"OK:         {counts[OK]:,}")
    if not args.decode:
        tell("Run again with --decode to also test every file with FFmpeg (slower, more thorough).")
    tell(f"Report written: {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
