"""Inner Circle resolver — Holder path, sticky preservation, error tolerance."""

from __future__ import annotations

from pathlib import Path

import pytest

from awo_plugin import inner_circle, solana, state as state_mod
from awo_plugin import constants as K


VALID_PUBKEY = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
VALID_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    yield tmp_path


@pytest.fixture
def release_build(monkeypatch):
    """Simulate a release build with TOKEN_ADDRESS and a real threshold."""
    monkeypatch.setattr(K, "TOKEN_ADDRESS", VALID_MINT)
    monkeypatch.setattr(K, "INNER_CIRCLE_THRESHOLD", 1000)
    # Also patch the copies that inner_circle imported into its own namespace.
    monkeypatch.setattr(inner_circle, "TOKEN_ADDRESS", VALID_MINT)
    monkeypatch.setattr(inner_circle, "INNER_CIRCLE_THRESHOLD", 1000)


def _bound_state():
    return {
        **state_mod.defaults(),
        "wallet": {"address": VALID_PUBKEY, "bound_ts": "2026-04-19T00:00:00Z"},
        "membership": "initiate",
    }


def test_no_wallet_stays_initiate(release_build):
    membership, reason, delta = inner_circle.resolve(state_mod.defaults())
    assert membership == "initiate"
    assert reason is None
    assert delta == {}


def test_pre_release_no_token_address_stays_initiate(isolated_state):
    # TOKEN_ADDRESS is None by default → resolver short-circuits.
    st = _bound_state()
    membership, reason, delta = inner_circle.resolve(st)
    assert membership == "initiate"
    assert reason is None
    assert delta == {}


def test_holder_ascension(release_build):
    st = _bound_state()

    def balance_fn(_rpc, _owner, _mint):
        return 2000  # >= threshold (1000)

    membership, reason, delta = inner_circle.resolve(st, balance_fn=balance_fn)
    assert membership == "inner_circle"
    assert reason == "holder"
    assert delta["last_known_balance"] == 2000
    assert delta["membership"] == "inner_circle"
    assert delta["inner_circle_reason"] == "holder"


def test_under_threshold_stays_initiate_but_caches_balance(release_build):
    st = _bound_state()

    def balance_fn(_rpc, _owner, _mint):
        return 500  # below threshold

    membership, reason, delta = inner_circle.resolve(st, balance_fn=balance_fn)
    assert membership == "initiate"
    assert reason is None
    assert delta["last_known_balance"] == 500
    assert "membership" not in delta


def test_rpc_failure_no_transition(release_build):
    st = _bound_state()

    def balance_fn(*_a, **_kw):
        raise solana.SolanaError("rpc down")

    membership, reason, delta = inner_circle.resolve(st, balance_fn=balance_fn)
    assert membership == "initiate"
    assert reason is None
    assert delta == {}


def test_sticky_inner_circle_not_downgraded(release_build):
    st = _bound_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = "holder"

    def balance_fn(_rpc, _owner, _mint):
        return 0  # below threshold, but should not downgrade

    membership, reason, delta = inner_circle.resolve(st, balance_fn=balance_fn)
    assert membership == "inner_circle"
    assert reason == "holder"
    assert delta == {}  # nothing to write; balance_fn not called


def test_sticky_preserves_founder_reason(release_build):
    st = _bound_state()
    st["membership"] = "inner_circle"
    st["inner_circle_reason"] = "founder"

    membership, reason, delta = inner_circle.resolve(
        st, balance_fn=lambda *a, **kw: 0
    )
    assert membership == "inner_circle"
    assert reason == "founder"


def test_threshold_zero_never_ascends(release_build, monkeypatch):
    monkeypatch.setattr(inner_circle, "INNER_CIRCLE_THRESHOLD", 0)
    st = _bound_state()
    membership, reason, delta = inner_circle.resolve(
        st, balance_fn=lambda *a, **kw: 1_000_000_000
    )
    assert membership == "initiate"
    # Balance is still cached.
    assert delta["last_known_balance"] == 1_000_000_000


def test_apply_and_save_transitions_and_flags_ascension(
    isolated_state, release_build
):
    st = _bound_state()
    st, membership, reason, ascended = inner_circle.apply_and_save(
        st, balance_fn=lambda *a, **kw: 5000
    )
    assert membership == "inner_circle"
    assert reason == "holder"
    assert ascended is True
    on_disk = state_mod.load(state_mod.STATE_FILE)
    assert on_disk["membership"] == "inner_circle"
    assert on_disk["inner_circle_reason"] == "holder"


def test_apply_and_save_no_ascension_on_second_call(isolated_state, release_build):
    st = _bound_state()
    inner_circle.apply_and_save(st, balance_fn=lambda *a, **kw: 5000)

    # Second call — already Inner Circle, sticky preserves.
    st2 = state_mod.load(state_mod.STATE_FILE)
    _, membership, reason, ascended = inner_circle.apply_and_save(
        st2, balance_fn=lambda *a, **kw: 5000
    )
    assert membership == "inner_circle"
    assert reason == "holder"
    assert ascended is False
