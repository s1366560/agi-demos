/**
 * JSON-RPC 2.0 wire types and validation for the native-messaging bridge.
 * Contract: docs in README.md — do not deviate without updating the sidecar.
 */

export const JSON_RPC_VERSION = '2.0' as const;

export const ErrorCodes = {
  methodNotFound: -32601,
  invalidParams: -32602,
  internalError: -32603,
  cdpTimeout: 1,
} as const;

export type JsonRpcId = string | number;

export interface JsonRpcRequest {
  jsonrpc: typeof JSON_RPC_VERSION;
  id: JsonRpcId;
  method: string;
  params?: unknown;
}

export interface JsonRpcNotification {
  jsonrpc: typeof JSON_RPC_VERSION;
  method: string;
  params?: unknown;
}

export interface JsonRpcSuccess {
  jsonrpc: typeof JSON_RPC_VERSION;
  id: JsonRpcId;
  result: unknown;
}

export interface JsonRpcFailure {
  jsonrpc: typeof JSON_RPC_VERSION;
  id: JsonRpcId;
  error: { code: number; message: string };
}

export type JsonRpcResponse = JsonRpcSuccess | JsonRpcFailure;

export class RpcError extends Error {
  readonly code: number;

  constructor(code: number, message: string) {
    super(message);
    this.name = 'RpcError';
    this.code = code;
  }
}

/** Defensive shape check on anything arriving over the native port. */
export function isJsonRpcRequest(message: unknown): message is JsonRpcRequest {
  if (typeof message !== 'object' || message === null) return false;
  const m = message as Record<string, unknown>;
  return (
    m.jsonrpc === JSON_RPC_VERSION &&
    (typeof m.id === 'string' || typeof m.id === 'number') &&
    typeof m.method === 'string'
  );
}

export function successResponse(id: JsonRpcId, result: unknown): JsonRpcSuccess {
  return { jsonrpc: JSON_RPC_VERSION, id, result };
}

export function errorResponse(id: JsonRpcId, code: number, message: string): JsonRpcFailure {
  return { jsonrpc: JSON_RPC_VERSION, id, error: { code, message } };
}

export function notification(method: string, params: unknown): JsonRpcNotification {
  return { jsonrpc: JSON_RPC_VERSION, method, params };
}

export function request(id: JsonRpcId, method: string, params?: unknown): JsonRpcRequest {
  return { jsonrpc: JSON_RPC_VERSION, id, method, params };
}

/**
 * True for broker→SW responses (id + result/error, no method). Requests also
 * carry `method`, so the two never collide on the wire.
 */
export function isJsonRpcResponse(message: unknown): message is JsonRpcResponse {
  if (typeof message !== 'object' || message === null) return false;
  const m = message as Record<string, unknown>;
  if (m.jsonrpc !== JSON_RPC_VERSION) return false;
  if (typeof m.id !== 'string' && typeof m.id !== 'number') return false;
  return 'result' in m || 'error' in m;
}

const CDP_METHOD_PATTERN = /^[A-Z][A-Za-z]+\.[a-zA-Z]+$/;

function requireParamsObject(params: unknown): Record<string, unknown> {
  if (typeof params !== 'object' || params === null || Array.isArray(params)) {
    throw new RpcError(ErrorCodes.invalidParams, 'params must be an object');
  }
  return params as Record<string, unknown>;
}

export function requireTabId(params: unknown): number {
  const tabId = requireParamsObject(params).tabId;
  if (typeof tabId !== 'number' || !Number.isInteger(tabId) || tabId <= 0) {
    throw new RpcError(ErrorCodes.invalidParams, 'tabId must be a positive integer');
  }
  return tabId;
}

export function requireCdpMethod(params: unknown): string {
  const method = requireParamsObject(params).method;
  if (typeof method !== 'string' || !CDP_METHOD_PATTERN.test(method)) {
    throw new RpcError(
      ErrorCodes.invalidParams,
      'method must be a string matching /^[A-Z][A-Za-z]+\\.[a-zA-Z]+$/',
    );
  }
  return method;
}

/** Optional `params` field of an executeCdp call: a plain object when present. */
export function optionalCdpParams(params: unknown): Record<string, unknown> | undefined {
  const value = requireParamsObject(params).params;
  if (value === undefined) return undefined;
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new RpcError(ErrorCodes.invalidParams, 'params.params must be an object');
  }
  return value as Record<string, unknown>;
}

function requireStringField(obj: Record<string, unknown>, name: string): string {
  const value = obj[name];
  if (typeof value !== 'string' || value.length === 0) {
    throw new RpcError(ErrorCodes.invalidParams, `${name} must be a non-empty string`);
  }
  return value;
}

function optionalStringField(obj: Record<string, unknown>, name: string): string | undefined {
  const value = obj[name];
  if (value === undefined) return undefined;
  if (typeof value !== 'string') {
    throw new RpcError(ErrorCodes.invalidParams, `${name} must be a string`);
  }
  return value;
}

function requireFiniteNumber(obj: Record<string, unknown>, name: string): number {
  const value = obj[name];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new RpcError(ErrorCodes.invalidParams, `${name} must be a finite number`);
  }
  return value;
}

/** Positive-integer groupId field (chrome tab group id). */
export function requireGroupId(params: unknown): number {
  const groupId = requireParamsObject(params).groupId;
  if (typeof groupId !== 'number' || !Number.isInteger(groupId) || groupId < 0) {
    throw new RpcError(ErrorCodes.invalidParams, 'groupId must be a non-negative integer');
  }
  return groupId;
}

export interface EnsureTabGroupParams {
  key: string;
  title: string;
  color?: string;
}

export function requireEnsureTabGroupParams(params: unknown): EnsureTabGroupParams {
  const obj = requireParamsObject(params);
  return {
    key: requireStringField(obj, 'key'),
    title: requireStringField(obj, 'title'),
    color: optionalStringField(obj, 'color'),
  };
}

export interface AssignTabParams {
  tabId: number;
  groupId: number;
}

export function requireAssignTabParams(params: unknown): AssignTabParams {
  return { tabId: requireTabId(params), groupId: requireGroupId(params) };
}

export interface MoveMouseParams {
  tabId: number;
  x: number;
  y: number;
  waitForArrival: boolean;
}

export function requireMoveMouseParams(params: unknown): MoveMouseParams {
  const obj = requireParamsObject(params);
  const waitForArrival = obj.waitForArrival;
  if (waitForArrival !== undefined && typeof waitForArrival !== 'boolean') {
    throw new RpcError(ErrorCodes.invalidParams, 'waitForArrival must be a boolean');
  }
  return {
    tabId: requireTabId(params),
    x: requireFiniteNumber(obj, 'x'),
    y: requireFiniteNumber(obj, 'y'),
    waitForArrival: waitForArrival ?? true,
  };
}

export type LeaseOrigin = 'agent' | 'user';
export type LeaseMark = 'handoff' | 'deliverable';

export interface TabLease {
  tabId: number;
  origin: LeaseOrigin;
  mark?: LeaseMark;
}

export function requireLeases(params: unknown): TabLease[] {
  const value = requireParamsObject(params).leases;
  if (!Array.isArray(value)) {
    throw new RpcError(ErrorCodes.invalidParams, 'leases must be an array');
  }
  return value.map((entry, index) => {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
      throw new RpcError(ErrorCodes.invalidParams, `leases[${index}] must be an object`);
    }
    const lease = entry as Record<string, unknown>;
    const tabId = lease.tabId;
    if (typeof tabId !== 'number' || !Number.isInteger(tabId) || tabId <= 0) {
      throw new RpcError(ErrorCodes.invalidParams, `leases[${index}].tabId must be a positive integer`);
    }
    const origin = lease.origin;
    if (origin !== 'agent' && origin !== 'user') {
      throw new RpcError(ErrorCodes.invalidParams, `leases[${index}].origin must be "agent" or "user"`);
    }
    const mark = lease.mark;
    if (mark !== undefined && mark !== 'handoff' && mark !== 'deliverable') {
      throw new RpcError(
        ErrorCodes.invalidParams,
        `leases[${index}].mark must be "handoff" or "deliverable"`,
      );
    }
    return { tabId, origin, mark } as TabLease;
  });
}
