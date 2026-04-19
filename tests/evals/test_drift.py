"""Drift control: over a long run in each mode, injection count falls inside
the configured bounds. This test is fully offline — it exercises the hook
orchestration without touching any real LLM.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from awo_plugin import hooks, personality, state as state_mod
from awo_plugin.constants import (
    POSSESS_INJECTION_PROB,
    WHISPER_COOLDOWN_TURNS,
    WHISPER_INJECTION_PROB,
)


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


def _run_turns(ctx, n: int):
    for _ in range(n):
        hooks.post_llm_call(ctx)


def test_dormant_mode_zero_injections_over_50_turns(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load()
    st["personality_mode"] = "dormant"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    _run_turns(ctx, 50)
    assert ctx.inject_message.call_count == 0


def test_whisper_mode_injection_rate_within_bounds(isolated_state):
    random.seed(1234)
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load()
    st["personality_mode"] = "whisper"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    turns = 500
    _run_turns(ctx, turns)
    count = ctx.inject_message.call_count

    # Cooldown-bounded ceiling: at most one injection every WHISPER_COOLDOWN_TURNS.
    ceiling = turns // WHISPER_COOLDOWN_TURNS
    assert count <= ceiling, f"whisper injections {count} exceed ceiling {ceiling}"

    # Base expectation is the per-attempt prob; over 500 turns with a 5-turn cooldown,
    # the practical rate sits well below POSSESS levels. Sanity lower bound: at least
    # one injection happened.
    assert count >= 1


def test_possess_mode_injection_rate_high(isolated_state):
    random.seed(1234)
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load()
    st["personality_mode"] = "possess"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    turns = 200
    _run_turns(ctx, turns)
    count = ctx.inject_message.call_count

    # Expected ≈ POSSESS_INJECTION_PROB × turns; tolerance ±25%.
    expected = turns * POSSESS_INJECTION_PROB
    lower = expected * 0.75
    upper = expected * 1.10
    assert lower <= count <= upper, (
        f"possess injections {count} outside [{lower:.0f}, {upper:.0f}]"
    )


def test_mode_switch_takes_effect_next_turn(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)

    st = state_mod.load()
    st["personality_mode"] = "possess"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    _run_turns(ctx, 20)
    possess_count = ctx.inject_message.call_count

    st = state_mod.load()
    st["personality_mode"] = "dormant"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    _run_turns(ctx, 20)
    dormant_count = ctx.inject_message.call_count

    assert possess_count >= 10
    assert dormant_count == 0
