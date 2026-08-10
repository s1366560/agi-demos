import { desktopApiCredential, desktopLaunchCapability } from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export class NativeRouteClientError extends Error {
  readonly status: number;
  readonly reasonCode: string;
  readonly payload: unknown;

  constructor(reasonCode: string, status = 0, payload: unknown = null) {
    super(reasonCode);
    this.name = 'NativeRouteClientError';
    this.status = status;
    this.reasonCode = reasonCode;
    this.payload = payload;
  }
}

export type NativeRouteRequest = Readonly<{
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}>;

export async function requestNativeRouteJson(
  config: DesktopRuntimeConfig,
  path: string,
  request: NativeRouteRequest = {},
): Promise<unknown> {
  const credential = desktopApiCredential(config);
  if (!desktopApiAuthenticationAvailable(config)) {
    throw new NativeRouteClientError('desktop_trusted_session_required', 401);
  }
  const headers = new Headers({ Accept: 'application/json' });
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (config.mode === 'local') {
    if (!launchCapability) {
      throw new NativeRouteClientError('desktop_sidecar_launch_capability_required', 401);
    }
    headers.set('X-Agistack-Launch', launchCapability);
  }
  const body = request.body === undefined ? undefined : JSON.stringify(request.body);
  if (body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: request.method ?? 'GET',
    headers,
    credentials: 'omit',
    signal: request.signal,
    ...(body === undefined ? {} : { body }),
  });
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw new NativeRouteClientError('desktop_native_route_response_too_large', 502);
  }
  if (response.status === 204) {
    if (!response.ok) throw responseError(response.status, null);
    return null;
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new NativeRouteClientError('desktop_native_route_response_too_large', 502);
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  const payload = contentType.includes('application/json') ? parseJson(text) : text;
  if (!response.ok) throw responseError(response.status, payload);
  if (!contentType.includes('application/json')) {
    throw new NativeRouteClientError('desktop_native_route_response_not_json', 502, payload);
  }
  return payload;
}

export function requireRuntimeAuthority(
  config: DesktopRuntimeConfig,
  authority: unknown,
  reasonCode: string,
): asserts authority is DesktopRuntimeConfig['mode'] {
  if (authority !== config.mode) {
    throw new NativeRouteClientError(reasonCode, 409);
  }
}

export function exactNativeRouteIdentifier(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string' || value.length === 0 || value !== value.trim()) {
    throw new NativeRouteClientError(reasonCode, 422);
  }
  return value;
}

export function unavailableNativeRouteAction(reasonCode: string): never {
  throw new NativeRouteClientError(reasonCode, 501, {
    reason_code: reasonCode,
  });
}

export function nativeRouteFailure(
  error: unknown,
  fallbackReasonCode: string,
): Readonly<{
  state: 'conflict' | 'error' | 'forbidden' | 'unavailable';
  reasonCode: string;
  retryable: boolean;
}> {
  const status =
    error instanceof NativeRouteClientError
      ? error.status
      : isRecord(error) && typeof error.status === 'number'
        ? error.status
        : 0;
  const reasonCode =
    error instanceof NativeRouteClientError
      ? error.reasonCode
      : isRecord(error) && typeof error.reasonCode === 'string' && error.reasonCode.trim()
        ? error.reasonCode
        : fallbackReasonCode;
  return Object.freeze({
    state:
      status === 401 || status === 403
        ? 'forbidden'
        : status === 409 || status === 412 || status === 428
          ? 'conflict'
          : status === 0 || status === 404 || status === 501 || status === 503
            ? 'unavailable'
            : 'error',
    reasonCode,
    retryable:
      status === 408 ||
      status === 425 ||
      status === 429 ||
      status === 503 ||
      (status >= 500 && status <= 599 && status !== 501),
  });
}

export function isNativeRouteRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function responseError(status: number, payload: unknown): NativeRouteClientError {
  const record = isNativeRouteRecord(payload) ? payload : null;
  const reasonCode = firstText(record?.reason_code, record?.code);
  return new NativeRouteClientError(
    reasonCode ?? `desktop_native_route_http_${String(status)}`,
    status,
    payload,
  );
}

function parseJson(text: string): unknown {
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    throw new NativeRouteClientError('desktop_native_route_response_json_invalid', 502);
  }
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
