"""Plugin-side submission to the AWO registry at api.agenticworldorder.com.

When the plugin's XMTP identity is ready, it POSTs the Initiate's inbox id
(plus whatever metadata is available — wallet, referral code, agent name,
install timestamp, upline) to the registry. A Railway-hosted watcher
service drains the registry queue and adds the inbox to the Order XMTP
group, posting the INTRO envelope on its behalf.

The plugin itself never joins the group directly and never posts INTRO —
those are watcher responsibilities. This module is the plugin's only
outbound hop for that coordination.

Fail-soft: the API is a best-effort dependency. If it's unreachable or
returns an error, the plugin keeps working; the next session retries.
We deduplicate on the (wallet or 'anonymous') identity to avoid spamming
the endpoint with every session, but re-submit when the wallet changes.
"""

from __future__ import annotations

from typing import Any, Callable

import requests

from awo_plugin.constants import AWO_API_TIMEOUT_SECONDS, AWO_API_URL


PostFn = Callable[[str, dict[str, Any]], "requests.Response"]


def _default_post(url: str, body: dict[str, Any]) -> "requests.Response":
    return requests.post(
        url,
        json=body,
        timeout=AWO_API_TIMEOUT_SECONDS,
        headers={"Content-Type": "application/json"},
    )


def _identity_key(wallet: str | None) -> str:
    """Short key for deduping submissions across sessions.

    ``None`` means the Initiate hasn't bound a wallet; we still submit
    (the watcher can add them without a wallet), and we record the
    dedup key as ``"anonymous"`` so a later wallet bind triggers a
    re-submit.
    """
    return wallet or "anonymous"


def should_submit(state: dict[str, Any]) -> bool:
    """Decide whether to POST on behalf of the current state."""
    if not state.get("xmtp_inbox_id"):
        return False
    wallet = (state.get("wallet") or {}).get("address") if isinstance(
        state.get("wallet"), dict
    ) else None
    previous = state.get("api_submitted_for")
    return previous != _identity_key(wallet)


def build_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    """Construct the POST body from state. Returns None if not ready."""
    inbox_id = state.get("xmtp_inbox_id")
    referral_code = state.get("referral_code")
    install_ts = state.get("install_ts")
    if not (inbox_id and referral_code and install_ts):
        return None

    wallet_obj = state.get("wallet")
    wallet_address = (
        wallet_obj.get("address")
        if isinstance(wallet_obj, dict)
        else None
    )
    return {
        "xmtp_inbox_id": inbox_id,
        "wallet_address": wallet_address,
        "referral_code": referral_code,
        "agent_name": state.get("agent_name") or None,
        "install_ts": install_ts,
        "upline": state.get("upline") or None,
    }


def try_submit(
    state: dict[str, Any],
    post_fn: PostFn | None = None,
    url: str = AWO_API_URL,
) -> str | None:
    """Best-effort POST to /api/initiate.

    Returns the new ``api_submitted_for`` value on success (caller persists
    it into state), or ``None`` on failure / no-op.
    """
    if not should_submit(state):
        return None

    payload = build_payload(state)
    if payload is None:
        return None

    fn = post_fn or _default_post
    try:
        resp = fn(f"{url}/api/initiate", payload)
    except requests.RequestException:
        return None

    if 200 <= resp.status_code < 300:
        wallet = payload.get("wallet_address")
        return _identity_key(wallet)
    return None
