#!/usr/bin/env python3
"""Verify deployed-page monitoring against repository HTML without network calls."""
from pathlib import Path
import unittest
from unittest.mock import patch
import monitor_site as monitor

ROOT = Path(__file__).resolve().parents[1]

class PublicPageMonitorTests(unittest.TestCase):
    def test_current_pages_keep_monitor_contract(self):
        for name, suffix, ids, script in monitor.PAGES:
            with self.subTest(page=name):
                body = (ROOT / (suffix or "index.html")).read_bytes()
                with patch.object(monitor, "read_url", return_value=(body, 200)):
                    self.assertEqual(monitor.check_page(suffix, ids, script)["http_status"], 200)

    def test_missing_or_wrong_script_is_still_unhealthy(self):
        _, suffix, ids, script = monitor.PAGES[0]
        body = (ROOT / "index.html").read_text(encoding="utf-8")
        for wrong in ("", "https://example.invalid/" + script, "assets/app-shell.js?wrong=1128b"):
            with self.subTest(script=wrong):
                changed = body.replace(script, wrong).encode()
                with patch.object(monitor, "read_url", return_value=(changed, 200)):
                    with self.assertRaisesRegex(monitor.CheckFailure, "required_script_reference_missing"):
                        monitor.check_page(suffix, ids, script)

if __name__ == "__main__":
    unittest.main()
