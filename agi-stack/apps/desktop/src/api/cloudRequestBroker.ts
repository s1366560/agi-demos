import { DesktopApiError } from './client';
import type { DesktopRuntimeConfig } from '../types';

export type VaultBoundCloudMutation =
  | Readonly<{
      expected_revision: number;
      idempotency_key: string;
    }>
  | Readonly<{
      kind: 'idempotency-only';
      idempotency_key: string;
    }>;

export type VaultBoundCloudFormPart =
  | Readonly<{ kind: 'text'; name: string; value: string }>
  | Readonly<{
      kind: 'file';
      name: string;
      filename: string;
      mime_type: string;
      bytes_base64: string;
    }>;

export type VaultBoundCloudResponsePolicy =
  | Readonly<{
      kind: 'binary';
      max_bytes: number;
    }>
  | Readonly<{
      kind: 'event-stream';
      max_bytes: number;
    }>;

export type VaultBoundCloudRequest = Readonly<{
  path: string;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  form?: readonly VaultBoundCloudFormPart[];
  mutation?: VaultBoundCloudMutation;
  response?: VaultBoundCloudResponsePolicy;
  signal?: AbortSignal;
}>;

export type DesktopApiFetchOptions = Readonly<{
  responseType?: 'json' | 'binary' | 'event-stream';
  maxBytes?: number;
}>;

export type VaultBoundCloudRequestBroker = Readonly<{
  requestResponse(
    request: VaultBoundCloudRequest,
  ): Promise<Readonly<{ status: number; body: unknown }>>;
  requestJson(request: VaultBoundCloudRequest): Promise<unknown>;
  requestNoContent(request: VaultBoundCloudRequest): Promise<void>;
}>;

export function desktopVaultBoundCloudRequestBroker(): VaultBoundCloudRequestBroker | null {
  if (typeof window === 'undefined') return null;
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) return null;
  const requestResponse = async (
    input: VaultBoundCloudRequest,
  ): Promise<Readonly<{ status: number; body: unknown }>> => {
    if (input.signal?.aborted) throw abortError();
    const requestId = globalThis.crypto.randomUUID();
    const invokeRequest = invoke('cloud_request', {
      requestId,
      request: compactRequest(input),
    });
    const result = input.signal
      ? await waitForCloudRequest(invoke, requestId, invokeRequest, input.signal)
      : await invokeRequest;
    return parseResponse(result);
  };
  const request = async (input: VaultBoundCloudRequest): Promise<unknown> => {
    const response = await requestResponse(input);
    if (response.status < 200 || response.status >= 300) {
      throw responseError(response.status, response.body);
    }
    return response.body;
  };
  return Object.freeze({
    requestResponse,
    requestJson: request,
    async requestNoContent(input) {
      await request(input);
    },
  });
}

export function desktopApiAuthenticationAvailable(config: DesktopRuntimeConfig): boolean {
  if (config.apiKey.trim()) return true;
  return config.mode === 'cloud' && desktopVaultBoundCloudRequestBroker() !== null;
}

export async function desktopApiFetch(
  config: DesktopRuntimeConfig,
  path: string,
  init: RequestInit = {},
  options: DesktopApiFetchOptions = {},
): Promise<Response> {
  const broker =
    config.mode === 'cloud' && !config.apiKey.trim()
      ? desktopVaultBoundCloudRequestBroker()
      : null;
  if (!broker) return fetch(absoluteApiUrl(config.apiBaseUrl, path), init);

  const method = (init.method ?? 'GET').toUpperCase();
  if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    throw new Error('cloud_request_method_unsupported');
  }
  const serializedBody = await serializeRequestBody(init.body);
  const mutation = mutationAuthority(init.headers);
  const responsePolicy = binaryResponsePolicy(options);
  const result = await broker.requestResponse({
    path,
    method: method as VaultBoundCloudRequest['method'],
    ...(serializedBody.body === undefined ? {} : { body: serializedBody.body }),
    ...(serializedBody.form === undefined ? {} : { form: serializedBody.form }),
    ...(mutation === null ? {} : { mutation }),
    ...(responsePolicy === null ? {} : { response: responsePolicy }),
    signal: init.signal ?? undefined,
  });
  if (responsePolicy && result.status >= 200 && result.status < 300) {
    return responsePolicy.kind === 'binary'
      ? binaryResponse(result.status, result.body, responsePolicy.max_bytes)
      : eventStreamResponse(result.status, result.body, responsePolicy.max_bytes);
  }
  const responseBody = result.status === 204 || result.body === null
    ? null
    : JSON.stringify(result.body);
  return new Response(responseBody, {
    status: result.status,
    headers: responseBody === null ? undefined : { 'Content-Type': 'application/json' },
  });
}

function compactRequest(input: VaultBoundCloudRequest): Readonly<Record<string, unknown>> {
  return Object.freeze({
    path: input.path,
    method: input.method ?? 'GET',
    ...(input.body === undefined ? {} : { body: input.body }),
    ...(input.form === undefined ? {} : { form: input.form }),
    ...(input.mutation === undefined ? {} : { mutation: input.mutation }),
    ...(input.response === undefined ? {} : { response: input.response }),
  });
}

async function serializeRequestBody(
  body: BodyInit | null | undefined,
): Promise<Readonly<{
  body?: Readonly<Record<string, unknown>>;
  form?: readonly VaultBoundCloudFormPart[];
}>> {
  if (body === undefined || body === null) return Object.freeze({});
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return Object.freeze({ form: await serializeFormData(body) });
  }
  if (typeof body !== 'string') throw new Error('cloud_request_body_unsupported');
  let parsed: unknown;
  try {
    parsed = JSON.parse(body) as unknown;
  } catch {
    throw new Error('cloud_request_body_unsupported');
  }
  if (!isRecord(parsed)) throw new Error('cloud_request_body_unsupported');
  return Object.freeze({ body: Object.freeze({ ...parsed }) });
}

const MAX_REQUEST_BYTES = 512 * 1024;
const MAX_BINARY_RESPONSE_BYTES = 16 * 1024 * 1024;
const MAX_EVENT_STREAM_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_FORM_PARTS = 32;
const MAX_FORM_TEXT_BYTES = 64 * 1024;
const FORM_NAME = /^[A-Za-z0-9_.-]{1,128}$/u;
const MIME_TYPE = /^[A-Za-z0-9!#$&^_.+-]+\/[A-Za-z0-9!#$&^_.+-]+$/u;

async function serializeFormData(form: FormData): Promise<readonly VaultBoundCloudFormPart[]> {
  const parts: VaultBoundCloudFormPart[] = [];
  let totalBytes = 0;
  for (const [name, value] of form.entries()) {
    if (parts.length >= MAX_FORM_PARTS || !FORM_NAME.test(name)) {
      throw new Error('cloud_request_form_invalid');
    }
    totalBytes += utf8Bytes(name);
    if (typeof value === 'string') {
      const valueBytes = utf8Bytes(value);
      if (valueBytes > MAX_FORM_TEXT_BYTES) throw new Error('cloud_request_body_too_large');
      totalBytes += valueBytes;
      parts.push(Object.freeze({ kind: 'text', name, value }));
    } else {
      const filename = formFilename(value);
      const mimeType = value.type || 'application/octet-stream';
      requireSafeFilename(filename, 'cloud_request_filename_invalid');
      requireMimeType(mimeType, 'cloud_request_mime_type_invalid');
      const bytes = new Uint8Array(await value.arrayBuffer());
      totalBytes += utf8Bytes(filename) + utf8Bytes(mimeType) + bytes.byteLength;
      parts.push(
        Object.freeze({
          kind: 'file',
          name,
          filename,
          mime_type: mimeType,
          bytes_base64: encodeBase64(bytes),
        }),
      );
    }
    if (totalBytes > MAX_REQUEST_BYTES) throw new Error('cloud_request_body_too_large');
  }
  if (parts.length === 0) throw new Error('cloud_request_form_invalid');
  return Object.freeze(parts);
}

function binaryResponsePolicy(
  options: DesktopApiFetchOptions,
): VaultBoundCloudResponsePolicy | null {
  if (options.responseType === undefined || options.responseType === 'json') return null;
  if (options.responseType !== 'binary' && options.responseType !== 'event-stream') {
    throw new Error('cloud_response_type_unsupported');
  }
  const maxAllowed = options.responseType === 'binary'
    ? MAX_BINARY_RESPONSE_BYTES
    : MAX_EVENT_STREAM_RESPONSE_BYTES;
  const maxBytes = options.maxBytes ?? maxAllowed;
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > maxAllowed) {
    throw new Error('cloud_response_size_invalid');
  }
  return Object.freeze({ kind: options.responseType, max_bytes: maxBytes });
}

function binaryResponse(status: number, input: unknown, maxBytes: number): Response {
  const record = exactRecord(
    input,
    new Set(['kind', 'bytes_base64', 'size_bytes', 'mime_type', 'filename']),
    'cloud_binary_response_contract_invalid',
  );
  if (
    record.kind !== 'binary' ||
    typeof record.bytes_base64 !== 'string' ||
    !Number.isSafeInteger(record.size_bytes) ||
    Number(record.size_bytes) < 0 ||
    Number(record.size_bytes) > maxBytes ||
    typeof record.mime_type !== 'string' ||
    typeof record.filename !== 'string'
  ) {
    throw new Error('cloud_binary_response_contract_invalid');
  }
  requireMimeType(record.mime_type, 'cloud_binary_response_contract_invalid');
  requireSafeFilename(record.filename, 'cloud_binary_response_contract_invalid');
  const bytes = decodeBase64(record.bytes_base64, 'cloud_binary_response_contract_invalid');
  if (bytes.byteLength !== record.size_bytes) {
    throw new Error('cloud_binary_response_contract_invalid');
  }
  const responseBody = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(responseBody).set(bytes);
  return new Response(responseBody, {
    status,
    headers: {
      'Content-Type': record.mime_type,
      'Content-Disposition': `attachment; filename="${record.filename}"`,
      'Content-Length': String(bytes.byteLength),
    },
  });
}

function eventStreamResponse(status: number, input: unknown, maxBytes: number): Response {
  const record = exactRecord(
    input,
    new Set(['kind', 'text', 'size_bytes', 'mime_type']),
    'cloud_event_stream_response_contract_invalid',
  );
  if (
    record.kind !== 'event-stream' ||
    typeof record.text !== 'string' ||
    !Number.isSafeInteger(record.size_bytes) ||
    Number(record.size_bytes) < 0 ||
    Number(record.size_bytes) > maxBytes ||
    record.mime_type !== 'text/event-stream' ||
    utf8Bytes(record.text) !== record.size_bytes
  ) {
    throw new Error('cloud_event_stream_response_contract_invalid');
  }
  return new Response(record.text, {
    status,
    headers: {
      'Content-Type': 'text/event-stream',
      'Content-Length': String(record.size_bytes),
    },
  });
}

function formFilename(value: File): string {
  return typeof value.name === 'string' && value.name ? value.name : 'blob';
}

function requireSafeFilename(value: string, reason: string): void {
  if (
    !value ||
    value !== value.trim() ||
    utf8Bytes(value) > 255 ||
    value === '.' ||
    value === '..' ||
    value.includes('/') ||
    value.includes('\\') ||
    hasControl(value)
  ) {
    throw new Error(reason);
  }
}

function requireMimeType(value: string, reason: string): void {
  if (value.length > 127 || value !== value.trim() || !MIME_TYPE.test(value)) {
    throw new Error(reason);
  }
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function encodeBase64(bytes: Uint8Array): string {
  const chunks: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)));
  }
  return btoa(chunks.join(''));
}

function decodeBase64(value: string, reason: string): Uint8Array {
  let decoded: string;
  try {
    decoded = atob(value);
  } catch {
    throw new Error(reason);
  }
  const bytes = Uint8Array.from(decoded, (character) => character.charCodeAt(0));
  if (encodeBase64(bytes) !== value) throw new Error(reason);
  return bytes;
}

function exactRecord(
  value: unknown,
  keys: ReadonlySet<string>,
  reason: string,
): Record<string, unknown> {
  if (!isRecord(value) || Object.keys(value).some((key) => !keys.has(key))) {
    throw new Error(reason);
  }
  return value;
}

function hasControl(value: string): boolean {
  return /[\u0000-\u001f\u007f]/u.test(value);
}

function mutationAuthority(headersInit: HeadersInit | undefined): VaultBoundCloudMutation | null {
  const headers = new Headers(headersInit);
  const revision = headers.get('X-Expected-Revision');
  const idempotencyKey = headers.get('Idempotency-Key');
  if (revision === null && idempotencyKey === null) return null;
  if (revision === null) {
    if (!validIdempotencyKey(idempotencyKey)) {
      throw new Error('cloud_request_mutation_invalid');
    }
    return Object.freeze({
      kind: 'idempotency-only',
      idempotency_key: idempotencyKey,
    });
  }
  if (
    idempotencyKey === null ||
    !/^\d+$/u.test(revision) ||
    !Number.isSafeInteger(Number(revision)) ||
    !validIdempotencyKey(idempotencyKey)
  ) {
    throw new Error('cloud_request_mutation_invalid');
  }
  return Object.freeze({
    expected_revision: Number(revision),
    idempotency_key: idempotencyKey,
  });
}

function validIdempotencyKey(value: string | null): value is string {
  return (
    value !== null &&
    value.length >= 16 &&
    value.length <= 256 &&
    value === value.trim()
  );
}

function absoluteApiUrl(baseUrl: string, path: string): string {
  return `${baseUrl.trim().replace(/\/+$/u, '')}/${path.replace(/^\/+/, '')}`;
}

async function waitForCloudRequest(
  invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>,
  requestId: string,
  request: Promise<unknown>,
  signal: AbortSignal,
): Promise<unknown> {
  let rejectAbort: ((reason: Error) => void) | null = null;
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectAbort = reject;
  });
  const handleAbort = (): void => {
    void invoke('cloud_request_cancel', { requestId }).catch(() => undefined);
    rejectAbort?.(abortError());
  };
  signal.addEventListener('abort', handleAbort, { once: true });
  try {
    if (signal.aborted) handleAbort();
    return await Promise.race([request, aborted]);
  } finally {
    signal.removeEventListener('abort', handleAbort);
  }
}

function parseResponse(input: unknown): Readonly<{ status: number; body: unknown }> {
  if (!isRecord(input) || Object.keys(input).some((key) => key !== 'status' && key !== 'body')) {
    throw new Error('cloud_request_broker_contract_invalid');
  }
  if (
    typeof input.status !== 'number' ||
    !Number.isSafeInteger(input.status) ||
    input.status < 100 ||
    input.status > 599
  ) {
    throw new Error('cloud_request_broker_contract_invalid');
  }
  return Object.freeze({ status: input.status, body: input.body });
}

function responseError(status: number, body: unknown): DesktopApiError {
  const detail = isRecord(body) ? body.detail : null;
  const reasonCode = isRecord(body)
    ? (exactReason(body.reason_code) ??
      exactReason(body.code) ??
      (isRecord(detail) ? exactReason(detail.code) : null))
    : null;
  return new DesktopApiError(reasonCode ?? `HTTP ${status}`, status, body);
}

function exactReason(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function abortError(): Error {
  return new DOMException('The cloud request was aborted.', 'AbortError');
}
