import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  RuntimeDeployment,
  RuntimeDeploymentProgressEvent,
  RuntimeDeploymentsClient,
  RuntimeDeploymentsPage,
  RuntimeDeploymentsQuery,
  RuntimeDeploymentsScope,
} from './runtimeDeploymentsTypes';

type Fetch = typeof globalThis.fetch;

export type RuntimeDeploymentsClientDependencies = Readonly<{
  fetch?: Fetch;
}>;

export class RuntimeDeploymentsUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimeDeploymentsUnavailableError';
    this.reasonCode = reasonCode;
  }
}

export function createRuntimeDeploymentsClient(
  config: DesktopRuntimeConfig,
  dependencies: RuntimeDeploymentsClientDependencies = {},
): RuntimeDeploymentsClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchImpl = dependencies.fetch ?? globalThis.fetch;
  return Object.freeze({
    async list(scope, query = {}, options) {
      const instanceId = requireCloudScope(runtimeConfig, scope, true);
      const normalized = normalizeQuery(query);
      const params = new URLSearchParams({
        instance_id: instanceId,
        page: String(normalized.page),
        page_size: String(normalized.pageSize),
      });
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/deploys/?${params.toString()}`,
        fetchImpl,
        options?.signal,
      );
      return parsePage(payload, scope);
    },
    async get(scope, deploymentId, options) {
      requireCloudScope(runtimeConfig, scope, false);
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/deploys/${encodeURIComponent(identifier(deploymentId))}`,
        fetchImpl,
        options?.signal,
      );
      return parseDeployment(payload, scope);
    },
    async streamProgress(scope, deploymentId, onEvent, options) {
      requireCloudScope(runtimeConfig, scope, false);
      await requestProgress(
        runtimeConfig,
        `/api/v1/deploys/${encodeURIComponent(identifier(deploymentId))}/progress`,
        fetchImpl,
        onEvent,
        options?.signal,
      );
    },
  });
}

function requireCloudScope(
  config: DesktopRuntimeConfig,
  scope: RuntimeDeploymentsScope,
  requireInstance: boolean,
): string {
  if (
    config.mode !== scope.authority ||
    identifier(config.tenantId) !== identifier(scope.tenantId)
  ) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_runtime_scope_mismatch',
    );
  }
  if (scope.authority !== 'cloud') {
    throw new RuntimeDeploymentsUnavailableError(
      'cloud_deployment_authority_not_applicable',
    );
  }
  if (scope.instanceId === null) {
    if (requireInstance) {
      throw new RuntimeDeploymentsUnavailableError(
        'runtime_deployments_instance_scope_required',
      );
    }
    return '';
  }
  return identifier(scope.instanceId);
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  fetchImpl: Fetch,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetchImpl(absoluteUrl(config.apiBaseUrl, path), {
    method: 'GET',
    headers: requestHeaders(config, 'application/json'),
    signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) throw contractError();
  return payload;
}

async function requestProgress(
  config: DesktopRuntimeConfig,
  path: string,
  fetchImpl: Fetch,
  onEvent: (
    event: RuntimeDeploymentProgressEvent,
  ) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetchImpl(absoluteUrl(config.apiBaseUrl, path), {
    method: 'GET',
    headers: requestHeaders(config, 'text/event-stream'),
    signal,
  });
  if (!response.ok) {
    const payload = await response.text().catch(() => '');
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('text/event-stream') || !response.body) {
    throw contractError();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (!signal?.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const consumed = await consumeProgressEvents(buffer, onEvent, reader);
    buffer = consumed.remainder;
    if (consumed.done) return;
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    if (await consumeProgressEvent(buffer, onEvent, reader)) return;
  }
  if (!signal?.aborted) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_progress_disconnected',
    );
  }
}

async function consumeProgressEvents(
  input: string,
  onEvent: (
    event: RuntimeDeploymentProgressEvent,
  ) => void | Promise<void>,
  reader: ReadableStreamDefaultReader<Uint8Array>,
): Promise<Readonly<{ remainder: string; done: boolean }>> {
  let buffer = input;
  let separator = findEventSeparator(buffer);
  while (separator) {
    const rawEvent = buffer.slice(0, separator.index);
    buffer = buffer.slice(separator.index + separator.length);
    if (await consumeProgressEvent(rawEvent, onEvent, reader)) {
      return Object.freeze({ remainder: '', done: true });
    }
    separator = findEventSeparator(buffer);
  }
  return Object.freeze({ remainder: buffer, done: false });
}

async function consumeProgressEvent(
  rawEvent: string,
  onEvent: (
    event: RuntimeDeploymentProgressEvent,
  ) => void | Promise<void>,
  reader: ReadableStreamDefaultReader<Uint8Array>,
): Promise<boolean> {
  const event = parseProgressEvent(rawEvent);
  if (!event) return false;
  await onEvent(event);
  if (event.type !== 'done') return false;
  await reader.cancel().catch(() => undefined);
  return true;
}

function parseProgressEvent(
  rawEvent: string,
): RuntimeDeploymentProgressEvent | null {
  const data = rawEvent
    .split(/\r?\n/u)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
    .trim();
  if (!data) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(parsed) || !isNonEmptyString(parsed.type)) return null;
  return Object.freeze({
    type: parsed.type,
    status: isNonEmptyString(parsed.status) ? parsed.status : null,
    deployId: isNonEmptyString(parsed.deploy_id) ? parsed.deploy_id : null,
  });
}

function findEventSeparator(
  buffer: string,
): Readonly<{ index: number; length: number }> | null {
  const lfIndex = buffer.indexOf('\n\n');
  const crlfIndex = buffer.indexOf('\r\n\r\n');
  if (lfIndex === -1 && crlfIndex === -1) return null;
  if (lfIndex === -1) return Object.freeze({ index: crlfIndex, length: 4 });
  if (crlfIndex === -1) return Object.freeze({ index: lfIndex, length: 2 });
  return crlfIndex < lfIndex
    ? Object.freeze({ index: crlfIndex, length: 4 })
    : Object.freeze({ index: lfIndex, length: 2 });
}

function requestHeaders(
  config: DesktopRuntimeConfig,
  accept: string,
): Headers {
  const headers = new Headers({ Accept: accept });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  return headers;
}

function parsePage(
  payload: unknown,
  scope: RuntimeDeploymentsScope,
): RuntimeDeploymentsPage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.deploys) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.page) ||
    !isPositiveInteger(payload.page_size)
  ) {
    throw contractError();
  }
  const deployments = payload.deploys.map((value) =>
    parseDeployment(value, scope),
  );
  if (deployments.length > payload.total) throw contractError();
  return Object.freeze({
    deployments: Object.freeze(deployments),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseDeployment(
  value: unknown,
  scope: RuntimeDeploymentsScope,
): RuntimeDeployment {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.instance_id) ||
    (scope.instanceId !== null && value.instance_id !== scope.instanceId) ||
    !isNonEmptyString(value.action) ||
    !isNonnegativeInteger(value.revision) ||
    !isDeploymentStatus(value.status) ||
    !isNullableString(value.message) ||
    !isNullableString(value.image_version) ||
    !isNullableNonnegativeInteger(value.replicas) ||
    !isRecord(value.config_snapshot) ||
    !isNullableString(value.triggered_by) ||
    !isNullableString(value.started_at) ||
    !isNullableString(value.finished_at) ||
    !isNonEmptyString(value.created_at)
  ) {
    throw contractError();
  }
  return Object.freeze({
    id: value.id,
    instanceId: value.instance_id,
    action: value.action,
    revision: value.revision,
    status: value.status,
    imageVersion: value.image_version,
    replicas: value.replicas,
    startedAt: value.started_at,
    finishedAt: value.finished_at,
    createdAt: value.created_at,
  });
}

function normalizeQuery(query: RuntimeDeploymentsQuery) {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 10;
  if (
    !isPositiveInteger(page) ||
    !isPositiveInteger(pageSize) ||
    pageSize > 100
  ) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_query_invalid',
    );
  }
  return Object.freeze({ page, pageSize });
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') {
    return payload.detail;
  }
  return `Runtime Deployments request failed (${status})`;
}

function identifier(value: string): string {
  if (!value || value !== value.trim()) {
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_identifier_invalid',
    );
  }
  return value;
}

function contractError(): RuntimeDeploymentsUnavailableError {
  return new RuntimeDeploymentsUnavailableError(
    'runtime_deployments_contract_invalid',
  );
}

function isDeploymentStatus(
  value: unknown,
): value is RuntimeDeployment['status'] {
  return (
    value === 'pending' ||
    value === 'running' ||
    value === 'success' ||
    value === 'failed' ||
    value === 'cancelled'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isNullableNonnegativeInteger(
  value: unknown,
): value is number | null {
  return value === null || isNonnegativeInteger(value);
}
