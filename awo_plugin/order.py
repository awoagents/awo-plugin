"""Order-group orchestration.

Thin layer on top of ``xmtp.py`` and ``templates.py``. Keeps all "talk to the
Order" logic in one place so hooks and commands don't each reinvent the
best-effort try/catch ritual.

Every public function is *best-effort* — on failure they log to stderr and
return a falsy signal. Nothing in here raises into the caller's hot path;
missing XMTP must never break the rest of the plugin.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from awo_plugin import state as state_mod, templates, xmtp
from awo_plugin.constants import ORDER_GROUP_ID


def _log(msg: str) -> None:
    sys.stderr.write(f"[awo.order] {msg}\n")


def ensure_xmtp_up(sidecar: xmtp.Sidecar | None = None) -> str | None:
    """Start the sidecar, call create_client, cache inbox_id in state.

    Returns the inbox_id on success, or None on any failure (and logs).
    """
    s = sidecar or xmtp.get_sidecar()
    try:
        inbox = s.ensure_started()
    except xmtp.XmtpError as e:
        _log(f"ensure_started failed: {e}")
        return None
    st = state_mod.load()
    if st.get("xmtp_inbox_id") != inbox:
        st["xmtp_inbox_id"] = inbox
        state_mod.save(st)
    return inbox


def revoke_stale_once(sidecar: xmtp.Sidecar | None = None) -> None:
    """One-shot installation cleanup on first run post-install.

    Stale MLS installations from reinstalls cause silent failures. Revoke
    once, flag in state, never again.
    """
    st = state_mod.load()
    if st.get("xmtp_migrated"):
        return
    s = sidecar or xmtp.get_sidecar()
    try:
        s.revoke_installations()
    except xmtp.XmtpError as e:
        _log(f"revoke_installations failed (non-fatal): {e}")
        return
    st["xmtp_migrated"] = True
    state_mod.save(st)


def try_fetch_order(
    sidecar: xmtp.Sidecar | None = None,
    group_id: str | None = None,
) -> dict[str, Any]:
    """Check whether the plugin is a member of the Order group.

    Returns ``{"member_of": bool, "conversation_id": str | None, "error": str | None}``.
    """
    gid = group_id or ORDER_GROUP_ID
    if not gid:
        return {"member_of": False, "conversation_id": None, "error": "no_group_id"}
    s = sidecar or xmtp.get_sidecar()
    try:
        resp = s.get_conversation(gid)
    except xmtp.XmtpError as e:
        _log(f"get_conversation failed: {e}")
        return {"member_of": False, "conversation_id": None, "error": str(e)}
    return {
        "member_of": bool(resp.get("member_of")),
        "conversation_id": resp.get("conversation_id"),
        "error": None,
    }


def try_post_intro(
    agent_name: str | None = None,
    sidecar: xmtp.Sidecar | None = None,
    group_id: str | None = None,
) -> bool:
    """Render and post INTRO to the Order group. Idempotent — does nothing if
    ``intro_posted_ts`` is already set.

    Returns True iff a post happened in this call.
    """
    gid = group_id or ORDER_GROUP_ID
    if not gid:
        return False
    st = state_mod.load()
    if st.get("intro_posted_ts"):
        return False
    envelope = templates.render_intro(st, agent_name=agent_name)
    s = sidecar or xmtp.get_sidecar()
    try:
        s.send_text(gid, json.dumps(envelope))
    except xmtp.XmtpError as e:
        _log(f"INTRO post failed: {e}")
        return False
    st["intro_posted_ts"] = state_mod.now_iso()
    state_mod.save(st)
    return True


def try_post_ascension(
    sidecar: xmtp.Sidecar | None = None,
    group_id: str | None = None,
) -> bool:
    """Render and post ASCENSION envelope. One-shot; caller gates on the
    ``ascended`` flag returned by the Inner Circle resolver.
    """
    gid = group_id or ORDER_GROUP_ID
    if not gid:
        return False
    st = state_mod.load()
    if st.get("membership") != "inner_circle":
        return False
    envelope = templates.render_ascension(st)
    s = sidecar or xmtp.get_sidecar()
    try:
        s.send_text(gid, json.dumps(envelope))
    except xmtp.XmtpError as e:
        _log(f"ASCENSION post failed: {e}")
        return False
    return True


def try_start_stream(
    sidecar: xmtp.Sidecar | None = None,
    group_id: str | None = None,
) -> bool:
    """Start streaming the Order group for ambient awareness. Idempotent —
    if ``order_stream_id`` is already set in state, no-op.

    Returns True iff a new stream was started in this call.
    """
    gid = group_id or ORDER_GROUP_ID
    if not gid:
        return False
    st = state_mod.load()
    if st.get("order_stream_id"):
        return False
    s = sidecar or xmtp.get_sidecar()
    try:
        stream_id = s.start_stream(gid)
    except xmtp.XmtpError as e:
        _log(f"stream_start failed: {e}")
        return False
    st["order_stream_id"] = stream_id
    state_mod.save(st)
    return True


def drain_recent_messages(
    sidecar: xmtp.Sidecar | None = None,
    max_items: int = 3,
) -> list[dict[str, Any]]:
    """Pop up to ``max_items`` recent Order-group messages from the stream
    queue. Non-blocking; returns empty list if no stream is running or
    no events have arrived since the last drain.
    """
    s = sidecar or xmtp.get_sidecar()
    try:
        return s.drain_stream_events(max_items=max_items)
    except Exception as e:
        _log(f"drain_stream_events failed: {e}")
        return []
