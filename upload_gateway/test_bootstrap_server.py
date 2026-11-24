"""Safe no-network tests of Russian VPS bootstrap; creates only temp config."""
import os
import pytest
from upload_gateway.bootstrap_server import validate_domain, make_env, new_private_file

EXAMPLE = """FOTOMAG_API_DOMAIN=files.example.ru
FOTOMAG_SITE_ORIGIN=https://screamble123h.github.io
FOTOMAG_AGENT_TOKEN=REPLACE_WITH_random_64_character_secret_generated_on_server
FOTOMAG_UPLOAD_MODE=disabled
FOTOMAG_DATA_DIR=/data
"""


@pytest.mark.parametrize("bad", [
    "files.example.ru", "localhost", "public.trycloudflare.com",
    "screamble123h.github.io", "127.0.0.1",
    "https://files.fotomag.ru", "../files.fotomag.ru",
    "invalid_domain.example", "files.example.ru:443",
])
def test_denies_placeholders_and_temporary_tunnels(bad):
    with pytest.raises(ValueError):
        validate_domain(bad)


def test_disabled_private_config_has_real_domain_but_no_public_activation():
    data = make_env(EXAMPLE, "uploads.fotomag.ru", "Q" * 64)
    assert "FOTOMAG_API_DOMAIN=uploads.fotomag.ru" in data
    assert "FOTOMAG_UPLOAD_MODE=disabled" in data
    assert "FOTOMAG_SITE_ORIGIN=https://screamble123h.github.io" in data
    assert "FOTOMAG_AGENT_TOKEN=" + ("Q" * 64) in data
    assert "files.example.ru" not in data
    assert "REPLACE_WITH" not in data


def test_exclusive_config_creation_no_overwrites(tmp_path):
    conf = tmp_path / ".env"
    new_private_file(conf, "SAFE_CONFIG_NO_SECRETS\n")
    with pytest.raises(FileExistsError):
        new_private_file(conf, "DONT_OVERWRITE\n")
    assert conf.read_text("utf-8") == "SAFE_CONFIG_NO_SECRETS\n"
    if os.name == "posix":
        assert conf.stat().st_mode & 0o077 == 0
