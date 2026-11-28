#!/usr/bin/env python3
"""Explicit manual FotoMag delivery probe; never schedule this script.

Actions: prepare neutral fixtures, send/resume this one test order, read its
status, or verify only its known workstation folder. There are no automatic
network retries, sleeps, redirects, notifications, printer calls, queue reads,
agent credentials or service changes. Re-run send with the SAME work directory
after interruption. One first-file PUT deliberately sends half its declared
body and closes its own HTTPS connection, then the normal full PUT follows.
One identical create, first full PUT and submit are deliberately repeated to
test idempotency; their completion is recorded in private state.

Pillow is needed only for prepare. The token stays in private_state.json outside
the repository. Restrictive file modes are used where supported; on Windows
this directory inherits the operator's existing ACL. Do not publish this state.
Origin is the exact HTTPS LAN portal origin; normal certificate verification
stays enabled. Filesystem verification is limited to this neutral test order.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import struct
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

API = "https://fotomag-izhevsk.dynv6.net:8443"
ORIGIN = API
CLIENT_NAME = "FM_TEST_20261128"
CONSENT_VERSION = "2026-11-26"
COMMENT = "TECHNICAL TEST DO NOT PRINT"
PROBE_ID = "FM-SITE-20261128-003"
TIMEOUT = 60
MAX_RESPONSE = 64 * 1024
TARGET_JPEG_BYTES = 25 * 1024 * 1024 - 1024
NAMES = ("FM_TEST_20261128_neutral.jpg", "Тест_Кириллица_FotoMag.pdf", "FM_TEST_20261128_25MiB.jpg")
STATE_NAME = "private_state.json"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class ProbeError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ProbeError("invalid_arguments;use_--help")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("redirect_refused")


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def emit(result):
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 4000:
        encoded = '{"ok":false,"error":"output_limit_exceeded"}'
    print(encoded)


def work_directory(value):
    path = Path(value)
    if not path.is_absolute():
        raise ProbeError("work_dir_must_be_absolute")
    path = path.resolve()
    repository = Path(__file__).resolve().parents[1]
    if path == repository or repository in path.parents:
        raise ProbeError("work_dir_must_be_outside_repository")
    return path


def atomic_state(directory, state):
    state["updated_at"] = utc_now()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix="private-state-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(state, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n"); output.flush(); os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, directory / STATE_NAME)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_state(directory):
    path = directory / STATE_NAME
    if path.is_symlink():
        raise ProbeError("state_symlink_refused")
    with path.open("rb") as source:
        raw = source.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ProbeError("state_size_limit_exceeded")
    state = json.loads(raw.decode("utf-8"))
    if not isinstance(state, dict) or state.get("schema") != 1 or state.get("probe_id") != PROBE_ID or state.get("api") != API:
        raise ProbeError("unexpected_private_state")
    if not re.fullmatch(r"[0-9a-f]{64}", state.get("request_key", "")):
        raise ProbeError("invalid_request_key")
    files = state.get("files")
    if not isinstance(files, list) or [item.get("name") for item in files] != list(NAMES):
        raise ProbeError("unexpected_fixture_manifest")
    return state


def file_hash(path):
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ProbeError("fixture_symlink_refused")
    digest, length = hashlib.sha256(), 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            length += len(chunk)
            if length > 25 * 1024 * 1024:
                raise ProbeError("fixture_size_limit_exceeded")
            digest.update(chunk)
    return length, digest.hexdigest()


def verify_fixtures(directory, state, pillow=False):
    for item in state["files"]:
        path = directory / item["name"]
        if path.resolve().parent != directory:
            raise ProbeError("fixture_outside_work_dir")
        length, digest = file_hash(path)
        if length != item["size"] or digest != item["sha256"]:
            raise ProbeError("fixture_changed_since_prepare")
    if pillow:
        from PIL import Image
        for name in (NAMES[0], NAMES[2]):
            with Image.open(directory / name) as photo:
                if photo.format != "JPEG" or photo.size != (640, 480):
                    raise ProbeError("invalid_jpeg_fixture")
                photo.verify()
            with Image.open(directory / name) as photo:
                photo.load()
        pdf = (directory / NAMES[1]).read_bytes()
        if not pdf.startswith(b"%PDF-") or not pdf.rstrip().endswith(b"%%EOF") or b"/Type /Page" not in pdf:
            raise ProbeError("invalid_pdf_fixture")


def padded_jpeg(base, target):
    if not base.startswith(b"\xff\xd8") or target - len(base) < 4:
        raise ProbeError("invalid_jpeg_padding_request")
    remaining, pieces = target - len(base), [base[:2]]
    neutral = b"FOTOMAG NEUTRAL TECHNICAL TEST. DO NOT PRINT. "
    while remaining:
        total = min(65537, remaining)
        if remaining - total in (1, 2, 3):
            total -= 4
        if total < 4:
            raise ProbeError("invalid_jpeg_comment_size")
        count = total - 4
        payload = (neutral * ((count + len(neutral) - 1) // len(neutral)))[:count]
        pieces.append(b"\xff\xfe" + struct.pack(">H", count + 2) + payload)
        remaining -= total
    pieces.append(base[2:])
    result = b"".join(pieces)
    if len(result) != target:
        raise ProbeError("jpeg_target_size_mismatch")
    return result


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / STATE_NAME).exists():
        state = read_state(directory); verify_fixtures(directory, state, pillow=True)
        return {"ok": True, "action": "prepare", "existing": True, "work_dir": str(directory), "files": [{key: item[key] for key in ("name", "size", "sha256")} for item in state["files"]]}
    if any((directory / name).exists() for name in NAMES):
        raise ProbeError("untracked_fixture_exists;use_a_new_empty_work_dir")
    from PIL import Image, ImageDraw
    picture = Image.new("RGB", (640, 480), (220, 220, 220))
    draw = ImageDraw.Draw(picture)
    draw.rectangle((40, 40, 600, 440), outline=(60, 60, 60), width=3)
    draw.text((70, 200), "FOTOMAG TECHNICAL TEST\nDO NOT PRINT\nNEUTRAL JPEG", fill=(30, 30, 30))
    small = io.BytesIO(); picture.save(small, format="JPEG", quality=90)
    (directory / NAMES[0]).write_bytes(small.getvalue())
    (directory / NAMES[2]).write_bytes(padded_jpeg(small.getvalue(), TARGET_JPEG_BYTES))
    page = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(page).text((100, 140), "FOTOMAG TECHNICAL TEST\nDO NOT PRINT\nNEUTRAL ONE PAGE PDF", fill="black")
    page.save(directory / NAMES[1], format="PDF", resolution=150)
    manifest = []
    for name in NAMES:
        size, digest = file_hash(directory / name)
        manifest.append({"name": name, "size": size, "sha256": digest, "uploaded": False})
    state = {"schema": 1, "probe_id": PROBE_ID, "api": API, "created_at": utc_now(),
             "request_key": secrets.token_hex(32), "files": manifest, "order": None,
             "create_repeat_verified": False, "first_put_repeat_verified": False,
             "interrupted_first_put": {"attempted": False, "completed": False, "bytes_sent": 0},
             "submit_started": False, "submit_received": False, "submit_repeat_verified": False,
             "last_operation": "prepared"}
    verify_fixtures(directory, state, pillow=True)
    atomic_state(directory, state)  # Persist key and immutable fixture manifest BEFORE any create.
    return {"ok": True, "action": "prepare", "work_dir": str(directory), "files": [{key: item[key] for key in ("name", "size", "sha256")} for item in manifest]}


def call_api(method, route, *, payload=None, body=None, token=None, require_json=True):
    if not route.startswith("/api/orders") or "?" in route or "#" in route or ".." in route:
        raise ProbeError("unexpected_api_route")
    headers = {"Origin": ORIGIN, "Accept": "application/json", "User-Agent": "FotoMagManualDeliveryProbe/1.0"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif body is not None:
        headers["Content-Type"] = "application/octet-stream"
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(Request(API + route, data=body, headers=headers, method=method), timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ProbeError("response_size_limit_exceeded")
            if not 200 <= response.status < 300:
                raise ProbeError("unexpected_http_status")
            if not require_json:
                return {}, response.status
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ProbeError("unexpected_json_response")
            return value, response.status
    except HTTPError as error:
        raise ProbeError("http_" + str(error.code) + ";rerun_same_action_and_work_dir_after_review") from None
    except (URLError, TimeoutError) as error:
        raise ProbeError("network_or_tls_failure;outcome_unknown;rerun_same_work_dir") from None


def create_payload(state):
    return {"kind": "documents", "phone": "", "client_name": CLIENT_NAME, "comment": COMMENT,
            "consent": True, "consent_version": CONSENT_VERSION, "request_key": state["request_key"],
            "files": [{"name": item["name"], "size": item["size"]} for item in state["files"]]}


def interrupt_first_put(directory, state, route, body, token):
    """Cut this one neutral request only; never alter workstation networking."""
    proof = state.setdefault("interrupted_first_put", {"attempted": False, "completed": False, "bytes_sent": 0})
    if proof["attempted"]:
        return
    half = max(1, len(body) // 2)
    proof.update(attempted=True, completed=False, bytes_sent=0, declared_bytes=len(body), planned_bytes=half)
    state["last_operation"] = "partial_first_put_started"
    atomic_state(directory, state)  # A crash cannot cause another deliberate cut.
    connection = http.client.HTTPSConnection("fotomag-izhevsk.dynv6.net", 8443, timeout=TIMEOUT, context=ssl.create_default_context())
    try:
        connection.putrequest("PUT", route, skip_accept_encoding=True)
        connection.putheader("Origin", ORIGIN)
        connection.putheader("Authorization", "Bearer " + token)
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(len(body)))
        connection.putheader("User-Agent", "FotoMagManualDeliveryProbe/1.0")
        connection.putheader("Connection", "close")
        connection.endheaders()
        connection.send(body[:half])
    finally:
        connection.close()
    proof.update(completed=True, bytes_sent=half, connection_closed=True)
    state["last_operation"] = "partial_first_put_connection_closed"
    atomic_state(directory, state)


def normalized_order(reply, expected_count):
    if not SAFE_ID.fullmatch(str(reply.get("order_id", ""))) or not SAFE_ID.fullmatch(str(reply.get("receipt", ""))):
        raise ProbeError("invalid_order_identity")
    if not isinstance(reply.get("upload_token"), str) or not reply["upload_token"]:
        raise ProbeError("missing_order_token")
    files = reply.get("files")
    if not isinstance(files, list) or len(files) != expected_count or any(not isinstance(item, dict) or not SAFE_ID.fullmatch(str(item.get("file_id", ""))) for item in files):
        raise ProbeError("invalid_order_file_slots")
    ids = [item["file_id"] for item in files]
    if len(set(ids)) != len(ids):
        raise ProbeError("duplicate_order_file_slots")
    return {"order_id": reply["order_id"], "receipt": reply["receipt"], "upload_token": reply["upload_token"], "file_ids": ids}


def own_order(state):
    order = state.get("order")
    if not isinstance(order, dict) or not SAFE_ID.fullmatch(str(order.get("order_id", ""))) or not SAFE_ID.fullmatch(str(order.get("receipt", ""))):
        raise ProbeError("no_valid_order_in_private_state")
    if not isinstance(order.get("upload_token"), str) or not order["upload_token"]:
        raise ProbeError("no_order_token_in_private_state")
    if not isinstance(order.get("file_ids"), list) or len(order["file_ids"]) != len(NAMES) or any(not SAFE_ID.fullmatch(str(item)) for item in order["file_ids"]):
        raise ProbeError("invalid_private_file_slots")
    return order


def status_of(state):
    order = own_order(state)
    answer, code = call_api("GET", "/api/orders/" + quote(order["order_id"], safe="") + "/status", token=order["upload_token"])
    if answer.get("receipt") != order["receipt"] or type(answer.get("downloaded_to_pc")) is not bool or not isinstance(answer.get("status"), str):
        raise ProbeError("status_does_not_match_this_order")
    status = answer["status"] if answer["status"] in ("pending", "received") else "unconfirmed"
    delivered = status == "received" and answer["downloaded_to_pc"] is True
    if answer["downloaded_to_pc"] and not delivered:
        raise ProbeError("inconsistent_delivery_status")
    return {"receipt": order["receipt"], "status": status, "server_accepted": status in ("pending", "received"),
            "downloaded_to_pc": delivered, "http_status": code}


def submit_once(state):
    order = own_order(state)
    answer, code = call_api("POST", "/api/orders/" + quote(order["order_id"], safe="") + "/submit", payload={}, token=order["upload_token"])
    if answer.get("receipt") != order["receipt"] or answer.get("received") is not True:
        raise ProbeError("submit_receipt_not_confirmed")
    return code


def send(directory):
    state = read_state(directory); verify_fixtures(directory, state)
    if state["order"] is None:
        state["last_operation"] = "create_started"; atomic_state(directory, state)
        reply, code = call_api("POST", "/api/orders", payload=create_payload(state))
        state["order"] = normalized_order(reply, len(NAMES)); state["create_http_status"] = code
        state["last_operation"] = "created"; atomic_state(directory, state)
    order = own_order(state)
    if not state["create_repeat_verified"]:
        state["last_operation"] = "create_repeat_started"; atomic_state(directory, state)
        reply, code = call_api("POST", "/api/orders", payload=create_payload(state))
        repeated = normalized_order(reply, len(NAMES))
        if any(repeated[key] != order[key] for key in ("order_id", "receipt", "file_ids")):
            raise ProbeError("create_idempotency_failed;do_not_create_another_order")
        state["order"] = order = repeated
        state["create_repeat_verified"] = True; state["create_repeat_http_status"] = code
        atomic_state(directory, state)
    if state["submit_started"] and not state["submit_received"]:
        current = status_of(state)
        if current["server_accepted"]:
            state["submit_received"] = True; state["last_status"] = current; atomic_state(directory, state)
    if not state["submit_received"]:
        for index, item in enumerate(state["files"]):
            route = "/api/orders/" + quote(order["order_id"], safe="") + "/files/" + quote(order["file_ids"][index], safe="")
            if item["uploaded"] and (index != 0 or state["first_put_repeat_verified"]):
                continue
            body = (directory / item["name"]).read_bytes()
            if len(body) != item["size"] or hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise ProbeError("fixture_changed_before_put")
            if not item["uploaded"]:
                if index == 0:
                    interrupt_first_put(directory, state, route, body, order["upload_token"])
                state["last_operation"] = "put_" + str(index) + "_started"; atomic_state(directory, state)
                _, code = call_api("PUT", route, body=body, token=order["upload_token"], require_json=False)
                item["uploaded"] = True; item["put_http_status"] = code; atomic_state(directory, state)
            if index == 0 and not state["first_put_repeat_verified"]:
                state["last_operation"] = "first_put_repeat_started"; atomic_state(directory, state)
                _, code = call_api("PUT", route, body=body, token=order["upload_token"], require_json=False)
                state["first_put_repeat_verified"] = True; state["first_put_repeat_http_status"] = code; atomic_state(directory, state)
        state["submit_started"] = True; state["last_operation"] = "submit_started"; atomic_state(directory, state)
        state["submit_http_status"] = submit_once(state)
        state["submit_received"] = True; state["last_operation"] = "server_received"; atomic_state(directory, state)
    if not state["submit_repeat_verified"]:
        state["last_operation"] = "submit_repeat_started"; atomic_state(directory, state)
        state["submit_repeat_http_status"] = submit_once(state)
        state["submit_repeat_verified"] = True; atomic_state(directory, state)
    current = status_of(state)
    state["last_status"] = current; state["last_operation"] = "send_complete"; atomic_state(directory, state)
    interruption = state.get("interrupted_first_put", {"attempted": False, "completed": False, "bytes_sent": 0})
    return {"ok": interruption.get("completed") is True, "action": "send", "order_id": order["order_id"], "receipt": order["receipt"], "file_count": len(NAMES),
            "idempotency": {"same_create_order": state["create_repeat_verified"], "first_put_repeat": state["first_put_repeat_verified"], "same_submit_order": state["submit_repeat_verified"]},
            "request_interruption": interruption,
            "server_status": current, "instruction": "Run status or verify explicitly; no printing is requested."}


def verify_delivery(directory):
    if os.name != "nt":
        raise ProbeError("verify_requires_the_authorized_windows_workstation")
    state = read_state(directory); verify_fixtures(directory, state)
    order = own_order(state)
    target = Path(r"D:\2026\11\28\Напрямую\FM_TEST_20261128") / order["receipt"]
    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
        raise ProbeError("delivery_folder_link_refused")
    originals, processed = target / "Исходники", target / "Обработанные JPEG"
    folder_state = {"order": target.is_dir(), "originals": originals.is_dir(), "processed_jpeg": processed.is_dir()}
    for candidate in (originals, processed):
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise ProbeError("delivery_subfolder_link_refused")
    rows, locations = [], []
    for index, item in enumerate(state["files"], start=1):
        received_name = f"{index:02d}_{item['name']}"
        candidates = [base / received_name for base in (target, originals) if (base / received_name).is_file()]
        row = {"name": item["name"], "received_name": received_name, "copies_found": len(candidates), "expected_size": item["size"], "expected_sha256": item["sha256"], "ok": False}
        if len(candidates) == 1:
            size, digest = file_hash(candidates[0]); locations.append(str(candidates[0].parent))
            row.update(size=size, sha256=digest, ok=size == item["size"] and digest == item["sha256"])
        rows.append(row)
    media_extensions = {".jpg", ".jpeg", ".pdf", ".png", ".webp", ".heic", ".heif", ".docx", ".xlsx"}
    media_count = sum(1 for base in (target, originals) if base.is_dir() for path in base.iterdir() if path.is_file() and path.suffix.lower() in media_extensions)
    files_ok = all(row["ok"] for row in rows) and media_count == len(NAMES)
    return {"ok": files_ok and all(folder_state.values()), "action": "verify", "receipt": order["receipt"], "path": str(target),
            "folders": folder_state, "expected_file_count": len(NAMES), "media_file_count": media_count,
            "source_locations": sorted(set(locations)), "files_integrity_ok": files_ok, "files": rows}


def main(argv=None):
    try:
        parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--action", required=True, choices=("prepare", "send", "status", "verify"))
        parser.add_argument("--work-dir", required=True, help="Absolute private directory outside this repository; always reuse for this probe")
        args = parser.parse_args(argv)
        directory = work_directory(args.work_dir)
        if args.action == "prepare":
            result = prepare(directory)
        elif args.action == "send":
            result = send(directory)
        elif args.action == "status":
            result = {"ok": True, "action": "status", **status_of(read_state(directory))}
        else:
            result = verify_delivery(directory)
        emit(result); return 0 if result["ok"] else 1
    except KeyboardInterrupt:
        emit({"ok": False, "error": "interrupted;resume_with_same_work_dir"}); return 130
    except Exception as error:
        reason = str(error) if isinstance(error, ProbeError) else "unexpected_" + type(error).__name__
        emit({"ok": False, "error": reason[:220]}); return 2


if __name__ == "__main__":
    raise SystemExit(main())
