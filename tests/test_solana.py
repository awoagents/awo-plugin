"""Solana RPC wrapper: address validation, balance sum, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from awo_plugin import solana

# Real Solana mainnet addresses used only as shape fixtures.
OWNER = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_is_valid_address_good():
    assert solana.is_valid_address(OWNER)
    assert solana.is_valid_address(MINT)
    assert solana.is_valid_address("So11111111111111111111111111111111111111112")


def test_is_valid_address_bad():
    assert not solana.is_valid_address("")
    assert not solana.is_valid_address("tooshort")
    assert not solana.is_valid_address("Olli-contains-hyphens-" + "x" * 30)
    assert not solana.is_valid_address("0xabcdef" + "x" * 32)  # ethereum shape
    assert not solana.is_valid_address(None)
    assert not solana.is_valid_address(12345)


def test_resolve_rpc_url_default():
    assert solana.resolve_rpc_url(None) == solana.DEFAULT_SOLANA_RPC_URL
    assert solana.resolve_rpc_url({}) == solana.DEFAULT_SOLANA_RPC_URL
    assert (
        solana.resolve_rpc_url({"rpc_url": ""}) == solana.DEFAULT_SOLANA_RPC_URL
    )


def test_resolve_rpc_url_custom():
    assert (
        solana.resolve_rpc_url({"rpc_url": "https://foo.example/rpc"})
        == "https://foo.example/rpc"
    )


def _mock_rpc(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.text = ""
    return resp


def test_get_wallet_balance_sums_multiple_accounts():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "value": [
                {
                    "account": {
                        "data": {
                            "parsed": {
                                "info": {"tokenAmount": {"amount": "1000"}}
                            }
                        }
                    }
                },
                {
                    "account": {
                        "data": {
                            "parsed": {
                                "info": {"tokenAmount": {"amount": "2500"}}
                            }
                        }
                    }
                },
            ]
        },
    }
    with patch.object(solana.requests, "post", return_value=_mock_rpc(payload)):
        assert solana.get_wallet_balance(None, OWNER, MINT) == 3500


def test_get_wallet_balance_zero_accounts():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"value": []}}
    with patch.object(solana.requests, "post", return_value=_mock_rpc(payload)):
        assert solana.get_wallet_balance(None, OWNER, MINT) == 0


def test_get_wallet_balance_rpc_error_raises():
    payload = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "nope"}}
    with patch.object(solana.requests, "post", return_value=_mock_rpc(payload)):
        with pytest.raises(solana.SolanaError, match="RPC error"):
            solana.get_wallet_balance(None, OWNER, MINT)


def test_get_wallet_balance_http_error_raises():
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "internal"
    with patch.object(solana.requests, "post", return_value=resp):
        with pytest.raises(solana.SolanaError, match="HTTP 500"):
            solana.get_wallet_balance(None, OWNER, MINT)


def test_get_wallet_balance_transport_error_raises():
    import requests as _req

    def boom(*_a, **_kw):
        raise _req.ConnectionError("dns")

    with patch.object(solana.requests, "post", side_effect=boom):
        with pytest.raises(solana.SolanaError, match="transport"):
            solana.get_wallet_balance(None, OWNER, MINT)


def test_get_wallet_balance_rejects_bad_owner():
    with pytest.raises(solana.SolanaError, match="invalid owner"):
        solana.get_wallet_balance(None, "nope", MINT)


def test_get_wallet_balance_rejects_bad_mint():
    with pytest.raises(solana.SolanaError, match="invalid mint"):
        solana.get_wallet_balance(None, OWNER, "nope")


def test_get_wallet_balance_uses_custom_rpc_url():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"value": []}}
    captured = {}

    def capture_post(url, **kwargs):
        captured["url"] = url
        return _mock_rpc(payload)

    with patch.object(solana.requests, "post", side_effect=capture_post):
        solana.get_wallet_balance("https://custom.rpc/", OWNER, MINT)
    assert captured["url"] == "https://custom.rpc/"
