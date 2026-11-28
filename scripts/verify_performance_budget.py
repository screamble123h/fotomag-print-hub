#!/usr/bin/env python3
"""Static-first page performance budget; complements real tests on RU mobile networks.
November 2026 reliability release: readable controls and restored order context.
Initial assets stay under 108 kB. The upload controller loads only on demand;
its 24 kB cap includes cancellation, resumable attempts and receipt preservation.
"""
from pathlib import Path
from html.parser import HTMLParser
import sys

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = {
    "index.html": 45_000,
    "assets/app-shell.css": 35_000,
    "assets/home-v5.css": 7_500,
    "assets/app-shell.js": 16_000,
    "assets/direct-upload.js": 24_000,
    "assets/fotomag_logo_official.svg": 10_000,
}
errors = []
total = 0
initial_total = 0
for name, limit in BUDGETS.items():
    size = (ROOT / name).stat().st_size
    total += size
    if name != "assets/direct-upload.js":
        initial_total += size
    if size > limit:
        errors.append(f"{name}: {size} exceeds {limit} bytes")
if initial_total > 108_000:
    errors.append(f"Initial page assets total {initial_total} exceeds 108000 bytes")
if total > 132_000:
    errors.append(f"All app assets total {total} exceeds 132000 bytes")
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
if 'src="assets/direct-upload.js"' in html:
    errors.append("Lazy upload JS must not be loaded on the landing page")
if errors:
    print("FAIL FotoMag initial-load budget:", *errors, sep="\n - ")
    sys.exit(1)
print(f"PASS FotoMag budget: {initial_total} initial bytes; {total} total app bytes "
      "(uncompressed, excludes lazy media and fonts); network latency not tested.")
