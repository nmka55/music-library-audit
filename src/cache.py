import json
import sqlite3

VERSION = 1


class Cache:
    def __init__(self, directory):
        self.db = sqlite3.connect(str(directory / "inventory.sqlite3"))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, version INTEGER, data TEXT)"
        )

    def get(self, path, stat, deep):
        row = self.db.execute(
            "SELECT data FROM files WHERE path=? AND size=? AND mtime=? AND version=?",
            (str(path), stat.st_size, stat.st_mtime_ns, VERSION),
        ).fetchone()
        if row:
            data = json.loads(row[0])
            if path.name.startswith("._") and not data.get("File Type"):
                return None
            if data.get("Scan Error") == "Metadata: ":
                return None
            if (
                data.get("FFprobe Error")
                and data.get("File Type") != "AppleDouble metadata sidecar"
                and data.get("Probe Policy") != 2
            ):
                return None
            if "timed out" in str(
                data.get("FFprobe Error", "")
            ).lower() or "File changed during scan" in data.get("Scan Error", ""):
                return None
            if not deep or data.get("Deep Integrity") in ("PASS", "FAIL"):
                return data

    def put(self, path, stat, data):
        self.db.execute(
            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
            (
                str(path),
                stat.st_size,
                stat.st_mtime_ns,
                VERSION,
                json.dumps(data, ensure_ascii=False),
            ),
        )

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()
