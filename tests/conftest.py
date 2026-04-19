"""Test isolation — prevent accidental XMTP sidecar spawns.

Before this file existed the plugin's unit tests relied on ``npm`` being
absent to short-circuit ``xmtp.get_sidecar().ensure_started()``. Once the
sidecar is actually buildable (lockfile + node_modules present), every
test that hit ``order.ensure_xmtp_up`` started connecting to the real
XMTP production network — 60+ seconds per test.

This autouse fixture replaces the module-level sidecar singleton with a
``MagicMock`` so tests never spawn a Node process or talk to XMTP.

Tests that *do* exercise the bridge (``test_xmtp.py``) construct their
own ``Sidecar`` directly with a fake-sidecar subprocess — those bypass
the singleton and are not affected by this stub.

Tests that exercise ``order.py`` pass an explicit ``sidecar=`` argument;
those also bypass the stub.

Real XMTP-network tests live under ``tests/integration/`` and are gated
by ``AWO_RUN_INTEGRATION=1``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_default_sidecar_singleton(request, monkeypatch):
    # test_xmtp.py exercises the bridge + singleton directly and must see
    # the real surface; everyone else gets a mock to keep tests offline.
    if "test_xmtp" in str(request.node.fspath):
        return

    from awo_plugin import xmtp

    mock = MagicMock(spec=xmtp.Sidecar)
    mock.ensure_started.return_value = "test-inbox-id"
    mock.get_inbox_id.return_value = "test-inbox-id"
    mock.get_conversation.return_value = {"member_of": False}
    mock.send_text.return_value = {"sent": True}
    mock.revoke_installations.return_value = {"revoked": True}
    mock.start_stream.return_value = "test-stream-id"
    mock.stop_stream.return_value = True
    mock.drain_stream_events.return_value = []

    monkeypatch.setattr(xmtp, "get_sidecar", lambda: mock)
