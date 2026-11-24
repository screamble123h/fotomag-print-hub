"""Export the approved portal into a new, private-to-the-host Caddy release."""
import argparse
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parents[1]
PAGES = "https://screamble123h.github.io/fotomag-print-hub/"
PUBLIC_FILES = (
    "index.html",
    "privacy.html",
    "site.webmanifest",
    "assets/app-shell.css",
    "assets/app-shell.js",
    "assets/direct-upload.js",
    "assets/fotomag_logo_official.svg",
    "assets/FotoMag_FACADE_APPROVED_web.webp",
    "assets/manrope-cyrillic.woff2",
    "assets/manrope-latin.woff2",
    "assets/OFL-Manrope.txt",
)


def https_origin(value: str) -> str:
    url = urlsplit(value)
    host = url.hostname or ""
    labels = host.split(".")
    if (url.scheme != "https" or url.port != 8443 or len(host) > 253 or len(labels) < 2
            or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
            or value != f"https://{host}:8443"):
        raise ValueError("Expected a DNS origin such as https://files.example.org:8443")
    return value


class ConsentSection(HTMLParser):
    def __init__(self):
        super().__init__()
        self.versions = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") == "consent":
            self.versions.append(values.get("data-consent-version"))


def approved_document(path: Path, version: str) -> bytes:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-v[1-9]\d*)?", version):
        raise ValueError("Expected the approved consent date or version")
    date.fromisoformat(version[:10])
    raw = path.read_bytes()
    html = raw.decode("utf-8-sig")
    if "TODO_PRIVACY" in html:
        raise ValueError("The privacy document still contains its draft marker")
    section = ConsentSection()
    section.feed(html)
    section.close()
    if section.versions != [version]:
        raise ValueError("Expected one consent section with the approved version")
    return raw


def build_release(origin: str, destination: Path, legal_draft: Path | None = None, *,
                  approved_legal: Path | None = None, consent_version: str | None = None) -> Path:
    origin = https_origin(origin)
    destination = destination.resolve()
    if destination.is_relative_to(SOURCE):
        raise ValueError("Choose a release directory outside the source repository")
    if destination.exists():
        raise FileExistsError(destination)
    original = (SOURCE / "index.html").read_text(encoding="utf-8")
    endpoint = '<meta content="" name="fotomag-upload-api"/>'
    if original.count(endpoint) != 1 or original.count("connect-src 'none'") != 1:
        raise ValueError("Review the source page: its disabled endpoint or CSP has changed")
    html = original.replace(endpoint, f'<meta content="{origin}" name="fotomag-upload-api"/>')
    html = html.replace("connect-src 'none'", "connect-src 'self'").replace(PAGES, origin + "/")

    if (approved_legal is None) != (consent_version is None):
        raise ValueError("Supply the approved legal folder and consent version together")
    if legal_draft is not None and approved_legal is not None:
        raise ValueError("Choose one legal edition for the release")
    legal_files = {}
    public_files = PUBLIC_FILES
    if legal_draft is not None or approved_legal is not None:
        # Existing TZ18 policy and separate consent keep their own filenames.
        directory = approved_legal if approved_legal is not None else legal_draft
        version = consent_version if approved_legal is not None else "2026-11-23-draft"
        previous = 'data-consent-version="2026-11-22-draft"'
        previous_link = 'href="privacy.html#consent"'
        if html.count(previous) != 1 or html.count(previous_link) != 1:
            raise ValueError("Review the form: its consent version or link has changed")
        for name in ("privacy.html", "consent.html"):
            if approved_legal is not None:
                legal_files[name] = approved_document(directory / name, version)
            else:
                data = (directory / name).read_bytes()
                section = ConsentSection()
                section.feed(data.decode("utf-8-sig"))
                section.close()
                if section.versions != [version]:
                    raise ValueError(f"Unexpected draft consent version in {name}")
                legal_files[name] = data
        html = html.replace(previous, f'data-consent-version="{version}"')
        html = html.replace(previous_link, 'href="consent.html"')
        public_files = (*PUBLIC_FILES, "consent.html")

    # The root is supplied as a quoted import argument by the local Caddyfile.
    # The separate route file stays outside the public directory.
    routes = (
        "@fotomag_form {\n"
        "    method GET HEAD\n"
        f"    path / {' '.join('/' + name for name in public_files)}\n"
        "}\n"
        "handle @fotomag_form {\n"
        "    root * {args[0]}\n"
        "    header X-Content-Type-Options nosniff\n"
        "    header Referrer-Policy no-referrer\n"
        "    header X-Frame-Options DENY\n"
        "    header Cache-Control no-store\n"
        "    file_server\n"
        "}\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        release = Path(temporary) / "release"
        site = release / "site"
        (site / "assets").mkdir(parents=True)
        for name in public_files:
            if name in legal_files:
                (site / name).write_bytes(legal_files[name])
            elif name != "index.html":
                shutil.copyfile(SOURCE / name, site / name)
        (site / "index.html").write_text(html, encoding="utf-8")
        (release / "Caddyfile.form").write_text(routes, encoding="utf-8")
        release.rename(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Public HTTPS origin of this Caddy listener, including :8443")
    parser.add_argument("--output", type=Path, required=True, help="New release directory outside the repository")
    parser.add_argument("--legal-draft", type=Path, help="Reviewed draft folder containing privacy.html and consent.html")
    parser.add_argument("--approved-legal", type=Path, help="Owner-approved folder containing privacy.html and consent.html")
    parser.add_argument("--consent-version", help="Approved version also configured in FOTOMAG_CONSENT_VERSION")
    options = parser.parse_args()
    print(build_release(options.origin, options.output, options.legal_draft, approved_legal=options.approved_legal,
                        consent_version=options.consent_version))
