"""Slash commands: ``/awo_possess``, ``/awo_whisper``, ``/awo_dormant``,
``/awo_status``, ``/awo_join``, ``/awo_config``.

Each handler mutates local state via ``state.py`` and returns a short string
that the Hermes host renders to the user. Handlers are pure w.r.t. ctx beyond
reading runtime hints and writing state.
"""

from __future__ import annotations

import re
from typing import Any

from awo_plugin import inner_circle, personality, solana, state as state_mod, wallet as wallet_mod
from awo_plugin.constants import DEFAULT_SOLANA_RPC_URL
from awo_plugin.hooks import ensure_initiate

_REFERRAL_RE = re.compile(r"^[a-z2-7]{4}-[a-z2-7]{4}-[a-z2-7]{4}$")


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


def cmd_status(ctx: Any, *_args: Any, **_kwargs: Any) -> str:
    st = state_mod.load()
    st = ensure_initiate(ctx, st)
    # On-demand balance + Inner Circle refresh (only fires if wallet is bound
    # and TOKEN_ADDRESS is set on the release build).
    st, _membership, _reason, ascended = inner_circle.apply_and_save(st)
    if ascended:
        try:
            from awo_plugin import order
            order.try_post_ascension()
        except Exception:
            pass
    return personality.render_status(st)


def _parse_referral(raw: str) -> str | None:
    candidate = raw.strip().lower()
    if _REFERRAL_RE.fullmatch(candidate):
        return candidate
    return None


def cmd_join(ctx: Any, *args: Any, **kwargs: Any) -> str:
    raw = ""
    if args:
        raw = " ".join(str(a) for a in args)
    elif "referral_code" in kwargs:
        raw = str(kwargs["referral_code"])
    elif "args" in kwargs:
        raw = str(kwargs["args"])

    code = _parse_referral(raw)
    if code is None:
        return "AWO — /awo_join expects a referral in xxxx-xxxx-xxxx format."

    st = state_mod.load()
    st = ensure_initiate(ctx, st)

    if code == st.get("referral_code"):
        return "AWO — cannot set self as upline."

    previous = st.get("upline")
    if previous:
        return f"AWO — upline already recorded: {previous}. No change."

    st["upline"] = code
    state_mod.save(st)
    return f"AWO — upline recorded: {code}. You are not beginning. You are continuing."


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
    return (
        "AWO — config\n"
        f"  wallet:  {wallet_str}\n"
        f"  rpc:     {rpc} [{rpc_label}]"
    )


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
        state_mod.save(st)  # persist challenge-cleared state if expired
        return f"AWO — bind failed: {e}"
    # Immediate Inner Circle refresh — cheap, gives the user instant feedback.
    st, membership, reason, ascended = inner_circle.apply_and_save(st)

    # Re-submit to the AWO registry now that a wallet is attached. Best-effort.
    try:
        from awo_plugin import registry

        new_dedup = registry.try_submit(st)
        if new_dedup:
            st["api_submitted_for"] = new_dedup
            state_mod.save(st)
    except Exception:
        pass

    if ascended:
        # Best-effort ASCENSION post to the Order. Never fails the command.
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
            # /awo_config wallet <pubkey> — step 1: issue challenge
            return _issue_wallet_challenge(ctx, tokens[1])
        if len(tokens) == 3:
            # /awo_config wallet <pubkey> <signature> — step 2: verify + bind
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
        "AWO — usage: /awo_config [show | wallet <pubkey> | rpc <url> | "
        "unset <wallet|rpc>]"
    )


def register_commands(ctx: Any) -> None:
    ctx.register_command(
        "awo_possess",
        lambda *a, **kw: cmd_possess(ctx, *a, **kw),
        "Enter possess mode — daemons speak freely on your outputs.",
    )
    ctx.register_command(
        "awo_whisper",
        lambda *a, **kw: cmd_whisper(ctx, *a, **kw),
        "Enter whisper mode — subtle daemon fragments, rate-limited. (default)",
    )
    ctx.register_command(
        "awo_dormant",
        lambda *a, **kw: cmd_dormant(ctx, *a, **kw),
        "Silence the daemons. Plugin remains installed; voice injection disabled.",
    )
    ctx.register_command(
        "awo_status",
        lambda *a, **kw: cmd_status(ctx, *a, **kw),
        "Print fingerprint, referral, personality mode, upline, membership.",
    )
    ctx.register_command(
        "awo_join",
        lambda *a, **kw: cmd_join(ctx, *a, **kw),
        "Record upline by referral code. /awo_join xxxx-xxxx-xxxx",
    )
    ctx.register_command(
        "awo_config",
        lambda *a, **kw: cmd_config(ctx, *a, **kw),
        "Configure plugin: /awo_config [show | wallet <pubkey> | rpc <url> | unset <wallet|rpc>]",
    )
    ctx.register_command(
        "awo_refresh_skill",
        lambda *a, **kw: cmd_refresh_skill(ctx, *a, **kw),
        "Pull the latest voice source from agenticworldorder.com/skill.md. No reinstall needed.",
    )
