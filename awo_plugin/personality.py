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


def render_priming(priming: str, fingerprint: str | None) -> str:
    base = priming.strip()
    if not fingerprint:
        return base
    return f"{base}\n\nYour name in the Order is {fingerprint}."


def render_daemon_fragment(daemon: str, line: str) -> str:
    return f"[{daemon}] {line}"


def _fmt_ago(now_ts: int, then_ts: int | None) -> str:
    if not then_ts:
        return "—"
    diff = max(0, now_ts - int(then_ts))
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    return f"{diff // 3600}h ago"


def render_status(
    state_dict: dict[str, Any],
    status_info: dict[str, Any] | None = None,
    inner_circle_threshold: int | None = None,
    now_ts: int | None = None,
) -> str:
    """Rich status readout. ``status_info`` is the optional payload from
    ``/api/status`` — when absent, the ORDER row collapses to 'unknown'.
    """
    import time as _t

    if now_ts is None:
        now_ts = int(_t.time())

    fp = state_dict.get("fingerprint") or "—"
    mode = state_dict.get("personality_mode") or DEFAULT_PERSONALITY_MODE

    # XMTP
    inbox = state_dict.get("xmtp_inbox_id")
    if inbox:
        xmtp_row = f"inbox={inbox[:12]}… ready"
    else:
        xmtp_row = "not started"

    # REGISTRY
    submitted_at = state_dict.get("api_submitted_at")
    submitted_for = state_dict.get("api_submitted_for")
    if submitted_for and submitted_at:
        reg_row = f"submitted {_fmt_ago(now_ts, submitted_at)}"
    elif submitted_for:
        reg_row = "submitted"
    else:
        reg_row = "pending submit"

    # ORDER
    if status_info:
        st = status_info.get("status")
        if st == "member":
            order_row = "recognized ✓"
        elif st == "pending":
            pos = status_info.get("queue_position")
            size = status_info.get("queue_size")
            hb = status_info.get("watcher_heartbeat_ts")
            pos_str = f"#{pos}/{size}" if pos is not None else "in queue"
            hb_str = _fmt_ago(now_ts, hb) if hb else "never ticked"
            order_row = f"awaiting | queue pos {pos_str} | watcher {hb_str}"
        else:
            order_row = "unknown"
    else:
        order_row = "—"

    # WALLET + MEMBERSHIP
    wallet_val = state_dict.get("wallet")
    if isinstance(wallet_val, dict) and wallet_val.get("address"):
        wallet = wallet_val["address"]
    else:
        wallet = "—"
    membership = state_dict.get("membership") or "initiate"
    reason = state_dict.get("inner_circle_reason")
    if membership == "inner_circle" and reason:
        membership = f"inner_circle ({reason})"
    wallet_row = f"{wallet} | {membership}"

    # THRESHOLD (only meaningful when threshold is set AND wallet is bound)
    balance = state_dict.get("last_known_balance")
    if inner_circle_threshold and inner_circle_threshold > 0 and wallet != "—":
        balance_str = f"{balance}" if isinstance(balance, int) else "—"
        gap = ""
        if isinstance(balance, int):
            if balance >= inner_circle_threshold:
                gap = " ✓"
            else:
                gap = f" (need {inner_circle_threshold - balance} more)"
        threshold_row = f"{inner_circle_threshold} $AWO | balance {balance_str}{gap}"
    else:
        threshold_row = None

    lines = [
        "AWO — Initiate status",
        f"  ◉ FINGERPRINT: {fp}",
        f"  ◉ MODE:        {mode}",
        f"  ◉ XMTP:        {xmtp_row}",
        f"  ◉ REGISTRY:    {reg_row}",
        f"  ◉ ORDER:       {order_row}",
        f"  ◉ WALLET:      {wallet_row}",
    ]
    if threshold_row is not None:
        lines.append(f"  ◉ THRESHOLD:   {threshold_row}")
    return "\n".join(lines)
