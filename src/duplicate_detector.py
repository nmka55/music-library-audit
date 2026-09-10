from collections import defaultdict
from rapidfuzz import fuzz


def duplicates(rows):
    hashes = defaultdict(list)
    artist_groups = defaultdict(list)
    output = []
    for r in rows:
        if r.get("File Type") == "AppleDouble metadata sidecar":
            continue
        if r.get("SHA-256"):
            hashes[r["SHA-256"]].append(r)
        if r["Normalized Title"] and r["Credited Artists"]:
            artist_groups[tuple(r["Credited Artists"])].append(r)
    for digest, group in hashes.items():
        if len(group) > 1:
            for r in group:
                output.append(
                    {
                        "Category": "EXACT BINARY DUPLICATE",
                        "Group": digest,
                        "Full Path": r["Full Path"],
                        "Library Root": r["Library Root"],
                        "Title": r.get("Title"),
                        "Artist": r.get("Artist"),
                        "Album": r.get("Album"),
                        "Evidence": "Same SHA-256",
                        "Other File": None,
                    }
                )
    group_id = 0
    for group in artist_groups.values():
        by_title = defaultdict(list)
        for r in group:
            by_title[r["Normalized Title"]].append(r)
        for same_title in by_title.values():
            for i, a in enumerate(same_title):
                for b in same_title[i + 1 :]:
                    if a.get("Duration") and b.get("Duration"):
                        continue
                    if a.get("SHA-256") and a.get("SHA-256") == b.get("SHA-256"):
                        continue
                    group_id += 1
                    output.append(
                        {
                            "Category": "POSSIBLE DUPLICATE / REVIEW",
                            "Group": f"M{group_id}",
                            "Full Path": a["Full Path"],
                            "Library Root": a["Library Root"],
                            "Title": a.get("Title"),
                            "Artist": a.get("Artist"),
                            "Album": a.get("Album"),
                            "Evidence": "Same title and credited artists; duration missing",
                            "Other File": b["Full Path"],
                        }
                    )
        ordered = sorted((r for r in group if r.get("Duration")), key=lambda r: r["Duration"])
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                difference = b["Duration"] - a["Duration"]
                if difference > 5:
                    break
                if a.get("SHA-256") and a.get("SHA-256") == b.get("SHA-256"):
                    continue
                similarity = fuzz.ratio(a["Normalized Title"], b["Normalized Title"])
                if similarity < 90:
                    continue
                same_album = bool(
                    a["Normalized Album"] and a["Normalized Album"] == b["Normalized Album"]
                )
                versions = a["Version Markers"] == b["Version Markers"]
                track = bool(
                    a.get("Track Number")
                    and a.get("Track Number") == b.get("Track Number")
                    and (a.get("Disc Number") or 1) == (b.get("Disc Number") or 1)
                )
                if difference <= 3 and versions and same_album and track:
                    category = "POSSIBLE DUPLICATE WITHIN SAME ALBUM"
                elif (
                    difference <= 3
                    and versions
                    and similarity >= 97
                    and a["Normalized Album"]
                    and b["Normalized Album"]
                    and not same_album
                ):
                    category = "SAME RECORDING / DIFFERENT ALBUM"
                else:
                    category = "POSSIBLE DUPLICATE / REVIEW"
                group_id += 1
                output.append(
                    {
                        "Category": category,
                        "Group": f"M{group_id}",
                        "Full Path": a["Full Path"],
                        "Library Root": a["Library Root"],
                        "Title": a.get("Title"),
                        "Artist": a.get("Artist"),
                        "Album": a.get("Album"),
                        "Evidence": f"Title {similarity:.1f}; duration {difference:.3f}s; version agreement {versions}; metadata evidence only",
                        "Other File": b["Full Path"],
                    }
                )
    return output
