"""Synthetic offline tests of ClamAV INSTREAM protocol. No real malware or network."""
import os
import struct
from pathlib import Path

import pytest
from upload_gateway import antivirus


class FakeSocket:
    def __init__(self, verdict=b"stream: OK\x00"):
        self.sent = bytearray()
        self.verdict = verdict
    def settimeout(self, value):
        pass
    def sendall(self, block):
        self.sent.extend(block)
    def recv(self, limit):
        response, self.verdict = self.verdict, b""
        return response
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def test_clamav_clean_file_is_streamed_not_exposed(monkeypatch, tmp_path):
    fake = FakeSocket()
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-scanner.test")
    monkeypatch.setattr(antivirus.socket, "create_connection",
                        lambda address, timeout: fake)
    content = b"SYNTHETIC TEST FILE ONLY"
    file = tmp_path / "sample.txt"
    file.write_bytes(content)
    antivirus.scan_file(file)
    sent = bytes(fake.sent)
    assert sent.startswith(b"zINSTREAM\x00")
    offset = len(b"zINSTREAM\x00")
    assert sent[offset:offset + 4] == struct.pack("!I", len(content))
    assert sent[offset + 4:offset + 4 + len(content)] == content
    assert sent.endswith(b"\x00\x00\x00\x00")


def test_clamav_detects_threat_and_denies(monkeypatch, tmp_path):
    fake = FakeSocket(b"stream: TEST SIGNATURE FOUND\x00")
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-scanner.test")
    monkeypatch.setattr(antivirus.socket, "create_connection",
                        lambda address, timeout: fake)
    p = tmp_path / "no-real-malware.txt"
    p.write_bytes(b"harmless test")
    with pytest.raises(antivirus.ThreatDetected):
        antivirus.scan_file(p)


def test_clamav_unexpected_verdict_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-scanner.test")
    monkeypatch.setattr(antivirus.socket, "create_connection",
                        lambda address, timeout: FakeSocket(b"stream: ERROR\x00"))
    p = tmp_path / "sample.txt"
    p.write_bytes(b"harmless test")
    with pytest.raises(antivirus.ScannerUnavailable):
        antivirus.scan_file(p)


def test_clamav_health_responds_only_to_pong(monkeypatch):
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-scanner.test")
    fake = FakeSocket(b"PONG\x00")
    monkeypatch.setattr(antivirus.socket, "create_connection",
                        lambda address, timeout: fake)
    assert antivirus.scanner_ready() is True
    assert bytes(fake.sent) == b"zPING\x00"
    monkeypatch.setattr(antivirus.socket, "create_connection",
                        lambda address, timeout: FakeSocket(b"ERROR\x00"))
    assert antivirus.scanner_ready() is False


def test_clamav_without_endpoint_not_ready(monkeypatch):
    monkeypatch.delenv("FOTOMAG_CLAMD_HOST", raising=False)
    assert antivirus.scanner_ready() is False
    with pytest.raises(antivirus.ScannerUnavailable):
        antivirus.scan_file(Path("nonexistent"))


def test_only_complete_exact_clean_verdict_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "scanner.test")
    sample = tmp_path / "sample.txt"
    sample.write_bytes(b"test")
    for reply in (b"stream: NOT OK\x00", b"stream: OK", b"stream: OK\x00extra"):
        monkeypatch.setattr(antivirus.socket, "create_connection", lambda address, timeout: FakeSocket(reply))
        with pytest.raises(antivirus.ScannerUnavailable):
            antivirus.scan_file(sample)
    fake = FakeSocket()
    chunks = iter([b"P", b"ON", b"G\x00"])
    monkeypatch.setattr(fake, "recv", lambda limit: next(chunks))
    monkeypatch.setattr(antivirus.socket, "create_connection", lambda address, timeout: fake)
    assert antivirus.scanner_ready() is True
