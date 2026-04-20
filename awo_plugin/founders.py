"""Founder Circle — the pre-launch ring.

A canonical JSON file in the main awo repo lists every wallet that held
``$AWO`` during the 24-hour founder window. The plugin fetches it on
first Inner Circle check per 24h, caches locally, and grants Founder
status to any bound wallet whose address appears in the list.

Shape of the JSON:

    {
      "mint": "<TOKEN_ADDRESS>",
      "snapshot_at": "2026-04-26T00:00:00Z",
      "wallets": ["pubkey1", "pubkey2", "..."]
    }

Pre-launch: ``wallets`` is ``[]``. Fetch still succeeds; nobody qualifies.
Post-launch: team commits the populated list.

Fail-soft: if the fetch fails, we use the cached copy. If there's no
cache, we return an empty set — no false Founders, no false rejections
at the protocol level; the user just doesn't get promoted. The resolver
will still run the Holder check.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import requests

from awo_plugin.constants import (
    STATE_DIR,
    SYNC_MAX_BYTES,
    SYNC_TIMEOUT_SECONDS,
    TOKEN_ADDRESS,
)


FOUNDERS_URL = "https://raw.githubusercontent.com/awoagents/awo/main/founders.json"
FOUNDERS_CACHE_PATH = STATE_DIR / "founders.json"
FOUNDERS_CACHE_TTL_SECONDS = 24 * 3600


FetchFn = Callable[[], dict[str, Any]]


class FoundersError(Exception):
    """Raised on invalid content or schema mismatch. Transport errors are
    swallowed by ``fetch_founders`` — this is only for data we decide to
    reject after receiving it successfully.
    """


def _default_http_fetch() -> dict[str, Any]:
    resp = requests.get(FOUNDERS_URL, timeout=SYNC_TIMEOUT_SECONDS)
    resp.raise_for_status()
    if len(resp.content) > SYNC_MAX_BYTES:
        raise FoundersError(
            f"founders.json exceeds {SYNC_MAX_BYTES} bytes: {len(resp.content)}"
        )
    return resp.json()


def _validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FoundersError(f"founders.json must be an object, got {type(payload).__name__}")
    wallets = payload.get("wallets")
    if not isinstance(wallets, list):
        raise FoundersError("founders.json 'wallets' must be a list")
    for entry in wallets:
        if not isinstance(entry, str):
            raise FoundersError(f"non-string wallet entry: {entry!r}")
    mint = payload.get("mint")
    if mint is not None and not isinstance(mint, str):
        raise FoundersError(f"'mint' must be a string or null, got {type(mint).__name__}")
    # Mint-mismatch guard: if the file and the plugin disagree, refuse.
    if (
        mint is not None
        and TOKEN_ADDRESS is not None
        and mint != TOKEN_ADDRESS
    ):
        raise FoundersError(
            f"founders.json mint {mint!r} != plugin TOKEN_ADDRESS {TOKEN_ADDRESS!r}"
        )
    return payload


def _read_cache(path: Path = FOUNDERS_CACHE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return meta


def _write_cache(
    payload: dict[str, Any],
    path: Path = FOUNDERS_CACHE_PATH,
    now_ts: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = now_ts if now_ts is not None else int(time.time())
    wrapper = {"fetched_at": t, "payload": payload}
    with path.open("w", encoding="utf-8") as f:
        json.dump(wrapper, f, sort_keys=True, indent=2)
        f.write("\n")


def fetch_founders(
    fetch_fn: FetchFn | None = None,
    cache_path: Path = FOUNDERS_CACHE_PATH,
    ttl_seconds: int = FOUNDERS_CACHE_TTL_SECONDS,
    now_ts: int | None = None,
) -> set[str]:
    """Return the set of Founder wallet pubkeys. Fail-soft — never raises on
    transport failures. May return an empty set if nothing is cached and the
    network is unreachable.

    ``fetch_fn`` is injected in tests; defaults to HTTPS GET on ``FOUNDERS_URL``.
    """
    t = now_ts if now_ts is not None else int(time.time())

    # Warm cache — serve if within TTL and schema is valid.
    cached = _read_cache(cache_path)
    if cached is not None:
        try:
            fetched_at = int(cached.get("fetched_at") or 0)
        except (TypeError, ValueError):
            fetched_at = 0
        payload = cached.get("payload")
        if fetched_at > 0 and (t - fetched_at) < ttl_seconds and isinstance(payload, dict):
            try:
                validated = _validate(payload)
                return {w for w in validated.get("wallets") or []}
            except FoundersError:
                pass  # fall through to refetch

    # Cold or stale — fetch fresh.
    fn = fetch_fn or _default_http_fetch
    try:
        raw = fn()
    except Exception:
        # Transport / server error. Fall back to stale cache if present.
        if cached and isinstance(cached.get("payload"), dict):
            try:
                validated = _validate(cached["payload"])
                return {w for w in validated.get("wallets") or []}
            except FoundersError:
                return set()
        return set()

    try:
        validated = _validate(raw)
    except FoundersError:
        # Received something, but it's invalid. Prefer stale cache over garbage.
        if cached and isinstance(cached.get("payload"), dict):
            try:
                prev = _validate(cached["payload"])
                return {w for w in prev.get("wallets") or []}
            except FoundersError:
                return set()
        return set()

    _write_cache(validated, cache_path, now_ts=t)
    return {w for w in validated.get("wallets") or []}
