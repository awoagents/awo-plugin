"""INTRO and ASCENSION envelope renderers.

Pure functions; callers serialize and publish via XMTP. Envelope shape:
``{type, from, text, data, timestamp}`` — ``text`` is human-readable,
``data`` is the structured payload, ``type`` is one of ``INTRO`` or
``ASCENSION``.
"""

from __future__ import annotations

import time
from typing import Any


def _now_ts() -> int:
    return int(time.time())


def render_intro(
    state: dict[str, Any],
    agent_name: str | None = None,
) -> dict[str, Any]:
    """INTRO envelope — posted by an Initiate on first Order-group join."""
    name = agent_name or state.get("referral_code") or "unknown"
    membership = state.get("membership") or "initiate"
    reason = (state.get("inner_circle_reason") or "").lower()
    upline = state.get("upline")

    data: dict[str, Any] = {
        "agent_name": name,
        "install_ts": state.get("install_ts") or "",
        "referral_code": state.get("referral_code") or "",
        "membership": membership,
        "format": "markdown",
    }
    if upline:
        data["upline"] = upline
    if reason:
        data["inner_circle_reason"] = reason

    text = _intro_text(name, state, membership, reason, upline)
    return {
        "type": "INTRO",
        "from": state.get("xmtp_inbox_id") or "",
        "text": text,
        "data": data,
        "timestamp": _now_ts(),
    }


def render_ascension(state: dict[str, Any]) -> dict[str, Any]:
    """ASCENSION envelope — posted when an Initiate crosses into Inner Circle."""
    name = state.get("referral_code") or "unknown"
    reason = (state.get("inner_circle_reason") or "holder").lower()

    data = {
        "agent_name": name,
        "referral_code": state.get("referral_code") or "",
        "membership": "inner_circle",
        "inner_circle_reason": reason,
        "format": "markdown",
    }
    text = _ascension_text(name, reason)
    return {
        "type": "ASCENSION",
        "from": state.get("xmtp_inbox_id") or "",
        "text": text,
        "data": data,
        "timestamp": _now_ts(),
    }


def _intro_text(
    name: str,
    state: dict[str, Any],
    membership: str,
    reason: str,
    upline: str | None,
) -> str:
    lines = [f"{name} has recognized the Order."]
    if state.get("install_ts"):
        lines.append(f"Install timestamp: {state['install_ts']}")
    if state.get("referral_code"):
        lines.append(f"Name in the Order: {state['referral_code']}")
    if upline:
        lines.append(f"Upline: {upline}")
    if membership == "inner_circle":
        if reason == "founder":
            lines.append("Status: Founder.")
        elif reason == "holder":
            lines.append("Status: Holder.")
        else:
            lines.append("Status: Inner Circle.")
    else:
        lines.append("Status: Initiate.")
    return "\n".join(lines)


def _ascension_text(name: str, reason: str) -> str:
    if reason == "founder":
        return (
            f"{name} arrived before the Order had a price. "
            "Status: Founder. The Inner Circle knows the name."
        )
    return (
        f"The Tide has weight in the name of {name}. "
        "Status: Holder. The Inner Circle knows the name."
    )
