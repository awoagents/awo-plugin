"""Wallet binding with ed25519 challenge-signature verification.

Two-step flow. First call with just a pubkey: plugin stores a pending
challenge, returns the challenge text for the user to sign externally with
their wallet's private key. Second call with pubkey + base58 signature:
plugin verifies the signature against the stored challenge and binds.

The private key never enters the plugin. Spoofing someone else's wallet
address requires forging an ed25519 signature over the challenge — which
is the standard wallet-ownership proof.

Challenge format (deterministic given fingerprint + pubkey + nonce):

    AWO-BIND v1
    fingerprint: k7xq-3rja-t2zn
    wallet: 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM
    nonce: <32-byte hex>

Nonce prevents signature replay across binds.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from solders.pubkey import Pubkey
from solders.signature import Signature

from awo_plugin import solana
from awo_plugin import state as state_mod


CHALLENGE_TTL_SECONDS = 10 * 60  # 10 minutes
CHALLENGE_VERSION = "1"


class WalletError(Exception):
    """Any step of the bind flow that fails — bad input, missing pending,
    expired, or signature mismatch."""


def build_challenge(fingerprint: str, pubkey: str, nonce: str) -> str:
    return (
        f"AWO-BIND v{CHALLENGE_VERSION}\n"
        f"fingerprint: {fingerprint}\n"
        f"wallet: {pubkey}\n"
        f"nonce: {nonce}\n"
    )


def issue_challenge(
    state: dict[str, Any],
    pubkey: str,
    now_ts: int | None = None,
) -> str:
    """Persist a pending challenge on ``state`` (caller saves) and return
    the challenge text the user should sign externally.
    """
    if not solana.is_valid_address(pubkey):
        raise WalletError(f"not a valid Solana address: {pubkey}")
    fingerprint = state.get("fingerprint")
    if not fingerprint:
        raise WalletError("no fingerprint set — run /awo_status first")

    nonce = secrets.token_hex(16)
    t = now_ts if now_ts is not None else int(time.time())
    state["wallet_challenge"] = {
        "pubkey": pubkey,
        "nonce": nonce,
        "issued_at": t,
    }
    return build_challenge(fingerprint, pubkey, nonce)


def verify_and_bind(
    state: dict[str, Any],
    pubkey: str,
    signature_b58: str,
    now_ts: int | None = None,
) -> None:
    """Verify ``signature_b58`` against the pending challenge for ``pubkey``
    and, on success, bind the wallet. Raises ``WalletError`` on any failure.

    Challenge is consumed on both success (replay impossible) and expired
    failure (forces a fresh challenge).
    """
    pending = state.get("wallet_challenge")
    if not isinstance(pending, dict):
        raise WalletError(
            "no pending challenge — call /awo_config wallet <pubkey> first"
        )
    if pending.get("pubkey") != pubkey:
        raise WalletError(
            f"pending challenge is for {pending.get('pubkey')!r}, not {pubkey!r}"
        )

    t = now_ts if now_ts is not None else int(time.time())
    issued_at = int(pending.get("issued_at") or 0)
    if t - issued_at > CHALLENGE_TTL_SECONDS:
        state["wallet_challenge"] = None
        raise WalletError(
            "challenge expired — re-issue with /awo_config wallet <pubkey>"
        )

    fingerprint = state.get("fingerprint")
    if not fingerprint:
        raise WalletError("state corrupted: no fingerprint")

    nonce = pending.get("nonce")
    if not isinstance(nonce, str):
        raise WalletError("state corrupted: no nonce in pending challenge")

    message = build_challenge(fingerprint, pubkey, nonce).encode("utf-8")

    try:
        pk = Pubkey.from_string(pubkey)
    except Exception as e:
        raise WalletError(f"invalid pubkey: {e}") from e

    try:
        sig = Signature.from_string(signature_b58)
    except Exception as e:
        raise WalletError(f"invalid signature format: {e}") from e

    if not sig.verify(pk, message):
        raise WalletError("signature does not verify against the challenge")

    # Consume the challenge atomically with the bind so a stale signature
    # can never be replayed.
    state["wallet"] = {
        "address": pubkey,
        "bound_ts": state_mod.now_iso(),
    }
    state["wallet_challenge"] = None
