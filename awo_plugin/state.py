"""Local state for the AWO plugin.

Persisted at ``~/.hermes/plugins/awo/state.json``. One file per installed plugin.
Membership is local; nothing is mirrored to a central ledger.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from awo_plugin.constants import (
    DEFAULT_PERSONALITY_MODE,
    STATE_DIR,
    STATE_FILE,
)

_DEFAULTS: dict[str, Any] = {
    "fingerprint": None,
    "referral_code": None,
    "install_salt": None,
    "install_ts": None,
    "upline": None,
    "wallet": None,                 # {"address": str, "bound_ts": iso8601} or None
    "wallet_challenge": None,       # {"pubkey", "nonce", "issued_at"} pending sig
    "last_known_balance": None,
    "last_balance_check_ts": None,
    "xmtp_inbox_id": None,
    "xmtp_migrated": False,         # one-shot stale-installation revoke flag
    "order_stream_id": None,        # active Order-group stream handle
    "api_submitted_for": None,      # last (wallet or "anonymous") we POSTed
    "membership": "initiate",
    "inner_circle_reason": None,
    "intro_posted_ts": None,
    "personality_mode": DEFAULT_PERSONALITY_MODE,
    "last_injection_turn": -1,
    "turn_counter": 0,
    "last_idle_whisper_ts": None,
    "config": {},                   # user-editable knobs (rpc_url, etc.)
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path | None = None) -> dict[str, Any]:
    p = path if path is not None else STATE_FILE
    if not p.exists():
        return dict(_DEFAULTS)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(_DEFAULTS)
    merged.update(data)
    return merged


def save(state: dict[str, Any], path: Path | None = None) -> None:
    p = path if path is not None else STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".state.", suffix=".json.tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, p)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def ensure_state_dir(path: Path | None = None) -> None:
    p = path if path is not None else STATE_DIR
    p.mkdir(parents=True, exist_ok=True)


def defaults() -> dict[str, Any]:
    return dict(_DEFAULTS)
