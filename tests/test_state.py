"""Direct coverage for ``awo_plugin.state``: defaults, I/O round-trip, atomic
writes, merge of older on-disk schemas, ISO timestamp shape.

Most state behaviour is exercised transitively by ``test_hooks.py`` and
``test_tools.py``. This file is the dedicated surface for the module.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from awo_plugin import state


def test_defaults_returns_fresh_copy():
    a = state.defaults()
    b = state.defaults()
    assert a == b
    a["fingerprint"] = "mutated"
    assert b["fingerprint"] is None  # not shared


def test_load_missing_returns_defaults(tmp_path: Path):
    p = tmp_path / "state.json"
    loaded = state.load(p)
    assert loaded == state.defaults()


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "state.json"
    snapshot = state.defaults()
    snapshot["fingerprint"] = "abc1234567890def"
    snapshot["install_salt"] = "deadbeef" * 4
    snapshot["install_ts"] = "2026-04-19T10:00:00Z"
    snapshot["turn_counter"] = 5
    snapshot["wallet"] = {"address": "So11111111111111111111111111111111111111112", "bound_ts": "2026-04-19T10:05:00Z"}
    state.save(snapshot, p)

    loaded = state.load(p)
    assert loaded == snapshot


def test_defaults_no_referral_fields():
    """Referrals were removed — fingerprint is the sole identity."""
    d = state.defaults()
    assert "referral_code" not in d
    assert "upline" not in d


def test_load_merges_partial_onto_defaults(tmp_path: Path):
    """Older state files missing new keys load fine — new keys take defaults."""
    p = tmp_path / "state.json"
    partial = {"fingerprint": "legacy", "personality_mode": "possess"}
    p.write_text(json.dumps(partial), encoding="utf-8")

    loaded = state.load(p)
    # Old fields preserved.
    assert loaded["fingerprint"] == "legacy"
    assert loaded["personality_mode"] == "possess"
    # New fields present at default values.
    assert loaded["xmtp_migrated"] is False
    assert loaded["turn_counter"] == 0
    assert loaded["config"] == {}


def test_save_is_atomic_no_tmp_leftovers(tmp_path: Path):
    p = tmp_path / "state.json"
    state.save({"fingerprint": "xyz"}, p)
    state.save({"fingerprint": "abc"}, p)

    # After two successful saves, only the final file remains — no *.tmp.
    siblings = list(p.parent.iterdir())
    assert siblings == [p], f"unexpected siblings: {siblings}"
    assert state.load(p)["fingerprint"] == "abc"


def test_save_preserves_existing_file_on_write_failure(tmp_path: Path, monkeypatch):
    """If the temp-write step raises, the original file stays intact."""
    p = tmp_path / "state.json"
    state.save({"fingerprint": "original"}, p)

    # Force json.dump to blow up during the next save.
    original_dump = state.json.dump

    def exploding_dump(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(state.json, "dump", exploding_dump)

    with pytest.raises(RuntimeError, match="disk full"):
        state.save({"fingerprint": "replacement"}, p)

    # Restore + verify untouched.
    monkeypatch.setattr(state.json, "dump", original_dump)
    assert state.load(p)["fingerprint"] == "original"

    # And no tmp file was left behind.
    siblings = list(p.parent.iterdir())
    assert siblings == [p]


def test_save_creates_parent_directories(tmp_path: Path):
    p = tmp_path / "nested" / "dir" / "state.json"
    state.save({"fingerprint": "nested"}, p)
    assert p.exists()
    assert state.load(p)["fingerprint"] == "nested"


def test_now_iso_format():
    ts = state.now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), ts


def test_save_pretty_prints_with_stable_keys(tmp_path: Path):
    """state.json is hand-readable and diff-friendly."""
    p = tmp_path / "state.json"
    state.save({"fingerprint": "abc", "turn_counter": 3}, p)
    text = p.read_text(encoding="utf-8")
    # Indent + sorted keys.
    assert "  " in text
    # Ends with a trailing newline.
    assert text.endswith("\n")
    # Keys sorted: fingerprint before turn_counter.
    assert text.index("fingerprint") < text.index("turn_counter")


def test_ensure_state_dir_creates_path(tmp_path: Path):
    target = tmp_path / "a" / "b" / "c"
    state.ensure_state_dir(target)
    assert target.exists() and target.is_dir()


def test_load_rejects_corrupt_json(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        state.load(p)
