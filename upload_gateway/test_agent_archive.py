r"""Offline tests for D:\2026\<date>\Напрямую\<client> delivery.

Only a temporary sandbox directory is used. No live server, Windows PC or customer
data is accessed. The real agent will refuse to start on non-Windows platforms.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path

import pytest
from upload_gateway import workstation_agent as agent


TEST_TIME = datetime(2026, 11, 21, 10, 7, tzinfo=timezone(timedelta(hours=4)))
RECEIPT = "FM-W-20261121-A1B2C3D"
FILE_DATA = b"\xff\xd8\xff\xe0FotoMag test picture\xff\xd9"


def sample_order(client_name="Алексей"):
    return {
        "order_id": "a" * 32,
        "receipt": RECEIPT,
        "created_ts": int(TEST_TIME.timestamp()),
        "kind": "photos",
        "client_name": client_name,
        "phone": "+7 900 000 00 00",
        "comment": "10 на 15, две штуки",
        "files": [{
            "file_id": "b" * 32,
            "name": "photo.jpg",
            "size": len(FILE_DATA),
            "sha256": hashlib.sha256(FILE_DATA).hexdigest(),
        }],
    }


def test_expected_channel_path_and_izhevsk_date(tmp_path):
    root = tmp_path / "2026"
    root.mkdir()
    path = agent.order_destination(sample_order(), root)
    assert path == root / "21.11.2026" / "Напрямую" / f"Клиент_Алексей_{RECEIPT}"
    assert not path.exists()  # Path selection alone must be read-only.


def test_monthly_archive_template_and_name_sanitization(tmp_path):
    root = tmp_path / "2026"
    root.mkdir()
    path = agent.order_destination(sample_order("Иван / Отправитель"), root,
                                   "%m.%Y/%d.%m.%Y")
    assert path == root / "11.2026" / "21.11.2026" / "Напрямую" / (
        f"Клиент_Отправитель_{RECEIPT}"
    )
    # User-provided content is never allowed to control directories.
    assert agent.safe_filename(r"C:\Users\test\CON.pdf") == "_CON.pdf"
    assert agent.safe_filename("../../client.jpg") == "client.jpg"
    with pytest.raises(ValueError):
        agent.order_destination(sample_order(), root, "../date")


def test_real_D_path_preview_without_writing():
    """Windows-specific read-only preview; never creates D: folders on CI."""
    import os
    if os.name != "nt":
        pytest.skip("D: path semantics are Windows-specific")
    path = agent.order_destination(sample_order(), Path(r"D:\2026"))
    assert str(path).startswith("D:\\2026\\21.11.2026\\Напрямую\\Клиент_")
    # Absolutely no mkdir(), no real order download and no test data on D:.


def test_bad_receipt_rejected_without_creating_folders(tmp_path):
    root = tmp_path / "2026"
    root.mkdir()
    order = sample_order()
    order["receipt"] = "FM-W-20261120-A1B2C3D"
    with pytest.raises(ValueError):
        agent.order_destination(order, root)
    assert list(root.iterdir()) == []


def test_files_and_metadata_saved_once_under_direct_channel(monkeypatch, tmp_path):
    root = tmp_path / "2026"
    root.mkdir()
    calls = []

    def fake_urlopen(request, timeout=None):
        assert "/api/agent/files/" in request.full_url
        return io.BytesIO(FILE_DATA)

    def fake_request(path, method="GET"):
        calls.append((path, method))
        return {"ok": True}

    monkeypatch.setattr(agent, "API_URL", "https://api.example.test")
    monkeypatch.setattr(agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(agent, "api_request", fake_request)
    order = sample_order()
    folder = agent.receive_order(order, root)
    assert folder == root / "21.11.2026" / "Напрямую" / (
        f"Клиент_Алексей_{RECEIPT}"
    )
    assert (folder / "01_photo.jpg").read_bytes() == FILE_DATA
    metadata = json.loads((folder / "order.json").read_text(encoding="utf-8"))
    assert metadata["channel"] == "Напрямую"
    assert metadata["client_name"] == "Алексей"
    assert metadata["phone"] == "+7 900 000 00 00"
    info = (folder / "ЗАКАЗ.txt").read_text(encoding="utf-8")
    assert "Канал: Напрямую" in info
    assert "21.11.2026 10:07" in info
    assert calls == [(f"/api/agent/orders/{order['order_id']}/ack", "POST")]
    agent.receive_order(order, root)
    assert (folder / "01_photo.jpg").read_bytes() == FILE_DATA
    assert len(list(folder.glob("*.jpg"))) == 1
    assert len(list(folder.glob("*.part"))) == 0
    assert len(calls) == 2  # Only ACK retried; no duplicated photos.


def test_collision_fails_without_overwrite_or_ack(monkeypatch, tmp_path):
    root = tmp_path / "2026"
    root.mkdir()
    order = sample_order()
    folder = agent.order_destination(order, root)
    folder.mkdir(parents=True)
    old = folder / "01_photo.jpg"
    old.write_bytes(b"KEEP OLD FILE")
    calls = []
    monkeypatch.setattr(agent, "api_request", lambda *a, **kw: calls.append(a))
    with pytest.raises(FileExistsError):
        agent.receive_order(order, root)
    assert old.read_bytes() == b"KEEP OLD FILE"
    assert not calls
    assert not (folder / "order.json").exists()


def test_interrupted_or_corrupted_file_rejected(monkeypatch, tmp_path):
    root = tmp_path / "2026"
    root.mkdir()
    monkeypatch.setattr(agent, "API_URL", "https://api.example.test")
    monkeypatch.setattr(agent.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(FILE_DATA[:-3]))
    order = sample_order()
    with pytest.raises(ValueError, match="integrity"):
        agent.receive_order(order, root)
    folder = agent.order_destination(order, root)
    assert not (folder / "01_photo.jpg").exists()
    assert not list(folder.glob("*.part"))
    assert not (folder / "order.json").exists()
