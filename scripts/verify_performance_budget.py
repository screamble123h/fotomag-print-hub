#!/usr/bin/env python3
"""Static-first page performance budget; complements real tests on RU mobile networks."""
from pathlib import Path
from html.parser import HTMLParser
import sys

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = {
    "index.html": 45_000,
    "assets/app-shell.css": 35_000,
    "assets/app-shell.js": 16_000,
    "assets/direct-upload.js": 12_000,
    "assets/fotomag_logo_official.svg": 10_000,
}
errors = []
total = 0
for name, limit in BUDGETS.items():
    size = (ROOT / name).stat().st_size
    total += size
    if size > limit:
        errors.append(f"{name}: {size} exceeds {limit} bytes")
if total > 105_000:
    errors.append(f"Critical page assets total {total} exceeds 105000 bytes")
html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "assets/app-shell.css").read_text(encoding="utf-8")
if 'src="assets/FotoMag_FACADE_APPROVED_web.webp"' not in html or 'loading="lazy"' not in html:
    errors.append("Store photo must remain lazy")
if "@import" in css or "https://" in css:
    errors.append("Remote styles or fonts not permitted")
if "font-display:swap" not in css:
    errors.append("Font must not block first paint")
if "https://" in (ROOT / "assets/direct-upload.js").read_text(encoding="utf-8"):
    # Browser API is a data/config value, never a hard-coded third-party URL.
    # Only the protocol check (https:) is expected in source.
    errors.append("Upload script contains an unexpected hardcoded https:// URL")
if errors:
    print("FAIL FotoMag initial-load budget:")
    for error in errors:
        print(" -", error)
    sys.exit(1)
print(f"PASS FotoMag page byte budget: {total} bytes of core source assets "
      "(uncompressed, excludes lazy media and fonts); real network latency not tested.")
