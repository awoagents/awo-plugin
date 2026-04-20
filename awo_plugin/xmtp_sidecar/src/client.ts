// XMTP Client singleton. Instantiated once per sidecar process — the whole
// point of running the sidecar long-lived is to avoid re-creating the Client,
// which churns MLS installations and silently breaks group membership.

import {
  Client,
  IdentifierKind,
  type Signer,
  type XmtpEnv,
} from "@xmtp/node-sdk";
import { privateKeyToAccount } from "viem/accounts";
import { toBytes } from "viem";
import {
  getDbEncryptionKey,
  getDbPath,
  loadOrCreatePrivateKey,
} from "./storage.js";

let _client: Client | null = null;
let _inboxId: string | null = null;

export async function getClient(env: XmtpEnv = "production"): Promise<Client> {
  if (_client) return _client;

  const privateKey = loadOrCreatePrivateKey();
  const account = privateKeyToAccount(privateKey as `0x${string}`);

  const signer: Signer = {
    type: "EOA",
    getIdentifier: () => ({
      identifier: account.address.toLowerCase(),
      identifierKind: IdentifierKind.Ethereum,
    }),
    signMessage: async (message: string) => {
      const sig = await account.signMessage({ message });
      return toBytes(sig);
    },
  };

  // NOTE: @xmtp/node-sdk 6.x types `Client.create`'s options as
  // `Omit<ClientOptions, "codecs"> & { codecs?: [] }`, where ClientOptions is
  // `(NetworkOptions | { backend: Backend }) & ...`. `Omit` on a discriminated
  // union only preserves keys common to every arm, which drops `env` (and
  // `backend`). Assigning the literal to a variable first sidesteps excess-
  // property checking while the runtime shape stays correct.
  const options = {
    env,
    dbEncryptionKey: getDbEncryptionKey(privateKey),
    dbPath: getDbPath(),
  };
  _client = await Client.create(signer, options);
  _inboxId = _client.inboxId;
  return _client;
}

export function getInboxIdCached(): string | null {
  return _inboxId;
}

export async function syncConversations(): Promise<void> {
  const c = _client;
  if (!c) return;
  try {
    await c.conversations.sync();
  } catch {
    // sync failures are surfaced upstream on the next op
  }
}
