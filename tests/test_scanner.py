import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audio_scanner import scan_one
from config import DEFAULTS


def load():
    return dict(DEFAULTS)


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires FFmpeg and FFprobe"
)
class ScannerIntegrationTests(unittest.TestCase):
    def test_formats_and_source_immutability(self):
        codecs = {
            "mp3": "libmp3lame",
            "m4a": "aac",
            "flac": "flac",
            "aac": "aac",
            "wav": "pcm_s16le",
            "ogg": "libvorbis",
            "opus": "libopus",
            "wma": "wmav2",
        }
        with tempfile.TemporaryDirectory() as td:
            for extension, codec in codecs.items():
                with self.subTest(extension=extension):
                    p = Path(td) / ("sample." + extension)
                    proc = subprocess.run(
                        [
                            "ffmpeg",
                            "-nostdin",
                            "-v",
                            "error",
                            "-f",
                            "lavfi",
                            "-i",
                            "sine=frequency=440:duration=0.3",
                            "-c:a",
                            codec,
                            "-metadata",
                            "title=Test recording",
                            "-metadata",
                            "artist=Test artist",
                            str(p),
                        ],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    before = (
                        p.stat().st_size,
                        p.stat().st_mtime_ns,
                        hashlib.sha256(p.read_bytes()).hexdigest(),
                    )
                    c = load()
                    c["deep_integrity_check"] = True
                    row = scan_one(td, p, c)
                    self.assertTrue(row["FFprobe OK"], row)
                    self.assertFalse(row["Scan Error"], row)
                    if extension not in ("aac", "wav"):
                        self.assertEqual(row.get("Title"), "Test recording", row)
                        self.assertEqual(
                            set(row.get("Artist", "").split("; ")), {"Test artist"}, row
                        )
                    self.assertEqual(row["Deep Integrity"], "PASS", row)
                    self.assertTrue(row["Archive Eligible"], row)
                    self.assertEqual(
                        before,
                        (
                            p.stat().st_size,
                            p.stat().st_mtime_ns,
                            hashlib.sha256(p.read_bytes()).hexdigest(),
                        ),
                    )

    def test_bad_file_and_appledouble(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "broken.flac"
            p.write_bytes(b"not audio")
            row = scan_one(td, p, load())
            self.assertFalse(row["Archive Eligible"])
            self.assertEqual(row["Integrity"], "FAIL")
            p = Path(td) / "._song.m4a"
            p.write_bytes(b"\x00\x05\x16\x07" + b"\0" * 30)
            row = scan_one(td, p, load())
            self.assertEqual(row["File Type"], "AppleDouble metadata sidecar")
            self.assertEqual(row["Integrity"], "NOT AUDIO")

    def test_m4p_extension_is_never_archive_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "protected.m4p"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=duration=0.1",
                    "-c:a",
                    "aac",
                    "-f",
                    "mp4",
                    str(p),
                ],
                check=True,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            row = scan_one(td, p, load())
            self.assertFalse(row["Archive Eligible"])
            self.assertEqual(row["DRM Status"], "Protected / DRM")

    def test_encrypted_m4a_is_not_archive_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "encrypted.m4a"
            import secrets

            # Ephemeral synthetic test encryption; never a user credential.
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=duration=0.2",
                    "-c:a",
                    "aac",
                    "-encryption_scheme",
                    "cenc-aes-ctr",
                    "-encryption_key",
                    secrets.token_hex(16),
                    "-encryption_kid",
                    secrets.token_hex(16),
                    str(p),
                ],
                check=True,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            row = scan_one(td, p, load())
            self.assertFalse(row["Archive Eligible"], row)
            self.assertEqual(row["DRM Status"], "Protected / DRM", row)
