import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  MAX_SCHEMA_RESPONSE_BYTES,
  MAX_SCHEMA_REQUEST_BYTES,
} from '../features/project-administration/nativeProjectSchemaSchemaGenerated';
import { parseNativeProjectSchemaJson } from '../features/project-administration/nativeProjectSchemaJson';
import {
  plainSchemaObject,
  utf8Length,
} from '../features/project-administration/nativeProjectSchemaShape';
import { projectKnowledgeError } from '../features/project-knowledge/projectKnowledgeClient';
import { requireNativeKnowledgeTransportV2 } from './desktopNativeKnowledgeSyncHttpV2';

type Options = Readonly<{
  method: 'GET' | 'POST';
  body?: object;
  signal?: AbortSignal;
}>;
/** Uses the existing native credential broker; callers must provide their live operation guard. */
export async function requestNativeProjectSchemaJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: Options,
  requireCurrent: () => void,
): Promise<unknown> {
  requireNativeKnowledgeTransportV2(config);
  const current = () => {
    requireCurrent();
    options.signal?.throwIfAborted();
  };
  current();
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  if (body !== undefined && utf8Length(body) > MAX_SCHEMA_REQUEST_BYTES)
    throw projectKnowledgeError('native_project_schema_request_too_large', 413);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config),
    launch = desktopLaunchCapability(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  if (launch) headers.set('X-Agistack-Launch', launch);
  if (body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: options.method,
    body,
    headers,
    credentials: 'omit',
    redirect: 'error',
    signal: options.signal,
  });
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let complete = false;
  try {
    current();
    if (response.redirected || (response.status >= 300 && response.status < 400))
      throw projectKnowledgeError('native_project_schema_redirect_rejected');
    const length = response.headers.get('content-length');
    if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_SCHEMA_RESPONSE_BYTES))
      throw projectKnowledgeError('native_project_schema_response_too_large', 413);
    if (!response.body)
      throw projectKnowledgeError('native_project_schema_response_contract_invalid');
    reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let bytes = 0,
      text = '';
    while (true) {
      current();
      const chunk = await reader.read();
      current();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > MAX_SCHEMA_RESPONSE_BYTES)
        throw projectKnowledgeError('native_project_schema_response_too_large', 413);
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    if (
      !response.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase().endsWith('/json')
    )
      throw projectKnowledgeError('native_project_schema_response_contract_invalid');
    const value = parseNativeProjectSchemaJson(text);
    current();
    if (!response.ok) {
      const error =
        plainSchemaObject(value) && plainSchemaObject(value.error) ? value.error.code : undefined;
      throw new DesktopApiError(
        typeof error === 'string' ? error : `HTTP ${response.status}`,
        response.status,
        value,
      );
    }
    complete = true;
    return value;
  } finally {
    if (!complete) {
      if (reader) await reader.cancel().catch(() => undefined);
      else await response.body?.cancel().catch(() => undefined);
    }
    reader?.releaseLock();
  }
}
