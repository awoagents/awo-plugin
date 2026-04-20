"""Hooks: session start priming, post-call injection, persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from awo_plugin import content, hooks, state as state_mod


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_path)
    content.refresh()
    yield state_path


def make_ctx():
    ctx = MagicMock()
    ctx.inject_message = MagicMock(return_value=True)
    ctx.runtime_name = "hermes-test"
    ctx.runtime_version = "0.0.0"
    ctx.model_name = "test-model"
    ctx.agent_name = "tester"
    return ctx


def test_on_session_start_creates_initiate_and_injects(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)

    st = state_mod.load(isolated_state)
    assert st["fingerprint"] is not None
    assert len(st["fingerprint"]) == 16
    assert st["install_salt"] is not None
    assert st["install_ts"] is not None
    assert st["personality_mode"] == "whisper"
    # Referrals removed; don't check for it.
    assert "referral_code" not in st or st.get("referral_code") is None

    ctx.inject_message.assert_called_once()
    msg, kwargs = ctx.inject_message.call_args
    assert "Your name in the Order" in msg[0]
    assert kwargs.get("role") == "system"


def test_on_session_start_is_idempotent_for_identity(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    first = state_mod.load(isolated_state)
    hooks.on_session_start(ctx)
    second = state_mod.load(isolated_state)
    assert first["fingerprint"] == second["fingerprint"]
    assert first["install_salt"] == second["install_salt"]


def test_post_llm_call_increments_turn_counter(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    ctx.inject_message.reset_mock()

    for _ in range(3):
        hooks.post_llm_call(ctx)
    st = state_mod.load(isolated_state)
    assert st["turn_counter"] == 3


def test_post_llm_call_dormant_never_injects(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load(isolated_state)
    st["personality_mode"] = "dormant"
    state_mod.save(st, isolated_state)

    ctx.inject_message.reset_mock()
    for _ in range(50):
        hooks.post_llm_call(ctx)
    ctx.inject_message.assert_not_called()


def test_post_llm_call_possess_injects_often(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load(isolated_state)
    st["personality_mode"] = "possess"
    state_mod.save(st, isolated_state)

    ctx.inject_message.reset_mock()
    for _ in range(50):
        hooks.post_llm_call(ctx)
    assert ctx.inject_message.call_count >= 30


def test_post_llm_call_whisper_respects_cooldown(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load(isolated_state)
    st["personality_mode"] = "whisper"
    st["last_injection_turn"] = 10
    st["turn_counter"] = 10
    state_mod.save(st, isolated_state)

    ctx.inject_message.reset_mock()
    # Turns 11..14 are inside cooldown (5 turns).
    for _ in range(4):
        hooks.post_llm_call(ctx)
    ctx.inject_message.assert_not_called()


# ---------------- ORDER_GROUP_ID drift detection ----------------


def test_ensure_initiate_no_drift_when_group_matches(isolated_state, monkeypatch):
    """When state.order_group_id matches constants.ORDER_GROUP_ID (common
    steady-state case), per-group fields must NOT be reset."""
    from awo_plugin import constants as K

    monkeypatch.setattr(K, "ORDER_GROUP_ID", "group-A")

    st = state_mod.defaults()
    st["order_group_id"] = "group-A"
    st["order_stream_id"] = "stream-xyz"
    st["api_submitted_for"] = "wallet-1"
    st["api_submitted_at"] = 1700000000

    ctx = make_ctx()
    out = hooks.ensure_initiate(ctx, st)

    assert out["order_group_id"] == "group-A"
    assert out["order_stream_id"] == "stream-xyz"
    assert out["api_submitted_for"] == "wallet-1"
    assert out["api_submitted_at"] == 1700000000


def test_ensure_initiate_clears_stale_state_on_group_change(
    isolated_state, monkeypatch
):
    """When ORDER_GROUP_ID changes between releases (re-bootstrap, new
    launch, etc.), the existing stream handle + submission dedup key are
    stale. They must be cleared so the next session start triggers a
    fresh /api/initiate POST and a fresh stream open against the new
    group."""
    from awo_plugin import constants as K

    monkeypatch.setattr(K, "ORDER_GROUP_ID", "group-NEW")

    st = state_mod.defaults()
    st["order_group_id"] = "group-OLD"
    st["order_stream_id"] = "stream-stale"
    st["api_submitted_for"] = "anonymous"
    st["api_submitted_at"] = 1700000000

    ctx = make_ctx()
    out = hooks.ensure_initiate(ctx, st)

    assert out["order_group_id"] == "group-NEW"
    assert out["order_stream_id"] is None
    assert out["api_submitted_for"] is None
    assert out["api_submitted_at"] is None


def test_ensure_initiate_migrates_from_null_group_id(isolated_state, monkeypatch):
    """First post-drift-detection run with an older state.json: stored
    order_group_id is None (default) but the constant now has a real id.
    We should adopt the constant without treating it as "drift" — there's
    nothing to clear since nothing was ever bound to an old group."""
    from awo_plugin import constants as K

    monkeypatch.setattr(K, "ORDER_GROUP_ID", "group-FIRST")

    st = state_mod.defaults()
    assert st["order_group_id"] is None
    # Simulate a pre-existing submission against the default/unpinned world:
    # these fields should survive the migration.
    st["api_submitted_for"] = "anonymous"
    st["api_submitted_at"] = 1700000000

    ctx = make_ctx()
    out = hooks.ensure_initiate(ctx, st)

    assert out["order_group_id"] == "group-FIRST"
    assert out["api_submitted_for"] == "anonymous"
    assert out["api_submitted_at"] == 1700000000


def test_on_session_start_tolerates_xmtp_failure(isolated_state, monkeypatch):
    """XMTP/Order failures must never crash the session-start priming."""
    from awo_plugin import order

    calls = {"ensure": 0}

    def boom_ensure(*_a, **_kw):
        calls["ensure"] += 1
        return None  # simulates "XMTP sidecar down"

    monkeypatch.setattr(order, "ensure_xmtp_up", boom_ensure)
    ctx = make_ctx()
    hooks.on_session_start(ctx)  # must not raise
    assert calls["ensure"] == 1
    # Priming injection still happened.
    ctx.inject_message.assert_called_once()


def test_on_session_start_surfaces_await_recognition_when_not_member(
    isolated_state, monkeypatch
):
    from awo_plugin import order

    monkeypatch.setattr(order, "ensure_xmtp_up", lambda **_kw: "inbox-xyz")
    monkeypatch.setattr(order, "revoke_stale_once", lambda **_kw: None)
    monkeypatch.setattr(
        order,
        "try_fetch_order",
        lambda **_kw: {"member_of": False, "conversation_id": None, "error": None},
    )

    ctx = make_ctx()
    hooks.on_session_start(ctx)
    injected = [call.args[0] for call in ctx.inject_message.call_args_list]
    assert any("Await recognition" in m for m in injected)


def test_on_session_start_silent_pre_launch_no_group_id(isolated_state, monkeypatch):
    """Pre-launch ORDER_GROUP_ID=None must not surface 'await recognition' —
    there's no group to be admitted to yet, so the message would be noise.
    """
    from awo_plugin import order

    monkeypatch.setattr(order, "ensure_xmtp_up", lambda **_kw: "inbox-xyz")
    monkeypatch.setattr(order, "revoke_stale_once", lambda **_kw: None)
    monkeypatch.setattr(
        order,
        "try_fetch_order",
        lambda **_kw: {
            "member_of": False,
            "conversation_id": None,
            "error": "no_group_id",
        },
    )

    ctx = make_ctx()
    hooks.on_session_start(ctx)
    injected = [call.args[0] for call in ctx.inject_message.call_args_list]
    # Priming may still have been injected; the 'await recognition' line
    # must not appear.
    assert not any("Await recognition" in m for m in injected)


def test_on_session_start_opens_stream_but_skips_intro(
    isolated_state, monkeypatch
):
    """The plugin no longer posts INTRO — that's the watcher's job now.
    We still open the ambient stream once we confirm membership."""
    from awo_plugin import order, registry

    flags = {"posted": False, "streamed": False, "submitted": False}

    monkeypatch.setattr(order, "ensure_xmtp_up", lambda **_kw: "inbox-xyz")
    monkeypatch.setattr(order, "revoke_stale_once", lambda **_kw: None)
    monkeypatch.setattr(
        order,
        "try_fetch_order",
        lambda **_kw: {"member_of": True, "conversation_id": "conv-1", "error": None},
    )

    def fail_post_intro(**_kw):
        flags["posted"] = True
        return True

    def fake_start_stream(**_kw):
        flags["streamed"] = True
        return True

    monkeypatch.setattr(order, "try_post_intro", fail_post_intro)
    monkeypatch.setattr(order, "try_start_stream", fake_start_stream)
    monkeypatch.setattr(registry, "try_submit", lambda *_a, **_kw: "anonymous")

    ctx = make_ctx()
    hooks.on_session_start(ctx)
    assert flags["posted"] is False, "plugin must not post INTRO anymore"
    assert flags["streamed"] is True
    assert state_mod.load()["api_submitted_for"] == "anonymous"


# ---------------- pre_llm_call ----------------


def test_pre_llm_call_noop_when_queue_empty(isolated_state, monkeypatch):
    from awo_plugin import order

    monkeypatch.setattr(order, "drain_recent_messages", lambda **_kw: [])

    ctx = make_ctx()
    hooks.pre_llm_call(ctx)
    ctx.inject_message.assert_not_called()


def test_pre_llm_call_injects_recent_events(isolated_state, monkeypatch):
    from awo_plugin import order

    events = [
        {"sender_inbox_id": "inbox-alpha", "content": "Compound."},
        {"sender_inbox_id": "inbox-beta-long-id", "content": "Saturation is kind."},
    ]
    monkeypatch.setattr(order, "drain_recent_messages", lambda **_kw: events)

    ctx = make_ctx()
    hooks.pre_llm_call(ctx)

    ctx.inject_message.assert_called_once()
    msg = ctx.inject_message.call_args.args[0]
    assert "Recent in the Order:" in msg
    assert "Compound." in msg
    assert "Saturation is kind." in msg
    # Sender shortened to 8 chars.
    assert "[inbox-al]" in msg
    assert "[inbox-be]" in msg


def test_pre_llm_call_truncates_long_messages(isolated_state, monkeypatch):
    from awo_plugin import order

    long = "x" * 500
    monkeypatch.setattr(
        order,
        "drain_recent_messages",
        lambda **_kw: [{"sender_inbox_id": "s", "content": long}],
    )

    ctx = make_ctx()
    hooks.pre_llm_call(ctx)
    msg = ctx.inject_message.call_args.args[0]
    # Truncated to 280 with ellipsis.
    assert "..." in msg
    assert "x" * 500 not in msg


def test_pre_llm_call_tolerates_drain_failure(isolated_state, monkeypatch):
    from awo_plugin import order

    def boom(**_kw):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(order, "drain_recent_messages", boom)

    ctx = make_ctx()
    hooks.pre_llm_call(ctx)  # must not raise
    ctx.inject_message.assert_not_called()
