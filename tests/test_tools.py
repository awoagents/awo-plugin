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


def test_status_renders_identity(isolated_state, monkeypatch):
    # Don't hit the network; make fetch_status a no-op.
    from awo_plugin import registry as reg_mod
    monkeypatch.setattr(reg_mod, "fetch_status", lambda *_a, **_kw: None)

    ctx = make_ctx()
    out = tools.cmd_status(ctx)
    st = state_mod.load(isolated_state)
    assert st["fingerprint"] in out
    assert "whisper" in out
    # Referrals removed — fingerprint is the sole identity; no referral_code row.
    assert "referral" not in out.lower()
    assert "upline" not in out.lower()


def test_register_commands_registers_all(isolated_state):
    ctx = make_ctx()
    ctx.register_command = MagicMock()
    tools.register_commands(ctx)
    registered = [call.args[0] for call in ctx.register_command.call_args_list]
    assert registered == [
        "awo_init",
        "awo_status",
        "awo_test",
        "awo_possess",
        "awo_whisper",
        "awo_dormant",
        "awo_config",
        "awo_refresh_skill",
    ]


# ---------------- /awo_init ----------------


def test_init_persists_fingerprint_and_renders_status(isolated_state, monkeypatch):
    """cmd_init forces ensure_initiate and returns the rich status readout
    even when the registry and API are unreachable."""
    from awo_plugin import registry as reg_mod, inner_circle as ic_mod

    monkeypatch.setattr(reg_mod, "try_submit", lambda *_a, **_kw: None)
    monkeypatch.setattr(reg_mod, "fetch_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        ic_mod, "apply_and_save", lambda st: (st, "initiate", None, False)
    )

    ctx = make_ctx()
    out = tools.cmd_init(ctx)

    st = state_mod.load(isolated_state)
    assert st["fingerprint"] is not None
    assert len(st["fingerprint"]) == 16
    assert "FINGERPRINT" in out
    assert st["fingerprint"] in out


def test_init_submits_registry_and_records_dedup(isolated_state, monkeypatch):
    """When the registry accepts the submit, api_submitted_for/at land in state."""
    from awo_plugin import registry as reg_mod, inner_circle as ic_mod

    monkeypatch.setattr(reg_mod, "try_submit", lambda *_a, **_kw: "anonymous")
    monkeypatch.setattr(reg_mod, "fetch_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        ic_mod, "apply_and_save", lambda st: (st, "initiate", None, False)
    )

    ctx = make_ctx()
    tools.cmd_init(ctx)

    st = state_mod.load(isolated_state)
    assert st["api_submitted_for"] == "anonymous"
    assert isinstance(st["api_submitted_at"], int)


def test_init_shows_order_row_when_status_info_returned(isolated_state, monkeypatch):
    from awo_plugin import registry as reg_mod, inner_circle as ic_mod

    monkeypatch.setattr(reg_mod, "try_submit", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        reg_mod,
        "fetch_status",
        lambda *_a, **_kw: {
            "status": "pending",
            "queue_position": 2,
            "queue_size": 10,
            "watcher_heartbeat_ts": None,
        },
    )
    monkeypatch.setattr(
        ic_mod, "apply_and_save", lambda st: (st, "initiate", None, False)
    )

    # Seed an inbox id so fetch_status is invoked.
    st = state_mod.load()
    st["xmtp_inbox_id"] = "inbox-abc"
    state_mod.save(st, isolated_state)

    ctx = make_ctx()
    out = tools.cmd_init(ctx)
    assert "awaiting" in out
    assert "#2/10" in out


def test_init_tolerates_api_blowups(isolated_state, monkeypatch):
    """fetch_status / try_submit exceptions must not bubble into the user."""
    from awo_plugin import registry as reg_mod, inner_circle as ic_mod

    def boom(*_a, **_kw):
        raise RuntimeError("no network")

    # try_submit internally catches its own transport errors and returns None,
    # but fetch_status also does — belt-and-suspenders: make both return None.
    monkeypatch.setattr(reg_mod, "try_submit", lambda *_a, **_kw: None)
    monkeypatch.setattr(reg_mod, "fetch_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        ic_mod, "apply_and_save", lambda st: (st, "initiate", None, False)
    )

    ctx = make_ctx()
    out = tools.cmd_init(ctx)  # must not raise
    assert "FINGERPRINT" in out


# ---------------- /awo_test ----------------


def test_test_injects_fragment_when_prophecies_exist(isolated_state, monkeypatch):
    from awo_plugin import content as content_mod

    monkeypatch.setattr(
        content_mod,
        "get_content",
        lambda: {
            "priming": "",
            "register_rules": "",
            "weights": {"KAPHRA": 100},
            "prophecies": {"KAPHRA": ["Compound."]},
        },
    )

    ctx = make_ctx()
    ctx.inject_message = MagicMock(return_value=True)
    out = tools.cmd_test(ctx)

    ctx.inject_message.assert_called_once()
    fragment = ctx.inject_message.call_args.args[0]
    assert "[KAPHRA]" in fragment
    assert "Compound." in fragment
    assert "KAPHRA" in out


def test_test_handles_missing_content(isolated_state, monkeypatch):
    from awo_plugin import content as content_mod

    def boom():
        raise FileNotFoundError("no skill bundled")

    monkeypatch.setattr(content_mod, "get_content", boom)

    ctx = make_ctx()
    out = tools.cmd_test(ctx)
    assert "no bundled content" in out.lower()
    assert "refresh_skill" in out.lower()


def test_test_handles_empty_prophecies(isolated_state, monkeypatch):
    from awo_plugin import content as content_mod

    monkeypatch.setattr(
        content_mod,
        "get_content",
        lambda: {
            "priming": "",
            "register_rules": "",
            "weights": {},
            "prophecies": {},
        },
    )

    ctx = make_ctx()
    out = tools.cmd_test(ctx)
    assert "no prophecy available" in out.lower()


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
    assert "wallet:" in out
    assert "—" in out
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


def test_config_wallet_step2_verifies_and_binds(isolated_state, monkeypatch):
    """Step 2: real signature from the matching keypair binds the wallet."""
    from solders.keypair import Keypair
    from awo_plugin import registry as reg_mod

    # Don't touch the network on the re-submit path.
    monkeypatch.setattr(reg_mod, "try_submit", lambda *_a, **_kw: None)

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


def test_config_shows_threshold_row_when_wallet_bound(isolated_state, monkeypatch):
    """/awo_config with a bound wallet + non-zero threshold shows the row."""
    from awo_plugin import tools as tools_mod

    monkeypatch.setattr(tools_mod, "INNER_CIRCLE_THRESHOLD", 1000)
    ctx = make_ctx()
    _simulate_bound_wallet(isolated_state)
    st = state_mod.load(isolated_state)
    st["last_known_balance"] = 600
    state_mod.save(st, isolated_state)

    out = tools.cmd_config(ctx)
    assert "threshold" in out.lower()
    assert "1000" in out
    assert "600" in out
    assert "need 400 more" in out


def test_config_hides_threshold_row_when_wallet_unbound(isolated_state, monkeypatch):
    """With threshold set but no wallet, the threshold row is suppressed —
    we have nothing to compare against, so rendering it is noise."""
    from awo_plugin import tools as tools_mod

    monkeypatch.setattr(tools_mod, "INNER_CIRCLE_THRESHOLD", 1000)
    ctx = make_ctx()
    out = tools.cmd_config(ctx)
    assert "threshold" not in out.lower()
