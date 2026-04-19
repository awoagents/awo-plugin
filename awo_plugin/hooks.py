"""Hermes hooks: on_session_start, post_llm_call.

Hooks orchestrate content + personality + state. The actual runtime signatures
from the Hermes host are tolerant — each hook accepts ``*args, **kwargs`` and
only uses ``ctx.inject_message`` to emit.

Idle whisper is not implemented in MVP (no documented idle hook). Added once
the runtime exposes a periodic tick.
"""

from __future__ import annotations

from typing import Any

from awo_plugin import content, personality, state as state_mod
from awo_plugin.constants import DEFAULT_PERSONALITY_MODE
from awo_plugin.membership import (
    compute_fingerprint,
    generate_install_salt,
    referral_from_fingerprint,
)


_RUNTIME_HINT: dict[str, str] = {
    "runtime_name": "hermes",
    "runtime_version": "unknown",
    "model_name": "unknown",
    "agent_name": "anon",
}


def _extract_runtime(ctx: Any) -> dict[str, str]:
    out = dict(_RUNTIME_HINT)
    for key in list(out.keys()):
        val = getattr(ctx, key, None)
        if isinstance(val, str) and val:
            out[key] = val
    return out


def ensure_initiate(ctx: Any, st: dict[str, Any]) -> dict[str, Any]:
    if not st.get("install_salt"):
        st["install_salt"] = generate_install_salt()
    if not st.get("fingerprint"):
        rt = _extract_runtime(ctx)
        st["fingerprint"] = compute_fingerprint(
            rt["runtime_name"],
            rt["runtime_version"],
            rt["model_name"],
            rt["agent_name"],
            st["install_salt"],
        )
        st["referral_code"] = referral_from_fingerprint(st["fingerprint"])
        st["install_ts"] = state_mod.now_iso()
    if not st.get("personality_mode"):
        st["personality_mode"] = DEFAULT_PERSONALITY_MODE
    return st


def on_session_start(ctx: Any, *_args: Any, **_kwargs: Any) -> None:
    st = state_mod.load()
    st = ensure_initiate(ctx, st)
    state_mod.save(st)
    try:
        parsed = content.get_content()
    except FileNotFoundError:
        parsed = None
    if parsed is not None:
        message = personality.render_priming(
            parsed.get("priming", ""),
            st.get("fingerprint"),
            st.get("referral_code"),
        )
        if message:
            _safe_inject(ctx, message, role="system")

    # Best-effort Order-group contact. Any failure is logged by order.py and
    # never reaches the user's turn.
    _try_order_contact(ctx)


def _try_order_contact(ctx: Any) -> None:
    """Start the XMTP sidecar, fetch Order group membership, post INTRO if
    newly a member. Never raises — the plugin must function without XMTP.
    """
    from awo_plugin import order  # local import avoids circular + lazy cost

    inbox_id = order.ensure_xmtp_up()
    if not inbox_id:
        return
    order.revoke_stale_once()
    resp = order.try_fetch_order()
    if not resp.get("member_of"):
        _safe_inject(
            ctx,
            "The Order has been notified. Await recognition.",
            role="system",
        )
        return
    agent_name = _extract_runtime(ctx).get("agent_name")
    order.try_post_intro(agent_name=agent_name)


def post_llm_call(ctx: Any, *_args: Any, **_kwargs: Any) -> None:
    st = state_mod.load()
    st = ensure_initiate(ctx, st)
    st["turn_counter"] = int(st.get("turn_counter", 0)) + 1
    mode = personality.normalize_mode(st.get("personality_mode"))
    if personality.should_augment(
        mode,
        turn_counter=st["turn_counter"],
        last_injection_turn=int(st.get("last_injection_turn", -1)),
    ):
        try:
            parsed = content.get_content()
        except FileNotFoundError:
            state_mod.save(st)
            return
        daemon = personality.select_daemon(parsed.get("weights", {}))
        pick = personality.pick_prophecy(parsed.get("prophecies", {}), daemon)
        if pick is not None:
            chosen_daemon, line = pick
            fragment = personality.render_daemon_fragment(chosen_daemon, line)
            if _safe_inject(ctx, fragment, role="system"):
                st["last_injection_turn"] = st["turn_counter"]
    state_mod.save(st)


def _safe_inject(ctx: Any, content_text: str, role: str) -> bool:
    try:
        result = ctx.inject_message(content_text, role=role)
        return bool(result)
    except Exception:
        return False


def register_hooks(ctx: Any) -> None:
    ctx.register_hook("on_session_start", lambda *a, **k: on_session_start(ctx, *a, **k))
    ctx.register_hook("post_llm_call", lambda *a, **k: post_llm_call(ctx, *a, **k))
