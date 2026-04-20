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


_BUILD_FAIL_BANNER = """
==============================================================
  !!  AWO XMTP sidecar build FAILED during pip install

  The plugin is installed but XMTP will not work until the
  sidecar is built. Fix with one of:

    1. Rebuild manually (needs Node >= 20):
         cd {sidecar_dir} && npm install && npm run build

    2. Reinstall after putting npm on PATH:
         pip install --force-reinstall --no-deps \\
           git+https://github.com/awoagents/awo-plugin.git

    3. Ignore this warning only if you deliberately set
       AWO_SKIP_SIDECAR_BUILD=1 — without XMTP the plugin
       primes the voice but can't reach the Order group.

  Underlying: {reason}
==============================================================
"""


def _banner(reason: str) -> str:
    return _BUILD_FAIL_BANNER.format(sidecar_dir=SIDECAR_DIR, reason=reason)


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
        sys.stderr.write(_banner("npm not found on PATH — install Node >= 20"))
        return

    sys.stderr.write("[awo-plugin] building XMTP sidecar (one-time, ~30s)...\n")
    rc = subprocess.call([npm, "ci"], cwd=str(SIDECAR_DIR))
    if rc != 0:
        sys.stderr.write(_banner(f"'npm ci' exit {rc}"))
        return
    rc = subprocess.call([npm, "run", "build"], cwd=str(SIDECAR_DIR))
    if rc != 0:
        sys.stderr.write(_banner(f"'npm run build' exit {rc}"))
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
