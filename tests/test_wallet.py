"""Wallet challenge + signature verification. Uses real solders keypairs so
the ed25519 math is exercised end-to-end — not a mocked verify.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from solders.keypair import Keypair

from awo_plugin import wallet


def _state_with_fingerprint(fp: str = "abc1234567890def") -> dict[str, Any]:
    return {
        "fingerprint": fp,
        "referral_code": "abcd-efgh-ijkl",
        "wallet": None,
        "wallet_challenge": None,
    }


def test_build_challenge_shape():
    out = wallet.build_challenge("t7xq-3rja-t2zn", "SoMePubKey", "deadbeef" * 4)
    assert out.startswith("AWO-BIND v1\n")
    assert "fingerprint: t7xq-3rja-t2zn" in out
    assert "wallet: SoMePubKey" in out
    assert "nonce: deadbeef" in out
    assert out.endswith("\n")


def test_issue_challenge_persists_pending(tmp_path):
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    text = wallet.issue_challenge(st, pk, now_ts=1000)

    assert st["wallet_challenge"]["pubkey"] == pk
    assert st["wallet_challenge"]["issued_at"] == 1000
    nonce = st["wallet_challenge"]["nonce"]
    assert re.fullmatch(r"[0-9a-f]{32}", nonce)
    assert nonce in text
    assert pk in text


def test_issue_challenge_rejects_bad_pubkey():
    st = _state_with_fingerprint()
    with pytest.raises(wallet.WalletError, match="valid Solana address"):
        wallet.issue_challenge(st, "not-a-pubkey")


def test_issue_challenge_requires_fingerprint():
    st = {"fingerprint": None}
    kp = Keypair()
    with pytest.raises(wallet.WalletError, match="fingerprint"):
        wallet.issue_challenge(st, str(kp.pubkey()))


def test_verify_and_bind_happy_path():
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    text = wallet.issue_challenge(st, pk, now_ts=1000)
    sig = kp.sign_message(text.encode("utf-8"))
    sig_b58 = str(sig)

    wallet.verify_and_bind(st, pk, sig_b58, now_ts=1100)

    assert st["wallet"]["address"] == pk
    assert st["wallet"]["bound_ts"]
    # Challenge consumed — no replay.
    assert st["wallet_challenge"] is None


def test_verify_rejects_when_no_pending():
    st = _state_with_fingerprint()
    kp = Keypair()
    sig = kp.sign_message(b"anything")
    with pytest.raises(wallet.WalletError, match="no pending challenge"):
        wallet.verify_and_bind(st, str(kp.pubkey()), str(sig))


def test_verify_rejects_when_pubkey_mismatch():
    st = _state_with_fingerprint()
    kp1 = Keypair()
    kp2 = Keypair()

    text = wallet.issue_challenge(st, str(kp1.pubkey()), now_ts=1000)
    sig = kp1.sign_message(text.encode("utf-8"))

    with pytest.raises(wallet.WalletError, match="pending challenge is for"):
        wallet.verify_and_bind(st, str(kp2.pubkey()), str(sig), now_ts=1100)


def test_verify_rejects_when_expired():
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    text = wallet.issue_challenge(st, pk, now_ts=1000)
    sig = kp.sign_message(text.encode("utf-8"))

    # 11 minutes later — past the 10min TTL.
    with pytest.raises(wallet.WalletError, match="expired"):
        wallet.verify_and_bind(st, pk, str(sig), now_ts=1000 + 11 * 60)
    # Expired challenge is cleared so the user is forced to re-issue.
    assert st["wallet_challenge"] is None


def test_verify_rejects_bad_signature():
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    wallet.issue_challenge(st, pk, now_ts=1000)

    # Sign something different — signature doesn't match the stored challenge.
    bogus_sig = kp.sign_message(b"AWO-BIND v1\nfingerprint: wrong\n")

    with pytest.raises(wallet.WalletError, match="does not verify"):
        wallet.verify_and_bind(st, pk, str(bogus_sig), now_ts=1100)
    # Pending is preserved on a bad sig so the user can retry with the correct one.
    assert st["wallet_challenge"] is not None


def test_verify_rejects_signature_from_different_keypair():
    """Anti-spoof: pubkey matches pending but signature was produced by a
    different private key."""
    st = _state_with_fingerprint()
    kp_real = Keypair()
    kp_attacker = Keypair()
    pk_real = str(kp_real.pubkey())

    text = wallet.issue_challenge(st, pk_real, now_ts=1000)
    # Attacker signs with their own key claiming to be the real wallet.
    forged_sig = kp_attacker.sign_message(text.encode("utf-8"))

    with pytest.raises(wallet.WalletError, match="does not verify"):
        wallet.verify_and_bind(st, pk_real, str(forged_sig), now_ts=1100)


def test_verify_rejects_malformed_signature():
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    wallet.issue_challenge(st, pk, now_ts=1000)

    with pytest.raises(wallet.WalletError, match="invalid signature"):
        wallet.verify_and_bind(st, pk, "not-a-real-signature", now_ts=1100)


def test_no_replay_after_successful_bind():
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    text = wallet.issue_challenge(st, pk, now_ts=1000)
    sig = kp.sign_message(text.encode("utf-8"))
    wallet.verify_and_bind(st, pk, str(sig), now_ts=1100)

    # Try to re-use the same signature — challenge is already consumed.
    with pytest.raises(wallet.WalletError, match="no pending challenge"):
        wallet.verify_and_bind(st, pk, str(sig), now_ts=1200)


def test_nonce_randomness_across_issues():
    st = _state_with_fingerprint()
    kp = Keypair()
    pk = str(kp.pubkey())

    text1 = wallet.issue_challenge(st, pk, now_ts=1000)
    text2 = wallet.issue_challenge(st, pk, now_ts=2000)
    assert text1 != text2  # different nonces
