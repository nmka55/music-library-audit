import re
import unicodedata

VERSION_WORDS = re.compile(
    r"\b(live|acoustic|demo|remix|remaster(?:ed)?|radio\s+edit|extended(?:\s+mix)?|instrumental|karaoke|mono|stereo|edit|version)\b",
    re.I,
)
FEATURE = re.compile(r"\s*[\[(]?\b(?:feat\.?|ft\.?|featuring)\s+([^\])]+)[\])]?", re.I)
WITH_FEATURE = re.compile(r"\s*[\[(]with\s+([^\])]+)[\])]", re.I)


CYRILLIC = re.compile(r"[\u0400-\u04ff]")
HIGH_LATIN = re.compile(r"[\u00c0-\u00ff]")
LATIN1_SYMBOL = re.compile(r"[\u00a0-\u00ff]")  # also ¸ ¨ ¹ « »
ASCII_LETTER = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[^\s\[\]()]+")


def _as_cp1251(word):
    try:
        raw = b"".join(
            c.encode("cp1252") if c.encode("cp1252", "ignore") else c.encode("latin-1")
            for c in word
        )
        return raw.decode("cp1251")
    except UnicodeError:
        return None


def repair_mojibake(text):
    """Read Windows-1251 Cyrillic that was decoded as Latin-1 ("Ñòîï!" is "Стоп!").

    Only words made entirely of non-ASCII Latin letters are converted, and only when some
    word has at least three of them and converts to pure Cyrillic, so French or Spanish
    titles with a few accents are never touched. The input is returned unchanged otherwise.
    """
    text = str(text or "")
    words = [w for w in WORD.findall(text) if HIGH_LATIN.search(w) and not ASCII_LETTER.search(w)]
    if not any(len(HIGH_LATIN.findall(w)) >= 3 for w in words):
        return text

    def fix(match):
        word = match.group()
        if not LATIN1_SYMBOL.search(word) or ASCII_LETTER.search(word):
            return word
        fixed = _as_cp1251(word)
        if fixed and all(CYRILLIC.match(c) for c in fixed if c.isalpha()):
            return fixed
        return word

    return WORD.sub(fix, text)


TRANSLITERATION = {
    **dict(zip("абвгдезийклмнопрстуфхіїґөү", "abvgdezi" "yklmnoprstufh" "iigou")),
    "ё": "e", "ж": "zh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ь": "",
    "ы": "y", "э": "e", "ю": "yu", "я": "ya", "є": "ye", "х": "kh",
}  # fmt: skip


def transliterate(text):
    """Latin spelling of Cyrillic text, close to how Apple Music spells artist names."""
    return "".join(
        (TRANSLITERATION.get(c.casefold(), c) if CYRILLIC.match(c) else c) for c in str(text or "")
    )


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
    fixed = [repair_mojibake(row.get(k, "")) for k in ("Name", "Artist", "Album")]
    row.update(comparison(*fixed))
    row["Duration Seconds"] = (row.get("Total Time") or 0) / 1000 or None


def prepare_offline(row):
    fixed = [repair_mojibake(row.get(k, "")) for k in ("Title", "Artist", "Album")]
    row.update(comparison(*fixed))
