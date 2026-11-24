"""Fail-closed ClamAV scan for untrusted file uploads.

Use ONLY a private clamd endpoint; never expose TCP 3310 on the public network.
"""
from __future__ import annotations

import os
import socket
import struct
from pathlib import Path


class ScannerUnavailable(Exception):
    pass


class ThreatDetected(Exception):
    pass


def read_reply(conn) -> bytes:
    data = bytearray()
    while len(data) < 4096:
        block = conn.recv(min(1024, 4096 - len(data)))
        if not block:
            break
        data.extend(block)
        if b"\x00" in block:
            if data.count(0) == 1 and data[-1] == 0:
                return bytes(data[:-1])
            break
    raise ScannerUnavailable("Incomplete or invalid ClamAV reply")


def scan_file(path: Path) -> None:
    host = os.environ.get("FOTOMAG_CLAMD_HOST", "")
    if not host:
        raise ScannerUnavailable("ClamAV scanner is not configured")
    try:
        port = int(os.environ.get("FOTOMAG_CLAMD_PORT", "3310"))
        with socket.create_connection((host, port), timeout=25) as conn:
            conn.settimeout(90)
            conn.sendall(b"zINSTREAM\x00")
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(262144), b""):
                    conn.sendall(struct.pack("!I", len(chunk)))
                    conn.sendall(chunk)
            conn.sendall(b"\x00\x00\x00\x00")
            verdict = read_reply(conn)
        if verdict.startswith(b"stream: ") and verdict.endswith(b" FOUND"):
            raise ThreatDetected("Potentially malicious file")
        if verdict != b"stream: OK":
            raise ScannerUnavailable("ClamAV did not return an OK verdict")
    except (OSError, TimeoutError, ValueError) as e:
        raise ScannerUnavailable("ClamAV service is unavailable") from e



def scanner_ready(timeout: float = 1.5) -> bool:
    """Small live probe used only when a customer opens the upload screen."""
    host = os.environ.get("FOTOMAG_CLAMD_HOST", "")
    if not host:
        return False
    try:
        port = int(os.environ.get("FOTOMAG_CLAMD_PORT", "3310"))
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall(b"zPING\x00")
            response = read_reply(conn)
        return response == b"PONG"
    except (OSError, TimeoutError, ValueError, ScannerUnavailable):
        return False
