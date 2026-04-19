"""Python ↔ Node XMTP sidecar bridge.

The sidecar is a long-lived TypeScript process that holds the ``@xmtp/node-sdk``
``Client`` singleton. Python talks to it via newline-delimited JSON-RPC 2.0
over stdin/stdout. We keep the sidecar alive for the lifetime of the Hermes
session because re-instantiating the ``Client`` per call churns MLS
installations and silently breaks group membership.

Public shape: a single ``Sidecar`` class that lazy-spawns on first call, holds
the subprocess handle, serializes writes under a lock, demuxes replies with a
reader thread, and shuts down cleanly on ``close()`` or atexit.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from awo_plugin.constants import XMTP_ENV


class XmtpError(Exception):
    """Any sidecar-related failure — spawn, transport, protocol, RPC."""


SIDECAR_DIR = Path(__file__).resolve().parent / "xmtp_sidecar"
SIDECAR_ENTRY = SIDECAR_DIR / "dist" / "index.js"
SIDECAR_DEV_ENTRY = SIDECAR_DIR / "src" / "index.ts"

REQUEST_TIMEOUT_SECONDS = 30.0
CREATE_CLIENT_TIMEOUT_SECONDS = 120.0


class Sidecar:
    """One sidecar subprocess per Hermes session, reused across calls."""

    def __init__(
        self,
        sidecar_dir: Path = SIDECAR_DIR,
        env: str = XMTP_ENV,
        node_cmd: str | None = None,
        auto_install: bool = True,
    ):
        self.sidecar_dir = Path(sidecar_dir)
        self.env = env
        self.node_cmd = node_cmd or shutil.which("node") or "node"
        self.auto_install = auto_install

        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._writer_lock = threading.Lock()
        self._pending: dict[int, Future] = {}
        self._id_counter = itertools.count(1)
        self._shutdown_requested = False
        self._start_lock = threading.Lock()
        # Unsolicited stream_event notifications from the sidecar land here.
        # Bounded queue so a stalled reader can't eat unlimited memory; when
        # full, oldest events are dropped to make room for newest.
        self._stream_queue: queue.Queue = queue.Queue(maxsize=100)

    # ------------------------------------------------------------ lifecycle

    def ensure_started(self, timeout: float = CREATE_CLIENT_TIMEOUT_SECONDS) -> str:
        """Start the sidecar if not running; call create_client; return inbox_id."""
        self._ensure_process()
        resp = self.call("create_client", {"env": self.env}, timeout=timeout)
        inbox_id = resp.get("inbox_id")
        if not isinstance(inbox_id, str) or not inbox_id:
            raise XmtpError(f"create_client returned no inbox_id: {resp!r}")
        return inbox_id

    def _ensure_process(self) -> None:
        with self._start_lock:
            if self._proc and self._proc.poll() is None:
                return
            self._prepare_sidecar()
            cmd, cwd = self._spawn_command()
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    text=True,
                )
            except FileNotFoundError as e:
                raise XmtpError(f"cannot spawn sidecar: {e}") from e
            self._reader = threading.Thread(
                target=self._read_loop, daemon=True, name="awo-xmtp-reader"
            )
            self._reader.start()
            atexit.register(self.close)

    def _prepare_sidecar(self) -> None:
        """First-run: install node_modules + build dist/ if auto_install."""
        if not self.auto_install:
            return
        node_modules = self.sidecar_dir / "node_modules"
        dist = self.sidecar_dir / "dist"
        if node_modules.exists() and dist.exists():
            return
        npm = shutil.which("npm")
        if not npm:
            raise XmtpError(
                "npm not found on PATH; cannot bootstrap XMTP sidecar. "
                "Install Node ≥ 20 or point to pre-built dist/."
            )
        sys.stderr.write("[awo] initializing XMTP sidecar (one-time, ~30s)...\n")
        if not node_modules.exists():
            rc = subprocess.run(
                [npm, "ci"], cwd=str(self.sidecar_dir)
            ).returncode
            if rc != 0:
                raise XmtpError(f"npm ci failed (exit {rc})")
        if not dist.exists():
            rc = subprocess.run(
                [npm, "run", "build"], cwd=str(self.sidecar_dir)
            ).returncode
            if rc != 0:
                raise XmtpError(f"npm run build failed (exit {rc})")

    def _spawn_command(self) -> tuple[list[str], Path]:
        if SIDECAR_ENTRY.exists():
            return [self.node_cmd, str(SIDECAR_ENTRY)], self.sidecar_dir
        # Fallback: dev mode with tsx (requires node_modules).
        tsx = self.sidecar_dir / "node_modules" / ".bin" / "tsx"
        if tsx.exists() and SIDECAR_DEV_ENTRY.exists():
            return [str(tsx), str(SIDECAR_DEV_ENTRY)], self.sidecar_dir
        raise XmtpError(
            f"sidecar entry point missing: neither {SIDECAR_ENTRY} nor "
            f"tsx+{SIDECAR_DEV_ENTRY} exist. Run 'npm ci && npm run build' "
            f"in {self.sidecar_dir}."
        )

    def close(self) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        proc = self._proc
        if not proc:
            return
        try:
            # Best-effort graceful shutdown.
            if proc.poll() is None:
                self._send_raw({"jsonrpc": "2.0", "id": 0, "method": "shutdown"})
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        finally:
            # Cancel any pending futures.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(XmtpError("sidecar shut down"))
            self._pending.clear()

    # -------------------------------------------------------- transport

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request; block until reply (or timeout)."""
        self._ensure_process()
        req_id = next(self._id_counter)
        fut: Future = Future()
        self._pending[req_id] = fut
        self._send_raw(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
        )
        try:
            return fut.result(timeout=timeout)
        except Exception as e:
            self._pending.pop(req_id, None)
            if isinstance(e, XmtpError):
                raise
            raise XmtpError(f"call {method} failed: {e}") from e

    def _send_raw(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if not proc or not proc.stdin:
            raise XmtpError("sidecar not running")
        line = json.dumps(payload) + "\n"
        with self._writer_lock:
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise XmtpError(f"sidecar stdin closed: {e}") from e

    def _read_loop(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Unsolicited notifications (no ``id``) — currently only
            # ``stream_event`` from the sidecar.
            if "id" not in msg:
                if msg.get("method") == "stream_event":
                    self._enqueue_stream_event(msg.get("params") or {})
                continue
            msg_id = msg["id"]
            fut = self._pending.pop(msg_id, None)
            if not fut:
                continue
            if "error" in msg:
                err = msg["error"]
                msg_text = err.get("message") if isinstance(err, dict) else str(err)
                fut.set_exception(XmtpError(f"RPC error: {msg_text}"))
            else:
                fut.set_result(msg.get("result") or {})

    def _enqueue_stream_event(self, event: dict[str, Any]) -> None:
        """Put a stream event on the queue; drop oldest on overflow."""
        try:
            self._stream_queue.put_nowait(event)
        except queue.Full:
            try:
                self._stream_queue.get_nowait()  # evict oldest
            except queue.Empty:
                pass
            try:
                self._stream_queue.put_nowait(event)
            except queue.Full:
                pass  # give up; next call to drain will have room

    # ---------------------------------------------------- high-level ops

    def get_conversation(self, group_id: str) -> dict[str, Any]:
        return self.call("get_conversation", {"group_id": group_id})

    def send_text(self, group_id: str, text: str) -> dict[str, Any]:
        return self.call("send_text", {"group_id": group_id, "text": text})

    def revoke_installations(self) -> dict[str, Any]:
        return self.call("revoke_installations", {})

    def get_inbox_id(self) -> str:
        resp = self.call("get_inbox_id", {})
        inbox_id = resp.get("inbox_id")
        if not isinstance(inbox_id, str) or not inbox_id:
            raise XmtpError(f"get_inbox_id returned no value: {resp!r}")
        return inbox_id

    def start_stream(self, group_id: str) -> str:
        resp = self.call("stream_start", {"group_id": group_id})
        stream_id = resp.get("stream_id")
        if not isinstance(stream_id, str) or not stream_id:
            raise XmtpError(f"stream_start returned no stream_id: {resp!r}")
        return stream_id

    def stop_stream(self, stream_id: str) -> bool:
        resp = self.call("stream_stop", {"stream_id": stream_id})
        return bool(resp.get("stopped"))

    def drain_stream_events(self, max_items: int = 5) -> list[dict[str, Any]]:
        """Pop up to ``max_items`` queued stream events. Non-blocking."""
        out: list[dict[str, Any]] = []
        while len(out) < max_items:
            try:
                out.append(self._stream_queue.get_nowait())
            except queue.Empty:
                break
        return out


# Module-level singleton used by hooks; reset for tests via ``_reset``.
_singleton: Sidecar | None = None
_singleton_lock = threading.Lock()


def get_sidecar() -> Sidecar:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = Sidecar()
        return _singleton


def _reset() -> None:
    """Test hook — close and clear the module singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.close()
            _singleton = None
