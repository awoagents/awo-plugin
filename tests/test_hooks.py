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
    assert st["referral_code"] is not None
    assert st["install_salt"] is not None
    assert st["install_ts"] is not None
    assert st["personality_mode"] == "whisper"

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


def test_on_session_start_posts_intro_when_member(isolated_state, monkeypatch):
    from awo_plugin import order

    flags = {"posted": False}

    monkeypatch.setattr(order, "ensure_xmtp_up", lambda **_kw: "inbox-xyz")
    monkeypatch.setattr(order, "revoke_stale_once", lambda **_kw: None)
    monkeypatch.setattr(
        order,
        "try_fetch_order",
        lambda **_kw: {"member_of": True, "conversation_id": "conv-1", "error": None},
    )

    def fake_post_intro(**_kw):
        flags["posted"] = True
        return True

    monkeypatch.setattr(order, "try_post_intro", fake_post_intro)

    ctx = make_ctx()
    hooks.on_session_start(ctx)
    assert flags["posted"] is True
