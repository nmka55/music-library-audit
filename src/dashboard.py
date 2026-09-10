from collections import Counter


def dashboard(apple, offline, matches, duplicates, albums, errors):
    counts = Counter(r["Status"] for r in matches)
    result = [
        {"Metric": "Total Apple Music tracks", "Value": len(apple)},
        {"Metric": "Supported-extension files discovered", "Value": len(offline)},
        {
            "Metric": "Total offline audio files",
            "Value": sum(r.get("File Type") != "AppleDouble metadata sidecar" for r in offline),
        },
    ]
    for s in ("MATCHED", "MISSING", "REVIEW"):
        result.append(
            {
                "Metric": s,
                "Value": counts[s],
                "Percentage": round(100 * counts[s] / len(apple), 2) if apple else 0,
            }
        )
    result.extend(
        {"Metric": k, "Value": v}
        for k, v in {
            "Matched with metadata problems": sum(
                r["Status"] == "MATCHED" and r["Metadata Quality"] != "GOOD" for r in matches
            ),
            "AppleDouble metadata sidecars (not audio)": sum(
                r.get("File Type") == "AppleDouble metadata sidecar" for r in offline
            ),
            "Offline audio candidates missing artwork": sum(
                not r.get("Artwork Present")
                and r.get("File Type") != "AppleDouble metadata sidecar"
                for r in offline
            ),
            "Corrupt / unreadable files": sum(r.get("Integrity") == "FAIL" for r in offline),
            "Archive eligible files": sum(bool(r.get("Archive Eligible")) for r in offline),
            "Exact duplicate groups": len(
                {r["Group"] for r in duplicates if r["Category"] == "EXACT BINARY DUPLICATE"}
            ),
            "Exact duplicate files": sum(
                r["Category"] == "EXACT BINARY DUPLICATE" for r in duplicates
            ),
            "Possible duplicate pairs": sum(
                r["Category"].startswith("POSSIBLE DUPLICATE") for r in duplicates
            ),
            "Same recording / different album pairs (informational)": sum(
                r["Category"] == "SAME RECORDING / DIFFERENT ALBUM" for r in duplicates
            ),
            "Album discs possibly incomplete": sum(
                r["Status"] == "POSSIBLY INCOMPLETE" for r in albums
            ),
            "Discovery errors": len(errors),
            "Deep integrity NOT TESTED (audio)": sum(
                r.get("Deep Integrity") == "NOT TESTED"
                and r.get("File Type") != "AppleDouble metadata sidecar"
                for r in offline
            ),
        }.items()
    )
    result.append(
        {
            "Metric": "Interpretation",
            "Value": "MATCHED requires archive eligibility. Probe-only PASS does not mean full decoding was tested. Album completeness is based only on available tags.",
        }
    )
    for error in errors:
        result.append({"Metric": "Discovery warning", "Value": error})
    return result
