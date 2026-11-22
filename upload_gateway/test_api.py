"""Offline integration tests for FotoMag's new private upload queue."""
import hashlib
import os
import tempfile

import pytest

os.environ["FOTOMAG_DATA_DIR"] = tempfile.mkdtemp(prefix="fotomag-api-test-")
os.environ["FOTOMAG_AGENT_TOKEN"] = "test" + ("Z" * 64)
os.environ["FOTOMAG_SITE_ORIGIN"] = "https://screamble123h.github.io"
os.environ["FOTOMAG_UPLOAD_MODE"] = "staging"

from fastapi.testclient import TestClient  # noqa: E402
from upload_gateway.api import app  # noqa: E402
import upload_gateway.api as gateway_api  # noqa: E402

client = TestClient(app)
ORIGIN = {"Origin": "https://screamble123h.github.io"}
ADMIN = {"Authorization": "Bearer " + os.environ["FOTOMAG_AGENT_TOKEN"]}
JPEG = b"\xff\xd8\xff\xe0" + b"FotoMag test jpeg" + b"\xff\xd9"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"


@pytest.fixture(autouse=True)
def approved_test_consent_and_scanner(monkeypatch):
    monkeypatch.setattr(gateway_api, "CONSENT_VERSION", "2026-11-22")
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: True)


def new_order(files=None):
    if files is None:
        files = [{"name": "photo.jpg", "size": len(JPEG)}]
    payload = {
        "kind": "photos", "phone": "+7 (900) 123-45-67",
        "client_name": "Алексей", "comment": "10x15 x2",
        "consent": True, "consent_version": gateway_api.CONSENT_VERSION, "files": files,
    }
    headers = dict(ORIGIN)
    if gateway_api.UPLOAD_MODE == "production":
        headers["X-FotoMag-Client-IP"] = "198.51.100.91"
    return client.post("/api/orders", json=payload, headers=headers)


def test_health_and_protection():
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert response.json()["accepting_uploads"] is False
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/agent/orders").status_code == 401
    assert client.post("/api/orders", json={
        "kind": "photos", "phone": "+79001234567",
        "consent": True, "consent_version": gateway_api.CONSENT_VERSION, "files": [{"name": "a.jpg", "size": 10}],
    }, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/orders", json={
        "kind": "photos", "phone": "+79001234567",
        "consent": False, "consent_version": gateway_api.CONSENT_VERSION, "files": [{"name": "a.jpg", "size": 10}],
    }, headers=ORIGIN).status_code == 422
    assert new_order([{"name": "malware.exe", "size": 10}]).status_code == 415


def test_full_order_delivered_to_agent_with_checksum():
    created_response = new_order([
        {"name": "portrait.jpg", "size": len(JPEG)},
        {"name": "printing.pdf", "size": len(PDF)},
    ])
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    order_id, token = created["order_id"], created["upload_token"]
    status_url = f"/api/orders/{order_id}/status"
    assert client.get(status_url).status_code == 404
    status = client.get(status_url, headers={"Authorization": "Bearer " + token})
    assert status.status_code == 200 and status.json()["downloaded_to_pc"] is False
    headers = dict(ORIGIN, Authorization="Bearer " + token,
                   **{"Content-Type": "application/octet-stream"})
    assert client.post(f"/api/orders/{order_id}/submit",
                       headers={"Authorization": "Bearer " + token}).status_code == 409
    for index, sample in enumerate((JPEG, PDF)):
        file_id = created["files"][index]["file_id"]
        url = f"/api/orders/{order_id}/files/{file_id}"
        uploaded = client.put(url, content=sample, headers=headers)
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["sha256"] == hashlib.sha256(sample).hexdigest()
    submitted = client.post(f"/api/orders/{order_id}/submit",
                            headers={"Authorization": "Bearer " + token})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["receipt"] == created["receipt"]
    pending = client.get(status_url, headers={"Authorization": "Bearer " + token})
    assert pending.json()["status"] == "pending" and not pending.json()["downloaded_to_pc"]
    queue = client.get("/api/agent/orders", headers=ADMIN).json()["orders"]
    order = next(o for o in queue if o["order_id"] == order_id)
    assert order["phone"] == "+7 (900) 123-45-67"
    assert order["client_name"] == "Алексей"
    for index, sample in enumerate((JPEG, PDF)):
        file_id = order["files"][index]["file_id"]
        assert order["files"][index]["sha256"] == hashlib.sha256(sample).hexdigest()
        downloaded = client.get("/api/agent/files/" + file_id, headers=ADMIN)
        assert downloaded.status_code == 200 and downloaded.content == sample
    assert client.post("/api/agent/orders/" + order_id + "/ack").status_code == 401
    assert client.post("/api/agent/orders/" + order_id + "/ack",
                       headers=ADMIN).json() == {"ok": True}
    delivered = client.get(status_url, headers={"Authorization": "Bearer " + token})
    assert delivered.json()["status"] == "received"
    assert delivered.json()["downloaded_to_pc"] is True
    repeated = client.post(f"/api/orders/{order_id}/submit",
                           headers={"Authorization": "Bearer " + token})
    assert repeated.status_code == 200 and repeated.json()["status"] == "received"
    queue_after = client.get("/api/agent/orders", headers=ADMIN).json()["orders"]
    assert not any(o["order_id"] == order_id for o in queue_after)


def test_reject_different_magic_and_incomplete_bytes():
    created = new_order().json()
    fid = created["files"][0]["file_id"]
    url = f"/api/orders/{created['order_id']}/files/{fid}"
    headers = dict(ORIGIN, Authorization="Bearer " + created["upload_token"],
                   **{"Content-Type": "application/octet-stream"})
    assert client.put(url, content=b"X" * len(JPEG), headers=headers).status_code == 415
    assert client.put(url, content=b"X", headers=headers).status_code == 422
    assert client.put(url, content=JPEG, headers=headers).status_code == 200
    assert client.put(url, content=JPEG, headers=headers).status_code == 200


def test_walk_in_without_phone_or_name_can_submit():
    """Counter customers may upload with a receipt only, without extra typing."""
    response = client.post("/api/orders", json={
        "kind": "documents", "consent": True, "consent_version": gateway_api.CONSENT_VERSION, "files": [
            {"name": "scan.pdf", "size": len(PDF)}
        ],
    }, headers=ORIGIN)
    assert response.status_code == 201, response.text
    data = response.json()
    queue_id, token = data["order_id"], data["upload_token"]
    upload = client.put(
        f"/api/orders/{queue_id}/files/{data['files'][0]['file_id']}",
        content=PDF, headers={**ORIGIN, "Authorization": "Bearer " + token},
    )
    assert upload.status_code == 200
    sent = client.post(
        f"/api/orders/{queue_id}/submit",
        headers={"Authorization": "Bearer " + token}
    )
    assert sent.status_code == 200
    queued = client.get("/api/agent/orders", headers=ADMIN).json()["orders"]
    item = next(o for o in queued if o["order_id"] == queue_id)
    assert item["client_name"] == "" and item["phone"] == ""


def test_upload_rejects_invalid_ownership_and_cross_origin():
    created = new_order().json()
    fid = created["files"][0]["file_id"]
    url = f"/api/orders/{created['order_id']}/files/{fid}"
    assert client.put(url, content=JPEG, headers={
        **ORIGIN, "Authorization": "Bearer wrong",
    }).status_code == 404
    assert client.put(url, content=JPEG, headers={
        "Origin": "https://attack.test",
        "Authorization": "Bearer " + created["upload_token"],
    }).status_code == 403


def test_disabled_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "disabled")
    response = new_order()
    assert response.status_code == 503
    assert client.get("/api/health").status_code == 200


def test_production_antivirus_clears_before_queue(monkeypatch):
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-av.invalid")
    calls = []
    monkeypatch.setattr(gateway_api, "scan_file", lambda path: calls.append(path))
    created = new_order().json()
    headers = {**ORIGIN, "Authorization": "Bearer " + created["upload_token"]}
    file_id = created["files"][0]["file_id"]
    uploaded = client.put(
        f"/api/orders/{created['order_id']}/files/{file_id}",
        content=JPEG, headers=headers,
    )
    assert uploaded.status_code == 200
    sent = client.post(f"/api/orders/{created['order_id']}/submit", headers=headers)
    assert sent.status_code == 200, sent.text
    assert len(calls) == 1


def test_production_antivirus_unavailable_keeps_order_hidden(monkeypatch):
    from upload_gateway.antivirus import ScannerUnavailable
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-av.invalid")
    def broken(_):
        raise ScannerUnavailable("scanner offline")
    monkeypatch.setattr(gateway_api, "scan_file", broken)
    created = new_order().json()
    headers = {**ORIGIN, "Authorization": "Bearer " + created["upload_token"]}
    assert client.put(
        f"/api/orders/{created['order_id']}/files/{created['files'][0]['file_id']}",
        content=JPEG, headers=headers,
    ).status_code == 200
    response = client.post(f"/api/orders/{created['order_id']}/submit",
                           headers=headers)
    assert response.status_code == 503
    status = client.get(f"/api/orders/{created['order_id']}/status",
                        headers=headers).json()
    assert status["status"] == "uploading"


def test_production_requires_trusted_proxy_header(monkeypatch):
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "internal-av.test")
    response = client.post("/api/orders", json={
        "kind": "photos", "consent": True, "consent_version": gateway_api.CONSENT_VERSION,
        "files": [{"name": "scan.jpg", "size": len(JPEG)}],
    }, headers=ORIGIN)
    assert response.status_code == 503
    assert "прокси" in response.json()["detail"]


def test_low_disk_space_is_rejected_before_order_creation(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(gateway_api.shutil, "disk_usage",
                        lambda path: SimpleNamespace(free=100))
    assert new_order().status_code == 507


def test_daily_byte_budget_fails_closed(monkeypatch):
    monkeypatch.setattr(gateway_api, "DAILY_BYTE_BUDGET", 1)
    response = new_order()
    assert response.status_code == 429
    assert "квота" in response.json()["detail"]


def test_health_gates_customer_form_on_live_av(monkeypatch):
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: False)
    assert client.get("/api/health").json()["accepting_uploads"] is False
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: True)
    assert client.get("/api/health").json()["accepting_uploads"] is True


def test_kill_switch_blocks_preexisting_file_tokens(monkeypatch):
    created = new_order().json()
    file_id = created["files"][0]["file_id"]
    headers = {**ORIGIN, "Authorization": "Bearer " + created["upload_token"]}
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "disabled")
    put = client.put(f"/api/orders/{created['order_id']}/files/{file_id}",
                     content=JPEG, headers=headers)
    assert put.status_code == 503
    submitted = client.post(f"/api/orders/{created['order_id']}/submit",
                            headers=headers)
    assert submitted.status_code == 503



def test_private_overview_exposes_counts_not_people():
    assert client.get("/api/agent/overview").status_code == 401
    response = client.get("/api/agent/overview", headers=ADMIN)
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "mode", "status_counts", "pending_count", "pending_over_15m",
        "oldest_pending_minutes", "storage_free_gib", "storage_low",
    }
    assert isinstance(data["pending_count"], int)
    assert data["pending_count"] >= 0
    assert data["pending_over_15m"] <= data["pending_count"]
    payload = response.text.lower()
    assert "client_name" not in payload and "phone" not in payload
    assert "агент" not in payload and "+7 " not in payload


def test_health_disables_upload_when_storage_low(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: True)
    monkeypatch.setattr(gateway_api.shutil, "disk_usage",
                        lambda _: SimpleNamespace(free=1))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["accepting_uploads"] is False


def test_production_rejects_draft_consent_and_offline_scanner(monkeypatch):
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "scanner.test")
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: False)
    assert new_order().status_code == 503
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: True)
    monkeypatch.setattr(gateway_api, "CONSENT_VERSION", "2026-11-22-draft")
    assert client.get("/api/health").json()["accepting_uploads"] is False
    assert new_order().status_code == 503


def test_consent_is_explicit_versioned_and_recorded():
    payload = {"kind": "photos", "consent": True, "consent_version": "old",
               "files": [{"name": "photo.jpg", "size": len(JPEG)}]}
    assert client.post("/api/orders", json=payload, headers=ORIGIN).status_code == 409
    payload.update(consent="true", consent_version=gateway_api.CONSENT_VERSION)
    assert client.post("/api/orders", json=payload, headers=ORIGIN).status_code == 422
    order = new_order().json()
    with gateway_api.db() as connection:
        row = connection.execute("SELECT * FROM orders WHERE id=?",
                                 (order["order_id"],)).fetchone()
    assert row["consent_version"] == gateway_api.CONSENT_VERSION
    assert row["consent_ts"] == row["created_ts"]


def test_proxy_cannot_publish_local_staging():
    response = client.post("/api/orders", headers={**ORIGIN, "X-FotoMag-Client-IP": "198.51.100.91"})
    assert response.status_code == 503


def test_scanner_stopped_between_order_and_upload(monkeypatch):
    monkeypatch.setattr(gateway_api, "UPLOAD_MODE", "production")
    monkeypatch.setenv("FOTOMAG_CLAMD_HOST", "scanner.test")
    created = new_order().json()
    monkeypatch.setattr(gateway_api, "scanner_ready", lambda: False)
    file_id = created["files"][0]["file_id"]
    response = client.put(
        f"/api/orders/{created['order_id']}/files/{file_id}", content=JPEG,
        headers={**ORIGIN, "Authorization": "Bearer " + created["upload_token"]},
    )
    assert response.status_code == 503
    assert not (gateway_api.UPLOADS / created["order_id"]).exists()
    with gateway_api.db() as connection:
        row = connection.execute("SELECT uploaded_size FROM files WHERE id=?", (file_id,)).fetchone()
    assert row["uploaded_size"] is None
