"""Integration-test gate.

Set ``AWO_RUN_INTEGRATION=1`` to run these against live networks.
Left unset, every test in ``tests/integration/`` is skipped.
"""

from __future__ import annotations

import os

import pytest


collect_ignore_glob: list[str] = []


def pytest_collection_modifyitems(config, items):
    if os.environ.get("AWO_RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="set AWO_RUN_INTEGRATION=1 to run")
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(skip)
