/**
 * JSON-RPC 2.0 server-side router for the iab browser-bridge backend.
 *
 * The sidecar drives the backend with requests (`hello`, `attach`, `detach`,
 * `executeCdp`, `getTabs`, `createTab`, `closeTab`, `focusTab`,
 * `ensureTabGroup`, `assignTab`, `ungroupTab`, `moveMouse`, `turnEnded`);
 * the backend answers with responses and may emit notifications
 * (`onCDPEvent`, `onCDPDetach`). Pure module — handlers are injected, so the
 * routing, envelope, and error-code behavior is unit-testable without
 * Electron. Wire field names are camelCase and fixed by the contract (see
 * `crates/adapters-browser/src/protocol.rs`).
 */

export const IAB_PROTOCOL_VERSION = 1;
export const IAB_BACKEND_NAME = 'iab';

/** Capabilities advertised in the `hello` result. Informational in M4. */
export const IAB_CAPABILITIES = Object.freeze([
  'cdp',
  'tabs',
  'tabGroups',
  'cursor',
  'turnLifecycle',
] as const);

export const IAB_METHODS = Object.freeze([
  'hello',
  'ping',
  'attach',
  'detach',
  'executeCdp',
  'getTabs',
  'createTab',
  'closeTab',
  'focusTab',
  'ensureTabGroup',
  'assignTab',
  'ungroupTab',
  'moveMouse',
  'turnEnded',
] as const);

export const IAB_NOTIFY_ON_CDP_EVENT = 'onCDPEvent';
export const IAB_NOTIFY_ON_CDP_DETACH = 'onCDPDetach';

/** Bridge-level error: the handler ran but failed (e.g. tab gone). */
export const IAB_ERR_HANDLER = 1;
export const IAB_ERR_METHOD_NOT_FOUND = -32601;
export const IAB_ERR_INVALID_PARAMS = -32602;
export const IAB_ERR_PARSE = -32700;
export const IAB_ERR_INVALID_REQUEST = -32600;

/** Throw from a handler to answer with `invalid params` (-32602). */
export class IabInvalidParamsError extends Error {}

export type IabRpcHandler = (params: unknown) => unknown | Promise<unknown>;

export type IabRpcRouter = (rawMessage: string) => Promise<string | null>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function encodeResponse(id: number | string | null, body: Record<string, unknown>): string {
  return JSON.stringify({ jsonrpc: '2.0', id, ...body });
}

function encodeError(id: number | string | null, code: number, message: string): string {
  return encodeResponse(id, { error: { code, message } });
}

/** Encode a backend → sidecar notification (`onCDPEvent` / `onCDPDetach`). */
export function encodeIabNotification(method: string, params: unknown): string {
  return JSON.stringify({ jsonrpc: '2.0', method, params });
}

export function buildIabHelloResult(): Readonly<{
  protocolVersion: number;
  backend: string;
  capabilities: readonly string[];
}> {
  return Object.freeze({
    protocolVersion: IAB_PROTOCOL_VERSION,
    backend: IAB_BACKEND_NAME,
    capabilities: IAB_CAPABILITIES,
  });
}

/**
 * Route one inbound text frame. Requests produce a response frame;
 * notifications and unparseable non-request frames produce none. Unknown
 * methods answer -32601; handler `IabInvalidParamsError` answers -32602;
 * any other handler failure answers the bridge-level code 1.
 */
export function createIabRpcRouter(handlers: Readonly<Record<string, IabRpcHandler>>): IabRpcRouter {
  return async (rawMessage) => {
    let message: unknown;
    try {
      message = JSON.parse(rawMessage);
    } catch {
      return encodeError(null, IAB_ERR_PARSE, 'invalid JSON');
    }
    if (!isRecord(message) || message.jsonrpc !== '2.0') {
      return encodeError(null, IAB_ERR_INVALID_REQUEST, 'invalid JSON-RPC envelope');
    }
    if (message.id === undefined) {
      // Notification from the sidecar: nothing to answer.
      return null;
    }
    const id = message.id;
    if (typeof id !== 'number' && typeof id !== 'string') {
      return encodeError(null, IAB_ERR_INVALID_REQUEST, 'invalid request id');
    }
    if (typeof message.method !== 'string' || message.method.length === 0) {
      return encodeError(id, IAB_ERR_INVALID_REQUEST, 'invalid method');
    }
    const handler = handlers[message.method];
    if (!handler) {
      return encodeError(id, IAB_ERR_METHOD_NOT_FOUND, `method not found: ${message.method}`);
    }
    try {
      const result = await handler(message.params);
      return encodeResponse(id, { result: result === undefined ? null : result });
    } catch (error) {
      if (error instanceof IabInvalidParamsError) {
        return encodeError(id, IAB_ERR_INVALID_PARAMS, error.message);
      }
      const messageText = error instanceof Error ? error.message : String(error);
      return encodeError(id, IAB_ERR_HANDLER, messageText);
    }
  };
}

// ---------------------------------------------------------------------------
// Param validators shared by the backend handlers.
// ---------------------------------------------------------------------------

export function requireIabParamsRecord(params: unknown, method: string): Record<string, unknown> {
  if (!isRecord(params)) {
    throw new IabInvalidParamsError(`${method} params must be an object`);
  }
  return params;
}

export function requireIabTabId(params: Record<string, unknown>, method: string): number {
  const tabId = params.tabId;
  if (typeof tabId !== 'number' || !Number.isSafeInteger(tabId) || tabId <= 0) {
    throw new IabInvalidParamsError(`${method} requires a positive integer tabId`);
  }
  return tabId;
}

export function requireIabString(
  params: Record<string, unknown>,
  field: string,
  method: string,
  { maxLength = 8192 }: { maxLength?: number } = {},
): string {
  const value = params[field];
  if (typeof value !== 'string' || value.length === 0 || value.length > maxLength) {
    throw new IabInvalidParamsError(`${method} requires a non-empty string ${field}`);
  }
  return value;
}

export function optionalIabString(
  params: Record<string, unknown>,
  field: string,
  method: string,
  { maxLength = 8192 }: { maxLength?: number } = {},
): string | null {
  const value = params[field];
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string' || value.length > maxLength) {
    throw new IabInvalidParamsError(`${method} field ${field} must be a string`);
  }
  return value;
}

export function requireIabCoordinate(
  params: Record<string, unknown>,
  field: string,
  method: string,
): number {
  const value = params[field];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new IabInvalidParamsError(`${method} requires a finite number ${field}`);
  }
  return value;
}

/** Parse one `turnEnded` lease; malformed entries are invalid params. */
export function parseIabTurnEndedLeases(
  params: unknown,
): readonly Readonly<{
  tabId: number;
  origin: 'agent' | 'user';
  mark: 'handoff' | 'deliverable' | null;
}>[] {
  const record = requireIabParamsRecord(params, 'turnEnded');
  if (!Array.isArray(record.leases)) {
    throw new IabInvalidParamsError('turnEnded requires a leases array');
  }
  return record.leases.map((lease, index) => {
    if (!isRecord(lease)) {
      throw new IabInvalidParamsError(`turnEnded lease ${index} must be an object`);
    }
    const tabId = lease.tabId;
    if (typeof tabId !== 'number' || !Number.isSafeInteger(tabId) || tabId <= 0) {
      throw new IabInvalidParamsError(`turnEnded lease ${index} has an invalid tabId`);
    }
    if (lease.origin !== 'agent' && lease.origin !== 'user') {
      throw new IabInvalidParamsError(`turnEnded lease ${index} has an invalid origin`);
    }
    const mark = lease.mark;
    if (mark !== undefined && mark !== null && mark !== 'handoff' && mark !== 'deliverable') {
      throw new IabInvalidParamsError(`turnEnded lease ${index} has an invalid mark`);
    }
    return Object.freeze({
      tabId,
      origin: lease.origin,
      mark: mark ?? null,
    });
  });
}
