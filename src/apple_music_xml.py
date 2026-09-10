import collections
import plistlib


def read_xml(path):
    with open(path, "rb") as f:
        document = plistlib.load(f)
    tracks = list(document.get("Tracks", {}).values())
    fields = collections.Counter(k for t in tracks for k in t)
    print(f"Apple Music tracks: {len(tracks):,}", flush=True)
    print("Common fields:", fields.most_common(20), flush=True)
    for key in (
        "Name",
        "Artist",
        "Album",
        "Album Artist",
        "Total Time",
        "Year",
        "Release Date",
        "Persistent ID",
    ):
        print(f"  {key}: {sum(bool(t.get(key)) for t in tracks):,}", flush=True)
    return tracks
