import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"
spec = importlib.util.spec_from_file_location("prepare_release", script)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PublicationTests(unittest.TestCase):
    def test_allowlist_excludes_private_artifacts_and_normalizes_zip(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            for relative in release.PUBLIC_FILES:
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("public synthetic text\n", encoding="utf-8")
            for relative in (
                "config.json",
                "input/Library.xml",
                "cache/inventory.sqlite3",
                "output/report.xlsx",
                ".git/config",
                "src/__pycache__/private.pyc",
            ):
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("PRIVATE_MARKER")
            target, archive = release.prepare(project)
            published = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
            self.assertEqual(published, set(release.PUBLIC_FILES) | {"PUBLIC_MANIFEST.json"})
            with zipfile.ZipFile(archive) as zipped:
                self.assertTrue(
                    all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in zipped.infolist())
                )
                self.assertFalse(
                    any(b"PRIVATE_MARKER" in zipped.read(n) for n in zipped.namelist())
                )
            second, second_zip = release.prepare(project)
            self.assertNotEqual(target, second)
            self.assertEqual(archive.read_bytes(), second_zip.read_bytes())

    def test_current_account_paths_and_credentials_are_rejected(self):
        self.assertTrue(release.privacy_issues(str(Path.home())))
        token = "gh" + "p_" + "x" * 30
        self.assertIn("Credential-shaped token", release.privacy_issues(token))
        self.assertEqual(
            release.privacy_issues("Use input/Library.xml and relative public templates."), []
        )
