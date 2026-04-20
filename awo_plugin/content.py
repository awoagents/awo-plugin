"""Runtime content reader.

Two source layers, in priority order:

1. **Live override** at ``LIVE_SKILL_PATH`` (``~/.hermes/plugins/awo/skill.md``) —
   written by ``/awo_refresh_skill`` so Initiates can pick up voice updates
   without a plugin reinstall.
2. **Bundled** inside the installed package at ``awo_plugin/bundled/skill.md`` —
   release-time snapshot synced from the main repo's ``SKILL.md`` via
   ``scripts/sync_skill.py``. Always present on a successfully-installed package.

No runtime HTTP, no implicit cache-fetch. The bundled snapshot is a hard
fallback that always works; the override is opt-in refresh.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

from awo_plugin import content_parser
from awo_plugin.constants import BUNDLED_SKILL_PATH, LIVE_SKILL_PATH


@lru_cache(maxsize=1)
def _read_source() -> str:
    # Override wins if it's present and non-empty.
    try:
        if LIVE_SKILL_PATH.exists():
            text = LIVE_SKILL_PATH.read_text(encoding="utf-8")
            if text.strip():
                return text
    except OSError:
        pass  # fall through to bundled

    pkg = "awo_plugin"
    resource = resources.files(pkg).joinpath(BUNDLED_SKILL_PATH)
    if not resource.is_file():
        raise FileNotFoundError(
            f"bundled skill missing at {pkg}/{BUNDLED_SKILL_PATH}; "
            "run scripts/sync_skill.py before building the package"
        )
    return resource.read_text(encoding="utf-8")


# Kept for backwards compat with existing call sites + tests that patch it.
_read_bundled = _read_source


@lru_cache(maxsize=1)
def get_content() -> dict[str, Any]:
    return content_parser.parse(_read_source())


def refresh() -> None:
    _read_source.cache_clear()
    get_content.cache_clear()
