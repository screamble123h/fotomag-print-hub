"""FotoMag Windows receiver launcher: no secrets in commands, no automatic installation.

The local agent_config.json is deliberately NOT in GitHub. It must be generated
only when a real Russian-hosted HTTPS gateway is ready. No launcher autostart
is registered by this file.
"""
from __future__ import annotations

import json
import logging
import ntpath
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

CONFIG = Path(os.environ.get(
    "FOTOMAG_AGENT_CONFIG", r"D:\FotoMag_Direct_Upload_Channel\agent_config.json"
))
BAD_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_settings(settings: dict) -> dict:
    """Pure validation; safe on Linux CI and Windows; never logs credentials."""
    if not isinstance(settings, dict):
        raise ValueError("Config is not a JSON object")
    accepted = {"api_url", "agent_token", "archive_root", "date_subpath", "poll_seconds"}
    if set(settings) - accepted:
        raise ValueError("Unrecognized config field")
    required = accepted - {"date_subpath", "poll_seconds"}
    if not required.issubset(settings):
        raise ValueError("Missing required config field")
    api = str(settings["api_url"])
    url = urlsplit(api)
    host = (url.hostname or "").lower()
    if (url.scheme != "https" or not host or host in BAD_HOSTS or
            host.endswith(".trycloudflare.com") or host.endswith(".github.io") or
            url.username or url.password or url.query or url.fragment or
            url.path not in ("", "/") or url.port not in (None, 443) or
            not re.fullmatch(r"[a-z0-9.-]{4,253}", host) or
            "." not in host):
        raise ValueError("Permanent agent requires a dedicated HTTPS domain")
    token = str(settings["agent_token"])
    if (len(token) < 40 or token.startswith("REPLACE") or
            not re.fullmatch(r"[A-Za-z0-9_-]{40,160}", token)):
        raise ValueError("Invalid private token format")
    root = str(settings["archive_root"])
    year = ntpath.basename(ntpath.normpath(root))
    if (ntpath.splitdrive(root)[0].upper() != "D:" or
            not ntpath.isabs(root) or not re.fullmatch(r"20[2-9]\d", year) or
            "\\.." in root or "/" in root):
        raise ValueError("Archive must use an existing D:\\year directory")
    pattern = settings.get("date_subpath", "%m/%d")
    if pattern != "%m/%d":  # Match the verified FotoMag date folder structure.
        raise ValueError("FotoMag month/day pattern is locked")
    seconds = int(settings.get("poll_seconds", 30))
    if seconds < 15 or seconds > 300:
        raise ValueError("Poll interval out of range")
    return {
        "api_url": url.geturl().rstrip("/"),
        "agent_token": token,
        "archive_root": root,
        "date_subpath": pattern,
        "poll_seconds": seconds,
    }


def lock_instance(path: Path):
    if os.name != "nt":
        raise RuntimeError("Production launcher is Windows-only")
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise RuntimeError("Another FotoMag direct-upload receiver is running")
    return handle


def main() -> int:
    if os.name != "nt":
        print("This receiver runs only on Windows", file=sys.stderr)
        return 2
    if not CONFIG.is_file() or CONFIG.is_symlink():
        print("FotoMag receiver is NOT ACTIVE: approved HTTPS config is missing")
        return 2
    try:
        settings = validate_settings(json.loads(CONFIG.read_text(encoding="utf-8")))
        import workstation_agent as receiver
        root = receiver.validate_pc_archive(Path(settings["archive_root"]))
        lock = lock_instance(CONFIG.parent / ".receiver.lock")
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print("Receiver preflight failed:", type(exc).__name__, file=sys.stderr)
        return 2
    # Do not print or put secrets into Task Scheduler command line.
    receiver.API_URL = settings["api_url"]
    receiver.TOKEN = settings["agent_token"]
    receiver.ARCHIVE_ROOT = root
    receiver.DATE_SUBPATH = settings["date_subpath"]
    receiver.INTERVAL = settings["poll_seconds"]
    logs = CONFIG.parent / "logs"
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        logs / "receiver.log", maxBytes=2 * 1024 * 1024,
        backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"
    ))
    receiver.LOG.addHandler(handler)
    receiver.LOG.setLevel(logging.INFO)
    print("FotoMag receiver started: HTTPS + D archive. No inbound PC ports.")
    try:
        return receiver.main()
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
