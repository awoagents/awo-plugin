"""Live XMTP sidecar smoke.

Requires ``npm`` on PATH and a working network (XMTP production). Gated by
``AWO_RUN_INTEGRATION=1``. Spins up the sidecar, creates a fresh identity,
calls ``get_conversation`` for a bogus group id (expects ``member_of: false``),
shuts down.

This does NOT post to the real Order group. Pre-launch smoke only — run
manually against a throwaway install directory.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from awo_plugin import xmtp


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    """Redirect the XMTP key + DB into a tmp dir so production state stays clean."""
    home_fake = tmp_path / "home"
    home_fake.mkdir()
    monkeypatch.setenv("HOME", str(home_fake))
    yield home_fake


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm not on PATH")
def test_sidecar_ping(fresh_install):
    s = xmtp.Sidecar(env="production", auto_install=True)
    try:
        resp = s.call("ping")
        assert resp == {"ok": True}
    finally:
        s.close()


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm not on PATH")
def test_sidecar_create_client(fresh_install):
    s = xmtp.Sidecar(env="production", auto_install=True)
    try:
        inbox = s.ensure_started(timeout=180.0)
        assert isinstance(inbox, str) and inbox
    finally:
        s.close()


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm not on PATH")
def test_sidecar_not_a_member_of_bogus_group(fresh_install):
    s = xmtp.Sidecar(env="production", auto_install=True)
    try:
        s.ensure_started(timeout=180.0)
        resp = s.get_conversation("bogus-nonexistent-group-id-12345")
        assert resp["member_of"] is False
    finally:
        s.close()
