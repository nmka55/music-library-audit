import json
import subprocess
import re


def run_tool(args, timeout):
    try:
        p = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (
            p.returncode,
            p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace")[:8000],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def probe(path, config):
    code, out, err = run_tool(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        config["probe_timeout_seconds"],
    )
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        data = {}
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    audio_errors = "\n".join(
        line
        for line in err.splitlines()
        if not re.match(r"^\[(png|mjpeg|jpeg2000|bmp|gif|webp) @", line)
    )
    return (
        code == 0 and bool(streams) and not audio_errors.strip(),
        streams,
        data.get("format", {}),
        err,
    )


def deep_check(path, config):
    if not config["deep_integrity_check"]:
        return "NOT TESTED", ""
    code, _, err = run_tool(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        config["deep_timeout_seconds"],
    )
    return ("PASS" if code == 0 and not err.strip() else "FAIL"), err
