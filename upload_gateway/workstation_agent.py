"""FotoMag Windows inbox synchronizer: poll HTTPS; no remote desktop access or printing.

Run only after explicit owner approval. New orders are written ONLY under
FOTOMAG_INBOX_DIR; existing files are never overwritten or deleted.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API_URL = os.environ.get("FOTOMAG_API_URL", "").rstrip("/")
TOKEN = os.environ.get("FOTOMAG_AGENT_TOKEN", "")
INBOX = Path(os.environ.get("FOTOMAG_INBOX_DIR", r"D:\FotoMag_WEB_ORDERS"))
INTERVAL = max(15, int(os.environ.get("FOTOMAG_POLL_SECONDS", "30")))
LOG = logging.getLogger("fotomag-web-inbox")


def request_json(path: str, method: str = "GET") -> dict:
    url = API_URL + path
    req = urllib.request.Request(
        url, data=b"" if method == "POST" else None,
        headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def clean_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", name).strip(" .")
    return name[:120] or "file"


def receive_order(order: dict) -> None:
    receipt = order["receipt"]
    if not re.fullmatch(r"FM-W-[0-9]{8}-[0-9A-F]{7}", receipt):
        raise ValueError("Unsafe receipt from server")
    folder = INBOX / receipt
    folder.mkdir(parents=True, exist_ok=True)
    for index, file in enumerate(order["files"], start=1):
        name = clean_filename(file["name"])
        target = folder / f"{index:02d}_{name}"
        expected = file["sha256"]
        if target.exists():
            if digest(target) != expected:
                raise FileExistsError(f"Different file already exists: {target}")
            continue
        temp = folder / (f".{index:02d}_" + file["file_id"] + "." + uuid.uuid4().hex + ".part")
        # Unique per attempt: never touch temp files left by a previous run.
        url = API_URL + "/api/agent/files/" + file["file_id"]
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
        sha = hashlib.sha256()
        count = 0
        try:
            with urllib.request.urlopen(req, timeout=90) as response, temp.open("xb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > file["size"]:
                        raise ValueError("Server file exceeds expected size")
                    sha.update(chunk)
                    output.write(chunk)
            if count != file["size"] or sha.hexdigest() != expected:
                raise ValueError("File integrity check failed")
            if target.exists():
                raise FileExistsError(str(target))
            temp.rename(target)  # Windows refuses overwriting an existing target.
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    metadata = {
        "receipt": receipt, "service": order["kind"], "phone": order["phone"],
        "comment": order["comment"], "created_ts": order["created_ts"],
        "files": [{"name": f["name"], "size": f["size"], "sha256": f["sha256"]}
                  for f in order["files"]],
        "note": "Files require employee verification; never auto-print or auto-open.",
    }
    metadata_file = folder / "order.json"
    if not metadata_file.exists():
        with metadata_file.open("x", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)
    request_json("/api/agent/orders/" + order["order_id"] + "/ack", method="POST")
    LOG.info("Downloaded and acknowledged %s (%d file(s))", receipt, len(order["files"]))


def main() -> int:
    if not API_URL.startswith("https://") or len(TOKEN) < 32:
        print("Configure HTTPS FOTOMAG_API_URL and FOTOMAG_AGENT_TOKEN", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    INBOX.mkdir(parents=True, exist_ok=True)
    LOG.info("FotoMag inbox monitor started; destination: %s", INBOX)
    failure_count = 0
    while True:
        try:
            orders = request_json("/api/agent/orders")["orders"]
            for order in orders:
                try:
                    receive_order(order)
                except Exception:
                    LOG.exception("Failed to download order %s; will retry", order.get("receipt", "?"))
            failure_count = 0
        except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError):
            failure_count = min(5, failure_count + 1)
            LOG.exception("Queue unavailable; retrying")
        time.sleep(INTERVAL * (2 ** min(failure_count, 3)))


if __name__ == "__main__":
    sys.exit(main())
