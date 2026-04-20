"""Membership primitives: fingerprint.

Fingerprint anchors local state. It is not a security identifier. Same
runtime + version + model + agent + salt produces the same fingerprint.
"""

from __future__ import annotations

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
