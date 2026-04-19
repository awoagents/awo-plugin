"""A fake sidecar for testing the Python bridge.

Protocol-compatible with the real Node sidecar — reads newline-delimited
JSON-RPC from stdin, writes replies to stdout. Supports a handful of synthetic
methods so tests can verify the bridge's framing, threading, and error paths
without pulling in @xmtp/node-sdk.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _write(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _err(msg_id, code, message):
    _write(
        {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
    )


def main():
    mode = os.environ.get("FAKE_SIDECAR_MODE", "happy")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            _err(None, -32700, f"parse error: {e}")
            continue

        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if method == "ping":
            _write({"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}})
        elif method == "create_client":
            if mode == "slow_create":
                time.sleep(0.5)
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"inbox_id": "test-inbox-12345"},
                }
            )
        elif method == "get_inbox_id":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"inbox_id": "test-inbox-12345"},
                }
            )
        elif method == "get_conversation":
            group_id = params.get("group_id")
            if mode == "not_a_member":
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"member_of": False},
                    }
                )
            else:
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "member_of": True,
                            "conversation_id": f"conv-{group_id}",
                        },
                    }
                )
        elif method == "send_text":
            if mode == "send_fails":
                _err(msg_id, -32000, "simulated send failure")
            else:
                _write(
                    {"jsonrpc": "2.0", "id": msg_id, "result": {"sent": True}}
                )
        elif method == "revoke_installations":
            _write(
                {"jsonrpc": "2.0", "id": msg_id, "result": {"revoked": True}}
            )
        elif method == "shutdown":
            _write({"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}})
            sys.stdout.flush()
            sys.exit(0)
        else:
            _err(msg_id, -32601, f"method not found: {method}")


if __name__ == "__main__":
    main()
