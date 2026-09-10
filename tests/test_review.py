import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from review import review_matches


class ReviewTests(unittest.TestCase):
    def base(self):
        apple = [{"Persistent ID": "P1", "Name": "Example", "Artist": "Artist", "Album": "Album"}]
        offline = [
            {
                "Full Path": "C:/music/first.flac",
                "Title": "Wrong",
                "Artist": "Artist",
                "Duration": 10,
                "Library Root": "C:/music",
                "Archive Eligible": True,
                "Integrity": "PASS",
                "Metadata Issues": "",
                "Artwork Present": True,
            },
            {
                "Full Path": "C:/music/right.flac",
                "Title": "Example",
                "Artist": "Artist",
                "Duration": 20,
                "Library Root": "C:/music",
                "Archive Eligible": True,
                "Integrity": "PASS",
                "Metadata Issues": "",
                "Artwork Present": True,
            },
        ]
        matches = [
            {
                "Status": "REVIEW",
                "Apple Persistent ID": "P1",
                "Apple Title": "Example",
                "Apple Artist": "Artist",
                "Apple Album": "Album",
                "Apple Duration": 20,
                "Matched File Path": offline[0]["Full Path"],
                "Alternative Candidate 1": offline[1]["Full Path"],
                "Match Reason": "version conflict",
            }
        ]
        return apple, offline, matches

    def test_no_then_yes_confirms_second_and_updates_fields(self):
        apple, offline, matches = self.base()
        answers = iter(["no", "yes"])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manual_matches.json"
            result, overrides = review_matches(
                apple,
                matches,
                {},
                path,
                offline=offline,
                ask=lambda _: next(answers),
                tell=lambda _: None,
            )
            self.assertEqual(result[0]["Status"], "MATCHED")
            self.assertEqual(result[0]["Matched File Path"], offline[1]["Full Path"])
            self.assertEqual(result[0]["Matched Offline Title"], "Example")
            self.assertEqual(json.loads(path.read_text())["P1"], offline[1]["Full Path"])
            self.assertEqual(overrides["P1"], offline[1]["Full Path"])

    def test_all_rejected_remains_review(self):
        apple, offline, matches = self.base()
        answers = iter(["no", "no"])
        with tempfile.TemporaryDirectory() as td:
            result, overrides = review_matches(
                apple,
                matches,
                {},
                Path(td) / "manual.json",
                offline=offline,
                ask=lambda _: next(answers),
                tell=lambda _: None,
            )
            self.assertEqual(result[0]["Status"], "REVIEW")
            self.assertEqual(overrides, {})

    def test_quit_preserves_prior_decisions(self):
        apple, offline, matches = self.base()
        second = {**matches[0], "Apple Persistent ID": "P2", "Apple Title": "Other"}
        answers = iter(["yes", "quit"])
        with tempfile.TemporaryDirectory() as td:
            result, overrides = review_matches(
                apple,
                matches + [second],
                {},
                Path(td) / "manual.json",
                offline=offline,
                ask=lambda _: next(answers),
                tell=lambda _: None,
            )
            self.assertEqual(result[0]["Status"], "MATCHED")
            self.assertEqual(result[1]["Status"], "REVIEW")
            self.assertIn("P1", overrides)

    def test_invalid_answer_repeats_candidate(self):
        apple, offline, matches = self.base()
        answers = iter(["maybe", "yes"])
        with tempfile.TemporaryDirectory() as td:
            result, _ = review_matches(
                apple,
                matches,
                {},
                Path(td) / "manual.json",
                offline=offline,
                ask=lambda _: next(answers),
                tell=lambda _: None,
            )
            self.assertEqual(result[0]["Status"], "MATCHED")


if __name__ == "__main__":
    unittest.main()
