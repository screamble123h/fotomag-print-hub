"""Prepare a private, disabled-by-default FotoMag VPS configuration.

No Docker containers, ports, client data, domains or paid resources are changed.
Only --write on a configured Linux server creates a *new* .env with mode=disabled.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
ALLOWED_SITE = "https://screamble123h.github.io"


def validate_domain(domain: str) -> str:
    domain = domain.strip().lower()
    if len(domain) > 253 or domain in ("files.example.ru", "localhost") or domain.endswith(
        (".trycloudflare.com", ".github.io")
    ):
        raise ValueError("Only a real dedicated DNS hostname is allowed")
    parts = domain.split(".")
    if len(parts) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
        for part in parts
    ):
        raise ValueError("Invalid DNS hostname")
    if not any(c.isalpha() for c in parts[-1]):
        raise ValueError("IP addresses are not valid DNS domains")
    return domain


def make_env(example: str, domain: str, token: str) -> str:
    domain = validate_domain(domain)
    if len(token) < 48 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("Random token required")
    required = {
        "FOTOMAG_API_DOMAIN": domain,
        "FOTOMAG_SITE_ORIGIN": ALLOWED_SITE,
        "FOTOMAG_AGENT_TOKEN": token,
        "FOTOMAG_UPLOAD_MODE": "disabled",
    }
    lines = []
    covered = set()
    for line in example.splitlines():
        key = line.split("=", 1)[0].strip()
        if key in required:
            if key in covered:
                raise ValueError("Duplicate environment key")
            line = key + "=" + required[key]
            covered.add(key)
        lines.append(line)
    if set(required) - covered:
        raise ValueError("Missing essential template keys")
    return "\n".join(lines) + "\n"


def new_private_file(path: Path, data: str) -> None:
    """Exclusive create, never overwrite: 0600 on Linux VPS."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="Actual HTTPS API hostname")
    parser.add_argument("--write", action="store_true",
                        help="Explicitly write NEW private disabled .env, no deployment")
    opts = parser.parse_args()
    try:
        domain = validate_domain(opts.domain)
    except ValueError as exc:
        print("FOTOMAG_BOOTSTRAP_BLOCKED:", str(exc), file=sys.stderr)
        return 2
    if not opts.write:
        print("FOTOMAG_DRY_RUN_OK:", domain)
        print("No files written and no server started. Run with --write only on chosen Russian VPS.")
        return 0
    if os.name != "posix" or not Path("/proc/meminfo").exists():
        print("FOTOMAG_BOOTSTRAP_BLOCKED: use a Linux VPS in Russia", file=sys.stderr)
        return 2
    target = FOLDER / ".env"
    if target.exists():
        print("FOTOMAG_BOOTSTRAP_BLOCKED: .env already exists; no overwrite", file=sys.stderr)
        return 2
    try:
        template = (FOLDER / ".env.example").read_text(encoding="utf-8")
        data = make_env(template, domain, secrets.token_urlsafe(48))
        new_private_file(target, data)
    except (OSError, ValueError) as exc:
        print("FOTOMAG_BOOTSTRAP_FAILED:", type(exc).__name__, file=sys.stderr)
        return 2
    print("FOTOMAG_PRIVATE_CONFIG_CREATED; mode=disabled; token never printed")
    print("NEXT: complete legal, AV, server hardening, backup and mobile tests before activation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
