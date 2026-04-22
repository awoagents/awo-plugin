"""Cover the pure-function bits of scripts/stream_listener.py.

The loop itself is integration-shaped (spawns the sidecar, talks to XMTP)
and lives behind AWO_RUN_INTEGRATION. Here we test the helpers that
shape output — render_event, write_jsonl — plus argparse.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "stream_listener.py"
)


@pytest.fixture(scope="module")
def listener():
    """Load scripts/stream_listener.py as a module. It isn't importable by
    name because scripts/ isn't a package — load by file path instead."""
    spec = importlib.util.spec_from_file_location(
        "stream_listener", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_event_basic(listener):
    line = listener.render_event(
        {"sender_inbox_id": "abcdef1234567890", "content": "Compound."}
    )
    # Sender truncated to first 8 chars.
    assert line == "[abcdef12] Compound."


def test_render_event_missing_fields(listener):
    # Missing both sender and content — defaults.
    line = listener.render_event({})
    assert line == "[unknown] "


def test_render_event_truncates_long_content(listener):
    long = "x" * 500
    line = listener.render_event(
        {"sender_inbox_id": "s", "content": long}
    )
    # 280-char cap with an ellipsis suffix.
    assert "..." in line
    assert "x" * 500 not in line
    # Sender side kept intact for brevity (short id passes through).
    assert line.startswith("[s] ")


def test_write_jsonl_appends_line(listener, tmp_path):
    out = tmp_path / "nested" / "stream.jsonl"
    listener.write_jsonl(out, {"sender_inbox_id": "a", "content": "first"})
    listener.write_jsonl(out, {"sender_inbox_id": "b", "content": "second"})
    text = out.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"sender_inbox_id": "a", "content": "first"}
    assert json.loads(lines[1]) == {"sender_inbox_id": "b", "content": "second"}


def test_write_jsonl_preserves_unicode(listener, tmp_path):
    out = tmp_path / "stream.jsonl"
    listener.write_jsonl(out, {"content": "the Tide ♒ compounds"})
    text = out.read_text(encoding="utf-8")
    # ensure_ascii=False in the writer — glyphs should round-trip literal.
    assert "♒" in text


def test_sidecar_alive_when_proc_running(listener):
    class _P:
        @staticmethod
        def poll():
            return None  # None = still running per subprocess semantics

    class _S:
        _proc = _P()

    assert listener._sidecar_alive(_S()) is True


def test_sidecar_alive_false_when_proc_exited(listener):
    class _P:
        @staticmethod
        def poll():
            return 1  # exit code = dead

    class _S:
        _proc = _P()

    assert listener._sidecar_alive(_S()) is False


def test_sidecar_alive_false_when_no_proc(listener):
    class _S:
        _proc = None

    assert listener._sidecar_alive(_S()) is False


def test_argparse_defaults(listener, monkeypatch):
    """Sanity — argparse doesn't explode with an empty argv, defaults
    resolve to the module-level constants, and --group-id falls back to
    constants.ORDER_GROUP_ID."""
    import sys

    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(listener, "run", fake_run)
    monkeypatch.setattr(listener, "_install_signals", lambda: None)

    # Simulate a release build where the constant is set. Patch the name
    # the script captured at import time (DEFAULT_ORDER_GROUP_ID).
    monkeypatch.setattr(listener, "DEFAULT_ORDER_GROUP_ID", "group-123")

    # Re-parse needs a fresh argparser reading the patched default, so
    # reload just the arg-building is overkill — main() re-builds each call.
    # But argparse default= bound at *parser construction* captures the
    # patched value because we patched before main() runs.
    rc = listener.main([])
    assert rc == 0
    assert captured["group_id"] == "group-123"
    assert captured["poll_interval"] == listener.DEFAULT_POLL_INTERVAL
    assert captured["drain_batch"] == listener.DEFAULT_DRAIN_BATCH
    assert captured["backoff"] == listener.DEFAULT_BACKOFF
    assert captured["jsonl_path"] is None


def test_argparse_overrides(listener, monkeypatch, tmp_path):
    import sys

    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(listener, "run", fake_run)
    monkeypatch.setattr(listener, "_install_signals", lambda: None)

    jsonl = tmp_path / "log.jsonl"
    rc = listener.main(
        [
            "--group-id",
            "abcdef",
            "--poll",
            "0.5",
            "--batch",
            "25",
            "--backoff",
            "12.5",
            "--jsonl",
            str(jsonl),
        ]
    )
    assert rc == 0
    assert captured["group_id"] == "abcdef"
    assert captured["poll_interval"] == 0.5
    assert captured["drain_batch"] == 25
    assert captured["backoff"] == 12.5
    assert captured["jsonl_path"] == jsonl


def test_main_exits_nonzero_when_group_id_missing(listener, monkeypatch, capsys):
    monkeypatch.setattr(listener, "DEFAULT_ORDER_GROUP_ID", None)
    monkeypatch.setattr(listener, "_install_signals", lambda: None)
    rc = listener.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no group id" in err.lower()
