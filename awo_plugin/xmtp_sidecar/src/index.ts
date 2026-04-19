// Sidecar entry point. Reads newline-delimited JSON-RPC 2.0 requests from
// stdin; writes responses to stdout. Logs go to stderr so the Python parent
// can surface them.

import { createInterface } from "node:readline";
import { handleRpc, stopAllStreams } from "./methods.js";

type JsonRpcRequest = {
  jsonrpc: "2.0";
  id: number | string | null;
  method: string;
  params?: Record<string, unknown>;
};

type JsonRpcResponse = {
  jsonrpc: "2.0";
  id: number | string | null;
  result?: unknown;
  error?: { code: number; message: string };
};

function write(resp: JsonRpcResponse): void {
  process.stdout.write(JSON.stringify(resp) + "\n");
}

function handleSignal(sig: string): void {
  process.stderr.write(`[awo-xmtp] ${sig} received, exiting\n`);
  stopAllStreams();
  setTimeout(() => process.exit(0), 50);
}

process.on("SIGTERM", () => handleSignal("SIGTERM"));
process.on("SIGINT", () => handleSignal("SIGINT"));

process.stderr.write("[awo-xmtp] sidecar ready\n");

const rl = createInterface({ input: process.stdin });
rl.on("line", async (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let req: JsonRpcRequest;
  try {
    req = JSON.parse(trimmed) as JsonRpcRequest;
  } catch (err) {
    write({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32700, message: `parse error: ${String(err)}` },
    });
    return;
  }
  try {
    const result = await handleRpc(req.method, req.params ?? {});
    write({ jsonrpc: "2.0", id: req.id, result });
  } catch (err) {
    write({
      jsonrpc: "2.0",
      id: req.id,
      error: { code: -32000, message: String(err) },
    });
  }
});

rl.on("close", () => {
  process.stderr.write("[awo-xmtp] stdin closed\n");
  stopAllStreams();
  process.exit(0);
});
