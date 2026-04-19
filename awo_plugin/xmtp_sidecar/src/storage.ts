// Filesystem + key derivation. Mirrors the Python side's constants so both
// agree on paths. Permissions are tightened here because this is the process
// that actually creates the files.

import { homedir } from "node:os";
import { join } from "node:path";
import fs from "node:fs";
import { keccak256, toBytes } from "viem";
import { generatePrivateKey } from "viem/accounts";

const BASE = join(homedir(), ".hermes", "plugins", "awo");
const KEY_PATH = join(BASE, "xmtp-key");
const DB_DIR = join(BASE, "xmtp");
const DB_PATH = join(DB_DIR, "xmtp.db3");

export function ensureBaseDir(): void {
  fs.mkdirSync(BASE, { recursive: true, mode: 0o700 });
}

export function getDbPath(): string {
  fs.mkdirSync(DB_DIR, { recursive: true, mode: 0o700 });
  return DB_PATH;
}

export function getDbEncryptionKey(privateKey: string): Uint8Array {
  const hash = keccak256(toBytes(privateKey + "awo-xmtp-db-key"));
  return toBytes(hash);
}

export function loadOrCreatePrivateKey(): string {
  ensureBaseDir();
  if (fs.existsSync(KEY_PATH)) {
    const existing = fs.readFileSync(KEY_PATH, "utf-8").trim();
    if (/^0x[0-9a-fA-F]{64}$/.test(existing)) return existing;
    // File corrupt or wrong shape — regenerate.
  }
  const priv = generatePrivateKey();
  fs.writeFileSync(KEY_PATH, priv, { mode: 0o600 });
  return priv;
}
