import concurrent.futures
import hashlib
import logging
import os
import re
import struct
from collections import Counter
from pathlib import Path

import mutagen
from mutagen.id3 import ID3
from mutagen.flac import Picture
from tqdm import tqdm

from config import EXTENSIONS
from integrity import probe, deep_check
from cache import Cache


def discover(roots):
    files, errors, seen = [], [], set()
    for root in roots:
        count = 0

        def onerror(error):
            errors.append(str(error))
            logging.warning("Discovery: %s", error)

        for directory, dirs, names in os.walk(root, onerror=onerror, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if not Path(directory, d).is_symlink()
                and not getattr(Path(directory, d), "is_junction", lambda: False)()
            ]
            for name in names:
                p = Path(directory, name)
                if p.suffix.lower() in EXTENSIONS and not p.is_symlink():
                    key = os.path.normcase(os.path.abspath(p))
                    if key not in seen:
                        seen.add(key)
                        files.append((str(root), p))
                        count += 1
        print(f"{root}: {count:,} supported files", flush=True)
    return files, errors


def text_value(value):
    if value is None:
        return ""
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        return "; ".join(text_value(v) for v in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def number(value):
    m = re.search(r"\d+", str(value or ""))
    return int(m.group()) if m else None


def dimensions(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return "%sx%s" % struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 255:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in (0xD8, 0xD9) or marker == 0:
                continue
            length = int.from_bytes(data[i : i + 2], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3) and length >= 7:
                h, w = struct.unpack(">HH", data[i + 3 : i + 7])
                return f"{w}x{h}"
            if length < 2:
                break
            i += length
    return ""


def scan_one(root, path, config):
    stat = path.stat()
    row = {
        "Library Root": root,
        "Full Path": str(path),
        "Relative Path": str(path.relative_to(root)),
        "Filename": path.name,
        "Extension": path.suffix.lower(),
        "File Size": stat.st_size,
        "Modification Time": stat.st_mtime,
        "Metadata Readable": False,
        "Scan Error": "",
    }
    with path.open("rb") as header:
        magic = header.read(4)
    if magic == b"\x00\x05\x16\x07":
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        row.update(
            {
                "File Type": "AppleDouble metadata sidecar",
                "Archive Eligible": False,
                "Integrity": "NOT AUDIO",
                "Deep Integrity": "NOT TESTED",
                "FFprobe OK": False,
                "FFprobe Error": "Not probed: AppleDouble header identifies a metadata sidecar",
                "DRM Status": "Not applicable",
                "Source Classification": "Unknown",
                "SHA-256": digest.hexdigest(),
                "Metadata Issues": "AppleDouble sidecar, not an audio recording",
                "Artwork Present": False,
                "Artwork Count": 0,
            }
        )
        return row
    row["File Type"] = "Audio candidate"
    tags, audio, pictures = {}, None, []
    try:
        audio = mutagen.File(path)
        if audio is None:
            raise ValueError("Mutagen did not recognize audio")
        native_tags = audio.tags
        tags = dict(native_tags or {})
        row["Metadata Readable"] = True

        def tag(*keys):
            for key in keys:
                if key in tags:
                    return text_value(tags[key])
            return ""

        for field, keys in {
            "Title": ("\xa9nam", "TIT2", "title", "Title"),
            "Artist": ("\xa9ART", "TPE1", "artist", "Author"),
            "Album Artist": ("aART", "TPE2", "albumartist", "album artist", "WM/AlbumArtist"),
            "Album": ("\xa9alb", "TALB", "album", "WM/AlbumTitle"),
            "Genre": ("\xa9gen", "TCON", "genre", "WM/Genre"),
            "Date": ("\xa9day", "TDRC", "TYER", "date", "year", "WM/Year"),
        }.items():
            row[field] = tag(*keys)
        row["Year"] = number(row["Date"])
        for label, mp4, keys, totalkeys in [
            (
                "Track",
                "trkn",
                ("TRCK", "tracknumber", "WM/TrackNumber"),
                ("tracktotal", "totaltracks"),
            ),
            ("Disc", "disk", ("TPOS", "discnumber", "WM/PartOfSet"), ("disctotal", "totaldiscs")),
        ]:
            if mp4 in tags:
                pair = tags[mp4][0]
                row[label + " Number"], row[label + " Total"] = pair[0] or None, pair[1] or None
            else:
                raw = tag(*keys).split("/")
                row[label + " Number"] = number(raw[0])
                row[label + " Total"] = number(raw[1]) if len(raw) > 1 else number(tag(*totalkeys))
        if isinstance(native_tags, ID3):
            pictures.extend(p.data for p in native_tags.getall("APIC"))
        pictures.extend(bytes(p) for p in tags.get("covr", []))
        pictures.extend(p.data for p in getattr(audio, "pictures", []))
        import base64

        for p in tags.get("metadata_block_picture", []):
            pictures.append(Picture(base64.b64decode(p)).data)
        for p in tags.get("WM/Picture", []):
            raw = bytes(p.value)
            # ASF picture: type byte, little-endian length, two UTF-16 strings, image.
            size = int.from_bytes(raw[1:5], "little")
            if size and size <= len(raw) - 5:
                pictures.append(raw[-size:])
        row["Duration"] = getattr(audio.info, "length", None)
    except Exception as e:
        row["Scan Error"] = f"Metadata: {e}"
        logging.warning("%s: %s", path, e)
    row["Artwork Present"] = bool(pictures)
    row["Artwork Count"] = len(pictures)
    row["Artwork Dimensions"] = "; ".join(filter(None, (dimensions(p) for p in pictures)))
    ok, streams, fmt, err = probe(path, config)
    row["FFprobe OK"], row["FFprobe Error"] = ok, err
    row["Probe Policy"] = 2
    stream = streams[0] if streams else {}
    for field, key in [
        ("Codec", "codec_name"),
        ("Bitrate", "bit_rate"),
        ("Sample Rate", "sample_rate"),
        ("Channels", "channels"),
    ]:
        row[field] = stream.get(key, fmt.get(key))
    try:
        row["Duration"] = (
            float(stream.get("duration") or fmt.get("duration") or row.get("Duration") or 0) or None
        )
    except (ValueError, TypeError):
        row["Duration"] = None
    format_tags = {str(k).casefold(): v for k, v in fmt.get("tags", {}).items()}
    protected = (
        path.suffix.lower() == ".m4p"
        or getattr(getattr(audio, "info", None), "codec", "") in ("enca", "drms")
        or any(k in format_tags for k in ("encryption", "asf_protection_type", "asf_key_id"))
        or any(
            s.get("codec_tag_string") in ("enca", "drms")
            or any("encrypt" in str(x).lower() for x in s.get("side_data_list", []))
            for s in streams
        )
    )
    codec = row.get("Codec")
    row["DRM Status"] = (
        "Protected / DRM"
        if protected
        else (
            "No DRM detected"
            if ok
            and codec
            in {
                "aac",
                "mp3",
                "flac",
                "alac",
                "vorbis",
                "opus",
                "wmav1",
                "wmav2",
                "wmapro",
                "wmalossless",
            }
            or ok
            and str(codec).startswith("pcm_")
            else "Unknown"
        )
    )
    row["Deep Integrity"], row["Deep Integrity Error"] = deep_check(path, config)
    row["Integrity"] = (
        "FAIL"
        if not ok or not row["Metadata Readable"] or row["Deep Integrity"] == "FAIL"
        else "PASS (probe only)"
        if row["Deep Integrity"] == "NOT TESTED"
        else "PASS"
    )
    row["Archive Eligible"] = (
        row["DRM Status"] == "No DRM detected"
        and ok
        and row["Metadata Readable"]
        and row["Deep Integrity"] != "FAIL"
    )
    purchase = "apID" in tags and ("purd" in tags or "sfID" in tags)
    row["Source Classification"] = (
        "Protected / DRM"
        if protected
        else "Unknown"
        if row["DRM Status"] == "Unknown"
        else "Likely iTunes Store Purchase"
        if purchase and codec == "aac"
        else "Generic DRM-Free AAC"
        if codec == "aac"
        else "MP3"
        if codec == "mp3"
        else "FLAC"
        if codec == "flac"
        else "Other DRM-Free Audio"
    )
    issues = []
    for field in (
        "Title",
        "Artist",
        "Album",
        "Album Artist",
        "Track Number",
        "Track Total",
        "Date",
        "Artwork Present",
    ):
        row["Has " + field.replace(" Present", "")] = bool(row.get(field))
        if not row.get(field):
            issues.append("Missing " + field.replace(" Present", ""))
    row["Has Disc Number"] = bool(row.get("Disc Number"))
    if (row.get("Disc Total") or 1) > 1 and not row.get("Disc Number"):
        issues.append("Missing Disc Number (multi-disc)")
    row["Metadata Issues"] = "; ".join(issues)
    if row["Scan Error"]:
        row["Metadata Issues"] += "; " + row["Scan Error"]
    if ok and err.strip():
        row["Metadata Issues"] += "; Embedded artwork probe warning: " + err.strip()
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    row["SHA-256"] = digest.hexdigest()
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        row["Scan Error"] += "; File changed during scan"
        row["Archive Eligible"] = False
        row["SHA-256"] = ""
    if not ok:
        logging.warning("FFprobe failed for %s: %s", path, err)
    return row


def inventory(files, config):
    cache = Cache(Path(config["cache_directory"]))
    rows, pending, reused = [], [], 0
    try:
        for root, p in files:
            try:
                st = p.stat()
                hit = cache.get(p, st, config["deep_integrity_check"])
                if hit:
                    hit["Library Root"] = root
                    hit["Relative Path"] = str(p.relative_to(root))
                    rows.append(hit)
                    reused += 1
                else:
                    pending.append((root, p, st))
            except OSError as e:
                rows.append(
                    {
                        "Library Root": root,
                        "Full Path": str(p),
                        "Scan Error": str(e),
                        "Archive Eligible": False,
                        "Integrity": "FAIL",
                    }
                )
        print(f"Cache reused: {reused:,}; scanning: {len(pending):,}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=config["workers"]) as executor:

            def work(item):
                root, p, st = item
                try:
                    return scan_one(root, p, config)
                except Exception as e:
                    logging.exception("Cannot scan %s", p)
                    return {
                        "Library Root": root,
                        "Full Path": str(p),
                        "Scan Error": str(e),
                        "Archive Eligible": False,
                        "Integrity": "FAIL",
                    }

            for i, (item, row) in enumerate(
                zip(
                    pending,
                    tqdm(
                        executor.map(work, pending),
                        total=len(pending),
                        desc="Metadata / probe / SHA-256",
                        mininterval=10,
                    ),
                )
            ):
                rows.append(row)
                cache.put(item[1], item[2], row)
                if i % 100 == 0:
                    cache.commit()
    finally:
        cache.close()
    rows.sort(key=lambda r: r["Full Path"].casefold())
    print("Formats:", Counter(r.get("Extension", "Unknown") for r in rows), flush=True)
    print("Sources:", Counter(r.get("Source Classification", "Unknown") for r in rows), flush=True)
    return rows
