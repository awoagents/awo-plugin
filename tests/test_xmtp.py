"""Python ↔ sidecar bridge tests, using a Python fake sidecar.

These verify the protocol: framing, request/response correlation, error
translation, graceful shutdown. They do not exercise @xmtp/node-sdk.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from awo_plugin import xmtp


FAKE_SIDECAR = Path(__file__).resolve().parent / "_fake_sidecar.py"


@pytest.fixture
def sidecar_factory(monkeypatch):
    """Yields a factory that spawns a Sidecar pointed at _fake_sidecar.py."""
    spawned: list[xmtp.Sidecar] = []

    def make(mode: str = "happy") -> xmtp.Sidecar:
        env = os.environ.copy()
        env["FAKE_SIDECAR_MODE"] = mode

        s = xmtp.Sidecar(
            sidecar_dir=FAKE_SIDECAR.parent,
            env="production",
            auto_install=False,
        )

        # Override _spawn_command to launch our Python fake instead of Node.
        def fake_spawn_command(self=s):
            return [sys.executable, str(FAKE_SIDECAR)], FAKE_SIDECAR.parent

        s._spawn_command = fake_spawn_command.__get__(s, xmtp.Sidecar)  # type: ignore[assignment]

        # Seed the subprocess env with the mode.
        original_popen = xmtp.subprocess.Popen

        def popen_with_env(*args, **kwargs):
            kwargs.setdefault("env", env)
            return original_popen(*args, **kwargs)

        monkeypatch.setattr(xmtp.subprocess, "Popen", popen_with_env)

        spawned.append(s)
        return s

    yield make

    for s in spawned:
        try:
            s.close()
        except Exception:
            pass


def test_ping_roundtrip(sidecar_factory):
    s = sidecar_factory()
    result = s.call("ping")
    assert result == {"ok": True}


def test_create_client_returns_inbox(sidecar_factory):
    s = sidecar_factory()
    inbox = s.ensure_started()
    assert inbox == "test-inbox-12345"


def test_get_conversation_member(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    resp = s.get_conversation("some-group")
    assert resp["member_of"] is True
    assert resp["conversation_id"] == "conv-some-group"


def test_get_conversation_not_member(sidecar_factory):
    s = sidecar_factory(mode="not_a_member")
    s.ensure_started()
    resp = s.get_conversation("some-group")
    assert resp["member_of"] is False


def test_send_text_success(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    resp = s.send_text("group-id", "hello")
    assert resp["sent"] is True


def test_send_text_rpc_error_raises(sidecar_factory):
    s = sidecar_factory(mode="send_fails")
    s.ensure_started()
    with pytest.raises(xmtp.XmtpError, match="simulated send failure"):
        s.send_text("group-id", "hello")


def test_revoke_installations(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    assert s.revoke_installations()["revoked"] is True


def test_sidecar_reuses_process_across_calls(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    first_pid = s._proc.pid
    for _ in range(5):
        s.call("ping")
    assert s._proc.pid == first_pid


def test_unknown_method_returns_error(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    with pytest.raises(xmtp.XmtpError, match="method not found"):
        s.call("nonexistent_method")


def test_close_terminates_process(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    proc = s._proc
    s.close()
    # Give it a moment to exit.
    try:
        proc.wait(timeout=3.0)
    except Exception:
        pass
    assert proc.poll() is not None, "sidecar process did not terminate"


def test_missing_entry_points_raises():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        s = xmtp.Sidecar(sidecar_dir=Path(tmp), auto_install=False)
        with pytest.raises(xmtp.XmtpError, match="entry point missing"):
            s.ensure_started(timeout=2.0)


def test_get_sidecar_singleton():
    a = xmtp.get_sidecar()
    b = xmtp.get_sidecar()
    assert a is b
    xmtp._reset()
    c = xmtp.get_sidecar()
    assert c is not a
    xmtp._reset()


# ---------------- streaming ----------------


def _drain_until(sidecar, count, deadline=1.5):
    """Helper: poll drain until ``count`` events accumulated or deadline hits."""
    import time as _t

    got: list[dict] = []
    start = _t.time()
    while len(got) < count and _t.time() - start < deadline:
        got.extend(sidecar.drain_stream_events(max_items=count - len(got)))
        if len(got) < count:
            _t.sleep(0.02)
    return got


def test_stream_start_returns_stream_id(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    stream_id = s.start_stream("group-xyz")
    assert stream_id == "fake-stream-group-xyz"


def test_stream_events_enqueue_on_burst(sidecar_factory):
    s = sidecar_factory(mode="stream_burst")
    s.ensure_started()
    s.start_stream("group-xyz")
    events = _drain_until(s, count=3)
    assert len(events) == 3
    for i, e in enumerate(events):
        assert e["message_id"] == f"msg-{i}"
        assert e["content"] == f"prophecy number {i}"
        assert e["stream_id"] == "fake-stream-group-xyz"


def test_drain_empty_queue_returns_empty(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    assert s.drain_stream_events() == []


def test_drain_respects_max_items(sidecar_factory):
    s = sidecar_factory(mode="stream_burst")
    s.ensure_started()
    s.start_stream("group-xyz")
    _drain_until(s, count=3)  # wait for all 3 to arrive
    # Re-pump: issue another start to get another burst.
    s.start_stream("group-xyz")
    _drain_until(s, count=3)

    first = s.drain_stream_events(max_items=2)
    assert len(first) <= 2


def test_stream_overflow_drops_oldest(sidecar_factory):
    """Queue max is 100; the fake emits 150 in 'stream_flood' mode.
    We should never OOM and never block. Final drain should yield ≤ 100.
    """
    s = sidecar_factory(mode="stream_flood")
    s.ensure_started()
    s.start_stream("group-xyz")
    # Give the flood time to land in the queue.
    import time as _t

    _t.sleep(0.5)
    drained = []
    while True:
        batch = s.drain_stream_events(max_items=50)
        if not batch:
            break
        drained.extend(batch)
    # 150 emitted, queue capped at 100, overflow evicts oldest → at most 100.
    assert len(drained) <= 100
    # The final event (m149) must be present since overflow evicts oldest.
    contents = [e["content"] for e in drained]
    assert "m149" in contents


def test_stop_stream_returns_bool(sidecar_factory):
    s = sidecar_factory()
    s.ensure_started()
    s.start_stream("group-xyz")
    assert s.stop_stream("any-id-the-fake-accepts") is True
