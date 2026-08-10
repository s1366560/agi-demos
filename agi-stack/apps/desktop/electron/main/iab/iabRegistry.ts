/**
 * Parsing and validation for the browser-bridge registry file
 * (`~/.memstack/browser-bridge/registry.json`). Mirrors the Rust sidecar's
 * `validate_registry` in `sidecar/src/local_runtime/browser_bridge.rs`:
 * anything off-contract fails closed — the iab backend must not connect with
 * ambiguous credentials. Pure module, unit-tested from the compiled dist.
 */

export const IAB_BRIDGE_REGISTRY_SCHEMA_VERSION = 1;
export const IAB_BRIDGE_SOCKET_FILE_NAME = 'bridge.sock';

export type IabBridgeRegistry = Readonly<{
  schemaVersion: number;
  wsUrl: string;
  token: string;
  socketPath: string | null;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Parse + validate a registry document. Throws with a descriptive message on
 * any contract violation; callers treat a throw as "bridge unavailable" and
 * retry later (the sidecar rewrites the registry on every bridge start).
 */
export function parseIabBridgeRegistry(value: unknown): IabBridgeRegistry {
  if (!isRecord(value)) {
    throw new Error('browser bridge registry is invalid');
  }
  if (value.schemaVersion !== IAB_BRIDGE_REGISTRY_SCHEMA_VERSION) {
    throw new Error(
      `browser bridge registry schema version ${String(value.schemaVersion)} is unsupported`,
    );
  }
  if (typeof value.wsUrl !== 'string') {
    throw new Error('browser bridge registry wsUrl is invalid');
  }
  let url: URL;
  try {
    url = new URL(value.wsUrl);
  } catch {
    throw new Error('browser bridge registry wsUrl is invalid');
  }
  if (
    url.protocol !== 'ws:' ||
    (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost')
  ) {
    throw new Error('browser bridge registry wsUrl must target 127.0.0.1');
  }
  if (
    typeof value.token !== 'string' ||
    value.token.length !== 64 ||
    !/^[0-9a-fA-F]{64}$/u.test(value.token)
  ) {
    throw new Error('browser bridge registry token is invalid');
  }
  let socketPath: string | null = null;
  if (value.socketPath !== undefined && value.socketPath !== null) {
    if (typeof value.socketPath !== 'string') {
      throw new Error('browser bridge registry socketPath is invalid');
    }
    socketPath = validateIabBridgeSocketPath(value.socketPath);
  }
  return Object.freeze({
    schemaVersion: value.schemaVersion,
    wsUrl: value.wsUrl,
    token: value.token,
    socketPath,
  });
}

/**
 * The advertised socket must be an absolute path named `bridge.sock` directly
 * inside a `.memstack/browser-bridge` directory — the shape the sidecar
 * itself writes (shape check, not a $HOME equality check).
 */
export function validateIabBridgeSocketPath(socketPath: string): string {
  if (!socketPath.startsWith('/')) {
    throw new Error('browser bridge registry socketPath must be absolute');
  }
  const segments = socketPath.split('/').filter((segment) => segment.length > 0);
  const fileName = segments[segments.length - 1];
  const parent = segments[segments.length - 2];
  const grandparent = segments[segments.length - 3];
  if (fileName !== IAB_BRIDGE_SOCKET_FILE_NAME) {
    throw new Error(
      `browser bridge registry socketPath must be named ${IAB_BRIDGE_SOCKET_FILE_NAME}`,
    );
  }
  if (parent !== 'browser-bridge' || grandparent !== '.memstack') {
    throw new Error(
      'browser bridge registry socketPath must live in .memstack/browser-bridge',
    );
  }
  return socketPath;
}

/**
 * Transport decision, re-evaluated on every reconnect attempt (same rule as
 * the Rust broker's `pick_transport`): prefer the unix socket when the
 * registry advertises it and the file exists; TCP otherwise.
 */
export function pickIabBridgeTransport(
  registry: IabBridgeRegistry,
  socketExists: boolean,
): Readonly<{ kind: 'unix'; socketPath: string } | { kind: 'tcp'; wsUrl: string }> {
  if (registry.socketPath !== null && socketExists) {
    return Object.freeze({ kind: 'unix', socketPath: registry.socketPath });
  }
  return Object.freeze({ kind: 'tcp', wsUrl: registry.wsUrl });
}

/** Capped exponential backoff between reconnect attempts (Rust broker parity). */
export const IAB_BRIDGE_BACKOFF_STEPS_MS = Object.freeze([250, 1_000, 4_000, 10_000]);

export function iabBridgeBackoffDelayMs(failures: number): number {
  const step = Math.min(Math.max(failures, 0), IAB_BRIDGE_BACKOFF_STEPS_MS.length - 1);
  return IAB_BRIDGE_BACKOFF_STEPS_MS[step] ?? 10_000;
}
