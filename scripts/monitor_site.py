#!/usr/bin/env python3
"""Read-only FotoMag availability check; Python standard library, no scheduler.

Checks the three public pages, optional allowlisted LAN health and the optional
existing receiver status file. It never creates orders, sends notifications,
starts services, executes shell commands, repairs the system or disables TLS.
HTML checks establish availability and important controls, not complete UI
correctness. A LAN result from the workstation is NOT evidence of external
internet reachability or proof that an individual customer's files arrived.

Normally one append-only JSONL record is written per Europe/Samara hour. --force
permits an additional manual check without replacing earlier log records.
latest.json is replaced atomically. No response bodies or receiver output are
written to logs. Optional receiver checks require an explicit success/exit
indicator; an unfamiliar status schema is reported instead of guessed.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import ntpath
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

PUBLIC_BASE = "https://screamble123h.github.io/fotomag-print-hub/"
LAN_HEALTH = "https://fotomag-izhevsk.dynv6.net:8443/api/health"
RECEIVER_STATUS = r"D:\FotoMag_Direct_Launch_20261125\receiver_last_status.json"
TIMEOUT_SECONDS = 10
MAX_HTML_BYTES = 128 * 1024
MAX_JSON_BYTES = 32 * 1024
MAX_DAILY_LOG_BYTES = 4 * 1024 * 1024
TZ_NAME = "Europe/Samara"
PAGES = (
    ("public_index", "", {"bot-primary-cta", "quick-id-photo", "quick-print-photo", "quick-documents", "direct-upload-primary", "screen-upload", "screen-wifi", "upload-submit", "upload-consent"}, "assets/app-shell.js"),
    ("public_souvenirs", "souvenirs.html", {"gift-request", "gift-copy", "gift-note", "gift-email"}, "assets/souvenirs.js"),
    ("public_mugs", "mugs.html", {"catalog", "forwardBtn", "backBtn", "photoDialog"}, "assets/mugs.js"),
)


class ConfigError(Exception):
    """A bounded, non-sensitive configuration or execution error."""


class CheckFailure(Exception):
    """An expected availability failure."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ConfigError("invalid_arguments; use --help")


def local_clock():
    try:
        from zoneinfo import ZoneInfo
        zone, source = ZoneInfo(TZ_NAME), "zoneinfo"
    except (ImportError, KeyError):
        zone, source = dt.timezone(dt.timedelta(hours=4), TZ_NAME), "fixed_UTC+04:00_fallback"
    return dt.datetime.now(zone), source


def parse_args(argv=None):
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log-dir", required=True, help="Separate absolute directory for daily JSONL and atomic latest.json")
    parser.add_argument("--lan", metavar="URL", help="Optional exact FotoMag LAN /api/health URL")
    parser.add_argument("--receiver-status", metavar="PATH", help="Optional exact existing receiver_last_status.json path")
    parser.add_argument("--receiver-max-age-minutes", type=int, default=10, help="Receiver status freshness threshold, 1..1440; default 10")
    parser.add_argument("--force", action="store_true", help="Manual extra run even if this hour is already logged; earlier records stay intact")
    args = parser.parse_args(argv)
    if not Path(args.log_dir).is_absolute():
        raise ConfigError("log_dir_must_be_absolute")
    if args.lan is not None and args.lan != LAN_HEALTH:
        raise ConfigError("lan_url_not_allowlisted")
    if args.receiver_status is not None and ntpath.normcase(ntpath.normpath(args.receiver_status)) != ntpath.normcase(RECEIVER_STATUS):
        raise ConfigError("receiver_status_path_not_allowlisted")
    if not 1 <= args.receiver_max_age_minutes <= 1440:
        raise ConfigError("receiver_max_age_out_of_range")
    return args


def approved_url(url, allowed):
    try:
        parsed = urlsplit(url)
        return (url in allowed and parsed.scheme == "https" and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


class RestrictedRedirect(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not approved_url(newurl, self.allowed):
            raise CheckFailure("redirect_not_allowlisted")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_url(url, limit, allowed, expected_type):
    if not approved_url(url, allowed):
        raise ConfigError("request_url_not_allowlisted")
    opener = build_opener(RestrictedRedirect(allowed), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, method="GET", headers={"User-Agent": "FotoMagSiteMonitor/1.0", "Accept": expected_type, "Cache-Control": "no-cache"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        if not approved_url(response.url, allowed):
            raise CheckFailure("final_url_not_allowlisted")
        if response.status != 200:
            raise CheckFailure("http_status_" + str(response.status))
        content_type = response.headers.get_content_type()
        if content_type != expected_type:
            raise CheckFailure("unexpected_content_type")
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > limit:
            raise CheckFailure("body_limit_exceeded")
        body = response.read(limit + 1)
        if len(body) > limit:
            raise CheckFailure("body_limit_exceeded")
        return body, response.status


class PageControls(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.scripts = set(), set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "script" and "src" in attrs:
            self.scripts.add(attrs["src"])


def failure_reason(error):
    if isinstance(error, (ConfigError, CheckFailure)):
        return str(error)[:160]
    if isinstance(error, HTTPError):
        return "http_error_" + str(error.code)
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
        return "tls_verification_or_handshake_failed"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "network_timeout"
    if isinstance(reason, socket.gaierror):
        return "dns_resolution_failed"
    if isinstance(error, (URLError, OSError)):
        return "network_or_file_unavailable"
    if isinstance(error, (UnicodeError, json.JSONDecodeError)):
        return "invalid_response_encoding_or_json"
    return "unexpected_" + type(error).__name__


def run_check(name, scope, action, url=None):
    started = time.monotonic()
    result = {"name": name, "scope": scope}
    if url:
        result["url"] = url
    try:
        result.update(action())
        result["status"] = "healthy"
    except ConfigError as error:
        result.update(status="error", reason=failure_reason(error))
    except (CheckFailure, HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError) as error:
        result.update(status="unhealthy", reason=failure_reason(error))
    except Exception as error:
        result.update(status="error", reason=failure_reason(error))
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


def check_page(suffix, expected_ids, script):
    url = PUBLIC_BASE + suffix
    allowed = {url}
    if not suffix:
        allowed.add(PUBLIC_BASE + "index.html")
    body, http_status = read_url(url, MAX_HTML_BYTES, allowed, "text/html")
    page = PageControls()
    page.feed(body.decode("utf-8"))
    if not expected_ids.issubset(page.ids):
        raise CheckFailure("critical_controls_missing:" + ",".join(sorted(expected_ids - page.ids)))
    if script not in page.scripts:
        raise CheckFailure("required_script_reference_missing")
    return {"http_status": http_status, "bytes": len(body), "reason": "critical_controls_present"}


def check_lan():
    body, http_status = read_url(LAN_HEALTH, MAX_JSON_BYTES, {LAN_HEALTH}, "application/json")
    payload = json.loads(body)
    if not isinstance(payload, dict) or type(payload.get("accepting_uploads")) is not bool:
        raise CheckFailure("unknown_health_response")
    if payload["accepting_uploads"] is not True:
        raise CheckFailure("receiver_not_accepting_uploads")
    return {"http_status": http_status, "bytes": len(body), "reason": "accepting_uploads;not_external_network_proof"}


def receiver_outcome(payload):
    # Existing Windows receiver wrapper: exit=0 and result empty/saved only.
    if not isinstance(payload, dict) or type(payload.get("exit")) is not int:
        raise ConfigError("unknown_receiver_status_schema")
    if payload["exit"] != 0:
        raise CheckFailure("receiver_last_exit_nonzero")
    result = payload.get("result")
    if result in ("error", "exception", "unexpected"):
        raise CheckFailure("receiver_result_failed")
    if result not in ("empty", "saved"):
        raise ConfigError("unknown_receiver_success_indicator")
    if result == "saved" and (type(payload.get("count")) is not int or payload["count"] < 0):
        raise ConfigError("invalid_receiver_saved_count")


def check_receiver(filename, max_age_minutes):
    path = Path(filename)
    metadata = path.stat()
    if metadata.st_size > MAX_JSON_BYTES:
        raise CheckFailure("receiver_status_body_limit_exceeded")
    with path.open("rb") as status_file:
        raw = status_file.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise CheckFailure("receiver_status_body_limit_exceeded")
    payload = json.loads(raw.decode("utf-8-sig"))
    receiver_outcome(payload)
    timestamp, age_source = metadata.st_mtime, "file_mtime"
    for key in ("checked_at", "completed_at", "finished_at", "timestamp", "utc"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                timestamp, age_source = min(timestamp, parsed.timestamp()), "oldest_of_mtime_and_record"
                break
        except ValueError:
            continue
    age = time.time() - timestamp
    if age < -300:
        raise CheckFailure("receiver_timestamp_in_future")
    if age > max_age_minutes * 60:
        raise CheckFailure("receiver_status_stale")
    return {"reason": "last_receiver_run_successful;not_order_delivery_proof", "age_seconds": max(0, round(age)), "age_source": age_source}


@contextlib.contextmanager
def log_lock(directory):
    """OS lock releases on exit/crash; no stale-lock deletion or repair needed."""
    with (directory / "monitor.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ConfigError("another_monitor_run_is_active") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def existing_hour(path, hour_key):
    if not path.exists():
        return None
    if path.stat().st_size > MAX_DAILY_LOG_BYTES:
        raise ConfigError("daily_log_size_limit_exceeded")
    last = None
    with path.open("rb") as log:
        while True:
            line = log.readline(8193)
            if not line:
                break
            if len(line) > 8192:
                raise ConfigError("daily_log_record_too_large")
            try:
                record = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ConfigError("daily_log_invalid_json;existing_records_preserved") from error
            if not isinstance(record, dict):
                raise ConfigError("daily_log_invalid_record")
            if record.get("hour_key") == hour_key:
                last = record
    return last


def compact_json(record):
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 4000:
        raise ConfigError("monitor_output_limit_exceeded")
    return encoded


def write_logs(directory, daily, encoded):
    with daily.open("a", encoding="utf-8", newline="\n") as log:
        log.write(encoded + "\n"); log.flush(); os.fsync(log.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=directory, prefix="latest-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded + "\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, directory / "latest.json")
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    try:
        args = parse_args(argv)
        now, clock_source = local_clock()
        hour_key = now.strftime("%Y-%m-%dT%H")
        directory = Path(args.log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        daily = directory / ("monitor-" + now.strftime("%Y-%m-%d") + ".jsonl")
        with log_lock(directory):
            previous = existing_hour(daily, hour_key)
            if previous and not args.force:
                code = previous.get("exit_code", 2)
                if type(code) is not int or code not in (0, 1, 2):
                    raise ConfigError("daily_log_invalid_exit_code")
                result = {"status": "skipped", "reason": "already_logged_for_hour", "hour_key": hour_key, "timezone": TZ_NAME,
                          "checked_at": now.isoformat(timespec="seconds"), "previous_status": previous.get("overall"), "exit_code": code}
                print(compact_json(result)); return code
            checks = []
            for name, suffix, ids, script in PAGES:
                checks.append(run_check(name, "public_site", lambda s=suffix, i=ids, j=script: check_page(s, i, j), PUBLIC_BASE + suffix))
            if args.lan:
                checks.append(run_check("lan_receiver_health", "LAN_from_workstation_not_external_proof", check_lan, LAN_HEALTH))
            if args.receiver_status:
                checks.append(run_check("receiver_last_run", "local_status_file", lambda: check_receiver(args.receiver_status, args.receiver_max_age_minutes)))
            code = 2 if any(c["status"] == "error" for c in checks) else 1 if any(c["status"] != "healthy" for c in checks) else 0
            result = {"schema": 1, "monitor": "FotoMag-site-and-receiver", "checked_at": now.isoformat(timespec="seconds"),
                      "timezone": TZ_NAME, "timezone_source": clock_source, "hour_key": hour_key, "forced": args.force,
                      "overall": {0: "healthy", 1: "unhealthy", 2: "error"}[code], "exit_code": code, "checks": checks}
            encoded = compact_json(result)
            write_logs(directory, daily, encoded)
            print(encoded); return code
    except (ConfigError, OSError) as error:
        print(compact_json({"overall": "error", "exit_code": 2, "reason": failure_reason(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
