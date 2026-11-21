"""Offline preflight tests for the permanent Windows receiver launcher.

Never starts an agent, opens a network connection or accesses a real D: folder.
"""
import pytest
from upload_gateway.agent_launcher import validate_settings


def sample():
    return {
        "api_url": "https://files.fotomag.ru",
        "agent_token": "R" * 64,
        "archive_root": r"D:\2026",
        "date_subpath": "%m/%d",
        "poll_seconds": 30,
    }


def test_accepts_owner_archive_and_dedicated_https_origin():
    cfg = validate_settings(sample())
    assert cfg["archive_root"] == r"D:\2026"
    assert cfg["date_subpath"] == "%m/%d"
    assert cfg["api_url"] == "https://files.fotomag.ru"
    assert len(cfg["agent_token"]) == 64


@pytest.mark.parametrize("bad", [
    "http://files.fotomag.ru",
    "https://localhost",
    "https://127.0.0.1",
    "https://random.trycloudflare.com",
    "https://screamble123h.github.io",
    "https://files.fotomag.ru/api/agent",
    "https://alice:pw@files.fotomag.ru",
    "https://files.fotomag.ru/?token=unsafe",
    "https://files.fotomag.ru:8000",
])
def test_rejects_insecure_or_test_server_urls(bad):
    conf = sample()
    conf["api_url"] = bad
    with pytest.raises(ValueError):
        validate_settings(conf)


@pytest.mark.parametrize("bad", [
    r"C:\2026",
    r"D:\2026\..\2027",
    r"D:\2026\existing_client",
    r"\\remote\share\2026",
    r"D:/2026",
])
def test_rejects_wrong_or_unsafe_archives(bad):
    conf = sample()
    conf["archive_root"] = bad
    with pytest.raises(ValueError):
        validate_settings(conf)


def test_rejects_weak_token_unknown_fields_and_unapproved_date_pattern():
    for change in (
        {"agent_token": "test"},
        {"agent_token": "REPLACE_WITH_SECRET"},
        {"date_subpath": "%d.%m.%Y"},
        {"poll_seconds": 0},
        {"unexpected": "field"},
    ):
        conf = sample()
        conf.update(change)
        with pytest.raises(ValueError):
            validate_settings(conf)
