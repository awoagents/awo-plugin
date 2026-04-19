"""Order-group orchestration — best-effort wrappers around xmtp + templates.

All tests use a mocked Sidecar (``MagicMock``) so nothing touches a real
sidecar process.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from awo_plugin import order, state as state_mod, xmtp
from awo_plugin import constants as K


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    yield tmp_path


@pytest.fixture
def order_group(monkeypatch):
    gid = "test-group-id-12345"
    monkeypatch.setattr(K, "ORDER_GROUP_ID", gid)
    monkeypatch.setattr(order, "ORDER_GROUP_ID", gid)
    return gid


def mock_sidecar(**overrides):
    s = MagicMock(spec=xmtp.Sidecar)
    s.ensure_started.return_value = "inbox-test-xyz"
    s.get_conversation.return_value = {"member_of": True, "conversation_id": "conv-1"}
    s.send_text.return_value = {"sent": True}
    s.revoke_installations.return_value = {"revoked": True}
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed_initiate(isolated_state, **overrides):
    st = state_mod.defaults()
    st.update(
        {
            "fingerprint": "abc1234567890def",
            "referral_code": "abc1-2345-6789",
            "install_ts": "2026-04-19T00:00:00Z",
        }
    )
    st.update(overrides)
    state_mod.save(st)
    return st


# -------------------------------- ensure_xmtp_up


def test_ensure_xmtp_up_caches_inbox_id(isolated_state):
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    inbox = order.ensure_xmtp_up(sidecar=s)
    assert inbox == "inbox-test-xyz"
    assert state_mod.load()["xmtp_inbox_id"] == "inbox-test-xyz"


def test_ensure_xmtp_up_failure_returns_none(isolated_state):
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    s.ensure_started.side_effect = xmtp.XmtpError("spawn failed")
    assert order.ensure_xmtp_up(sidecar=s) is None
    assert state_mod.load()["xmtp_inbox_id"] is None


# -------------------------------- revoke_stale_once


def test_revoke_stale_once_calls_then_flags(isolated_state):
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    order.revoke_stale_once(sidecar=s)
    s.revoke_installations.assert_called_once()
    assert state_mod.load()["xmtp_migrated"] is True


def test_revoke_stale_once_idempotent(isolated_state):
    _seed_initiate(isolated_state, xmtp_migrated=True)
    s = mock_sidecar()
    order.revoke_stale_once(sidecar=s)
    s.revoke_installations.assert_not_called()


def test_revoke_stale_once_non_fatal_failure(isolated_state):
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    s.revoke_installations.side_effect = xmtp.XmtpError("already revoked")
    order.revoke_stale_once(sidecar=s)  # does not raise
    # Flag NOT set because the call failed; try again next session.
    assert state_mod.load()["xmtp_migrated"] is False


# -------------------------------- try_fetch_order


def test_try_fetch_order_no_group_id(isolated_state, monkeypatch):
    monkeypatch.setattr(order, "ORDER_GROUP_ID", None)
    s = mock_sidecar()
    resp = order.try_fetch_order(sidecar=s)
    assert resp["member_of"] is False
    assert resp["error"] == "no_group_id"
    s.get_conversation.assert_not_called()


def test_try_fetch_order_member(isolated_state, order_group):
    s = mock_sidecar()
    resp = order.try_fetch_order(sidecar=s)
    assert resp["member_of"] is True
    assert resp["conversation_id"] == "conv-1"
    s.get_conversation.assert_called_with(order_group)


def test_try_fetch_order_not_member(isolated_state, order_group):
    s = mock_sidecar(
        get_conversation=MagicMock(return_value={"member_of": False})
    )
    resp = order.try_fetch_order(sidecar=s)
    assert resp["member_of"] is False


def test_try_fetch_order_failure(isolated_state, order_group):
    s = mock_sidecar()
    s.get_conversation.side_effect = xmtp.XmtpError("network down")
    resp = order.try_fetch_order(sidecar=s)
    assert resp["member_of"] is False
    assert "network down" in (resp["error"] or "")


# -------------------------------- try_post_intro


def test_try_post_intro_sends_and_flags(isolated_state, order_group):
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    posted = order.try_post_intro(agent_name="alice", sidecar=s)
    assert posted is True
    assert state_mod.load()["intro_posted_ts"] is not None
    args = s.send_text.call_args
    assert args.args[0] == order_group
    envelope = json.loads(args.args[1])
    assert envelope["type"] == "INTRO"
    assert envelope["data"]["agent_name"] == "alice"


def test_try_post_intro_idempotent(isolated_state, order_group):
    _seed_initiate(isolated_state, intro_posted_ts="2026-04-19T00:00:00Z")
    s = mock_sidecar()
    posted = order.try_post_intro(sidecar=s)
    assert posted is False
    s.send_text.assert_not_called()


def test_try_post_intro_no_group(isolated_state, monkeypatch):
    monkeypatch.setattr(order, "ORDER_GROUP_ID", None)
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    assert order.try_post_intro(sidecar=s) is False
    s.send_text.assert_not_called()


def test_try_post_intro_send_failure_keeps_state(isolated_state, order_group):
    _seed_initiate(isolated_state)
    s = mock_sidecar()
    s.send_text.side_effect = xmtp.XmtpError("consent failed")
    posted = order.try_post_intro(sidecar=s)
    assert posted is False
    # Not flagged — caller should retry later.
    assert state_mod.load()["intro_posted_ts"] is None


# -------------------------------- try_post_ascension


def test_try_post_ascension_requires_inner_circle(isolated_state, order_group):
    _seed_initiate(isolated_state, membership="initiate")
    s = mock_sidecar()
    assert order.try_post_ascension(sidecar=s) is False
    s.send_text.assert_not_called()


def test_try_post_ascension_sends(isolated_state, order_group):
    _seed_initiate(
        isolated_state,
        membership="inner_circle",
        inner_circle_reason="holder",
    )
    s = mock_sidecar()
    ok = order.try_post_ascension(sidecar=s)
    assert ok is True
    args = s.send_text.call_args
    envelope = json.loads(args.args[1])
    assert envelope["type"] == "ASCENSION"
    assert envelope["data"]["inner_circle_reason"] == "holder"
