"""Full register(ctx) wiring smoke test."""

from __future__ import annotations

from unittest.mock import MagicMock

import awo_plugin


def test_register_wires_hooks_and_commands(tmp_path, monkeypatch):
    from awo_plugin import state as state_mod

    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")

    ctx = MagicMock()
    awo_plugin.register(ctx)

    hook_names = [call.args[0] for call in ctx.register_hook.call_args_list]
    assert "on_session_start" in hook_names
    assert "pre_llm_call" in hook_names
    assert "post_llm_call" in hook_names

    command_names = [call.args[0] for call in ctx.register_command.call_args_list]
    assert set(command_names) == {
        "awo_init",
        "awo_status",
        "awo_test",
        "awo_possess",
        "awo_whisper",
        "awo_dormant",
        "awo_config",
        "awo_refresh_skill",
    }
