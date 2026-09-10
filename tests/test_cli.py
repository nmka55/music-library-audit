"""Exercise fresh-install setup, the full CLI, and updated XML without private data."""

import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from openpyxl import load_workbook

PROJECT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def run_cli(self, workspace, *args, input_text=None, script="audit.py"):
        return subprocess.run(
            [sys.executable, str(PROJECT / "src" / script), "--workspace", str(workspace), *args],
            input=input_text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=60,
        )

    def test_unconfigured_noninteractive_fails_without_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_cli(td, "--non-interactive")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unconfigured", result.stderr)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires FFmpeg and FFprobe"
    )
    def test_setup_full_run_updated_xml_cache_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            roots = [base / "music one", base / "music two"]
            for root in roots:
                root.mkdir()
            songs = [("Signal", "Artist One"), ("Elsewhere", "Artist Two")]
            audio_paths = []
            for root, (title, artist) in zip(roots, songs):
                p = root / "song.m4a"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=duration=0.5",
                        "-c:a",
                        "aac",
                        "-metadata",
                        f"title={title}",
                        "-metadata",
                        f"artist={artist}",
                        str(p),
                    ],
                    check=True,
                    capture_output=True,
                )
                audio_paths.append(p)
            sidecar = roots[1] / "._song.m4a"
            sidecar.write_bytes(b"\x00\x05\x16\x07" + b"\0" * 30)
            broken = roots[1] / "broken.m4a"
            broken.write_bytes(b"not a media file")
            paths = audio_paths + [sidecar, broken]
            before = {
                str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in paths
            }
            xml = base / "Library.xml"
            tracks = {
                str(i): {
                    "Track ID": i,
                    "Persistent ID": f"SYNTHETIC{i}",
                    "Name": title,
                    "Artist": "Artist One",
                    "Total Time": 500,
                }
                for i, title in enumerate(("Signal", "Signal (Live)", "Unrelated composition"), 1)
            }
            xml.write_bytes(plistlib.dumps({"Tracks": tracks}))
            result = self.run_cli(
                base,
                "--setup",
                input_text="\n".join([str(xml), *[str(r) for r in roots], "done", ""]),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((base / "output").exists(), "Setup must not start a scan")
            self.assertEqual(
                len(json.loads((base / "config.json").read_text())["offline_music_roots"]), 2
            )
            result = self.run_cli(base, "--inspect", "--non-interactive")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("4 files", result.stdout)
            result = self.run_cli(base, "--non-interactive")
            self.assertEqual(result.returncode, 0, result.stderr)
            wb = load_workbook(base / "output" / "Music_Library_Audit.xlsx", read_only=True)
            rows = list(wb["Match Results"].values)
            status = rows[0].index("Status")
            self.assertEqual([r[status] for r in rows[1:]], ["MATCHED", "REVIEW", "MISSING"])
            wb.close()
            tracks["4"] = {
                "Track ID": 4,
                "Persistent ID": "SYNTHETIC4",
                "Name": "Signal",
                "Artist": "Artist One",
                "Total Time": 500,
            }
            xml.write_bytes(plistlib.dumps({"Tracks": tracks}))
            result = self.run_cli(base, "--non-interactive")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Cache reused: 4; scanning: 0", result.stdout)
            result = self.run_cli(base, script="validate_report.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads((base / "output" / "validation.json").read_text())["status"], "PASS"
            )
            self.assertEqual(
                before,
                {
                    str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in paths
                },
            )

    @unittest.skipUnless(shutil.which("ffprobe"), "Requires FFprobe")
    def test_explicit_repeated_roots_and_missing_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            xml = base / "Library.xml"
            xml.write_bytes(plistlib.dumps({"Tracks": {}}))
            for name in ("one", "two"):
                (base / name).mkdir()
            result = self.run_cli(
                base,
                "--xml",
                str(xml),
                "--music-root",
                "one",
                "--music-root",
                "two",
                "--inspect",
                "--save-config",
                "--non-interactive",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                len(json.loads((base / "config.json").read_text())["offline_music_roots"]), 2
            )
            result = self.run_cli(
                base, "--music-root", "unavailable", "--inspect", "--non-interactive"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Music folder unavailable", result.stderr)
