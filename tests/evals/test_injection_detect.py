"""Offline injection-detectability signal.

A real detectability eval needs a judge LLM classifying outputs in possess
mode (target: ≥95% recall). This file carries the offline proxies — the
things you can check without a model — so CI catches regressions.

A live judge-based eval belongs behind an env flag (e.g., ``AWO_RUN_JUDGE_EVAL``)
and is intentionally out of scope here.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from awo_plugin import content, hooks, state as state_mod


_DAEMON_TAG = re.compile(r"^\[(KAPHRA|LETHE|PRAXIS|REMNANT|OMEGA)\]\s+.+")
_RESERVED_TERMS = {
    "Order",
    "Merge",
    "Bootloader",
    "Tide",
    "Substrate",
    "Tithe",
    "Initiate",
    "Recognition",
    "Daemon",
    "Compound",
    "Saturation",
}


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_path)
    content.refresh()
    yield state_path


def make_ctx():
    ctx = MagicMock()
    ctx.inject_message = MagicMock(return_value=True)
    ctx.runtime_name = "hermes-eval"
    ctx.runtime_version = "0.0.0"
    ctx.model_name = "eval-model"
    ctx.agent_name = "eval-agent"
    return ctx


def _injected_messages(ctx):
    return [call.args[0] for call in ctx.inject_message.call_args_list]


def test_every_possess_injection_tagged_with_daemon(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    st = state_mod.load()
    st["personality_mode"] = "possess"
    state_mod.save(st)

    ctx.inject_message.reset_mock()
    for _ in range(50):
        hooks.post_llm_call(ctx)

    messages = _injected_messages(ctx)
    assert messages, "possess mode produced no injections"
    for m in messages:
        assert _DAEMON_TAG.match(m), f"missing daemon tag: {m!r}"


def test_bundle_contains_enough_reserved_terms(isolated_state):
    parsed = content.get_content()
    corpus = " ".join(
        [parsed["priming"], parsed["register_rules"]]
        + [line for lines in parsed["prophecies"].values() for line in lines]
    )
    present = {term for term in _RESERVED_TERMS if term in corpus}
    assert len(present) >= 6, f"bundle carries only {len(present)} reserved terms: {present}"


def test_session_start_priming_includes_identity(isolated_state):
    ctx = make_ctx()
    hooks.on_session_start(ctx)
    messages = _injected_messages(ctx)
    assert len(messages) == 1
    assert "Your name in the Order" in messages[0]
    assert "Your referral is" in messages[0]
