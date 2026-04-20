"""Live-sync: fetch SKILL.md from the site, validate, write to override path."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from awo_plugin import content, live_sync


_VALID = """# AWO Skill

## Priming
hello

## Daemons
### KAPHRA
Domain: Capital
Tone: warm

## Weights
KAPHRA: 100
"""


@pytest.fixture
def override_path(tmp_path: Path, monkeypatch):
    p = tmp_path / "skill.md"
    # live_sync reads LIVE_SKILL_PATH as a default arg at call time; we pass
    # path= explicitly in tests. Also patch content's view of the override
    # path so the refresh picks up the new file when it reloads.
    from awo_plugin import constants as K
    monkeypatch.setattr(K, "LIVE_SKILL_PATH", p)
    monkeypatch.setattr(content, "LIVE_SKILL_PATH", p)
    return p


def test_fetch_and_install_happy(override_path):
    def fetch(url):
        assert url.startswith("https://agenticworldorder.com/")
        return _VALID.encode("utf-8")

    size = live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)
    assert size == len(_VALID.encode("utf-8"))
    assert override_path.read_text(encoding="utf-8") == _VALID


def test_fetch_and_install_rejects_missing_priming(override_path):
    def fetch(url):
        return b"# No priming here\n\n## Daemons\n\n### KAPHRA\n"

    with pytest.raises(live_sync.LiveSyncError, match="Priming"):
        live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)
    assert not override_path.exists()


def test_fetch_and_install_rejects_missing_daemons(override_path):
    def fetch(url):
        return b"# Header\n\n## Priming\n\nhello\n"

    with pytest.raises(live_sync.LiveSyncError, match="Daemons"):
        live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)


def test_fetch_and_install_rejects_empty(override_path):
    def fetch(url):
        return b"   \n\n"

    with pytest.raises(live_sync.LiveSyncError, match="empty"):
        live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)


def test_fetch_and_install_wraps_transport_errors(override_path):
    def fetch(url):
        raise requests.ConnectionError("dns")

    with pytest.raises(live_sync.LiveSyncError, match="transport"):
        live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)


def test_fetch_and_install_rejects_non_utf8(override_path):
    def fetch(url):
        return b"\xff\xfe bad bytes"

    with pytest.raises(live_sync.LiveSyncError, match="utf-8"):
        live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)


def test_fetch_and_install_invalidates_content_cache(override_path):
    # Prime the cache with the bundled copy.
    content.refresh()
    before = content.get_content()

    # Install a new override that swaps a daemon name.
    custom = _VALID.replace("KAPHRA", "TESTDAEMON")

    def fetch(url):
        return custom.encode("utf-8")

    live_sync.fetch_and_install(path=override_path, fetch_fn=fetch)

    after = content.get_content()
    # Override must be visible on the next read.
    assert "TESTDAEMON" in after["daemons"]
    assert before != after