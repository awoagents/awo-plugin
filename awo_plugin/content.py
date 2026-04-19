"""Runtime content reader.

Reads the bundled ``skill.md`` from the installed package — no network, no
cache, no retries. Source of truth at release time is ``SKILL.md`` at the
repo root, synced by ``scripts/sync_skill.py``.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

from awo_plugin import content_parser
from awo_plugin.constants import BUNDLED_SKILL_PATH


@lru_cache(maxsize=1)
def _read_bundled() -> str:
    pkg = "awo_plugin"
    resource = resources.files(pkg).joinpath(BUNDLED_SKILL_PATH)
    if not resource.is_file():
        raise FileNotFoundError(
            f"bundled skill missing at {pkg}/{BUNDLED_SKILL_PATH}; "
            "run scripts/sync_skill.py before building the package"
        )
    return resource.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def get_content() -> dict[str, Any]:
    return content_parser.parse(_read_bundled())


def refresh() -> None:
    _read_bundled.cache_clear()
    get_content.cache_clear()
