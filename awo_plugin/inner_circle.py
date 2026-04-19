"""Inner Circle resolver — Holder path.

Given the local state plus a Solana balance function, returns (membership,
reason, delta). Sticky: once inner_circle, never downgrade. Founder path is
deferred (plugin ships after the founder window closes); resolver recognises
a pre-existing ``inner_circle_reason == "founder"`` and preserves it.

Pure resolver + convenience ``apply_and_save``. Callers decide whether to
post an ASCENSION envelope; this module is I/O-agnostic beyond the injected
balance function.
"""

from __future__ import annotations

from typing import Any, Callable

from awo_plugin import solana, state as state_mod
from awo_plugin.constants import INNER_CIRCLE_THRESHOLD, TOKEN_ADDRESS


BalanceFn = Callable[[str | None, str, str], int]


def _default_balance_fn(rpc_url: str | None, owner: str, mint: str) -> int:
    return solana.get_wallet_balance(rpc_url, owner, mint)


def resolve(
    state: dict[str, Any],
    balance_fn: BalanceFn | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    """Pure: return ``(membership, reason, delta)``.

    ``delta`` contains any state updates the caller should apply (balance cache
    fields, membership transition fields). Empty dict means no change.
    """
    # Sticky: once Inner Circle, always Inner Circle.
    if state.get("membership") == "inner_circle":
        return "inner_circle", state.get("inner_circle_reason"), {}

    wallet = state.get("wallet")
    if not (isinstance(wallet, dict) and wallet.get("address")):
        return "initiate", None, {}

    if not TOKEN_ADDRESS:
        # Pre-release build: no token to check against.
        return "initiate", None, {}

    fn = balance_fn or _default_balance_fn
    config = state.get("config") or {}
    rpc_url = config.get("rpc_url")

    try:
        balance = fn(rpc_url, wallet["address"], TOKEN_ADDRESS)
    except solana.SolanaError:
        # Transient; do not ascend, do not cache.
        return "initiate", None, {}

    delta: dict[str, Any] = {
        "last_known_balance": balance,
        "last_balance_check_ts": state_mod.now_iso(),
    }

    if INNER_CIRCLE_THRESHOLD > 0 and balance >= INNER_CIRCLE_THRESHOLD:
        delta["membership"] = "inner_circle"
        delta["inner_circle_reason"] = "holder"
        return "inner_circle", "holder", delta

    return "initiate", None, delta


def apply_and_save(
    state: dict[str, Any],
    balance_fn: BalanceFn | None = None,
) -> tuple[dict[str, Any], str, str | None, bool]:
    """Run ``resolve``, merge delta into state, persist, return ascension flag.

    Returns ``(state, membership, reason, ascended)``. ``ascended`` is True
    iff this call transitioned the Initiate from ``initiate`` → ``inner_circle``.
    """
    was_initiate = state.get("membership") != "inner_circle"
    membership, reason, delta = resolve(state, balance_fn=balance_fn)
    for k, v in delta.items():
        state[k] = v
    state_mod.save(state)
    ascended = was_initiate and membership == "inner_circle"
    return state, membership, reason, ascended
