from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import reconcile_libraries as rl
from config import DEFAULTS
from normalization import prepare_apple, prepare_offline, repair_mojibake
from track_matching import LIKELY, POSSIBLE, STRICT, LooseIndex, prepare

CONFIG = {**DEFAULTS, "_workspace": ".", "_config_path": "config.json"}


def query(title="Signal", artist="The Beatles", seconds=200.0):
    row = {"Name": title, "Artist": artist, "Album": "Original Album", "Total Time": seconds * 1000}
    prepare_apple(row)
    return prepare(row)


def download(title="Signal", artist="The Beatles", seconds=200.0, path="/net/a/song.mp3", **extra):
    return {
        "Full Path": path,
        "Library Root": "/net",
        "Title": title,
        "Artist": artist,
        "Album": "All Time Hits",
        "Duration": seconds,
        "Archive Eligible": True,
        "Integrity": "PASS",
        "Metadata Issues": "",
        **extra,
    }


def best(a, *files, **kwargs):
    for f in files:
        prepare_offline(f)
    found = LooseIndex(list(files)).find(a, CONFIG, **kwargs)
    return found[0] if found else None


class TierTests(unittest.TestCase):
    def test_clean_copy_is_strict_even_with_a_different_album(self):
        self.assertEqual(best(query(), download())["tier"], STRICT)

    def test_each_common_tag_difference_is_still_found(self):
        cases = {
            "title suffix": download(title="Signal (Remastered 2011)"),
            "single version": download(title="Signal - Single Version"),
            "explicit flag": download(title="Signal (Explicit)"),
            "feature credit": download(title="Signal (feat. Someone)"),
            "dropped The": download(artist="Beatles"),
            "extra guest": download(artist="The Beatles & Guest"),
            "duration off": download(seconds=207.5),
            "track number in title": download(title="07 - Signal"),
            "case and punctuation": download(title="SIGNAL!", artist="the beatles"),
        }
        for name, row in cases.items():
            with self.subTest(name):
                self.assertIn(best(query(), row)["tier"], (STRICT, LIKELY))

    def test_untagged_file_is_found_from_filename_and_folder(self):
        row = download(
            title="", artist="", path="/net/The Beatles/Some Album/03 - Signal.mp3", Album=""
        )
        found = best(query(), row)
        self.assertEqual((found["tier"], found["basis"]), (LIKELY, "folder name"))
        row = download(title="", artist="", path="/net/misc/03 - The Beatles - Signal.mp3")
        found = best(query(), row)
        self.assertEqual((found["tier"], found["basis"]), (LIKELY, "filename"))
        row = download(title="", artist="", path="/net/The Beatles/x/Signal.mp3")
        self.assertEqual(best(query(), row)["tier"], LIKELY)

    def test_different_recordings_are_never_likely(self):
        cases = {
            "live": download(title="Signal (Live at Home)"),
            "remix": download(title="Signal (DJ Remix)"),
            "other part": download(title="Signal Part 2"),
            "too long": download(seconds=260),
            "unknown length": download(seconds=None),
            "protected": download(**{"Archive Eligible": False}),
        }
        for name, row in cases.items():
            with self.subTest(name):
                found = best(query("Signal Part 1") if name == "other part" else query(), row)
                self.assertTrue(found is None or found["tier"] == POSSIBLE)

    def test_unrelated_artist_or_title_is_not_a_match(self):
        self.assertIsNone(best(query(), download(artist="Someone Else")))
        self.assertIsNone(best(query(), download(title="Different Song")))

    def test_duration_window_is_adjustable(self):
        row = download(seconds=212)
        self.assertEqual(best(query(), row)["tier"], POSSIBLE)
        self.assertEqual(best(query(), row, loose_seconds=15)["tier"], LIKELY)

    def test_titles_that_start_with_a_number_still_match(self):
        found = best(query("7 Rings", "Ariana Grande"), download("7 Rings", "Ariana Grande"))
        self.assertEqual(found["tier"], STRICT)


class MojibakeTests(unittest.TestCase):
    def test_windows_1251_read_as_latin1_is_repaired(self):
        cases = {
            "Ñòîï! Ñòîï! Ñòîï!": "Стоп! Стоп! Стоп!",
            "ÂÈÀ Ãðà": "ВИА Гра",
            "Áèîëîãèÿ [Club mix by RainMan]": "Биология [Club mix by RainMan]",
            "Â ýòîì òû ïðîôåññîð": "В этом ты профессор",
            "Ïîïûòêà ¹5": "Попытка №5",
        }
        for broken, fixed in cases.items():
            self.assertEqual(repair_mojibake(broken), fixed)

    def test_real_accented_and_cyrillic_text_is_never_changed(self):
        for text in (
            "Où sont les héros éphémères",
            "Ça me fait mal à l'âme",
            "Señor Ñoño",
            "Beyoncé",
            "Стоп! Снято!",
            "",
        ):
            self.assertEqual(repair_mojibake(text), text)

    def test_garbled_download_matches_the_real_russian_track(self):
        a = query("Стоп! Стоп! Стоп!", "ВИА Гра")
        row = download("Ñòîï! Ñòîï! Ñòîï!", "ÂÈÀ Ãðà", path="/net/ÂÈÀ Ãðà/Áèîëîãèÿ/01 Ñòîï.mp3")
        found = best(a, row)
        self.assertIn(found["tier"], (STRICT, LIKELY))
        self.assertEqual(row["Title"], "Ñòîï! Ñòîï! Ñòîï!")  # the original tag is not rewritten


class TransliterationTests(unittest.TestCase):
    def test_latin_apple_artist_matches_cyrillic_file_artist(self):
        cases = [
            ("Ласковый май", "Laskovy May"),
            ("Валерий Меладзе", "Valeriy Meladze"),
            ("Конец фильма", "Konets Filma"),
            ("Филипп Киркоров", "Philipp Kirkorov"),
            ("Лосолын Болдбаатар", "Losolyn Boldbaatar"),
        ]
        for cyrillic, latin in cases:
            with self.subTest(latin):
                a = query("Название", latin)
                found = best(a, download("Название", cyrillic))
                self.assertIn(found["tier"], (STRICT, LIKELY))
                self.assertEqual(found["basis"], "transliteration")

    def test_different_artists_do_not_match_through_transliteration(self):
        self.assertIsNone(best(query("Название", "Laskovy May"), download("Название", "Градусы")))
        self.assertIsNone(
            best(query("Название", "Laskovy May"), download("Другая песня", "Ласковый май"))
        )


class ReconcileLooseTests(unittest.TestCase):
    def purchased(self, name="Signal", artist="The Beatles", seconds=200, **extra):
        return {
            "Persistent ID": name,
            "Name": name,
            "Artist": artist,
            "Album": "Original Album",
            "Total Time": seconds * 1000,
            **extra,
        }

    def test_likely_duplicates_are_reviewable_and_never_marked_removable(self):
        tracks = [self.purchased("Signal"), self.purchased("Echo")]
        files = [
            download("Signal (Remastered)", "Beatles", 205, "/net/Hits/Signal.mp3"),
            download("Echo", "The Beatles", 200, "/net/Hits/Echo.mp3"),
        ]
        ok = lambda t: ("OK", "/buy/x.m4a")
        plan, albums, _, _ = rl.reconcile([], tracks, files, CONFIG, ok)
        got = {Path(r["Internet File"]).name: r["Recommendation"] for r in plan}
        self.assertEqual(got, {"Signal.mp3": rl.LIKELY_DUP, "Echo.mp3": rl.REMOVE})
        self.assertEqual(albums[0]["Tracks In That Folder"], 2)
        self.assertEqual(albums[0]["Best Internet Folder"], "/net/Hits")
        self.assertTrue(all(r["Album Tracks In This Folder"] == "2 of 2" for r in plan))

    def test_apple_tracks_with_messy_downloads_are_not_reported_missing(self):
        apple = [
            {
                "Persistent ID": "A1",
                "Name": "Signal",
                "Artist": "The Beatles",
                "Total Time": 200000,
            },
            {"Persistent ID": "A2", "Name": "Echo", "Artist": "The Beatles", "Total Time": 200000},
            {"Persistent ID": "A3", "Name": "Gone", "Artist": "Nobody", "Total Time": 200000},
        ]
        files = [
            download("Signal - Single Version", "Beatles", 206, "/net/a/1.mp3"),
            download("", "", 200, "/net/The Beatles/Hits/02 Echo.mp3"),
        ]
        _, _, missing, _ = rl.reconcile(apple, [], files, CONFIG)
        self.assertEqual([(r["Title"], r["Status"]) for r in missing], [("Gone", rl.MISSING)])


if __name__ == "__main__":
    unittest.main()
