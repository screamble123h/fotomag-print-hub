#!/usr/bin/env python3
"""Scoped FotoMag LAN static release. No service restart, order access or scheduler.

Run on DESKTOP-P6L7HTI only, after review:
  python scripts/lan_release.py --action prepare --commit <40-character SHA>
  python scripts/lan_release.py --action activate --commit <same SHA>
  python scripts/lan_release.py --action verify --commit <same SHA>
  python scripts/lan_release.py --action rollback --commit <same SHA>

prepare does not change live configuration. activate gracefully reloads Caddy;
its success is distinct from the HTTPS checks performed by verify. A failed
activation attempts restoration of the original configuration and a graceful
reload. No action removes releases, orders, files or existing backups.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

SOURCE = Path(r"D:\FotoMag_Site_Orders")
MOUNT = Path(r"D:\FotoMag_MVP_20261125\site_v1\site")
LIVE_CONFIG = Path(r"D:\FotoMag_Direct_Launch_20261125\Caddyfile")
CONTROL = Path(r"D:\FotoMag_Site_Orders_Control")
CONTAINER = "fotomag-direct-prod-edge-1"
HOST = "fotomag-izhevsk.dynv6.net"
PORT = 8443
ORIGIN = f"https://{HOST}:{PORT}"
ROOT_FILES = {"index.html", "privacy.html", "mugs.html", "souvenirs.html", "site.webmanifest"}
EXTENSIONS = {".html", ".webmanifest", ".css", ".js", ".json", ".svg", ".png", ".jpg",
              ".jpeg", ".webp", ".gif", ".avif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".txt"}
MAX_FILES, MAX_BYTES, MAX_VERIFY = 300, 100 * 1024 * 1024, 32 * 1024 * 1024
SAMARA = timezone(timedelta(hours=4), "Europe/Samara")
SECRET = re.compile(rb"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


class ReleaseError(Exception):
    """Messages are deliberately short and do not include command/config output."""


def now() -> str:
    return datetime.now(SAMARA).isoformat(timespec="seconds")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    checked_path(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked_path(path: Path) -> None:
    # realpath resolves Windows junctions as well as symlinks. Refuse redirection.
    if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.realpath(path)):
        raise ReleaseError("A guarded path resolves through a symlink or junction.")


def relative_name(name: str, *, old: bool = False) -> str:
    parts = PurePosixPath(name).parts
    if (not parts or name.startswith("/") or any(p in (".", "..") or p.startswith(".") for p in parts)
            or any(c in name for c in '\\:\x00*?[]{}"`') or any(ord(c) < 32 for c in name)
            or str(PurePosixPath(name)) != name):
        raise ReleaseError("Unsafe static relative path.")
    selected = name in ROOT_FILES or name.startswith("assets/")
    if old:
        selected = selected or (len(parts) == 1 and name.endswith(".html"))
    if not selected:
        raise ReleaseError("A file is outside the selected static scope.")
    if not old and Path(name).suffix.lower() not in EXTENSIONS:
        raise ReleaseError("An unexpected file type is present in tracked static assets.")
    if not old and any(re.search(r"(?:^|[._-])(?:secret|credential|token|private[-_]?key)(?:[._-]|$)", p, re.I) for p in parts):
        raise ReleaseError("A suspicious asset filename requires review.")
    return name


def bounded_json(path: Path) -> dict:
    checked_path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ReleaseError("Receipt exceeds the bounded metadata limit.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ReleaseError("Invalid receipt format.")
    return result


def atomic_write(path: Path, data: bytes) -> None:
    checked_path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + ".stage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        # Only our unused temporary file; never remove a release or user file.
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def run(command: list[str], label: str, timeout: int = 45) -> bytes:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise ReleaseError(f"{label}: command timed out; do not retry blindly.") from exc
    if len(result.stdout) > 256 * 1024:
        raise ReleaseError(f"{label}: command output exceeded the bounded limit.")
    if result.returncode:
        raise ReleaseError(f"{label}: exit {result.returncode}; output SHA-256 {digest(result.stdout)}.")
    return result.stdout


def git(*args: str) -> bytes:
    return run(["git", "-C", str(SOURCE), *args], "git")


def source_files(commit: str) -> list[str]:
    if os.path.normcase(git("rev-parse", "--show-toplevel").decode().strip().replace("/", "\\")) != os.path.normcase(str(SOURCE)):
        raise ReleaseError("Unexpected Git worktree root.")
    if git("rev-parse", "HEAD").decode().strip() != commit:
        raise ReleaseError("Source HEAD differs from the requested commit.")
    selectors = [*sorted(ROOT_FILES), "assets"]
    if git("status", "--porcelain=v1", "--untracked-files=no", "--", *selectors).strip():
        raise ReleaseError("Tracked static source files have uncommitted changes.")
    result = []
    for entry in git("ls-tree", "-r", "-z", "--full-tree", commit, "--", *selectors).split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, _ = header.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ReleaseError("Symlinks, submodules and nonregular static sources are forbidden.")
        result.append(relative_name(name.decode("utf-8")))
    if not ROOT_FILES.issubset(result) or not any(n.startswith("assets/") for n in result):
        raise ReleaseError("Required tracked static files are missing.")
    check_limits(SOURCE, result)
    return sorted(result)


def check_limits(root: Path, names: list[str]) -> None:
    if not names or len(names) > MAX_FILES or len(names) != len(set(names)):
        raise ReleaseError("Static file count is invalid or exceeds 300.")
    total = 0
    for name in names:
        path = root / name
        checked_path(path)
        if not path.is_file():
            raise ReleaseError("A selected static file is missing or not regular.")
        total += path.stat().st_size
        if total > MAX_BYTES:
            raise ReleaseError("Static bundle exceeds 100 MiB.")


def static_root(original: bytes) -> str:
    if len(original) > 64 * 1024:
        raise ReleaseError("Caddy configuration exceeds 64 KiB; manual review required.")
    roots = [line.strip() for line in original.decode("utf-8").splitlines()
             if re.match(r"[ \t]*root[ \t]+", line)]
    if len(roots) != 1:
        raise ReleaseError("Expected exactly one static root directive.")
    match = re.fullmatch(r"root \* (/srv/site(?:/releases/[0-9a-f]{40})?)[ \t]*", roots[0])
    if not match:
        raise ReleaseError("Static root must be the guarded mount or an immutable release.")
    return match.group(1)


def static_path(root: str) -> Path:
    if not isinstance(root, str) or not re.fullmatch(r"/srv/site(?:/releases/[0-9a-f]{40})?", root):
        raise ReleaseError("Unexpected previous static root.")
    path = MOUNT if root == "/srv/site" else MOUNT / "releases" / root.rsplit("/", 1)[1]
    checked_path(path)
    if not path.is_dir():
        raise ReleaseError("Previous static root is missing.")
    return path


def old_files(root: Path = MOUNT) -> list[str]:
    names = []
    for item in root.iterdir():
        if item.is_file() and (item.suffix.lower() == ".html" or item.name == "site.webmanifest"):
            names.append(relative_name(item.name, old=True))
    assets = root / "assets"
    if assets.exists():
        checked_path(assets)
        for directory, dirs, files in os.walk(assets, followlinks=False):
            for child in dirs:
                checked_path(Path(directory) / child)
            for child in files:
                name = (Path(directory) / child).relative_to(root).as_posix()
                names.append(relative_name(name, old=True))
                if len(names) > MAX_FILES:
                    raise ReleaseError("Old static backup exceeds 300 files.")
    check_limits(root, names)
    return sorted(names)


def copy_checked(source: Path, destination: Path) -> dict:
    checked_path(source)
    checked_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    h, size = hashlib.sha256(), 0
    with source.open("rb") as src, destination.open("xb") as dst:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            size += len(block)
            if size > MAX_BYTES:
                raise ReleaseError("A static file grew beyond the bundle limit.")
            h.update(block)
            dst.write(block)
    if h.hexdigest() != file_digest(source) or size != source.stat().st_size:
        raise ReleaseError("A source file changed while it was being copied.")
    return {"size": size, "sha256": h.hexdigest()}


def lan_index(data: bytes) -> bytes:
    meta = b'<meta content="" name="fotomag-upload-api"/>'
    csp = b"connect-src 'none'"
    if data.count(meta) != 1 or data.count(csp) != 1:
        raise ReleaseError("Public index does not contain the exact approved API/CSP placeholders.")
    return data.replace(meta, f'<meta content="{ORIGIN}" name="fotomag-upload-api"/>'.encode(), 1).replace(csp, b"connect-src 'self'", 1)


def candidate_config(original: bytes, names: list[str], commit: str) -> bytes:
    if len(original) > 64 * 1024:
        raise ReleaseError("Caddy configuration exceeds 64 KiB; manual review required.")
    previous_root = static_root(original)
    lines = original.decode("utf-8").splitlines(keepends=True)
    matcher_starts, roots = [], []
    for number, line in enumerate(lines):
        text = line.rstrip("\r\n")
        if re.fullmatch(r"[ \t]*@static[ \t]+\{[ \t]*", text):
            matcher_starts.append(number)
        if re.fullmatch(r"[ \t]*root \* " + re.escape(previous_root) + r"[ \t]*", text):
            roots.append(number)
    if len(matcher_starts) != 1 or len(roots) != 1:
        raise ReleaseError("Expected one @static matcher block and one guarded static root line.")
    static, methods, closed = [], [], False
    for number in range(matcher_starts[0] + 1, len(lines)):
        text = lines[number].rstrip("\r\n")
        if re.fullmatch(r"[ \t]*\}[ \t]*", text):
            closed = True
            break
        if "{" in text or "}" in text:
            raise ReleaseError("Unexpected nested syntax in the static matcher; review required.")
        if re.fullmatch(r"[ \t]*path[ \t]+[^\r\n]+", text):
            static.append(number)
        if re.fullmatch(r"[ \t]*method[ \t]+GET[ \t]+HEAD[ \t]*", text):
            methods.append(number)
    if not closed or len(static) != 1 or len(methods) != 1:
        raise ReleaseError("Static matcher must contain exactly one path line and method GET HEAD.")
    paths = ["/", *("/" + relative_name(name) for name in names)]
    replacements = {
        static[0]: "path " + " ".join(json.dumps(p, ensure_ascii=False) for p in paths),
        roots[0]: f"root * /srv/site/releases/{commit}",
    }
    for number, text in replacements.items():
        line = lines[number]
        indent = re.match(r"[ \t]*", line).group()
        ending = line[len(line.rstrip("\r\n")):]
        lines[number] = indent + text + ending
    return "".join(lines).encode("utf-8")


def log(control: Path, event: str, **values) -> None:
    with (control / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": now(), "timezone": "Europe/Samara", "event": event, **values}, ensure_ascii=True) + "\n")


def caddy(commit: str, operation: str, filename: str) -> None:
    if operation not in ("validate", "reload") or filename not in ("candidate.Caddyfile", "rollback.Caddyfile"):
        raise ReleaseError("Unexpected Caddy operation.")
    run(["docker", "exec", CONTAINER, "caddy", operation, "--config",
         f"/srv/site/releases/{commit}/{filename}", "--adapter", "caddyfile"], f"Caddy {operation}")


def set_phase(control: Path, phase: str, **values) -> None:
    previous = bounded_json(control / "state.json") if (control / "state.json").exists() else {}
    write_json(control / "state.json", {**previous, "phase": phase, "updated": now(), **values})
    log(control, phase, **values)


def prepare(commit: str, control: Path, release: Path) -> dict:
    if control.exists() or release.exists():
        raise ReleaseError("This commit already has a release or control record; inspect it instead of preparing again.")
    control.mkdir()
    set_phase(control, "preparing", commit=commit)
    names = source_files(commit)
    original = LIVE_CONFIG.read_bytes()
    previous_root = static_root(original)
    previous_path = static_path(previous_root)
    candidate = candidate_config(original, names, commit)
    backup = control / "backup"
    backup.mkdir()
    (backup / "Caddyfile").write_bytes(original)
    old = {name: copy_checked(previous_path / name, backup / "site" / name) for name in old_files(previous_path)}
    release.parent.mkdir(exist_ok=True)
    checked_path(release.parent)
    stage = release.parent / (".prepare-" + commit + "-" + uuid4().hex[:8])
    stage.mkdir()
    files = {}
    for name in names:
        info = copy_checked(SOURCE / name, stage / name)
        info["source_sha256"] = info["sha256"]
        info["source_size"] = info["size"]
        if Path(name).suffix.lower() in {".html", ".js", ".json", ".css", ".txt", ".svg", ".webmanifest"}:
            content = (stage / name).read_bytes()
            if SECRET.search(content):
                raise ReleaseError("Potential secret detected in a static source; release stopped.")
            if name == "index.html":
                content = lan_index(content)
                (stage / name).write_bytes(content)
                info.update(size=len(content), sha256=digest(content))
        files[name] = info
    manifest = {"schema": 1, "commit": commit, "created": now(), "timezone": "Europe/Samara",
                "source": str(SOURCE), "mount": str(MOUNT), "live_config": str(LIVE_CONFIG),
                "original_config_sha256": digest(original), "candidate_config_sha256": digest(candidate),
                "files": files, "old_files": old, "old_static_root": previous_root}
    (stage / "candidate.Caddyfile").write_bytes(candidate)
    (stage / "rollback.Caddyfile").write_bytes(original)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (stage / "bundle-manifest.json").write_bytes(manifest_bytes)
    if source_files(commit) != names or file_digest(LIVE_CONFIG) != digest(original):
        raise ReleaseError("Source list or live configuration changed during preparation.")
    for name, info in files.items():
        if file_digest(SOURCE / name) != info["source_sha256"]:
            raise ReleaseError("Static source changed during preparation.")
    os.rename(stage, release)
    # The complete release becomes visible before validation, but no live matcher points at it.
    caddy(commit, "validate", "candidate.Caddyfile")
    caddy(commit, "validate", "rollback.Caddyfile")
    manifest["bundle_manifest_sha256"] = digest(manifest_bytes)
    write_json(control / "prepared.json", manifest)
    set_phase(control, "prepared", source_head=commit, files=len(files), bytes=sum(f["size"] for f in files.values()))
    return {"status": "prepared", "files": len(files), "release": str(release), "control": str(control)}


def load_prepared(commit: str, control: Path, release: Path) -> tuple[dict, dict]:
    manifest = bounded_json(control / "prepared.json")
    state = bounded_json(control / "state.json")
    if (manifest.get("schema") != 1 or manifest.get("commit") != commit
            or manifest.get("source") != str(SOURCE) or manifest.get("mount") != str(MOUNT)
            or manifest.get("live_config") != str(LIVE_CONFIG)):
        raise ReleaseError("Prepared receipt does not match the fixed deployment scope.")
    files = manifest.get("files", {})
    names = [relative_name(name) for name in files]
    check_limits(release, names)
    for name, info in files.items():
        if (release / name).stat().st_size != info["size"] or file_digest(release / name) != info["sha256"]:
            raise ReleaseError("Immutable static release content changed.")
    expected = {"candidate.Caddyfile": manifest["candidate_config_sha256"],
                "rollback.Caddyfile": manifest["original_config_sha256"],
                "bundle-manifest.json": manifest["bundle_manifest_sha256"]}
    for name, sha in expected.items():
        if file_digest(release / name) != sha:
            raise ReleaseError("Immutable release configuration or manifest changed.")
    if file_digest(control / "backup" / "Caddyfile") != manifest["original_config_sha256"]:
        raise ReleaseError("Original configuration backup changed.")
    original = (control / "backup" / "Caddyfile").read_bytes()
    if static_root(original) != manifest.get("old_static_root", "/srv/site"):
        raise ReleaseError("Previous static root differs from the verified rollback configuration.")
    return manifest, state


def assert_old_static(manifest: dict) -> None:
    previous_path = static_path(manifest.get("old_static_root", "/srv/site"))
    if old_files(previous_path) != sorted(manifest["old_files"]):
        raise ReleaseError("Old live static file list changed since preparation.")
    for name, info in manifest["old_files"].items():
        relative_name(name, old=True)
        if file_digest(previous_path / name) != info["sha256"]:
            raise ReleaseError("Old live static files changed; preserve concurrent edits.")


def restore_config(commit: str, control: Path, manifest: dict) -> None:
    current = file_digest(LIVE_CONFIG)
    if current not in (manifest["candidate_config_sha256"], manifest["original_config_sha256"]):
        raise ReleaseError("Live configuration changed concurrently; automatic restoration refused.")
    original = (control / "backup" / "Caddyfile").read_bytes()
    if digest(original) != manifest["original_config_sha256"]:
        raise ReleaseError("Original configuration backup checksum mismatch.")
    atomic_write(LIVE_CONFIG, original)
    caddy(commit, "reload", "rollback.Caddyfile")
    if file_digest(LIVE_CONFIG) != manifest["original_config_sha256"]:
        raise ReleaseError("Configuration changed during rollback.")


def activate(commit: str, control: Path, release: Path) -> dict:
    manifest, state = load_prepared(commit, control, release)
    if state.get("phase") != "prepared" or state.get("activation_attempted"):
        raise ReleaseError("Activation is allowed once for a prepared commit; no re-release.")
    names = source_files(commit)
    if names != sorted(manifest["files"]):
        raise ReleaseError("Source static selection changed.")
    for name in names:
        if file_digest(SOURCE / name) != manifest["files"][name]["source_sha256"]:
            raise ReleaseError("Source bytes changed since preparation.")
    assert_old_static(manifest)
    if file_digest(LIVE_CONFIG) != manifest["original_config_sha256"]:
        raise ReleaseError("Live configuration no longer matches the prepared original SHA-256.")
    caddy(commit, "validate", "candidate.Caddyfile")
    if file_digest(LIVE_CONFIG) != manifest["original_config_sha256"]:
        raise ReleaseError("Live configuration changed during validation.")
    set_phase(control, "activating", activation_attempted=True)
    try:
        atomic_write(LIVE_CONFIG, (release / "candidate.Caddyfile").read_bytes())
        caddy(commit, "reload", "candidate.Caddyfile")
        if file_digest(LIVE_CONFIG) != manifest["candidate_config_sha256"]:
            raise ReleaseError("Live configuration changed during activation.")
    except Exception as exc:
        log(control, "activation_failed", error_type=type(exc).__name__)
        try:
            restore_config(commit, control, manifest)
            set_phase(control, "activation_failed_restored", activation_attempted=True)
        except Exception as recovery:
            set_phase(control, "recovery_required", activation_attempted=True, error_type=type(recovery).__name__)
            raise ReleaseError("Activation failed and graceful rollback was not confirmed; inspect the receipt. No service restart was attempted.") from recovery
        raise ReleaseError("Activation failed; original host configuration and graceful rollback reload were restored. No reactivation is permitted for this receipt.") from exc
    set_phase(control, "activated", activation_attempted=True, https_verified=False)
    return {"status": "activated_not_yet_https_verified", "commit": commit, "control": str(control)}


def get_https(path: str, remaining: int) -> tuple[bytes, int]:
    connection = http.client.HTTPSConnection(HOST, PORT, timeout=15, context=ssl.create_default_context())
    try:
        connection.request("GET", quote(path, safe="/._-~"), headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"})
        response = connection.getresponse()
        if response.status != 200:
            raise ReleaseError(f"HTTPS GET {path}: HTTP {response.status}; redirects are not followed.")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ReleaseError("Unexpected response compression prevents exact byte verification.")
        declared = response.getheader("Content-Length")
        if declared and (not declared.isdigit() or int(declared) > remaining):
            raise ReleaseError("HTTPS response exceeds verification byte budget.")
        content = bytearray()
        while True:
            chunk = response.read(min(64 * 1024, remaining - len(content) + 1))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > remaining:
                raise ReleaseError("HTTPS verification exceeded 32 MiB total.")
        return bytes(content), len(content)
    finally:
        connection.close()


def verify(commit: str, control: Path, release: Path) -> dict:
    manifest, state = load_prepared(commit, control, release)
    if state.get("phase") not in ("activated", "verified", "verification_failed"):
        raise ReleaseError("HTTPS verification requires an activated release.")
    if file_digest(LIVE_CONFIG) != manifest["candidate_config_sha256"]:
        raise ReleaseError("Live configuration does not select this release.")
    critical = ["index.html", "privacy.html", "mugs.html", "souvenirs.html", "site.webmanifest",
                "assets/app-shell.css", "assets/home-v5.css", "assets/app-shell.js", "assets/direct-upload.js",
                "assets/mugs.css", "assets/mugs.js", "assets/souvenirs.css", "assets/souvenirs.js",
                "assets/mug-catalog.json", "assets/fotomag_logo_official.svg", "assets/mugs/10335.webp"]
    if any(name not in manifest["files"] for name in critical):
        raise ReleaseError("A required critical static resource is absent from the release manifest.")
    checked, used = [], 0
    try:
        for path, name in [("/", "index.html"), *(("/" + n, n) for n in critical)]:
            content, size = get_https(path, MAX_VERIFY - used)
            used += size
            expected = manifest["files"][name]
            if size != expected["size"] or digest(content) != expected["sha256"]:
                raise ReleaseError(f"HTTPS byte/hash mismatch for {path}.")
            checked.append({"path": path, "size": size, "sha256": digest(content)})
        content, size = get_https("/api/health", min(64 * 1024, MAX_VERIFY - used))
        used += size
        health = json.loads(content)
        if not isinstance(health, dict) or health.get("accepting_uploads") is not True:
            raise ReleaseError("Health did not confirm accepting_uploads=true.")
        if file_digest(LIVE_CONFIG) != manifest["candidate_config_sha256"]:
            raise ReleaseError("Configuration changed during HTTPS verification.")
    except Exception as exc:
        write_json(control / "verification.json", {"commit": commit, "time": now(), "status": "failed",
                                                  "checked": checked, "bytes": used, "error_type": type(exc).__name__})
        set_phase(control, "verification_failed", https_verified=False)
        raise
    write_json(control / "verification.json", {"commit": commit, "time": now(), "status": "passed",
                                              "checked": checked, "bytes": used, "health_http": 200,
                                              "accepting_uploads": True, "normal_tls_validation": True})
    set_phase(control, "verified", https_verified=True)
    return {"status": "verified", "resources": len(checked), "bytes": used, "health": "200/accepting", "control": str(control)}


def rollback(commit: str, control: Path, release: Path) -> dict:
    manifest, state = load_prepared(commit, control, release)
    if not state.get("activation_attempted"):
        raise ReleaseError("This release has not been activated; rollback is unnecessary.")
    assert_old_static(manifest)
    caddy(commit, "validate", "rollback.Caddyfile")
    restore_config(commit, control, manifest)
    set_phase(control, "rolled_back", https_verified=False)
    return {"status": "original_configuration_reloaded", "commit": commit, "control": str(control), "orders_touched": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("prepare", "activate", "verify", "rollback"))
    parser.add_argument("--commit", required=True, help="Exact source HEAD, 40 lowercase hexadecimal characters")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("--commit must contain exactly 40 lowercase hexadecimal characters")
    lock_fd, lock = None, CONTROL / "lan-release.lock"
    control, release = CONTROL / ("lan-release-" + args.commit), MOUNT / "releases" / args.commit
    try:
        if os.name != "nt" or os.environ.get("COMPUTERNAME", "").upper() != "DESKTOP-P6L7HTI":
            raise ReleaseError("This command is restricted to Windows DESKTOP-P6L7HTI.")
        for path in (SOURCE, MOUNT, CONTROL, LIVE_CONFIG, control, release):
            checked_path(path)
        if not all(path.is_dir() for path in (SOURCE, MOUNT, CONTROL)) or not LIVE_CONFIG.is_file():
            raise ReleaseError("A fixed source, mount, control directory or Caddyfile is missing.")
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, json.dumps({"pid": os.getpid(), "commit": args.commit, "action": args.action, "time": now()}).encode())
        result = {"prepare": prepare, "activate": activate, "verify": verify, "rollback": rollback}[args.action](args.commit, control, release)
        print(json.dumps({"ok": True, "action": args.action, "time": now(), **result}, ensure_ascii=True))
        return 0
    except Exception as exc:
        # Do not print subprocess output, health JSON, environment or credentials.
        message = str(exc) if isinstance(exc, ReleaseError) else "Operation stopped; inspect the scoped local receipt and existing state before retrying."
        if lock_fd is not None and control.is_dir():
            log(control, "operation_failed", action=args.action, error_type=type(exc).__name__)
        print(json.dumps({"ok": False, "action": args.action, "commit": args.commit,
                          "error_type": type(exc).__name__, "message": message, "control": str(control)}, ensure_ascii=True))
        return 1
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            os.unlink(lock)


if __name__ == "__main__":
    sys.exit(main())
