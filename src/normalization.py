import re
import unicodedata

VERSION_WORDS = re.compile(
    r"\b(live|acoustic|demo|remix|remaster(?:ed)?|radio\s+edit|extended(?:\s+mix)?|instrumental|karaoke|mono|stereo|edit|version)\b",
    re.I,
)
FEATURE = re.compile(r"\s*[\[(]?\b(?:feat\.?|ft\.?|featuring)\s+([^\])]+)[\])]?", re.I)
WITH_FEATURE = re.compile(r"\s*[\[(]with\s+([^\])]+)[\])]", re.I)


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'").replace("‘", "'")
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


def comparison(title, artist, album):
    featured = FEATURE.findall(title or "") + WITH_FEATURE.findall(title or "")
    base = WITH_FEATURE.sub("", FEATURE.sub("", title or ""))
    credits = re.split(
        r"\s+(?:&|and|with|feat\.?|ft\.?|featuring|x)\s+|\s*[,;]\s*", artist or "", flags=re.I
    )
    for credit in featured:
        credits.extend(re.split(r"\s+(?:&|and|with)\s+|\s*[,;]\s*", credit, flags=re.I))
    versions = []
    # Retain complete version descriptors, including remaster year/remixer name.
    for bracket in re.findall(r"[\[(]([^\])]+)[\])]", base):
        if VERSION_WORDS.search(bracket):
            versions.append(normalize(bracket))
    for suffix in re.split(r"\s[-–—]\s", base)[1:]:
        if VERSION_WORDS.search(suffix):
            versions.append(normalize(suffix))
    if VERSION_WORDS.search(base) and not versions:
        versions = [normalize(m.group()) for m in VERSION_WORDS.finditer(base)]
    basic = re.sub(
        r"[\[(]([^\])]+)[\])]",
        lambda m: "" if VERSION_WORDS.search(m.group(1)) else m.group(0),
        base,
    )
    basic = re.split(r"\s[-–—]\s", basic)[0] if versions else basic
    album_versions = sorted(
        {
            normalize(m.group())
            for m in VERSION_WORDS.finditer(album or "")
            if normalize(m.group()) not in ("version", "edit", "remaster", "remastered")
        }
    )
    return {
        "Normalized Title": normalize(base),
        "Normalized Base Title": normalize(basic),
        "Normalized Artist": normalize(artist),
        "Normalized Album": normalize(album),
        "Credited Artists": sorted({normalize(c) for c in credits if normalize(c)}),
        "Version Markers": sorted(set(versions)),
        "Album Version Markers": album_versions,
    }


def prepare_apple(row):
    row.update(comparison(row.get("Name", ""), row.get("Artist", ""), row.get("Album", "")))
    row["Duration Seconds"] = (row.get("Total Time") or 0) / 1000 or None


def prepare_offline(row):
    row.update(comparison(row.get("Title", ""), row.get("Artist", ""), row.get("Album", "")))
