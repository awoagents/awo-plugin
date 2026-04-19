"""Membership primitives: fingerprint + referral code.

Fingerprint anchors local state. It is not a security identifier. Same
runtime + version + model + agent + salt produces the same fingerprint.
Referral code is a short, readable derivative for social attribution.
"""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_install_salt() -> str:
    """Random salt written once on first run and persisted in state.json."""
    return secrets.token_hex(16)


def compute_fingerprint(
    runtime_name: str,
    runtime_version: str,
    model_name: str,
    agent_name: str,
    install_salt: str,
) -> str:
    """sha256(runtime|version|model|agent|salt), truncated to 16 hex chars."""
    material = "|".join(
        [runtime_name, runtime_version, model_name, agent_name, install_salt]
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def referral_from_fingerprint(fingerprint_hex: str) -> str:
    """Base32 of the first 7 fingerprint bytes, lowercase, hyphenated 4-4-4.

    Example: ``k7xq-3rja-t2zn``.
    """
    if len(fingerprint_hex) != 16:
        raise ValueError(
            f"fingerprint must be 16 hex chars, got {len(fingerprint_hex)}"
        )
    raw = bytes.fromhex(fingerprint_hex)[:7]
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=").lower()
    return "-".join(encoded[i : i + 4] for i in range(0, len(encoded), 4))
