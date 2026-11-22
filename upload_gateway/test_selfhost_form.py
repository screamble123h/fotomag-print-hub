from html.parser import HTMLParser
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

from upload_gateway.build_selfhost_form import PUBLIC_FILES, build_release


class PageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "meta":
            self.meta[attr.get("name") or attr.get("http-equiv")] = attr.get("content")
        for key in ("src", "href"):
            value = attr.get(key, "")
            if value and not value.startswith(("#", "https:", "tel:", "mailto:")):
                self.references.append(value.split("#", 1)[0])


class SelfHostFormTests(unittest.TestCase):
    def test_export_separates_public_files_and_internal_routes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "new release"
            origin = "https://files.example.org:8443"
            build_release(origin, root)
            site = root / "site"
            exported = {file.relative_to(site).as_posix() for file in site.rglob("*") if file.is_file()}
            self.assertEqual(exported, set(PUBLIC_FILES))
            parser = PageReferences()
            parser.feed((site / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(parser.meta["fotomag-upload-api"], origin)
            self.assertIn("connect-src 'self'", parser.meta["Content-Security-Policy"])
            self.assertNotIn("github.io", parser.meta["Content-Security-Policy"])
            self.assertTrue(set(parser.references) <= exported)
            self.assertIn("assets/direct-upload.js", exported)
            with self.assertRaises(FileExistsError):
                build_release(origin, root)

    def test_credentials_paths_and_insecure_hosts_are_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "bad"
            for origin in ("http://files.example.org:8443", "https://name@files.example.org:8443",
                           "https://files.example.org:8443/path", "https://files.example.org:8443?q=x"):
                with self.assertRaises(ValueError):
                    build_release(origin, root)
            self.assertFalse(root.exists())
