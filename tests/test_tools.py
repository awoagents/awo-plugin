"""Slash command tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from awo_plugin import state as state_mod, tools


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_path)
    yield state_path


def make_ctx():
    ctx = MagicMock()
    ctx.runtime_name = "hermes-test"
    ctx.runtime_version = "0.0.0"
    ctx.model_name = "test-model"
    ctx.agent_name = "tester"
    return ctx


def test_mode_commands_mutate_state(isolated_state):
    ctx = make_ctx()
    msg = tools.cmd_possess(ctx)
    assert "possess" in msg
    assert state_mod.load(isolated_state)["personality_mode"] == "possess"

    tools.cmd_whisper(ctx)
    assert state_mod.load(isolated_state)["personality_mode"] == "whisper"

    tools.cmd_dormant(ctx)
    assert state_mod.load(isolated_state)["personality_mode"] == "dormant"


def test_status_renders_identity(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_status(ctx)
    st = state_mod.load(isolated_state)
    assert st["fingerprint"] in out
    assert st["referral_code"] in out
    assert "whisper" in out


def test_join_records_upline(isolated_state):
    ctx = make_ctx()
    tools.cmd_status(ctx)  # force Initiate creation

    msg = tools.cmd_join(ctx, "abcd-efgh-ijkl")
    st = state_mod.load(isolated_state)
    assert st["upline"] == "abcd-efgh-ijkl"
    assert "upline recorded" in msg
    assert "continuing" in msg


def test_join_normalizes_casing(isolated_state):
    ctx = make_ctx()
    tools.cmd_status(ctx)
    tools.cmd_join(ctx, "ABCD-EFGH-IJKL")
    assert state_mod.load(isolated_state)["upline"] == "abcd-efgh-ijkl"


def test_join_rejects_bad_format(isolated_state):
    ctx = make_ctx()
    tools.cmd_status(ctx)
    msg = tools.cmd_join(ctx, "not-a-code")
    assert "expects a referral" in msg
    assert state_mod.load(isolated_state)["upline"] is None


def test_join_refuses_self_as_upline(isolated_state):
    ctx = make_ctx()
    tools.cmd_status(ctx)
    referral = state_mod.load(isolated_state)["referral_code"]

    msg = tools.cmd_join(ctx, referral)
    assert "self" in msg.lower()
    assert state_mod.load(isolated_state)["upline"] is None


def test_join_idempotent_does_not_overwrite(isolated_state):
    ctx = make_ctx()
    tools.cmd_status(ctx)
    tools.cmd_join(ctx, "abcd-efgh-ijkl")
    msg = tools.cmd_join(ctx, "mnop-qrst-uvwx")
    assert "already recorded" in msg
    assert state_mod.load(isolated_state)["upline"] == "abcd-efgh-ijkl"


def test_join_accepts_kwargs_referral_code(isolated_state):
    ctx = make_ctx()
    tools.cmd_status(ctx)
    tools.cmd_join(ctx, referral_code="abcd-efgh-ijkl")
    assert state_mod.load(isolated_state)["upline"] == "abcd-efgh-ijkl"


def test_register_commands_registers_all(isolated_state):
    ctx = make_ctx()
    ctx.register_command = MagicMock()
    tools.register_commands(ctx)
    registered = [call.args[0] for call in ctx.register_command.call_args_list]
    assert registered == [
        "awo_possess",
        "awo_whisper",
        "awo_dormant",
        "awo_status",
        "awo_join",
        "awo_config",
        "awo_refresh_skill",
    ]


# ---------------- /awo_refresh_skill ----------------


def test_refresh_skill_happy(isolated_state, monkeypatch):
    from awo_plugin import live_sync

    calls = {"n": 0}

    def fake_fetch_and_install():
        calls["n"] += 1
        return 1234

    monkeypatch.setattr(live_sync, "fetch_and_install", fake_fetch_and_install)

    ctx = make_ctx()
    out = tools.cmd_refresh_skill(ctx)
    assert calls["n"] == 1
    assert "1234" in out
    assert "refreshed" in out.lower()


def test_refresh_skill_failure(isolated_state, monkeypatch):
    from awo_plugin import live_sync

    def boom():
        raise live_sync.LiveSyncError("network down")

    monkeypatch.setattr(live_sync, "fetch_and_install", boom)

    ctx = make_ctx()
    out = tools.cmd_refresh_skill(ctx)
    assert "failed" in out.lower()
    assert "network down" in out


# ---------------- /awo_config ----------------

VALID_PUBKEY = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


def test_config_show_empty(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx)
    assert "wallet:  —" in out
    assert "default" in out


def test_config_show_explicit(isolated_state):
    ctx = make_ctx()
    out_default = tools.cmd_config(ctx)
    out_show = tools.cmd_config(ctx, "show")
    assert out_default == out_show


def test_config_wallet_step1_issues_challenge(isolated_state):
    """Step 1: one-arg wallet form issues a pending challenge, does NOT bind."""
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "wallet", VALID_PUBKEY)
    assert "challenge issued" in out.lower()
    assert "AWO-BIND" in out
    assert VALID_PUBKEY in out
    st = state_mod.load(isolated_state)
    # Not bound yet — wallet remains None until step 2.
    assert st["wallet"] is None
    # Pending challenge persisted.
    assert st["wallet_challenge"] is not None
    assert st["wallet_challenge"]["pubkey"] == VALID_PUBKEY


def test_config_wallet_step1_accepts_args_kwarg_string(isolated_state):
    """Simulates a Hermes runtime that passes args as a single string."""
    ctx = make_ctx()
    out = tools.cmd_config(ctx, args=f"wallet {VALID_PUBKEY}")
    assert "challenge issued" in out.lower()
    assert state_mod.load(isolated_state)["wallet_challenge"] is not None


def test_config_wallet_step2_verifies_and_binds(isolated_state):
    """Step 2: real signature from the matching keypair binds the wallet."""
    from solders.keypair import Keypair

    kp = Keypair()
    pk = str(kp.pubkey())

    ctx = make_ctx()
    # Step 1 — capture the challenge text.
    challenge_out = tools.cmd_config(ctx, "wallet", pk)
    # Extract the challenge body between the ──── delimiters in the response.
    import re as _re
    m = _re.search(r"────\n(.+?)────", challenge_out, _re.DOTALL)
    assert m, f"no challenge found in: {challenge_out!r}"
    challenge_text = m.group(1)

    # Sign externally (in real life, agent's tool would do this).
    sig = kp.sign_message(challenge_text.encode("utf-8"))

    # Step 2 — submit signature.
    out = tools.cmd_config(ctx, "wallet", pk, str(sig))
    assert "bound and verified" in out.lower()
    st = state_mod.load(isolated_state)
    assert st["wallet"]["address"] == pk
    # Challenge is consumed — no replay.
    assert st["wallet_challenge"] is None


def test_config_wallet_step2_rejects_forged_signature(isolated_state):
    """Anti-spoof: signature from a different keypair fails even if pubkey
    matches the pending challenge."""
    from solders.keypair import Keypair

    real_kp = Keypair()
    attacker_kp = Keypair()
    pk = str(real_kp.pubkey())

    ctx = make_ctx()
    challenge_out = tools.cmd_config(ctx, "wallet", pk)
    import re as _re
    challenge_text = _re.search(r"────\n(.+?)────", challenge_out, _re.DOTALL).group(1)

    # Attacker signs with their own key, hoping the plugin won't check.
    forged = attacker_kp.sign_message(challenge_text.encode("utf-8"))
    out = tools.cmd_config(ctx, "wallet", pk, str(forged))

    assert "bind failed" in out.lower()
    assert "does not verify" in out
    st = state_mod.load(isolated_state)
    assert st["wallet"] is None


def test_config_wallet_invalid_pubkey_at_step1(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "wallet", "not-a-pubkey")
    assert "valid Solana address" in out
    assert state_mod.load(isolated_state)["wallet"] is None
    assert state_mod.load(isolated_state)["wallet_challenge"] is None


def test_config_wallet_missing_arg(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "wallet")
    assert "usage" in out.lower()
    assert state_mod.load(isolated_state)["wallet"] is None


def test_config_rpc_https(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "rpc", "https://custom.rpc/")
    assert "Solana RPC set" in out
    st = state_mod.load(isolated_state)
    assert st["config"]["rpc_url"] == "https://custom.rpc/"


def test_config_rpc_rejects_http(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "rpc", "http://insecure/")
    assert "HTTPS" in out
    assert "rpc_url" not in (state_mod.load(isolated_state).get("config") or {})


def _simulate_bound_wallet(state_path, pubkey: str = VALID_PUBKEY):
    """Shortcut for tests that need a wallet already bound — bypasses the
    full two-step flow since they're exercising other surfaces."""
    st = state_mod.load(state_path)
    st["wallet"] = {"address": pubkey, "bound_ts": "2026-04-19T10:00:00Z"}
    state_mod.save(st, state_path)


def test_config_show_with_custom_values(isolated_state):
    ctx = make_ctx()
    _simulate_bound_wallet(isolated_state)
    tools.cmd_config(ctx, "rpc", "https://custom.rpc/")
    out = tools.cmd_config(ctx)
    assert VALID_PUBKEY in out
    assert "https://custom.rpc/" in out
    assert "custom" in out


def test_config_unset_wallet(isolated_state):
    ctx = make_ctx()
    _simulate_bound_wallet(isolated_state)
    out = tools.cmd_config(ctx, "unset", "wallet")
    assert "unset" in out
    assert "sticky" in out
    assert state_mod.load(isolated_state)["wallet"] is None


def test_config_unset_rpc(isolated_state):
    ctx = make_ctx()
    tools.cmd_config(ctx, "rpc", "https://custom.rpc/")
    out = tools.cmd_config(ctx, "unset", "rpc")
    assert "default" in out
    config = state_mod.load(isolated_state).get("config") or {}
    assert "rpc_url" not in config


def test_config_unset_unknown_key(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "unset", "bogus")
    assert "wallet" in out and "rpc" in out


def test_config_unknown_subcommand(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "bogus")
    assert "usage" in out
