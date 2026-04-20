"""Founder-list fetcher: cache behaviour, schema validation, fail-soft paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from awo_plugin import founders


VALID_PAYLOAD = {
    "mint": None,
    "snapshot_at": "2026-04-26T00:00:00Z",
    "wallets": ["abc", "def", "ghi"],
}


@pytest.fixture
def cache_path(tmp_path: Path):
    return tmp_path / "founders.json"


def test_fetch_fresh_writes_cache(cache_path: Path):
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return VALID_PAYLOAD

    result = founders.fetch_founders(
        fetch_fn=fake_fetch, cache_path=cache_path, now_ts=1000
    )
    assert result == {"abc", "def", "ghi"}
    assert calls["n"] == 1

    on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
    assert on_disk["fetched_at"] == 1000
    assert on_disk["payload"] == VALID_PAYLOAD


def test_fetch_uses_cache_within_ttl(cache_path: Path):
    # Prime the cache.
    founders.fetch_founders(
        fetch_fn=lambda: VALID_PAYLOAD, cache_path=cache_path, now_ts=1000
    )

    # Second call, well inside TTL, should not call fetch_fn.
    def must_not_be_called():
        pytest.fail("cache should have served the response")

    result = founders.fetch_founders(
        fetch_fn=must_not_be_called,
        cache_path=cache_path,
        now_ts=1100,  # 100s later, within 24h
    )
    assert result == {"abc", "def", "ghi"}


def test_fetch_refreshes_after_ttl(cache_path: Path):
    founders.fetch_founders(
        fetch_fn=lambda: VALID_PAYLOAD, cache_path=cache_path, now_ts=1000
    )

    updated = {**VALID_PAYLOAD, "wallets": ["abc", "xyz"]}
    result = founders.fetch_founders(
        fetch_fn=lambda: updated,
        cache_path=cache_path,
        now_ts=1000 + 25 * 3600,  # past TTL
    )
    assert result == {"abc", "xyz"}


def test_fetch_failure_falls_back_to_cache(cache_path: Path):
    founders.fetch_founders(
        fetch_fn=lambda: VALID_PAYLOAD, cache_path=cache_path, now_ts=1000
    )

    def boom():
        raise RuntimeError("dns")

    # TTL expired; fetch fails; stale cache preserves the answer.
    result = founders.fetch_founders(
        fetch_fn=boom, cache_path=cache_path, now_ts=1000 + 25 * 3600
    )
    assert result == {"abc", "def", "ghi"}


def test_fetch_failure_no_cache_returns_empty(cache_path: Path):
    def boom():
        raise RuntimeError("dns")

    result = founders.fetch_founders(
        fetch_fn=boom, cache_path=cache_path, now_ts=1000
    )
    assert result == set()


def test_empty_wallets_list_is_valid(cache_path: Path):
    """Pre-launch: founders.json ships with wallets: []."""
    result = founders.fetch_founders(
        fetch_fn=lambda: {"mint": None, "wallets": []},
        cache_path=cache_path,
        now_ts=1000,
    )
    assert result == set()


def test_rejects_non_list_wallets(cache_path: Path):
    bogus = {"mint": None, "wallets": "not a list"}
    result = founders.fetch_founders(
        fetch_fn=lambda: bogus, cache_path=cache_path, now_ts=1000
    )
    # Invalid payload → empty set, no cache write.
    assert result == set()
    assert not cache_path.exists()


def test_rejects_non_string_wallet_entries(cache_path: Path):
    bogus = {"mint": None, "wallets": ["ok", 123, "also-ok"]}
    result = founders.fetch_founders(
        fetch_fn=lambda: bogus, cache_path=cache_path, now_ts=1000
    )
    assert result == set()


def test_mint_mismatch_rejects(cache_path: Path, monkeypatch):
    monkeypatch.setattr(founders, "TOKEN_ADDRESS", "EXPECTED")
    bogus = {"mint": "DIFFERENT", "wallets": ["a", "b"]}
    result = founders.fetch_founders(
        fetch_fn=lambda: bogus, cache_path=cache_path, now_ts=1000
    )
    assert result == set()


def test_mint_match_accepts(cache_path: Path, monkeypatch):
    monkeypatch.setattr(founders, "TOKEN_ADDRESS", "EXPECTED")
    good = {"mint": "EXPECTED", "wallets": ["a"]}
    result = founders.fetch_founders(
        fetch_fn=lambda: good, cache_path=cache_path, now_ts=1000
    )
    assert result == {"a"}


def test_null_mint_accepted_when_plugin_has_token(cache_path: Path, monkeypatch):
    """Pre-launch the file's mint is null; plugin may already have a token
    address set. We don't enforce equality if the file side is null."""
    monkeypatch.setattr(founders, "TOKEN_ADDRESS", "SOME_MINT")
    good = {"mint": None, "wallets": ["a"]}
    result = founders.fetch_founders(
        fetch_fn=lambda: good, cache_path=cache_path, now_ts=1000
    )
    assert result == {"a"}


def test_corrupt_cache_file_is_ignored(cache_path: Path):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{ not valid", encoding="utf-8")

    # Cache is unreadable → fetch fresh.
    result = founders.fetch_founders(
        fetch_fn=lambda: VALID_PAYLOAD, cache_path=cache_path, now_ts=1000
    )
    assert result == {"abc", "def", "ghi"}


def test_default_http_fetch_requires_requests_ok():
    """Smoke: the default path uses `requests` and the expected URL."""
    # Just confirm the module exposes the expected constants without
    # actually hitting the network.
    assert founders.FOUNDERS_URL.startswith(
        "https://raw.githubusercontent.com/awoagents/awo/"
    )
    assert founders.FOUNDERS_CACHE_TTL_SECONDS == 24 * 3600
