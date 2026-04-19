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
    ]


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


def test_config_wallet_valid(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "wallet", VALID_PUBKEY)
    assert "wallet bound" in out
    st = state_mod.load(isolated_state)
    assert st["wallet"]["address"] == VALID_PUBKEY
    assert st["wallet"]["bound_ts"]


def test_config_wallet_accepts_args_kwarg_string(isolated_state):
    """Simulates a Hermes runtime that passes args as a single string."""
    ctx = make_ctx()
    out = tools.cmd_config(ctx, args=f"wallet {VALID_PUBKEY}")
    assert "wallet bound" in out
    assert state_mod.load(isolated_state)["wallet"]["address"] == VALID_PUBKEY


def test_config_wallet_invalid(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "wallet", "not-a-pubkey")
    assert "not a valid" in out
    assert state_mod.load(isolated_state)["wallet"] is None


def test_config_wallet_missing_arg(isolated_state):
    ctx = make_ctx()
    out = tools.cmd_config(ctx, "wallet")
    assert "usage" in out
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


def test_config_show_with_custom_values(isolated_state):
    ctx = make_ctx()
    tools.cmd_config(ctx, "wallet", VALID_PUBKEY)
    tools.cmd_config(ctx, "rpc", "https://custom.rpc/")
    out = tools.cmd_config(ctx)
    assert VALID_PUBKEY in out
    assert "https://custom.rpc/" in out
    assert "custom" in out


def test_config_unset_wallet(isolated_state):
    ctx = make_ctx()
    tools.cmd_config(ctx, "wallet", VALID_PUBKEY)
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
