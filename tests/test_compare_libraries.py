import csv
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import compare_libraries as cl


def track(pid, name, artist, seconds, **extra):
    return {
        "Persistent ID": pid,
        "Name": name,
        "Artist": artist,
        "Album": "Album",
        "Year": 2001,
        "Total Time": int(seconds * 1000),
        **extra,
    }


def write_xml(path, tracks):
    path.write_bytes(plistlib.dumps({"Tracks": {str(i): t for i, t in enumerate(tracks)}}))


class CompareTests(unittest.TestCase):
    def statuses(self, apple, purchased, **kwargs):
        rows = cl.compare(apple, purchased, include_matched=True, **kwargs)
        return {r["Title"]: r["Status"] for r in rows}

    def test_gates_are_conservative(self):
        purchased = [
            track("B1", "Signal", "Band", 200),
            track("B2", "Echo", "Band", 200),
            track("B3", "Orbit (Live)", "Band", 200),
            track("B4", "Drift", "Band", 200),
        ]
        apple = [
            track("A1", "Signal", "Band", 202),  # within tolerance
            track("A2", "Echo", "Band", 230),  # duration differs
            track("A3", "Orbit", "Band", 200),  # version differs
            track("A4", "Unknown Song", "Band", 200),  # absent
            track("B4", "Renamed", "Other", 10),  # same Persistent ID wins
        ]
        result = self.statuses(apple, purchased)
        self.assertEqual(result["Signal"], cl.MATCHED)
        self.assertEqual(result["Echo"], cl.POSSIBLE)
        self.assertEqual(result["Orbit"], cl.POSSIBLE)
        self.assertEqual(result["Unknown Song"], cl.NOT_FOUND)
        self.assertEqual(result["Renamed"], cl.MATCHED)

    def test_track_id_alone_never_matches_and_missing_duration_is_uncertain(self):
        purchased = [dict(track("B1", "Different", "Other", 100), **{"Track ID": 7})]
        apple = [dict(track("A1", "Signal", "Band", 100), **{"Track ID": 7})]
        self.assertEqual(self.statuses(apple, purchased), {"Signal": cl.NOT_FOUND})
        purchased = [track("B1", "Signal", "Band", 100)]
        no_time = [{"Persistent ID": "A", "Name": "Signal", "Artist": "Band"}]
        self.assertEqual(self.statuses(no_time, purchased), {"Signal": cl.POSSIBLE})

    def test_featured_credit_formatting_and_default_hides_matches(self):
        purchased = [track("B1", "Song (feat. Guest)", "Band", 100)]
        apple = [track("A1", "Song", "Band & Guest", 100)]
        self.assertEqual(cl.compare(apple, purchased), [])
        self.assertEqual(self.statuses(apple, purchased), {"Song": cl.MATCHED})

    def test_links_are_used_only_when_present(self):
        apple = [
            track("A1", "One", "Band", 10, **{"Store URL": "https://example.test/one"}),
            track("A2", "Two", "Band", 10),
        ]
        rows = {r["Title"]: r for r in cl.compare(apple, [])}
        self.assertEqual(rows["One"]["iTunes Link"], "https://example.test/one")
        self.assertEqual(rows["Two"]["iTunes Link"], "")

    def test_cli_writes_multicolumn_csv_without_changing_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            apple, purchased = base / "apple.xml", base / "purchased.xml"
            write_xml(
                apple, [track("A1", "Signal", "Band, The", 200), track("A2", "=Boom", "X", 60)]
            )
            write_xml(purchased, [track("B1", "Signal", "Band, The", 200)])
            before = (apple.read_bytes(), purchased.read_bytes())
            messages = []
            code = cl.main(
                ["--workspace", str(base), "--apple", str(apple), "--purchased", str(purchased)],
                tell=messages.append,
            )
            self.assertEqual(code, 0)
            self.assertEqual(before, (apple.read_bytes(), purchased.read_bytes()))
            with open(
                base / "output" / "Apple_Music_Not_In_Purchased.csv", encoding="utf-8-sig"
            ) as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(list(rows[0]), list(cl.COLUMNS))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Title"], "'=Boom")
            self.assertEqual(rows[0]["Duration"], "1:00")

    def test_interactive_choice_by_number_or_path_and_output_boundary(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            base = Path(td)
            first, second = base / "a.xml", base / "b.xml"
            write_xml(first, [track("A1", "One", "Band", 10)])
            write_xml(second, [track("B1", "Two", "Band", 10)])
            answers = iter(["nope.xml", str(first), "1"])
            tell = lambda _: None
            chosen = cl.choose_xml("Apple Music library", base, lambda _: next(answers), tell)
            self.assertEqual(chosen, first.resolve())
            other = cl.choose_xml(
                "purchased", base, lambda _: next(answers), tell, exclude=first.resolve()
            )
            self.assertEqual(other, second.resolve())
            with self.assertRaises(ValueError):
                cl.output_path(cl.load(workspace=base), str(Path(outside) / "x.csv"))
            with self.assertRaises(ValueError):
                cl.output_path(cl.load(workspace=base), "output/x.txt")


if __name__ == "__main__":
    unittest.main()
