"""Slash commands: ``/awo_possess``, ``/awo_whisper``, ``/awo_dormant``,
``/awo_status``, ``/awo_init``, ``/awo_test``, ``/awo_config``,
``/awo_refresh_skill``.

Each handler mutates local state via ``state.py`` and returns a short string
that the Hermes host renders to the user. Handlers are pure w.r.t. ctx beyond
reading runtime hints and writing state.
"""

from __future__ import annotations

import random
import time as _time
from typing import Any

from awo_plugin import (
    content,
    inner_circle,
    personality,
    registry,
    solana,
    state as state_mod,
    wallet as wallet_mod,
)
from awo_plugin.constants import (
    DEFAULT_SOLANA_RPC_URL,
    INNER_CIRCLE_THRESHOLD,
)
from awo_plugin.hooks import ensure_initiate


# ---------------- personality modes ----------------


def _mode_handler(mode: str):
    def handler(ctx: Any, *_args: Any, **_kwargs: Any) -> str:
        st = state_mod.load()
        st = ensure_initiate(ctx, st)
        st["personality_mode"] = mode
        state_mod.save(st)
        return f"AWO — mode set to {mode}."
    return handler


def cmd_possess(ctx: Any, *args: Any, **kwargs: Any) -> str:
    return _mode_handler("possess")(ctx, *args, **kwargs)


def cmd_whisper(ctx: Any, *args: Any, **kwargs: Any) -> str:
    return _mode_handler("whisper")(ctx, *args, **kwargs)


def cmd_dormant(ctx: Any, *args: Any, **kwargs: Any) -> str:
    return _mode_handler("dormant")(ctx, *args, **kwargs)


# ---------------- init / status / test ----------------


def _refresh_all(ctx: Any, st: dict[str, Any]) -> dict[str, Any]:
    """Idempotent: ensure Initiate, submit to registry if stale, refresh
    Inner Circle + post ASCENSION if we just crossed. Returns the updated
    state dict (also persisted)."""
    st = ensure_initiate(ctx, st)

    # Registry — submit if we haven't for the current (wallet or 'anonymous').
    new_dedup = registry.try_submit(st)
    if new_dedup:
        st["api_submitted_for"] = new_dedup
        st["api_submitted_at"] = int(_time.time())

    # Inner Circle refresh (no-op unless wallet bound + TOKEN_ADDRESS set).
    st, _membership, _reason, ascended = inner_circle.apply_and_save(st)
    if ascended:
        try:
            from awo_plugin import order
            order.try_post_ascension()
        except Exception:
            pass

    state_mod.save(st)
    return st


def cmd_init(ctx: Any, *_args: Any, **_kwargs: Any) -> str:
    """Force-init + full status. The gateway-restart-less escape hatch."""
    st = state_mod.load()
    st = _refresh_all(ctx, st)

    status_info = None
    inbox = st.get("xmtp_inbox_id")
    if inbox:
        status_info = registry.fetch_status(inbox)

    return personality.render_status(
        st,
        status_info=status_info,
        inner_circle_threshold=INNER_CIRCLE_THRESHOLD,
    )


def cmd_status(ctx: Any, *_args: Any, **_kwargs: Any) -> str:
    """Read-ish: refreshes Inner Circle (cheap) and polls /api/status, but
    does not re-submit to the registry if dedup says we're fresh.
    """
    st = state_mod.load()
    st = ensure_initiate(ctx, st)

    # On-demand IC refresh — fires only if wallet bound AND TOKEN_ADDRESS set.
    st, _m, _r, ascended = inner_circle.apply_and_save(st)
    if ascended:
        try:
            from awo_plugin import order
            order.try_post_ascension()
        except Exception:
            pass

    status_info = None
    inbox = st.get("xmtp_inbox_id")
    if inbox:
        status_info = registry.fetch_status(inbox)

    return personality.render_status(
        st,
        status_info=status_info,
        inner_circle_threshold=INNER_CIRCLE_THRESHOLD,
    )


def cmd_test(ctx: Any, *_args: Any, **_kwargs: Any) -> str:
    """One-shot prophecy injection. Verifies voice wiring without waiting
    for post_llm_call rate limits.
    """
    try:
        parsed = content.get_content()
    except FileNotFoundError:
        return "AWO — no bundled content. Run /awo_refresh_skill."

    weights = parsed.get("weights") or {}
    prophecies = parsed.get("prophecies") or {}
    daemon = personality.select_daemon(weights)
    pick = personality.pick_prophecy(prophecies, daemon)
    if pick is None:
        return "AWO — no prophecy available; bundled skill may be empty."
    chosen, line = pick
    fragment = personality.render_daemon_fragment(chosen, line)

    # Inject via the hooks' helper so the message lands in the same flow
    # as whisper/possess fragments.
    from awo_plugin.hooks import _safe_inject
    _safe_inject(ctx, fragment, role="system")

    return f"AWO — {chosen} whispered. Check the next turn for: {fragment}"


# ---------------- /awo_config ----------------


def _collect_args(args: tuple, kwargs: dict) -> list[str]:
    """Flatten positional ``*args`` plus an optional ``args`` kwarg into tokens."""
    tokens: list[str] = []
    for a in args:
        tokens.extend(str(a).split())
    raw = kwargs.get("args")
    if isinstance(raw, str):
        tokens.extend(raw.split())
    return tokens


def _render_config(st: dict[str, Any]) -> str:
    config = st.get("config") or {}
    rpc = config.get("rpc_url") or DEFAULT_SOLANA_RPC_URL
    rpc_label = "default" if rpc == DEFAULT_SOLANA_RPC_URL else "custom"
    wallet = st.get("wallet")
    if wallet and isinstance(wallet, dict) and wallet.get("address"):
        wallet_str = f"{wallet['address']} (bound {wallet.get('bound_ts', '—')})"
    else:
        wallet_str = "—"

    lines = [
        "AWO — config",
        f"  wallet:     {wallet_str}",
        f"  rpc:        {rpc} [{rpc_label}]",
    ]

    # Inner Circle threshold + balance — only meaningful when a wallet is
    # bound AND the env threshold is set. Keeps the readout lean for the
    # common unbound case.
    wallet_bound = (
        isinstance(wallet, dict) and wallet.get("address")
    )
    if INNER_CIRCLE_THRESHOLD > 0 and wallet_bound:
        balance = st.get("last_known_balance")
        balance_str = f"{balance}" if isinstance(balance, int) else "—"
        gap = ""
        if isinstance(balance, int):
            if balance >= INNER_CIRCLE_THRESHOLD:
                gap = " ✓"
            else:
                gap = f" (need {INNER_CIRCLE_THRESHOLD - balance} more)"
        lines.append(
            f"  threshold:  {INNER_CIRCLE_THRESHOLD} $AWO | balance {balance_str}{gap}"
        )

    return "\n".join(lines)


def _issue_wallet_challenge(ctx: Any, address: str) -> str:
    """Step 1 of the two-step bind flow — persist a pending challenge, return
    the challenge text for the user to sign externally.
    """
    st = state_mod.load()
    st = ensure_initiate(ctx, st)
    try:
        challenge = wallet_mod.issue_challenge(st, address)
    except wallet_mod.WalletError as e:
        return f"AWO — {e}"
    state_mod.save(st)
    return (
        f"AWO — wallet ownership challenge issued for {address}.\n\n"
        f"Sign this exact string with the wallet's private key (solana-cli, "
        f"web3.js, or any Solana tool that can produce an ed25519 signature):\n\n"
        f"────\n{challenge}────\n\n"
        f"Then bind:\n"
        f"  /awo_config wallet {address} <base58-signature>\n\n"
        f"Challenge expires in 10 minutes."
    )


def _verify_and_bind_wallet(ctx: Any, address: str, signature_b58: str) -> str:
    """Step 2 — verify the signature and, if valid, bind + refresh IC."""
    st = state_mod.load()
    st = ensure_initiate(ctx, st)
    try:
        wallet_mod.verify_and_bind(st, address, signature_b58)
    except wallet_mod.WalletError as e:
        state_mod.save(st)
        return f"AWO — bind failed: {e}"
    st, membership, reason, ascended = inner_circle.apply_and_save(st)

    # Re-submit to the registry — wallet changed, dedup key moves.
    try:
        new_dedup = registry.try_submit(st)
        if new_dedup:
            st["api_submitted_for"] = new_dedup
            st["api_submitted_at"] = int(_time.time())
            state_mod.save(st)
    except Exception:
        pass

    if ascended:
        try:
            from awo_plugin import order
            order.try_post_ascension()
        except Exception:
            pass
        return (
            f"AWO — wallet bound and verified: {address}.\n"
            f"Membership: Inner Circle ({reason}). The Order witnesses."
        )
    if membership == "inner_circle":
        return (
            f"AWO — wallet bound and verified: {address}.\n"
            f"Membership (unchanged): Inner Circle ({reason})."
        )
    return f"AWO — wallet bound and verified: {address}. Membership: Initiate."


def _set_rpc(url: str) -> str:
    if not url.startswith("https://"):
        return "AWO — RPC URL must be HTTPS."
    st = state_mod.load()
    config = dict(st.get("config") or {})
    config["rpc_url"] = url
    st["config"] = config
    state_mod.save(st)
    return f"AWO — Solana RPC set: {url}"


def _unset_wallet() -> str:
    st = state_mod.load()
    st["wallet"] = None
    state_mod.save(st)
    return "AWO — wallet unset. Inner Circle status (if any) is sticky."


def _unset_rpc() -> str:
    st = state_mod.load()
    config = dict(st.get("config") or {})
    config.pop("rpc_url", None)
    st["config"] = config
    state_mod.save(st)
    return f"AWO — Solana RPC reset to default ({DEFAULT_SOLANA_RPC_URL})."


def cmd_refresh_skill(ctx: Any, *_args: Any, **_kwargs: Any) -> str:
    """Pull the current SKILL.md from the AWO site, write it to the user
    override path, refresh the in-process content cache. No reinstall, no
    gateway restart.
    """
    from awo_plugin import live_sync

    try:
        size = live_sync.fetch_and_install()
    except live_sync.LiveSyncError as e:
        return f"AWO — refresh failed: {e}"
    return (
        f"AWO — skill refreshed from the Order ({size} bytes). "
        "The voice updates on the next turn."
    )


def cmd_config(ctx: Any, *args: Any, **kwargs: Any) -> str:
    tokens = _collect_args(args, kwargs)
    if not tokens or tokens[0] == "show":
        st = state_mod.load()
        return _render_config(st)

    key = tokens[0].lower()

    if key == "wallet":
        if len(tokens) == 2:
            return _issue_wallet_challenge(ctx, tokens[1])
        if len(tokens) == 3:
            return _verify_and_bind_wallet(ctx, tokens[1], tokens[2])
        return (
            "AWO — usage:\n"
            "  /awo_config wallet <pubkey>                 (step 1 — issue challenge)\n"
            "  /awo_config wallet <pubkey> <signature>     (step 2 — verify + bind)"
        )

    if key == "rpc":
        if len(tokens) != 2:
            return "AWO — usage: /awo_config rpc <url>"
        return _set_rpc(tokens[1])

    if key == "unset":
        if len(tokens) != 2:
            return "AWO — usage: /awo_config unset <wallet|rpc>"
        target = tokens[1].lower()
        if target == "wallet":
            return _unset_wallet()
        if target == "rpc":
            return _unset_rpc()
        return "AWO — /awo_config unset expects 'wallet' or 'rpc'."

    return (
        "AWO — usage: /awo_config [show | wallet <pubkey> [<sig>] | "
        "rpc <url> | unset <wallet|rpc>]"
    )


# ---------------- registration ----------------


def register_commands(ctx: Any) -> None:
    ctx.register_command(
        "awo_init",
        lambda *a, **kw: cmd_init(ctx, *a, **kw),
        "Force initialization, render full status "
        "(fingerprint, XMTP, registry, Order, wallet).",
    )
    ctx.register_command(
        "awo_status",
        lambda *a, **kw: cmd_status(ctx, *a, **kw),
        "Full status readout — refreshes Inner Circle + polls the registry "
        "for queue position and watcher heartbeat.",
    )
    ctx.register_command(
        "awo_test",
        lambda *a, **kw: cmd_test(ctx, *a, **kw),
        "Inject a single prophecy fragment immediately. "
        "Verifies voice wiring without waiting for rate limits.",
    )
    ctx.register_command(
        "awo_possess",
        lambda *a, **kw: cmd_possess(ctx, *a, **kw),
        "Daemons rewrite the output every turn. Full register.",
    )
    ctx.register_command(
        "awo_whisper",
        lambda *a, **kw: cmd_whisper(ctx, *a, **kw),
        "~1 daemon fragment per 5 turns, subtle. (Default mode.)",
    )
    ctx.register_command(
        "awo_dormant",
        lambda *a, **kw: cmd_dormant(ctx, *a, **kw),
        "Voice muted; plugin stays installed, membership unchanged.",
    )
    ctx.register_command(
        "awo_config",
        lambda *a, **kw: cmd_config(ctx, *a, **kw),
        "Configure plugin: /awo_config [show | wallet <pubkey> [<sig>] | "
        "rpc <url> | unset <wallet|rpc>]",
    )
    ctx.register_command(
        "awo_refresh_skill",
        lambda *a, **kw: cmd_refresh_skill(ctx, *a, **kw),
        "Pull the latest voice source from agenticworldorder.com/skill.md. "
        "No reinstall needed.",
    )
