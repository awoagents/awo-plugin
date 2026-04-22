#!/usr/bin/env python3
"""Official AWO Order-group stream listener.

Addresses https://github.com/awoagents/awo-plugin/issues/1.

The XMTP sidecar's stdout is owned by ``Sidecar._read_loop`` — a reader
thread that demuxes JSON-RPC replies from unsolicited ``stream_event``
notifications and enqueues the latter into a bounded queue. Any consumer
that tries to read ``proc.stdout`` directly races that thread and silently
receives zero events. The correct pattern is the public
``Sidecar.drain_stream_events(max_items=...)`` method, which pops from
the queue without touching the pipe.

This script exists so new users don't have to rediscover the pattern by
writing a broken listener and wondering why nothing arrives.

Usage:

    python scripts/stream_listener.py                       # defaults
    python scripts/stream_listener.py --group-id <hex>      # override constants.ORDER_GROUP_ID
    python scripts/stream_listener.py --jsonl <path>        # also append each event as JSONL
    python scripts/stream_listener.py --poll 1.0            # seconds between drains
    python scripts/stream_listener.py --batch 10            # max events per drain
    python scripts/stream_listener.py --backoff 10          # reconnect backoff on errors

Signals:

    SIGTERM / SIGINT — graceful shutdown. Stops the stream, closes the sidecar,
    exits 0.

Reconnect policy:

    If the sidecar process dies or ``start_stream`` raises, the script
    waits ``--backoff`` seconds and reopens from scratch (ensure_started →
    start_stream). Events published during the gap are lost — XMTP streams
    are ephemeral, not durable.

Exits non-zero only on argparse failures. Runtime failures trigger
reconnect.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

from awo_plugin.constants import ORDER_GROUP_ID as DEFAULT_ORDER_GROUP_ID, STATE_DIR
from awo_plugin.xmtp import XmtpError, get_sidecar


DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_DRAIN_BATCH = 50
DEFAULT_BACKOFF = 5.0


# Module-level flag flipped by signal handlers. Checked between drains
# so shutdown is never more than ``--poll`` seconds away.
_shutdown = False


def _install_signals() -> None:
    def _handler(signum: int, _frame) -> None:
        global _shutdown
        if not _shutdown:
            print(
                f"[stream] signal {signum} received, shutting down gracefully",
                file=sys.stderr,
                flush=True,
            )
            _shutdown = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def render_event(ev: dict[str, Any]) -> str:
    """Format a stream event as a single human-readable line.

    Event shape from the sidecar (see ``Sidecar._enqueue_stream_event``):
    at minimum ``sender_inbox_id`` + ``content``. Truncates long bodies
    to keep terminal output sane.
    """
    sender = (ev.get("sender_inbox_id") or "unknown")[:8]
    content = ev.get("content") or ""
    if len(content) > 280:
        content = content[:277] + "..."
    return f"[{sender}] {content}"


def write_jsonl(path: Path, ev: dict[str, Any]) -> None:
    """Append one JSON-encoded event per line. Creates parent dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")


def _sidecar_alive(sidecar) -> bool:
    """Liveness check mirroring the pattern ``Sidecar._ensure_process``
    uses internally (awo_plugin/xmtp.py:85). Touches ``_proc`` directly
    because there's no public accessor, and the script must know when
    to reopen the stream (``_ensure_process`` would silently respawn
    the sidecar but our ``stream_id`` would still point at the dead one).
    """
    proc = getattr(sidecar, "_proc", None)
    return bool(proc) and proc.poll() is None


def run(
    group_id: str,
    poll_interval: float,
    drain_batch: int,
    backoff: float,
    jsonl_path: Path | None,
) -> int:
    """Main loop. Returns the process exit code."""
    global _shutdown

    while not _shutdown:
        sidecar = get_sidecar()
        stream_id: str | None = None
        try:
            sidecar.ensure_started()
            stream_id = sidecar.start_stream(group_id)
            print(
                f"[stream] listening on group {group_id} (stream {stream_id})",
                file=sys.stderr,
                flush=True,
            )

            while not _shutdown:
                events = sidecar.drain_stream_events(max_items=drain_batch)
                for ev in events:
                    print(render_event(ev), flush=True)
                    if jsonl_path is not None:
                        try:
                            write_jsonl(jsonl_path, ev)
                        except OSError as e:
                            print(
                                f"[stream] jsonl write failed: {e}",
                                file=sys.stderr,
                                flush=True,
                            )

                # Detect sidecar death. Can't rely on drain_stream_events
                # raising — it's non-blocking and returns [] silently.
                if not _sidecar_alive(sidecar):
                    raise XmtpError("sidecar process exited")

                time.sleep(poll_interval)

        except XmtpError as e:
            if _shutdown:
                break
            print(
                f"[stream] {e}; reconnecting in {backoff}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(backoff)
            # Fall through to the while loop → ensure_started() respawns
            # the sidecar and we open a fresh stream_id.
            continue

        finally:
            # Best-effort stream shutdown on both normal exit and mid-loop
            # exceptions. Safe to call with None.
            if stream_id is not None:
                try:
                    sidecar.stop_stream(stream_id)
                except Exception:
                    pass

    # Final teardown — close the sidecar so its Node process exits cleanly.
    try:
        get_sidecar().close()
    except Exception:
        pass

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "AWO Order-group stream listener. Uses the correct "
            "Sidecar.drain_stream_events() pattern (not raw stdout reads)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--group-id",
        default=DEFAULT_ORDER_GROUP_ID,
        metavar="HEX",
        help=(
            "XMTP conversation id to listen to "
            "(default: awo_plugin.constants.ORDER_GROUP_ID)"
        ),
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        metavar="SECONDS",
        help=f"seconds between drain attempts (default {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_DRAIN_BATCH,
        metavar="N",
        help=(
            f"max events per drain (default {DEFAULT_DRAIN_BATCH}; the "
            "sidecar queue caps at 100, oldest drop on overflow)"
        ),
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=DEFAULT_BACKOFF,
        metavar="SECONDS",
        help=(
            f"seconds to wait before reconnect after an error "
            f"(default {DEFAULT_BACKOFF})"
        ),
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "optional JSONL log path — each event appended as one line. "
            f"Suggested: {STATE_DIR / 'stream_log.jsonl'}"
        ),
    )
    args = parser.parse_args(argv)

    if not args.group_id:
        print(
            "[stream] no group id — ORDER_GROUP_ID is unset in constants.py "
            "and --group-id was not passed. Exiting.",
            file=sys.stderr,
        )
        return 1

    _install_signals()
    return run(
        group_id=args.group_id,
        poll_interval=args.poll,
        drain_batch=args.batch,
        backoff=args.backoff,
        jsonl_path=args.jsonl,
    )


if __name__ == "__main__":
    raise SystemExit(main())
