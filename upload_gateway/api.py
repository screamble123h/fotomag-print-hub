"""FotoMag direct-upload relay: private disk queue, no automatic printing.

Requires HTTPS reverse proxy, a Russian-hosted server and explicit environment
configuration before production. Never expose AGENT_TOKEN or data directory.
"""
from __future__ import annotations

import hashlib
import hmac
from contextlib import contextmanager
import os
import re
import secrets
import sqlite3
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from upload_gateway.antivirus import scan_file, ScannerUnavailable, ThreatDetected

DATA = Path(os.environ.get("FOTOMAG_DATA_DIR", "/data")).resolve()
AGENT_TOKEN = os.environ.get("FOTOMAG_AGENT_TOKEN", "")
SITE_ORIGIN = os.environ.get("FOTOMAG_SITE_ORIGIN", "https://screamble123h.github.io")
if len(AGENT_TOKEN) < 32:
    raise RuntimeError("Set FOTOMAG_AGENT_TOKEN to a random value of at least 32 characters")
if not (SITE_ORIGIN.startswith("https://") or SITE_ORIGIN.startswith("http://127.0.0.1:")):
    raise RuntimeError("FOTOMAG_SITE_ORIGIN must be an HTTPS origin")
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS = DATA / "uploads"
UPLOADS.mkdir(exist_ok=True)
DB = DATA / "queue.sqlite3"
MAX_FILE = 25 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_FILES = 10
MAX_HOURLY = 6
UPLOAD_MODE = os.environ.get('FOTOMAG_UPLOAD_MODE', 'disabled')
if UPLOAD_MODE not in ('disabled', 'staging', 'production'):
    raise RuntimeError('Invalid upload mode')
SHOP_TZ = timezone(timedelta(hours=4))  # Izhevsk/Samara standard UTC+4.
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf", ".docx", ".xlsx"}

app = FastAPI(title="FotoMag upload gateway", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[SITE_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@contextmanager
def db():
    connection = sqlite3.connect(str(DB), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, receipt TEXT UNIQUE NOT NULL,
                token_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
                phone TEXT NOT NULL, client_name TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL,
                ip_hash TEXT NOT NULL, status TEXT NOT NULL,
                created_ts INTEGER NOT NULL, received_ts INTEGER
            );
            CREATE INDEX IF NOT EXISTS orders_created_ip ON orders(ip_hash,created_ts);
            CREATE INDEX IF NOT EXISTS orders_status ON orders(status,created_ts);
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
                original_name TEXT NOT NULL, extension TEXT NOT NULL,
                expected_size INTEGER NOT NULL, uploaded_size INTEGER,
                sha256 TEXT, stored_path TEXT
            );
            CREATE INDEX IF NOT EXISTS files_order ON files(order_id);
        """)
        # Support an existing test database without deleting any orders.
        columns = {row[1] for row in c.execute("PRAGMA table_info(orders)")}
        if "client_name" not in columns:
            c.execute("ALTER TABLE orders ADD COLUMN client_name TEXT NOT NULL DEFAULT ''")


initialize()


class IncomingFile(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    size: int = Field(gt=0, le=MAX_FILE)


class IncomingOrder(BaseModel):
    kind: Literal["photos", "documents", "id450"]
    phone: str = Field(default="", max_length=32)
    client_name: str = Field(default="", max_length=70)
    comment: str = Field(default="", max_length=500)
    consent: bool
    files: list[IncomingFile] = Field(min_length=1, max_length=MAX_FILES)


def clean_name(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", name)
    return name.strip(" .")[:120]


def reject(status: int, msg: str):
    raise HTTPException(status_code=status, detail=msg)


def require_agent(auth: str | None):
    if not auth or not hmac.compare_digest(auth, "Bearer " + AGENT_TOKEN):
        reject(401, "Требуется авторизация рабочего компьютера")


def require_order(order_id: str, auth: str | None, c: sqlite3.Connection):
    row = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not row or not auth or not auth.startswith("Bearer "):
        reject(404, "Заявка не найдена")
    token = auth[7:]
    if not hmac.compare_digest(row["token_sha256"], hashlib.sha256(token.encode()).hexdigest()):
        reject(404, "Заявка не найдена")
    return row


def sniff(path: Path, ext: str) -> bool:
    with path.open("rb") as stream:
        header = stream.read(32)
    if ext in (".jpg", ".jpeg"):
        return header.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".webp":
        return header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if ext in (".heic", ".heif"):
        return header[4:8] == b"ftyp" and header[8:12] in (
            b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"
        )
    if ext == ".pdf":
        return header.startswith(b"%PDF-")
    if ext in (".docx", ".xlsx"):
        if not zipfile.is_zipfile(path):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > 1200 or sum(i.file_size for i in members) > 150 * 1024 * 1024:
                    return False
                names = set(archive.namelist())
                needed = "word/document.xml" if ext == ".docx" else "xl/workbook.xml"
                return "[Content_Types].xml" in names and needed in names
        except (zipfile.BadZipFile, OSError):
            return False
    return False


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "fotomag-direct-upload"}


@app.post("/api/orders", status_code=201)
def create_order(payload: IncomingOrder, request: Request):
    if UPLOAD_MODE == 'disabled':
        reject(503, 'Приём файлов пока не включён')
    if UPLOAD_MODE == 'staging' and (not request.client or request.client.host not in ('127.0.0.1', '::1', 'testclient')):
        reject(503, 'Тестовый приёмник не доступен из интернета')
    if UPLOAD_MODE == 'production' and not os.environ.get('FOTOMAG_CLAMD_HOST'):
        reject(503, 'Невозможно принимать файлы без антивируса')
    if request.headers.get("origin") != SITE_ORIGIN:
        reject(403, "Недопустимый источник запроса")
    if not payload.consent:
        reject(422, "Требуется согласие на обработку данных")
    phone = payload.phone.strip()
    if phone and (not re.fullmatch(r"\+?[0-9()\-\s]{7,25}", phone)
                  or len(re.sub(r"\D", "", phone)) < 10):
        reject(422, "Введите корректный номер телефона")
    if sum(f.size for f in payload.files) > MAX_TOTAL:
        reject(413, "Суммарный размер файлов превышает 100 МБ")
    file_specs = []
    for f in payload.files:
        name = clean_name(f.name)
        ext = Path(name).suffix.lower()
        if not name or ext not in EXTS:
            reject(415, "Поддерживаются JPG, PNG, WEBP, HEIC, PDF, DOCX и XLSX")
        file_specs.append((uuid.uuid4().hex, name, ext, f.size))
    remote_ip = request.client.host if request.client else "unknown"
    ip_hash = hmac.new(AGENT_TOKEN.encode(), remote_ip.encode(), hashlib.sha256).hexdigest()
    now = int(time.time())
    order_id = uuid.uuid4().hex
    receipt = "FM-W-" + datetime.fromtimestamp(now, SHOP_TZ).strftime("%Y%m%d") + "-" + order_id[:7].upper()
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        hourly = c.execute(
            "SELECT COUNT(*) FROM orders WHERE ip_hash=? AND created_ts>?",
            (ip_hash, now - 3600),
        ).fetchone()[0]
        if hourly >= MAX_HOURLY:
            reject(429, "Превышен лимит заявок. Позвоните в FotoMag")
        c.execute(
            "INSERT INTO orders"
            "(id,receipt,token_sha256,kind,phone,client_name,comment,ip_hash,"
            "status,created_ts,received_ts) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
            (order_id, receipt, hashlib.sha256(token.encode()).hexdigest(),
             payload.kind, phone, payload.client_name.strip(),
             payload.comment.strip(), ip_hash, "uploading", now),
        )
        for fid, name, ext, size in file_specs:
            c.execute(
                "INSERT INTO files(id,order_id,original_name,extension,expected_size)"
                " VALUES(?,?,?,?,?)", (fid, order_id, name, ext, size),
            )
    return {
        "order_id": order_id, "receipt": receipt, "upload_token": token,
        "files": [{"file_id": f[0]} for f in file_specs],
    }


@app.put("/api/orders/{order_id}/files/{file_id}")
async def upload_file(order_id: str, file_id: str, request: Request,
                      authorization: str | None = Header(default=None)):
    if request.headers.get("origin") != SITE_ORIGIN:
        reject(403, "Недопустимый источник запроса")
    with db() as c:
        order = require_order(order_id, authorization, c)
        if order["status"] != "uploading":
            reject(409, "Отправка заявки уже завершена")
        info = c.execute(
            "SELECT * FROM files WHERE id=? AND order_id=?", (file_id, order_id)
        ).fetchone()
        if not info:
            reject(404, "Файл не зарегистрирован")
        if info["uploaded_size"] is not None:
            return {"ok": True, "sha256": info["sha256"]}
        expected, ext = info["expected_size"], info["extension"]
    folder = UPLOADS / order_id
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / (file_id + "." + uuid.uuid4().hex + ".part")
    final = folder / (file_id + ext)
    count = 0
    digest = hashlib.sha256()
    try:
        with temp.open("xb") as stream:
            async for chunk in request.stream():
                count += len(chunk)
                if count > expected or count > MAX_FILE:
                    reject(413, "Размер файла превышает заявленный")
                digest.update(chunk)
                stream.write(chunk)
        if count != expected:
            reject(422, "Файл загружен не полностью")
        if not sniff(temp, ext):
            reject(415, "Тип файла не соответствует его содержимому")
        # A separate malware scanner is required before employee opens the files.
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            cursor = c.execute(
                "UPDATE files SET uploaded_size=?,sha256=?,stored_path=? "
                "WHERE id=? AND uploaded_size IS NULL",
                (count, digest.hexdigest(), str(final.relative_to(DATA)), file_id),
            )
            if cursor.rowcount != 1:
                reject(409, "Файл уже загружен в другом запросе")
            temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)
    return {"ok": True, "sha256": digest.hexdigest()}


@app.post("/api/orders/{order_id}/submit")
def submit_order(order_id: str, authorization: str | None = Header(default=None)):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        order = require_order(order_id, authorization, c)
        if order["status"] not in ("uploading", "pending"):
            reject(409, "Заказ уже передан сотруднику")
        missing = c.execute(
            "SELECT COUNT(*) FROM files WHERE order_id=? AND uploaded_size IS NULL", (order_id,)
        ).fetchone()[0]
        if missing:
            reject(409, "Не все файлы загружены")
        c.execute("UPDATE orders SET status='pending' WHERE id=?", (order_id,))
    return {"received": True, "receipt": order["receipt"], "status": "queued"}


@app.get("/api/orders/{order_id}/status")
def order_status(order_id: str, authorization: str | None = Header(default=None)):
    """Client may check only its own receipt; no names/phones are disclosed."""
    with db() as c:
        row = require_order(order_id, authorization, c)
        return {
            "receipt": row["receipt"],
            "status": row["status"],
            "downloaded_to_pc": row["status"] == "received",
        }


@app.get("/api/agent/orders")
def agent_orders(authorization: str | None = Header(default=None)):
    require_agent(authorization)
    result = []
    with db() as c:
        orders = c.execute(
            "SELECT * FROM orders WHERE status='pending' ORDER BY created_ts LIMIT 25"
        ).fetchall()
        for o in orders:
            files = c.execute(
                "SELECT id,original_name,uploaded_size,sha256 FROM files WHERE order_id=?",
                (o["id"],),
            ).fetchall()
            result.append({
                "order_id": o["id"], "receipt": o["receipt"], "kind": o["kind"],
                "phone": o["phone"], "client_name": o["client_name"],
                "comment": o["comment"], "created_ts": o["created_ts"],
                "files": [{"file_id": f["id"], "name": f["original_name"],
                           "size": f["uploaded_size"], "sha256": f["sha256"]}
                          for f in files],
            })
    return {"orders": result}


@app.get("/api/agent/files/{file_id}")
def agent_file(file_id: str, authorization: str | None = Header(default=None)):
    require_agent(authorization)
    with db() as c:
        f = c.execute(
            "SELECT * FROM files WHERE id=? AND uploaded_size IS NOT NULL", (file_id,)
        ).fetchone()
        if not f:
            reject(404, "Файл не найден")
        order = c.execute("SELECT status FROM orders WHERE id=?", (f["order_id"],)).fetchone()
        if not order or order["status"] not in ("pending", "received"):
            reject(404, "Файл ещё не готов")
        full = (DATA / f["stored_path"]).resolve()
        if not full.is_relative_to(UPLOADS) or not full.is_file():
            reject(404, "Файл отсутствует на сервере")
        filename = f["original_name"]
    return FileResponse(full, media_type="application/octet-stream", filename=filename)


@app.post("/api/agent/orders/{order_id}/ack")
def agent_ack(order_id: str, authorization: str | None = Header(default=None)):
    require_agent(authorization)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        status = c.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        if not status or status["status"] not in ("pending", "received"):
            reject(404, "Заявка не готова к подтверждению")
        c.execute(
            "UPDATE orders SET status='received',received_ts=COALESCE(received_ts,?) "
            "WHERE id=?", (int(time.time()), order_id),
        )
    return {"ok": True}
