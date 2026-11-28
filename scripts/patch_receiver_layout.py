"""Manual, hash-guarded folder-layout patch for the known FotoMag receiver.

Run one action at a time on the authorized Windows computer, after reading its
stability instructions. This script never starts/stops a receiver, service or
scheduler and never accesses an API. Activation affects the next process that
loads the source; it does not claim that an existing process has reloaded it.

The backup and manifest remain outside the public repository. Existing order
root files, including partial/legacy copies, are preserved, never migrated.
The patched receiver logs their count and keeps metadata at the receipt root.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
import warnings

SOURCE = Path(r"D:\FotoMag_Direct_Launch_20261125\receiver\upload_gateway\workstation_agent.py")
CONTROL = Path(r"D:\FotoMag_Site_Orders_Control\receiver-layout-20261128")
EXPECTED_SHA256 = "670f8ad413f91d577894d1ed3af9cc106d3a46c9e556b93494583ea58968d668"
PATCH_ID = "receiver-layout-20261128-v1"
ORIGINAL_NAME = "workstation_agent.original.py"
CANDIDATE_NAME = "workstation_agent.candidate.py"
MANIFEST_NAME = "manifest.json"

OLD_BLOCK = '''    for index, info in enumerate(files, start=1):
        download_file(info, index, folder)
'''
NEW_BLOCK = '''    originals = folder / "Исходники"
    processed = folder / "Обработанные JPEG"
    ensure_safe_directory(originals, root)
    ensure_safe_directory(processed, root)
    # Keep legacy root copies/partials in place; never migrate or overwrite them.
    legacy_count = sum(1 for item in folder.iterdir()
                       if item.is_file() and item.name not in {"order.json", "ЗАКАЗ.txt"})
    if legacy_count:
        LOG.info("Order %s: preserving %d legacy root file(s); new files use originals",
                 receipt, legacy_count)
    for index, info in enumerate(files, start=1):
        download_file(info, index, originals)
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_candidate(original: bytes) -> bytes:
    """Check the exact live bytes, replace one known block, compile without import."""
    if digest(original) != EXPECTED_SHA256:
        raise ValueError("Receiver source does not match the approved original SHA-256")
    before = OLD_BLOCK.replace("\n", "\r\n").encode("utf-8")
    after = NEW_BLOCK.replace("\n", "\r\n").encode("utf-8")
    if original.count(before) != 1:
        raise ValueError("Expected receiver block must occur exactly once")
    candidate = original.replace(before, after, 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        compile(candidate, str(SOURCE), "exec")
    return candidate


def require_plain_path(path: Path) -> None:
    """Reject symlinks and Windows reparse points, including existing parents."""
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Symbolic link is not allowed: {part}")
        if part.exists():
            attributes = getattr(part.lstat(), "st_file_attributes", 0)
            if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                raise ValueError(f"Reparse point is not allowed: {part}")


def read_plain(path: Path) -> bytes:
    require_plain_path(path)
    if not path.is_file():
        raise ValueError(f"Expected an ordinary file: {path}")
    return path.read_bytes()


def write_exclusive_or_same(path: Path, value: bytes) -> None:
    require_plain_path(path)
    if path.exists():
        if read_plain(path) != value:
            raise ValueError(f"Existing control file differs; it was preserved: {path}")
        return
    with path.open("xb") as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())


def source_identity(source: Path) -> str:
    return os.path.normcase(os.path.abspath(source))


def load_bundle(source: Path, control: Path) -> tuple[dict, bytes, bytes]:
    manifest = json.loads(read_plain(control / MANIFEST_NAME).decode("utf-8"))
    if manifest.get("patch_id") != PATCH_ID or manifest.get("source") != source_identity(source):
        raise ValueError("Manifest identifies another patch or receiver")
    original = read_plain(control / ORIGINAL_NAME)
    candidate = read_plain(control / CANDIDATE_NAME)
    if manifest.get("original_sha256") != EXPECTED_SHA256 or digest(original) != EXPECTED_SHA256:
        raise ValueError("Original backup failed the approved SHA-256 check")
    if manifest.get("candidate_sha256") != digest(candidate) or candidate != build_candidate(original):
        raise ValueError("Candidate differs from the exact approved transformation")
    return manifest, original, candidate


def prepare(source: Path = SOURCE, control: Path = CONTROL) -> dict:
    original = read_plain(source)
    candidate = build_candidate(original)
    require_plain_path(control)
    control.mkdir(parents=True, exist_ok=True)
    require_plain_path(control)
    if (control / MANIFEST_NAME).exists():
        manifest, _, _ = load_bundle(source, control)
        return {"state": "prepared", **manifest}
    write_exclusive_or_same(control / ORIGINAL_NAME, original)
    write_exclusive_or_same(control / CANDIDATE_NAME, candidate)
    manifest = {
        "patch_id": PATCH_ID, "source": source_identity(source),
        "prepared_utc": datetime.now(timezone.utc).isoformat(),
        "original_sha256": digest(original), "candidate_sha256": digest(candidate),
        "original_bytes": len(original), "candidate_bytes": len(candidate),
        "legacy_policy": "Preserve receipt-root files and partials; log their count; no migration.",
        "layout": {"originals": "Исходники", "processed": "Обработанные JPEG",
                   "metadata_at_root": ["order.json", "ЗАКАЗ.txt"]},
        "activation": "Atomic file replacement only; no services, processes or schedules changed.",
    }
    write_exclusive_or_same(control / MANIFEST_NAME,
                            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    load_bundle(source, control)
    return {"state": "prepared", **manifest}


def replace_exact(source: Path, value: bytes, expected_current: str) -> None:
    """Same-directory atomic replacement, guarded immediately before the swap."""
    if digest(read_plain(source)) != expected_current:
        raise ValueError("Receiver changed; refusing to replace it")
    temp = source.with_name("." + source.name + "." + PATCH_ID + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        shutil.copymode(source, temp)
        if digest(read_plain(source)) != expected_current:
            raise ValueError("Receiver changed during preparation; original source preserved")
        os.replace(temp, source)
        if read_plain(source) != value:
            raise RuntimeError("Post-replacement byte verification failed; inspect before continuing")
    finally:
        # Only this invocation's unique staging file may be removed.
        temp.unlink(missing_ok=True)


def verify(source: Path = SOURCE, control: Path = CONTROL) -> dict:
    manifest, _, _ = load_bundle(source, control)
    current = digest(read_plain(source))
    if current == EXPECTED_SHA256:
        state = "original"
    elif current == manifest["candidate_sha256"]:
        state = "active"
    else:
        raise ValueError("Receiver has unrelated changes; activation and rollback are refused")
    return {"state": state, "source": source_identity(source), "sha256": current,
            "backup": str(control / ORIGINAL_NAME), "candidate_sha256": manifest["candidate_sha256"]}


def activate(source: Path = SOURCE, control: Path = CONTROL) -> dict:
    manifest, _, candidate = load_bundle(source, control)
    current = digest(read_plain(source))
    if current != manifest["candidate_sha256"]:
        replace_exact(source, candidate, EXPECTED_SHA256)
    return verify(source, control)


def rollback(source: Path = SOURCE, control: Path = CONTROL) -> dict:
    manifest, original, _ = load_bundle(source, control)
    if digest(read_plain(source)) != EXPECTED_SHA256:
        replace_exact(source, original, manifest["candidate_sha256"])
    return verify(source, control)


@contextmanager
def one_operation(control: Path, action: str):
    require_plain_path(control)
    if action == "prepare":
        control.mkdir(parents=True, exist_ok=True)
    lock = control / "operation.lock"
    require_plain_path(lock)
    try:
        output = lock.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise RuntimeError("Another operation or unresolved lock exists; inspect it before retrying") from error
    try:
        with output:
            json.dump({"pid": os.getpid(), "action": action,
                       "started_utc": datetime.now(timezone.utc).isoformat()}, output)
            output.flush()
            os.fsync(output.fileno())
        yield
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("prepare", "activate", "verify", "rollback"))
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Operational actions are restricted to the fixed Windows paths; use offline tests elsewhere")
    actions = {"prepare": prepare, "activate": activate, "verify": verify, "rollback": rollback}
    try:
        with one_operation(CONTROL, args.action):
            result = actions[args.action]()
            record = {"action": args.action, "utc": datetime.now(timezone.utc).isoformat(), **result}
            history = CONTROL / "actions.jsonl"
            require_plain_path(history)
            with history.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
        print(json.dumps(record, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"action": args.action, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
