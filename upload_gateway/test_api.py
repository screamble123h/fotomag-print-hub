"""Offline integration tests for FotoMag's new private upload queue."""
import hashlib
import os
import tempfile

os.environ["FOTOMAG_DATA_DIR"] = tempfile.mkdtemp(prefix="fotomag-api-test-")
os.environ["FOTOMAG_AGENT_TOKEN"] = "test" + ("Z" * 64)
os.environ["FOTOMAG_SITE_ORIGIN"] = "https://screamble123h.github.io"

from fastapi.testclient import TestClient  # noqa: E402
from upload_gateway.api import app  # noqa: E402

client = TestClient(app)
ORIGIN = {"Origin": "https://screamble123h.github.io"}
ADMIN = {"Authorization": "Bearer " + os.environ["FOTOMAG_AGENT_TOKEN"]}
JPEG = b"\xff\xd8\xff\xe0" + b"FotoMag test jpeg" + b"\xff\xd9"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"


def new_order(files=None):
    if files is None:
        files = [{"name": "photo.jpg", "size": len(JPEG)}]
    payload = {
        "kind": "photos", "phone": "+7 (900) 123-45-67", "comment": "10x15 x2",
        "consent": True, "files": files,
    }
    return client.post("/api/orders", json=payload, headers=ORIGIN)


def test_health_and_protection():
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/agent/orders").status_code == 401
    assert client.post("/api/orders", json={
        "kind": "photos", "phone": "+79001234567",
        "consent": True, "files": [{"name": "a.jpg", "size": 10}],
    }, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/orders", json={
        "kind": "photos", "phone": "+79001234567",
        "consent": False, "files": [{"name": "a.jpg", "size": 10}],
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
    queue = client.get("/api/agent/orders", headers=ADMIN).json()["orders"]
    order = next(o for o in queue if o["order_id"] == order_id)
    assert order["phone"] == "+7 (900) 123-45-67"
    for index, sample in enumerate((JPEG, PDF)):
        file_id = order["files"][index]["file_id"]
        assert order["files"][index]["sha256"] == hashlib.sha256(sample).hexdigest()
        downloaded = client.get("/api/agent/files/" + file_id, headers=ADMIN)
        assert downloaded.status_code == 200 and downloaded.content == sample
    assert client.post("/api/agent/orders/" + order_id + "/ack").status_code == 401
    assert client.post("/api/agent/orders/" + order_id + "/ack",
                       headers=ADMIN).json() == {"ok": True}
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
