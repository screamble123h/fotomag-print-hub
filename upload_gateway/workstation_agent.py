r"""FotoMag web-channel receiver: archive orders in D:\2026\DATE\Напрямую\CLIENT.

This only downloads pending web orders from a separate HTTPS queue. Never
opens/prints files, modifies legacy bot data, or overwrites existing files.
The executable must be installed and started separately with the owner's
explicit local-computer authorization. No action is taken by importing it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_URL = os.environ.get("FOTOMAG_API_URL", "").rstrip("/")
TOKEN = os.environ.get("FOTOMAG_AGENT_TOKEN", "")
ARCHIVE_ROOT = Path(os.environ.get("FOTOMAG_ARCHIVE_ROOT", r"D:\2026"))
# Configure to match EXISTING archive, e.g. "%m.%Y/%d.%m.%Y" for month/day folders.
DATE_SUBPATH = os.environ.get("FOTOMAG_DATE_SUBPATH", "%m/%d")
INTERVAL = max(15, int(os.environ.get("FOTOMAG_POLL_SECONDS", "30")))
CHANNEL = "Напрямую"
IZHEVSK_TIME = timezone(timedelta(hours=4), name="Izhevsk")
LOG = logging.getLogger("fotomag-direct-inbox")
RECEIPT_PATTERN = re.compile(r"FM-W-(\d{8})-[A-F0-9]{7}\Z")
UUID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")
SHA_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{index}" for prefix in ("COM", "LPT") for index in range(1, 10)
}


def api_request(path: str, method: str = "GET") -> dict:
    url = API_URL + path
    req = urllib.request.Request(
        url,
        data=b"" if method == "POST" else None,
        headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def safe_part(value: str, max_length: int = 55) -> str:
    # Keep normal Cyrillic/Latin names; reject path traversal and Windows devices.
    value = unicodedata.normalize("NFC", str(value)).replace("\\", "/").split("/")[-1]
    value = re.sub(r"[^\w .()-]", "_", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value).strip(" ._")[:max_length].rstrip(" ._")
    if not value:
        return "Без_имени"
    if value.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        value = "_" + value
    return value


def safe_filename(name: str) -> str:
    name = str(name).replace("\\", "/").split("/")[-1]
    stem, dot, ext = name.rpartition(".")
    if not dot or not re.fullmatch(r"[a-zA-Z0-9]{1,8}", ext):
        raise ValueError("Invalid file extension in order")
    ext = ext.lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "heic", "heif", "pdf", "docx", "xlsx"}:
        raise ValueError("Unsupported file type in order")
    return safe_part(stem, 95) + "." + ext


def order_destination(order: dict, root: Path, pattern: str = DATE_SUBPATH) -> Path:
    """Pure mapping; does not write anything to disk.

    D:\2026\11\21\Напрямую\Алексей\FM-W-20261121-ABC1234
    """
    receipt = str(order.get("receipt", ""))
    match = RECEIPT_PATTERN.fullmatch(receipt)
    if not match:
        raise ValueError("Invalid order receipt")
    created = int(order["created_ts"])
    if not 1_700_000_000 <= created <= 4_102_444_800:
        raise ValueError("Order date is out of range")
    date = datetime.fromtimestamp(created, IZHEVSK_TIME)
    if match.group(1) != date.strftime("%Y%m%d"):
        raise ValueError("Receipt and local Izhevsk order date disagree")
    # The archive is year-specific, never silently write 2027 under 2026.
    if root.name != str(date.year) and os.name == "nt":
        raise ValueError("Configure the correct D: year archive before new-year orders")
    formatted = date.strftime(pattern).replace("\\", "/")
    parts = formatted.split("/")
    if not 1 <= len(parts) <= 3:
        raise ValueError("Invalid archive date pattern")
    if any(not re.fullmatch(r"[\w .-]{1,64}", p, re.UNICODE) or p in (".", "..")
           for p in parts):
        raise ValueError("Unsafe archive date folder")
    client_name = safe_part(order.get("client_name") or "Без_имени", 46)
    return root.joinpath(*parts, CHANNEL, client_name, receipt)


def validate_pc_archive(root: Path) -> Path:
    if os.name != "nt":
        raise RuntimeError("Production receiver may run only on the authorized Windows computer")
    if not root.is_absolute() or root.drive.upper() != "D:":
        raise RuntimeError("Archive root must be an absolute D: path")
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("Existing D: year archive was not found. Nothing has been created")
    resolved = root.resolve(strict=True)
    if resolved.drive.upper() != "D:":
        raise RuntimeError("Archive root resolves outside D:")
    return resolved


def ensure_safe_directory(folder: Path, root: Path) -> None:
    resolved = root.resolve(strict=True)
    if not folder.resolve(strict=False).is_relative_to(resolved):
        raise ValueError("Destination escapes the existing year archive")
    current = root
    for component in folder.relative_to(root).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("Symbolic link is forbidden in an order archive")
        current.mkdir(exist_ok=True)
    if not folder.resolve(strict=True).is_relative_to(resolved):
        raise ValueError("Destination redirected outside archive")


def download_file(order_file: dict, index: int, folder: Path) -> None:
    file_id = str(order_file["file_id"])
    expected_sha = str(order_file["sha256"])
    size = int(order_file["size"])
    if not UUID_PATTERN.fullmatch(file_id) or not SHA_PATTERN.fullmatch(expected_sha):
        raise ValueError("Invalid file identifier or SHA-256")
    if size < 1 or size > 25 * 1024 * 1024:
        raise ValueError("Invalid file size in queue")
    name = safe_filename(order_file["name"])
    target = folder / f"{index:02d}_{name}"
    if target.exists():
        if not target.is_file() or sha256_file(target) != expected_sha:
            raise FileExistsError(f"Different file already exists: {target}")
        return  # Retry after ACK failure: never download/overwrite twice.
    temp = folder / f".{index:02d}_{file_id}_{uuid.uuid4().hex}.part"
    url = API_URL + "/api/agent/files/" + file_id
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
                if count > size:
                    raise ValueError("Server returned oversized file")
                sha.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if count != size or sha.hexdigest() != expected_sha:
            raise ValueError("File integrity check failed")
        if target.exists():
            raise FileExistsError(f"Order file already exists: {target}")
        temp.rename(target)  # On Windows rename refuses overwriting an existing file.
    except Exception:
        # Only our unique partial file from this very attempt is cleaned up.
        temp.unlink(missing_ok=True)
        raise


def create_exclusive(path: Path, value: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise FileExistsError(f"Conflicting existing order metadata: {path}")
        return
    with path.open("x", encoding="utf-8") as target:
        target.write(value)


def receive_order(order: dict, root: Path = ARCHIVE_ROOT,
                  pattern: str = DATE_SUBPATH) -> Path:
    receipt = str(order.get("receipt", ""))
    folder = order_destination(order, root, pattern)
    ensure_safe_directory(folder, root)
    files = list(order["files"])
    if not 1 <= len(files) <= 10:
        raise ValueError("Unexpected file count")
    if not re.fullmatch(r"[a-f0-9]{32}", str(order["order_id"])):
        raise ValueError("Unsafe order id")
    for index, info in enumerate(files, start=1):
        download_file(info, index, folder)
    details = {
        "channel": CHANNEL, "receipt": receipt,
        "service": order["kind"], "client_name": order.get("client_name", ""),
        "phone": order["phone"], "comment": order["comment"],
        "created_ts": order["created_ts"],
        "files": [
            {"name": info["name"], "size": info["size"], "sha256": info["sha256"]}
            for info in files
        ],
        "notice": "Входящие файлы: проверить антивирусом и глазами; не печатать автоматически.",
    }
    create_exclusive(folder / "order.json", json.dumps(details, ensure_ascii=False, indent=2) + "\n")
    service_label = {
        "photos": "Печать фотографий",
        "documents": "Печать документов",
        "id450": "Фото на документы из готового снимка — 450 ₽",
    }.get(order["kind"], "Уточнить услугу")
    text = (
        f"Канал: {CHANNEL}\nНомер заявки: {receipt}\n"
        f"Дата поступления: {datetime.fromtimestamp(int(order['created_ts']), IZHEVSK_TIME):%d.%m.%Y %H:%M}\n"
        f"Клиент: {order.get('client_name') or 'Не указано'}\n"
        f"Телефон: {order['phone']}\nУслуга: {service_label}\n"
        f"Комментарий: {order['comment'] or 'Нет'}\n"
        f"Файлов: {len(files)}\n\n"
        "ВНИМАНИЕ: Перед открытием проверить файлы; печать и стоимость подтверждаются сотрудником.\n"
    )
    create_exclusive(folder / "ЗАКАЗ.txt", text)
    # Acknowledge only AFTER all files and both metadata records are stored.
    api_request("/api/agent/orders/" + order["order_id"] + "/ack", method="POST")
    LOG.info("Order %s saved to %s (%d file(s))", receipt, folder, len(files))
    return folder


def main() -> int:
    if not API_URL.startswith("https://") or len(TOKEN) < 32:
        print("Set HTTPS FOTOMAG_API_URL and private FOTOMAG_AGENT_TOKEN", file=sys.stderr)
        return 2
    try:
        root = validate_pc_archive(ARCHIVE_ROOT)
        # A preview is non-destructive; the receiver is enabled only by explicit launch.
        LOG.warning("Archive root confirmed: %s; date subpath: %s", root, DATE_SUBPATH)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Receiver not started: {error}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    failure_count = 0
    while True:
        try:
            orders = api_request("/api/agent/orders")["orders"]
            for order in orders:
                try:
                    receive_order(order, root, DATE_SUBPATH)
                except Exception:
                    LOG.exception("Failed to receive order %s; will retry", order.get("receipt", "?"))
            failure_count = 0
        except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError):
            failure_count = min(5, failure_count + 1)
            LOG.exception("Queue unavailable; retrying")
        time.sleep(INTERVAL * (2 ** min(failure_count, 3)))


if __name__ == "__main__":
    sys.exit(main())
