// JSON-RPC method dispatch. One async handler per method. Errors bubble up
// and are encoded as JSON-RPC error responses by the caller in index.ts.

import { ConsentState, type XmtpEnv } from "@xmtp/node-sdk";
import { getClient, getInboxIdCached, syncConversations } from "./client.js";

const state: { env: XmtpEnv } = { env: "production" };

// Active streams keyed by stream_id. Value is a cleanup function that ends
// the async iterator when `stream_stop` is called or the process exits.
const activeStreams = new Map<string, () => void>();

export async function handleRpc(
  method: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  switch (method) {
    case "ping":
      return { ok: true };

    case "create_client": {
      const env = ((params.env as XmtpEnv) || "production") as XmtpEnv;
      state.env = env;
      const client = await getClient(env);
      return { inbox_id: client.inboxId };
    }

    case "get_inbox_id": {
      const cached = getInboxIdCached();
      if (cached) return { inbox_id: cached };
      const client = await getClient(state.env);
      return { inbox_id: client.inboxId };
    }

    case "revoke_installations": {
      const client = await getClient(state.env);
      try {
        await client.revokeAllOtherInstallations();
        return { revoked: true };
      } catch (err) {
        return { revoked: false, error: String(err) };
      }
    }

    case "get_conversation": {
      const groupId = requireString(params, "group_id");
      const client = await getClient(state.env);
      await syncConversations();
      const conv = await client.conversations.getConversationById(groupId);
      if (!conv) return { member_of: false };
      return { member_of: true, conversation_id: conv.id };
    }

    case "send_text": {
      const groupId = requireString(params, "group_id");
      const text = requireString(params, "text");
      const client = await getClient(state.env);
      const conv = await client.conversations.getConversationById(groupId);
      if (!conv) throw new Error(`conversation ${groupId} not found`);
      await conv.sendText(text);
      return { sent: true };
    }

    case "stream_start": {
      const groupId = requireString(params, "group_id");
      const streamId = `s_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`;
      const client = await getClient(state.env);

      const stream = await client.conversations.streamAllMessages({
        consentStates: [ConsentState.Allowed],
      });

      // Consume messages in the background. Emit matching events to stdout
      // as unsolicited JSON-RPC notifications.
      let stopped = false;
      (async () => {
        try {
          for await (const message of stream) {
            if (stopped) break;
            if (message.conversationId !== groupId) continue;
            const contentStr =
              typeof message.content === "string"
                ? message.content
                : JSON.stringify(message.content ?? null);
            emitStreamEvent({
              stream_id: streamId,
              group_id: groupId,
              message_id: message.id ?? "",
              sender_inbox_id: message.senderInboxId ?? "",
              content: contentStr,
              sent_at_ns:
                message.sentAtNs !== undefined
                  ? String(message.sentAtNs)
                  : "0",
            });
          }
        } catch (err) {
          process.stderr.write(
            `[awo-xmtp] stream ${streamId} error: ${String(err)}\n`,
          );
        }
      })();

      activeStreams.set(streamId, () => {
        stopped = true;
        try {
          // Stream may expose end(), return(), or neither.
          const anyStream = stream as unknown as {
            end?: () => void;
            return?: () => void;
          };
          if (typeof anyStream.end === "function") anyStream.end();
          else if (typeof anyStream.return === "function") anyStream.return();
        } catch {
          // best-effort
        }
      });

      return { stream_id: streamId };
    }

    case "stream_stop": {
      const streamId = requireString(params, "stream_id");
      const cleanup = activeStreams.get(streamId);
      if (cleanup) {
        cleanup();
        activeStreams.delete(streamId);
        return { stopped: true };
      }
      return { stopped: false };
    }

    case "shutdown": {
      stopAllStreams();
      setTimeout(() => process.exit(0), 10);
      return { ok: true };
    }

    default:
      throw new Error(`unknown method: ${method}`);
  }
}

export function stopAllStreams(): void {
  for (const cleanup of activeStreams.values()) {
    try {
      cleanup();
    } catch {
      // ignore
    }
  }
  activeStreams.clear();
}

function emitStreamEvent(params: Record<string, unknown>): void {
  process.stdout.write(
    JSON.stringify({
      jsonrpc: "2.0",
      method: "stream_event",
      params,
    }) + "\n",
  );
}

function requireString(params: Record<string, unknown>, key: string): string {
  const v = params[key];
  if (typeof v !== "string" || !v.length) {
    throw new Error(`missing or empty param: ${key}`);
  }
  return v;
}
