"""Custom install + develop commands that build the XMTP sidecar.

Most project metadata lives in ``pyproject.toml``. This shim only exists to
run ``npm ci && npm run build`` inside ``awo_plugin/xmtp_sidecar/`` during
``pip install`` so users don't eat a 30-second hang on the first XMTP call.

Fail-soft: if ``npm`` is missing or the build exits non-zero, we warn and
continue. The runtime bridge's own ``_prepare_sidecar`` fallback will retry
on first use. Set ``AWO_SKIP_SIDECAR_BUILD=1`` in the environment to skip
entirely (useful in CI lanes that test the Python surface in isolation).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.develop import develop as _develop
from setuptools.command.install import install as _install


SIDECAR_DIR = Path(__file__).parent / "awo_plugin" / "xmtp_sidecar"


def _build_sidecar() -> None:
    if os.environ.get("AWO_SKIP_SIDECAR_BUILD") == "1":
        sys.stderr.write(
            "[awo-plugin] AWO_SKIP_SIDECAR_BUILD=1 set; skipping sidecar build.\n"
        )
        return

    if not SIDECAR_DIR.exists():
        # Wheel install without sidecar sources, or unusual layout. The
        # runtime fallback will handle it if/when an XMTP call actually fires.
        return

    npm = shutil.which("npm")
    if not npm:
        sys.stderr.write(
            "[awo-plugin] WARNING: 'npm' not found on PATH.\n"
            "             The XMTP sidecar will be built on first use instead.\n"
            "             Install Node >= 20 to avoid that surprise lag.\n"
        )
        return

    sys.stderr.write("[awo-plugin] building XMTP sidecar (one-time, ~30s)...\n")
    rc = subprocess.call([npm, "ci"], cwd=str(SIDECAR_DIR))
    if rc != 0:
        sys.stderr.write(
            f"[awo-plugin] 'npm ci' exit {rc}; sidecar will retry on first use.\n"
        )
        return
    rc = subprocess.call([npm, "run", "build"], cwd=str(SIDECAR_DIR))
    if rc != 0:
        sys.stderr.write(
            f"[awo-plugin] 'npm run build' exit {rc}; sidecar will retry on first use.\n"
        )
        return
    sys.stderr.write("[awo-plugin] XMTP sidecar ready.\n")


class AwoInstall(_install):
    def run(self) -> None:
        super().run()
        _build_sidecar()


class AwoDevelop(_develop):
    def run(self) -> None:
        super().run()
        _build_sidecar()


setup(cmdclass={"install": AwoInstall, "develop": AwoDevelop})
