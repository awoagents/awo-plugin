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
        elif method == "stream_start":
            group_id = params.get("group_id") or "unknown"
            stream_id = f"fake-stream-{group_id}"
            _write(
                {"jsonrpc": "2.0", "id": msg_id, "result": {"stream_id": stream_id}}
            )
            # If mode requests it, emit a burst of synthetic events immediately.
            if mode == "stream_burst":
                for i in range(3):
                    _write(
                        {
                            "jsonrpc": "2.0",
                            "method": "stream_event",
                            "params": {
                                "stream_id": stream_id,
                                "group_id": group_id,
                                "message_id": f"msg-{i}",
                                "sender_inbox_id": f"inbox-other-{i}",
                                "content": f"prophecy number {i}",
                                "sent_at_ns": str(1_000_000_000 + i),
                            },
                        }
                    )
            elif mode == "stream_flood":
                # More than the queue's max_size (100) to exercise overflow.
                for i in range(150):
                    _write(
                        {
                            "jsonrpc": "2.0",
                            "method": "stream_event",
                            "params": {
                                "stream_id": stream_id,
                                "group_id": group_id,
                                "message_id": f"msg-{i}",
                                "sender_inbox_id": "sender",
                                "content": f"m{i}",
                                "sent_at_ns": str(i),
                            },
                        }
                    )
        elif method == "stream_stop":
            _write(
                {"jsonrpc": "2.0", "id": msg_id, "result": {"stopped": True}}
            )
        elif method == "shutdown":
            _write({"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}})
            sys.stdout.flush()
            sys.exit(0)
        else:
            _err(msg_id, -32601, f"method not found: {method}")


if __name__ == "__main__":
    main()
