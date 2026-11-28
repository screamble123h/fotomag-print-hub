"""Offline receiver-layout checks against a separately supplied source snapshot.

Usage: python scripts/test_receiver_layout.py --reference /path/to/receiver-reference.py

The production module is never imported. Only its three relevant functions are
extracted from the patched AST; downloads/API calls use local test doubles.
No production configuration, tokens, network, services or scheduling are used.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch as mock_patch
import uuid
import warnings

import patch_receiver_layout as patcher

REFERENCE_RAW = None


def reference_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if patcher.digest(data) == patcher.EXPECTED_SHA256:
        return data
    # The read-only reference supplied to this workspace was newline-normalized.
    # Reconstruct only CRLF, and accept it only when the fixed live hash matches.
    restored = data.replace(b"\n", b"\r\n") if b"\r" not in data else b""
    if patcher.digest(restored) != patcher.EXPECTED_SHA256:
        raise ValueError("Reference does not match the exact approved source, even with CRLF restored")
    return restored


class SourceRequired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REFERENCE_RAW is None:
            raise unittest.SkipTest("Supply the independent receiver snapshot with --reference")


class PatchLifecycleTests(SourceRequired):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "workstation_agent.py"
        self.control = self.base / "private-control"
        self.source.write_bytes(REFERENCE_RAW)

    def test_prepare_activate_verify_and_exact_rollback(self):
        manifest = patcher.prepare(self.source, self.control)
        self.assertEqual(self.source.read_bytes(), REFERENCE_RAW)
        self.assertEqual((self.control / patcher.ORIGINAL_NAME).read_bytes(), REFERENCE_RAW)
        self.assertEqual(patcher.verify(self.source, self.control)["state"], "original")
        candidate = patcher.build_candidate(REFERENCE_RAW)
        self.assertEqual(manifest["candidate_sha256"], patcher.digest(candidate))
        self.assertEqual(patcher.prepare(self.source, self.control)["candidate_sha256"], manifest["candidate_sha256"])
        self.assertEqual(patcher.activate(self.source, self.control)["state"], "active")
        self.assertEqual(self.source.read_bytes(), candidate)
        self.assertEqual(patcher.activate(self.source, self.control)["state"], "active")
        self.assertEqual(patcher.rollback(self.source, self.control)["state"], "original")
        self.assertEqual(self.source.read_bytes(), REFERENCE_RAW)
        self.assertEqual(patcher.rollback(self.source, self.control)["state"], "original")

    def test_unrelated_live_edits_are_never_overwritten(self):
        patcher.prepare(self.source, self.control)
        edited = REFERENCE_RAW + b"\r\n# unrelated local edit\r\n"
        self.source.write_bytes(edited)
        for action in (patcher.activate, patcher.rollback, patcher.verify):
            with self.assertRaises(ValueError):
                action(self.source, self.control)
            self.assertEqual(self.source.read_bytes(), edited)
        with self.assertRaises(ValueError):
            patcher.prepare(self.source, self.base / "other-control")
        self.assertFalse((self.base / "other-control").exists())

    def test_tampered_candidate_is_rejected(self):
        patcher.prepare(self.source, self.control)
        candidate = self.control / patcher.CANDIDATE_NAME
        candidate.write_bytes(candidate.read_bytes() + b"\r\n# not the approved patch\r\n")
        with self.assertRaises(ValueError):
            patcher.activate(self.source, self.control)
        self.assertEqual(self.source.read_bytes(), REFERENCE_RAW)

    def test_failed_atomic_swap_preserves_original(self):
        patcher.prepare(self.source, self.control)
        with mock_patch.object(patcher.os, "replace", side_effect=PermissionError("simulated file lock")):
            with self.assertRaises(PermissionError):
                patcher.activate(self.source, self.control)
        self.assertEqual(self.source.read_bytes(), REFERENCE_RAW)
        self.assertEqual(list(self.base.glob(".*.tmp")), [])


class ReceiverLayoutTests(SourceRequired):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "2026"
        self.root.mkdir()
        self.payloads = {
            "Пример.jpg": b"\xff\xd8neutral first jpeg\xff\xd9",
            "document.pdf": b"%PDF-1.4\nneutral PDF fixture\n%%EOF\n",
            "second.jpg": b"\xff\xd8neutral second jpeg\xff\xd9",
        }
        self.order = {
            "order_id": "a" * 32, "receipt": "FM-W-20261128-ABC1234", "kind": "documents",
            "client_name": "Контроль", "phone": "", "comment": "Офлайн-проверка, не печатать",
            "created_ts": int(datetime(2026, 11, 28, 12, tzinfo=timezone.utc).timestamp()),
            "files": [{"file_id": str(index) * 32, "name": name, "size": len(value),
                       "sha256": hashlib.sha256(value).hexdigest()}
                      for index, (name, value) in enumerate(self.payloads.items(), 1)],
        }
        self.folder = self.root / "11" / "28" / "Напрямую" / "Контроль" / self.order["receipt"]
        self.originals = self.folder / "Исходники"
        self.processed = self.folder / "Обработанные JPEG"
        self.write_count = 0
        self.download_calls = []
        self.acks = []
        self.logs = []
        self.fail_ack_once = False
        self.fail_download_index = None

        class Logger:
            def info(_, template, *args):
                self.logs.append(template % args)

        def download_file(info, index, folder):
            # Both safe destinations must exist BEFORE the first download/ACK.
            self.assertEqual(folder, self.originals)
            self.assertTrue(self.originals.is_dir())
            self.assertTrue(self.processed.is_dir())
            self.download_calls.append(index)
            if index == self.fail_download_index:
                raise ConnectionError("simulated interrupted download")
            target = folder / f"{index:02d}_{info['name']}"
            expected = self.payloads[info["name"]]
            if target.exists():
                if target.read_bytes() != expected:
                    raise FileExistsError("existing different original must be preserved")
                return
            with target.open("xb") as output:
                output.write(expected)
            self.write_count += 1

        def api_request(path, *, method):
            self.assertEqual((path, method), ("/api/agent/orders/" + self.order["order_id"] + "/ack", "POST"))
            self.assertTrue(self.originals.is_dir())
            self.assertTrue(self.processed.is_dir())
            self.assertEqual(len(list(self.originals.iterdir())), 3)
            for index, info in enumerate(self.order["files"], 1):
                value = (self.originals / f"{index:02d}_{info['name']}").read_bytes()
                self.assertEqual(hashlib.sha256(value).hexdigest(), info["sha256"])
                self.assertEqual(len(value), info["size"])
            metadata = json.loads((self.folder / "order.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["receipt"], self.order["receipt"])
            self.assertEqual([item["name"] for item in metadata["files"]], list(self.payloads))
            self.assertIn(self.order["receipt"], (self.folder / "ЗАКАЗ.txt").read_text(encoding="utf-8"))
            self.acks.append(path)
            if self.fail_ack_once and len(self.acks) == 1:
                raise ConnectionError("simulated lost ACK response")
            return {"ok": True}

        namespace = {
            "Path": Path, "ARCHIVE_ROOT": self.root, "DATE_SUBPATH": "%m/%d", "CHANNEL": "Напрямую",
            "IZHEVSK_TIME": timezone(timedelta(hours=4)), "datetime": datetime, "json": json,
            "os": os, "uuid": uuid, "re": re, "LOG": Logger(),
            "order_destination": lambda order, root, pattern: self.folder,
            "download_file": download_file, "api_request": api_request,
        }
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(patcher.build_candidate(REFERENCE_RAW))
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in {"receive_order", "ensure_safe_directory", "create_exclusive"}]
        self.assertEqual(len(selected), 3)
        # Execute only function definitions; never top-level receiver configuration.
        exec(compile(ast.Module(body=selected, type_ignores=[]), "isolated-receiver", "exec"), namespace)
        self.receive = namespace["receive_order"]

    def snapshot(self):
        return {str(path.relative_to(self.folder)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.folder.rglob("*") if path.is_file()}

    def test_three_originals_and_metadata_before_ack_retry_preserves_every_file(self):
        self.folder.mkdir(parents=True)
        legacy = self.folder / "01_Пример.jpg"
        legacy.write_bytes(b"preserved legacy root copy")
        partial = self.folder / ".old-receiver.part"
        partial.write_bytes(b"preserved partial bytes")
        self.fail_ack_once = True
        with self.assertRaises(ConnectionError):
            self.receive(self.order, self.root)
        first = self.snapshot()
        self.assertEqual(self.receive(self.order, self.root), self.folder)
        self.assertEqual(self.snapshot(), first, "Retry changed file bytes or timestamps")
        self.assertEqual(self.write_count, 3)
        self.assertEqual(len(self.acks), 2, "Only two bounded attempts were exercised")
        self.assertEqual(legacy.read_bytes(), b"preserved legacy root copy")
        self.assertEqual(partial.read_bytes(), b"preserved partial bytes")
        self.assertEqual(list(self.processed.iterdir()), [], "No JPEG conversion or printing is performed")
        self.assertTrue(any("preserving 2 legacy root file(s)" in message for message in self.logs))

    def test_incomplete_download_is_not_acknowledged(self):
        self.fail_download_index = 2
        with self.assertRaises(ConnectionError):
            self.receive(self.order, self.root)
        self.assertEqual(self.acks, [])
        self.assertFalse((self.folder / "order.json").exists())
        first = self.snapshot()
        self.fail_download_index = None
        self.receive(self.order, self.root)
        for name, value in first.items():
            self.assertEqual(self.snapshot()[name], value)
        self.assertEqual(self.write_count, 3)
        self.assertEqual(len(self.acks), 1)

    def test_blocked_processed_directory_prevents_download_and_ack(self):
        self.folder.mkdir(parents=True)
        self.processed.write_bytes(b"existing data occupying the folder name")
        with self.assertRaises((FileExistsError, ValueError)):
            self.receive(self.order, self.root)
        self.assertEqual(self.download_calls, [])
        self.assertEqual(self.acks, [])
        self.assertEqual(self.processed.read_bytes(), b"existing data occupying the folder name")

    def test_conflicting_metadata_is_preserved_without_ack(self):
        self.folder.mkdir(parents=True)
        metadata = self.folder / "order.json"
        metadata.write_bytes(b"existing unrelated metadata")
        with self.assertRaises(FileExistsError):
            self.receive(self.order, self.root)
        self.assertEqual(metadata.read_bytes(), b"existing unrelated metadata")
        self.assertEqual(self.acks, [])


def main() -> int:
    global REFERENCE_RAW
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    REFERENCE_RAW = reference_bytes(args.reference)
    suite = unittest.defaultTestLoader.loadTestsFromNames(["__main__.PatchLifecycleTests", "__main__.ReceiverLayoutTests"])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(json.dumps({"original_sha256": patcher.digest(REFERENCE_RAW),
                          "candidate_sha256": patcher.digest(patcher.build_candidate(REFERENCE_RAW)),
                          "tests": result.testsRun, "production_actions": False}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
