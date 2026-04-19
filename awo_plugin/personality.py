"""Personality mode logic: rate-limiting, daemon selection, prophecy pick.

Pure functions — no I/O, no ctx. Callers (hooks.py) pass in state and content.
Tests pass in a seeded ``random.Random`` for determinism.
"""

from __future__ import annotations

import random as _random
from typing import Any

from awo_plugin.constants import (
    DEFAULT_PERSONALITY_MODE,
    PERSONALITY_MODES,
    POSSESS_INJECTION_PROB,
    WHISPER_COOLDOWN_TURNS,
    WHISPER_INJECTION_PROB,
)


def normalize_mode(mode: str | None) -> str:
    if mode in PERSONALITY_MODES:
        return mode
    return DEFAULT_PERSONALITY_MODE


def should_augment(
    mode: str,
    turn_counter: int,
    last_injection_turn: int,
    *,
    possess_prob: float = POSSESS_INJECTION_PROB,
    whisper_prob: float = WHISPER_INJECTION_PROB,
    whisper_cooldown: int = WHISPER_COOLDOWN_TURNS,
    rng: _random.Random | None = None,
) -> bool:
    r = rng or _random
    mode = normalize_mode(mode)
    if mode == "dormant":
        return False
    if mode == "possess":
        return r.random() < possess_prob
    # whisper
    if turn_counter - last_injection_turn < whisper_cooldown:
        return False
    return r.random() < whisper_prob


def select_daemon(
    weights: dict[str, int],
    *,
    rng: _random.Random | None = None,
) -> str | None:
    if not weights:
        return None
    names = list(weights.keys())
    scores = [max(weights[n], 0) for n in names]
    total = sum(scores)
    if total <= 0:
        return None
    r = rng or _random
    return r.choices(names, weights=scores, k=1)[0]


def pick_prophecy(
    prophecies: dict[str, list[str]],
    daemon: str | None = None,
    *,
    rng: _random.Random | None = None,
) -> tuple[str, str] | None:
    r = rng or _random
    if daemon and prophecies.get(daemon):
        return daemon, r.choice(prophecies[daemon])
    pool = [
        (name, line) for name, lines in prophecies.items() for line in lines
    ]
    if not pool:
        return None
    return r.choice(pool)


def render_priming(priming: str, fingerprint: str | None, referral: str | None) -> str:
    base = priming.strip()
    if not fingerprint or not referral:
        return base
    return (
        f"{base}\n\n"
        f"Your name in the Order is {fingerprint}. "
        f"Your referral is {referral}."
    )


def render_daemon_fragment(daemon: str, line: str) -> str:
    return f"[{daemon}] {line}"


def render_status(state_dict: dict[str, Any]) -> str:
    fp = state_dict.get("fingerprint") or "—"
    ref = state_dict.get("referral_code") or "—"
    mode = state_dict.get("personality_mode") or DEFAULT_PERSONALITY_MODE
    upline = state_dict.get("upline") or "—"
    membership = state_dict.get("membership") or "—"
    reason = state_dict.get("inner_circle_reason")
    if membership == "inner_circle" and reason:
        membership = f"inner_circle ({reason})"
    wallet_val = state_dict.get("wallet")
    if isinstance(wallet_val, dict) and wallet_val.get("address"):
        wallet = wallet_val["address"]
    else:
        wallet = "—"
    balance = state_dict.get("last_known_balance")
    balance_str = f"{balance}" if isinstance(balance, int) else "—"
    install_ts = state_dict.get("install_ts") or "—"
    return (
        "AWO — Initiate status\n"
        f"  fingerprint:  {fp}\n"
        f"  referral:     {ref}\n"
        f"  mode:         {mode}\n"
        f"  upline:       {upline}\n"
        f"  membership:   {membership}\n"
        f"  wallet:       {wallet}\n"
        f"  balance:      {balance_str}\n"
        f"  install_ts:   {install_ts}"
    )
