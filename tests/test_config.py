import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import load, read_overrides, save
from setup_wizard import configure


class ConfigurationTests(unittest.TestCase):
    def test_multiple_entries_then_done_and_reload(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            xml = base / "library export.xml"
            xml.write_bytes(plistlib.dumps({"Tracks": {}}))
            for name in ("first collection", "second collection"):
                (base / name).mkdir()
            answers = iter(
                [
                    str(xml),
                    "done",
                    "missing folder",
                    "first collection",
                    "first collection",
                    "second collection",
                    "that's all",
                ]
            )
            result = configure(
                load(workspace=base), ask=lambda _: next(answers), tell=lambda _: None
            )
            self.assertEqual(len(result["offline_music_roots"]), 2)
            reloaded = load(workspace=base)
            self.assertEqual(result, reloaded)
            self.assertEqual(reloaded["apple_music_xml"], str(xml.resolve()))

    def test_cli_overrides_do_not_persist_without_save(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = load(
                workspace=base,
                updates={"apple_music_xml": "next.xml", "offline_music_roots": ["music"]},
            )
            self.assertFalse((base / "config.json").exists())
            save(c)
            self.assertEqual(load(workspace=base)["apple_music_xml"], str(base / "next.xml"))
            self.assertEqual(
                json.loads((base / "config.json").read_text())["apple_music_xml"], "next.xml"
            )

    def test_reject_music_write_overlap_and_output_escape(self):
        with tempfile.TemporaryDirectory() as td:
            for update in (
                {"offline_music_roots": [td]},
                {"output_excel": "../escape.xlsx"},
                {"cache_directory": "../cache"},
            ):
                with self.subTest(update=update), self.assertRaises(ValueError):
                    load(workspace=td, updates=update)

    def test_config_path_selects_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            c = load(config_path=path)
            self.assertEqual(c["_workspace"], td)
            self.assertEqual(
                c["output_excel"], str(Path(td) / "output" / "Music_Library_Audit.xlsx")
            )

    def test_symlink_output_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            try:
                (Path(td) / "output").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation not permitted on this host")
            with self.assertRaises(ValueError):
                load(workspace=td)

    def test_relative_overrides_and_no_overrides_file(self):
        with tempfile.TemporaryDirectory() as td:
            c = load(workspace=td)
            self.assertEqual(read_overrides(c), {})
            Path(c["manual_matches_file"]).write_text(json.dumps({"EXAMPLE": "music/song.flac"}))
            self.assertEqual(read_overrides(c)["EXAMPLE"], str(Path(td) / "music" / "song.flac"))

    def test_invalid_settings(self):
        with tempfile.TemporaryDirectory() as td:
            for update in (
                {"workers": True},
                {"matched_threshold": float("nan")},
                {"offline_music_roots": "not a list"},
                {"deep_integrity_check": "false"},
            ):
                with self.subTest(update=update), self.assertRaises(ValueError):
                    load(workspace=td, updates=update)
