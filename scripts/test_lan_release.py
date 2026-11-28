#!/usr/bin/env python3
"""Offline LAN-release regression tests; no Docker, network or production paths."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

import lan_release as release


OLD = "a" * 40
NEW = "b" * 40
OLD_ROOT = f"/srv/site/releases/{OLD}"


def config(root="/srv/site"):
    return (""":8080 {
    @static {
        method GET HEAD
        path / /index.html /assets/old.txt
    }
    handle @static {
        root * ROOT
        file_server
    }
    handle /api/* {
        reverse_proxy gateway:8000
    }
}
""").replace("ROOT", root).encode()


class RootTests(unittest.TestCase):
    def test_original_and_release_roots(self):
        for root in ("/srv/site", OLD_ROOT):
            with self.subTest(root=root):
                self.assertEqual(release.static_root(config(root)), root)

    def test_malformed_traversal_and_multiple_roots(self):
        for root in ("/srv/site/", "/srv/site/../private", "/srv/site/releases/../private",
                     "/srv/site/releases/" + "a" * 39, "/srv/site/releases/" + "A" * 40,
                     OLD_ROOT + "/assets", '"/srv/site"', "/other/site"):
            with self.subTest(root=root), self.assertRaises(release.ReleaseError):
                release.static_root(config(root))
        for data in (b"# no root\n", config() + b"root * /srv/site\n",
                     config(OLD_ROOT) + b"root * /other/site\n"):
            with self.subTest(data=data), self.assertRaises(release.ReleaseError):
                release.static_root(data)

    def test_candidate_changes_only_static_selection(self):
        names = ["index.html", "assets/app.js", "mugs.html"]
        for old_root in ("/srv/site", OLD_ROOT):
            original = config(old_root).replace(b"\n", b"\r\n")
            candidate = release.candidate_config(original, names, NEW)
            expected = original.replace(
                b"path / /index.html /assets/old.txt",
                b'path "/" "/index.html" "/assets/app.js" "/mugs.html"'
            ).replace(("root * " + old_root).encode(), ("root * /srv/site/releases/" + NEW).encode())
            self.assertEqual(candidate, expected)
            self.assertIn(b"handle /api/* {\r\n        reverse_proxy gateway:8000\r\n    }", candidate)


class ScopedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fotomag-release-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.mount = self.base / "mount"
        self.control_parent = self.base / "control"
        for directory in (self.source, self.mount, self.control_parent):
            directory.mkdir()
        self.live = self.base / "Caddyfile"
        self.original = config(OLD_ROOT)
        self.live.write_bytes(self.original)
        self.active = self.mount / "releases" / OLD
        (self.active / "assets").mkdir(parents=True)
        (self.active / "index.html").write_bytes(b"active previous release")
        (self.active / "assets" / "old.txt").write_bytes(b"active asset")
        (self.active / "candidate.Caddyfile").write_bytes(b"not a public asset")
        (self.mount / "index.html").write_bytes(b"stale mount root")
        for name in release.ROOT_FILES:
            (self.source / name).write_bytes(b"new static file")
        (self.source / "index.html").write_bytes(
            b'<meta content="" name="fotomag-upload-api"/><meta content="connect-src \'none\'"/>'
        )
        (self.source / "assets").mkdir()
        (self.source / "assets" / "app.js").write_bytes(b"'use strict';")
        self.names = sorted([*release.ROOT_FILES, "assets/app.js"])
        self.control = self.control_parent / ("lan-release-" + NEW)
        self.destination = self.mount / "releases" / NEW
        patches = (
            patch.multiple(release, SOURCE=self.source, MOUNT=self.mount,
                           LIVE_CONFIG=self.live, CONTROL=self.control_parent),
            patch.object(release, "source_files", return_value=self.names),
            patch.object(release, "caddy"),
        )
        for item in patches:
            value = item.start()
            self.addCleanup(item.stop)
            if item is patches[-1]:
                self.caddy = value

    def prepare(self):
        release.prepare(NEW, self.control, self.destination)
        return json.loads((self.control / "prepared.json").read_text())

    def test_static_path_rejects_escape_missing_and_symlink(self):
        self.assertEqual(release.static_path("/srv/site"), self.mount)
        self.assertEqual(release.static_path(OLD_ROOT), self.active)
        for root in ("/srv/site/releases/../private", "/srv/site/releases/" + "c" * 40):
            with self.subTest(root=root), self.assertRaises(release.ReleaseError):
                release.static_path(root)
        link = self.mount / "releases" / ("d" * 40)
        try:
            link.symlink_to(self.active, target_is_directory=True)
        except (OSError, NotImplementedError):
            return  # Windows may require an explicit privilege to create a link.
        with self.assertRaises(release.ReleaseError):
            release.static_path("/srv/site/releases/" + "d" * 40)

    def test_prepare_backs_up_active_release_and_keeps_live_unchanged(self):
        manifest = self.prepare()
        self.assertEqual(manifest["old_static_root"], OLD_ROOT)
        self.assertEqual(release.old_files(self.active), ["assets/old.txt", "index.html"])
        self.assertEqual(sorted(manifest["old_files"]), ["assets/old.txt", "index.html"])
        self.assertEqual((self.control / "backup/site/index.html").read_bytes(), b"active previous release")
        self.assertEqual((self.control / "backup/site/assets/old.txt").read_bytes(), b"active asset")
        self.assertEqual((self.control / "backup/Caddyfile").read_bytes(), self.original)
        self.assertEqual((self.destination / "rollback.Caddyfile").read_bytes(), self.original)
        self.assertEqual(self.live.read_bytes(), self.original)
        self.assertEqual((self.active / "index.html").read_bytes(), b"active previous release")
        self.caddy.assert_has_calls([call(NEW, "validate", "candidate.Caddyfile"),
                                     call(NEW, "validate", "rollback.Caddyfile")])

    def test_old_file_guard_watches_active_root_not_stale_mount(self):
        manifest = self.prepare()
        (self.mount / "index.html").write_bytes(b"unrelated stale edit")
        release.assert_old_static(manifest)
        (self.active / "index.html").write_bytes(b"concurrent active edit")
        with self.assertRaisesRegex(release.ReleaseError, "changed"):
            release.assert_old_static(manifest)
        (self.active / "index.html").write_bytes(b"active previous release")
        (self.active / "assets/extra.txt").write_bytes(b"new concurrent asset")
        with self.assertRaisesRegex(release.ReleaseError, "list changed"):
            release.assert_old_static(manifest)

    def test_manifest_root_is_bound_to_verified_original_config(self):
        manifest = self.prepare()
        release.load_prepared(NEW, self.control, self.destination)
        for wrong_root in ("/srv/site", "/srv/site/releases/" + "c" * 40):
            with self.subTest(root=wrong_root):
                manifest["old_static_root"] = wrong_root
                (self.control / "prepared.json").write_text(json.dumps(manifest))
                with self.assertRaisesRegex(release.ReleaseError, "Previous static root differs"):
                    release.load_prepared(NEW, self.control, self.destination)

    def test_failed_activation_restores_previous_release_config(self):
        self.prepare()

        def fail_candidate_reload(commit, operation, filename):
            if operation == "reload" and filename == "candidate.Caddyfile":
                raise release.ReleaseError("controlled reload failure")

        self.caddy.side_effect = fail_candidate_reload
        with self.assertRaisesRegex(release.ReleaseError, "original host configuration"):
            release.activate(NEW, self.control, self.destination)
        self.assertEqual(self.live.read_bytes(), self.original)
        self.assertEqual(release.static_root(self.live.read_bytes()), OLD_ROOT)
        self.assertEqual((self.active / "index.html").read_bytes(), b"active previous release")
        state = json.loads((self.control / "state.json").read_text())
        self.assertEqual(state["phase"], "activation_failed_restored")
        self.caddy.assert_any_call(NEW, "reload", "rollback.Caddyfile")


if __name__ == "__main__":
    unittest.main()
