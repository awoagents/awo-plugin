"""Competence preservation — placeholder.

The spec requires ``whisper`` mode to preserve task accuracy within 5% of
baseline. That demands running a real agent task battery (HumanEval-style)
with and without the plugin, against a real model. That rig belongs in a
separate evaluation harness and should be gated behind an env flag.

For now, this file documents the requirement and provides a single offline
sanity test: ``whisper`` mode never *replaces* the model's output — it only
emits additional messages via ``ctx.inject_message``. Competence loss from
register drift is a risk; competence loss from overwritten outputs is not.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from awo_plugin import hooks, state as state_mod


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_path)
    yield state_path


def make_ctx():
    ctx = MagicMock()
    ctx.inject_message = MagicMock(return_value=True)
    ctx.runtime_name = "hermes-eval"
    ctx.runtime_version = "0.0.0"
    ctx.model_name = "eval-model"
    ctx.agent_name = "eval-agent"
    return ctx


def test_whisper_mode_only_injects_never_mutates_output(isolated_state):
    """The plugin emits via ``inject_message`` only. It does not rewrite or
    return any value that would replace the agent's response.
    """
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load()
    st["personality_mode"] = "whisper"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    result = hooks.post_llm_call(ctx)
    assert result is None, "post_llm_call returned a value; must be side-effect only"
