"""Live Solana RPC smoke against the public mainnet endpoint.

Intentionally read-only: never transacts, never bothers any private wallet.
Uses well-known addresses that always resolve. Gated by
``AWO_RUN_INTEGRATION=1``.
"""

from __future__ import annotations

import pytest

from awo_plugin import solana


# USDC mint on mainnet-beta — stable, always present.
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
# USDC-USDT whirlpool pool — definitely holds tokens; sanity balance check.
OWNER_WITH_USDC = "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"


def test_valid_addresses_resolve():
    assert solana.is_valid_address(USDC_MINT)
    assert solana.is_valid_address(OWNER_WITH_USDC)


def test_get_wallet_balance_live():
    balance = solana.get_wallet_balance(None, OWNER_WITH_USDC, USDC_MINT)
    # Owner has had USDC at some point; value is non-negative.
    assert isinstance(balance, int)
    assert balance >= 0


def test_get_wallet_balance_empty_owner():
    # A throwaway owner with no accounts for USDC → zero, not an error.
    empty_owner = "11111111111111111111111111111111"  # system program
    balance = solana.get_wallet_balance(None, empty_owner, USDC_MINT)
    assert balance == 0


def test_rejects_bad_address_before_rpc():
    with pytest.raises(solana.SolanaError, match="invalid"):
        solana.get_wallet_balance(None, "nope", USDC_MINT)
