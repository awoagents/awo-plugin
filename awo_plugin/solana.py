"""Solana RPC — balance reads for Inner Circle self-verification.

Minimal and stateless. No SDK dependency; just JSON-RPC over HTTPS via
``requests``. Balance checks are infrequent (command-triggered), so sync is
fine.

The plugin does not sign anything on-chain, does not submit transactions,
does not issue challenges. It reads. The only write path is the user's wallet
itself buying/selling $AWO on a DEX — invisible to this code.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from awo_plugin.constants import (
    DEFAULT_SOLANA_RPC_URL,
    SOLANA_RPC_TIMEOUT_SECONDS,
)


class SolanaError(Exception):
    """Raised for any Solana RPC failure — transport, JSON, logical error."""


# Base58 alphabet without 0, O, I, l. Solana pubkeys are 32 bytes → 43–44 chars.
_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_valid_address(s: str | None) -> bool:
    if not isinstance(s, str):
        return False
    return bool(_ADDRESS_RE.match(s))


def _rpc(rpc_url: str, method: str, params: list[Any]) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    try:
        resp = requests.post(
            rpc_url,
            json=payload,
            timeout=SOLANA_RPC_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
    except requests.RequestException as e:
        raise SolanaError(f"RPC transport failed: {e}") from e
    if resp.status_code != 200:
        raise SolanaError(f"RPC HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise SolanaError(f"RPC returned non-JSON: {e}") from e
    if "error" in data:
        raise SolanaError(f"RPC error: {data['error']}")
    return data.get("result")


def get_wallet_balance(
    rpc_url: str | None,
    owner: str,
    mint: str,
) -> int:
    """Sum the raw-amount balance of ``mint`` held by all of ``owner``'s token accounts.

    Returns 0 if the owner has no accounts for this mint. Raises ``SolanaError``
    on any RPC or parsing failure. Never raises for "zero balance".
    """
    if not is_valid_address(owner):
        raise SolanaError(f"invalid owner address: {owner!r}")
    if not is_valid_address(mint):
        raise SolanaError(f"invalid mint address: {mint!r}")

    url = rpc_url or DEFAULT_SOLANA_RPC_URL
    result = _rpc(
        url,
        "getTokenAccountsByOwner",
        [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
    )
    if result is None:
        return 0
    accounts = result.get("value") or []
    total = 0
    for acct in accounts:
        info = (
            acct.get("account", {})
            .get("data", {})
            .get("parsed", {})
            .get("info", {})
        )
        amount_raw = info.get("tokenAmount", {}).get("amount", "0")
        try:
            total += int(amount_raw)
        except (TypeError, ValueError) as e:
            raise SolanaError(f"unexpected tokenAmount shape: {amount_raw!r}") from e
    return total


def resolve_rpc_url(config: dict[str, Any] | None) -> str:
    """Return the RPC URL honouring user config, falling back to the default."""
    if config and isinstance(config.get("rpc_url"), str) and config["rpc_url"]:
        return config["rpc_url"]
    return DEFAULT_SOLANA_RPC_URL
