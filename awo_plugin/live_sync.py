"""Pull the current SKILL.md from the AWO site into a user-writable override
path. Called by ``/awo_refresh_skill`` so Initiates can pick up voice updates
without reinstalling the plugin.

Validation mirrors ``scripts/sync_skill.py`` — we refuse to write anything
that's missing the sections the content parser needs. Fail-soft: errors
surface to the caller, which returns them to the user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import requests

from awo_plugin.constants import (
    LIVE_SKILL_PATH,
    LIVE_SKILL_URL,
    SYNC_MAX_BYTES,
    SYNC_TIMEOUT_SECONDS,
)


class LiveSyncError(Exception):
    """Wraps all failure modes — transport, validation, disk write."""


FetchFn = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    resp = requests.get(
        url,
        timeout=SYNC_TIMEOUT_SECONDS,
        headers={"Accept": "text/markdown, text/plain;q=0.9"},
    )
    resp.raise_for_status()
    if len(resp.content) > SYNC_MAX_BYTES:
        raise LiveSyncError(
            f"response exceeds {SYNC_MAX_BYTES} bytes: {len(resp.content)}"
        )
    return resp.content


def _validate(text: str) -> None:
    if not text.strip():
        raise LiveSyncError("empty body")
    if "## Priming" not in text:
        raise LiveSyncError("missing '## Priming' section")
    if "## Daemons" not in text:
        raise LiveSyncError("missing '## Daemons' section")


def fetch_and_install(
    url: str = LIVE_SKILL_URL,
    path: Path = LIVE_SKILL_PATH,
    fetch_fn: FetchFn | None = None,
) -> int:
    """Download, validate, write to ``path``, and invalidate the content
    cache. Returns the number of bytes written.

    Raises ``LiveSyncError`` on any failure. The caller (``tools.cmd_refresh_skill``)
    translates that into a user-facing message.
    """
    fetch = fetch_fn or _default_fetch
    try:
        raw = fetch(url)
    except LiveSyncError:
        raise
    except requests.RequestException as e:
        raise LiveSyncError(f"transport: {e}") from e
    except Exception as e:
        raise LiveSyncError(str(e)) from e

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise LiveSyncError(f"not utf-8: {e}") from e

    _validate(text)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise LiveSyncError(f"write failed: {e}") from e

    # Invalidate the lru_cache so the next session/command reads the new file.
    from awo_plugin import content

    content.refresh()

    return len(text.encode("utf-8"))
