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

    def test_release_requires_matching_consent_and_preserves_exact_approved_bytes(self):
        origin = "https://files.example.org:8443"
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            legal = parent / "legal"
            legal.mkdir()
            privacy = legal / "privacy.html"
            consent = legal / "consent.html"
            version = "2000-01-01-v1"
            document = f'<section id="consent" data-consent-version="{version}">Synthetic test</section>'.encode()
            privacy.write_bytes(document)
            consent.write_bytes(document)
            target = parent / "release"
            for source, tag in ((None, version), (legal, None), (legal, "2000-01-01-v2"),
                                (legal, "2000-01-01-draft")):
                with self.assertRaises(ValueError):
                    build_release(origin, target, approved_legal=source, consent_version=tag)
                self.assertFalse(target.exists())
            for invalid in (document + document, b"<!-- TODO_PRIVACY -->" + document):
                privacy.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    build_release(origin, target, approved_legal=legal, consent_version=version)
            privacy.write_bytes(document)
            build_release(origin, target, approved_legal=legal, consent_version=version)
            self.assertEqual((target / "site/privacy.html").read_bytes(), document)
            self.assertEqual((target / "site/consent.html").read_bytes(), document)
            self.assertIn('href="consent.html"', (target / "site/index.html").read_text(encoding="utf-8"))
            self.assertIn("/consent.html", (target / "Caddyfile.form").read_text(encoding="utf-8"))
            self.assertIn(f'data-consent-version="{version}"',
                          (target / "site/index.html").read_text(encoding="utf-8"))
