import {
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiError,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopApiFetchOptions } from '../api/cloudRequestBroker';
import {
  RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS,
  RUNTIME_DEPLOYMENTS_CLOUD_REASON,
  RUNTIME_DEPLOYMENTS_LOCAL_REASON,
  RuntimeDeploymentsUnavailableError,
} from '../features/runtime-deployments/runtimeDeploymentsContract';
import type {
  RuntimeDeployment,
  RuntimeDeploymentProgressEvent,
  RuntimeDeploymentsPage,
  RuntimeDeploymentsQuery,
  RuntimeDeploymentsScope,
} from '../features/runtime-deployments/runtimeDeploymentsTypes';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopRuntimeDeploymentsConfigV2,
  cloneDesktopRuntimeDeploymentsScopeV2,
} from './desktopRuntimeDeploymentsOperationContractV2';

type FetchPathV2 = (
  path: string,
  init: RequestInit,
  options?: DesktopApiFetchOptions,
) => Promise<Response>;

const MAX_DEPLOYMENT_PROGRESS_BYTES_V2 = 2 * 1024 * 1024;

export type DesktopRuntimeDeploymentsHttpAuthorityV2 = Readonly<{
  list: (
    query: Required<RuntimeDeploymentsQuery>,
    signal?: AbortSignal,
  ) => Promise<RuntimeDeploymentsPage>;
  get: (deploymentId: string, signal?: AbortSignal) => Promise<RuntimeDeployment>;
  streamProgress: (
    deploymentId: string,
    onEvent: (
      event: RuntimeDeploymentProgressEvent,
    ) => void | Promise<void>,
    signal?: AbortSignal,
  ) => Promise<void>;
  probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}>;

export function createDesktopRuntimeDeploymentsHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: RuntimeDeploymentsScope,
): DesktopRuntimeDeploymentsHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopRuntimeDeploymentsConfigV2(config);
  const operationScope = cloneDesktopRuntimeDeploymentsScopeV2(scope, runtimeConfig);
  const fetchPath: FetchPathV2 = (path, init, options) =>
    desktopApiFetch(runtimeConfig, path, init, options);
  return Object.freeze({
    async list(query, signal) {
      const instanceId = requireCloudScopeV2(operationScope, true);
      const params = new URLSearchParams({
        instance_id: instanceId,
        page: String(query.page),
        page_size: String(query.pageSize),
      });
      const payload = await requestJsonV2(
        runtimeConfig,
        `/api/v1/deploys/?${params.toString()}`,
        fetchPath,
        signal,
      );
      return parsePageV2(payload, operationScope);
    },
    async get(deploymentId, signal) {
      requireCloudScopeV2(operationScope, false);
      const payload = await requestJsonV2(
        runtimeConfig,
        `/api/v1/deploys/${encodeURIComponent(requireIdentifierV2(deploymentId))}`,
        fetchPath,
        signal,
      );
      return parseDeploymentV2(payload, operationScope);
    },
    async streamProgress(deploymentId, onEvent, signal) {
      requireCloudScopeV2(operationScope, false);
      await requestProgressV2(
        runtimeConfig,
        `/api/v1/deploys/${encodeURIComponent(requireIdentifierV2(deploymentId))}/progress`,
        fetchPath,
        onEvent,
        signal,
      );
    },
    async probe() {
      return capabilityV2(operationScope);
    },
  });
}

function requireCloudScopeV2(scope: RuntimeDeploymentsScope, requireInstance: boolean): string {
  if (scope.authority !== 'cloud') {
    throw new RuntimeDeploymentsUnavailableError(RUNTIME_DEPLOYMENTS_LOCAL_REASON);
  }
  if (scope.instanceId === null) {
    if (requireInstance) {
      throw new RuntimeDeploymentsUnavailableError(
        'runtime_deployments_instance_scope_required',
      );
    }
    return '';
  }
  return requireIdentifierV2(scope.instanceId);
}

async function requestJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  fetchPath: FetchPathV2,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetchPath(path, {
    method: 'GET',
    headers: requestHeadersV2(config, 'application/json'),
    signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessageV2(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) throw responseContractErrorV2();
  return payload;
}

async function requestProgressV2(
  config: DesktopRuntimeConfig,
  path: string,
  fetchPath: FetchPathV2,
  onEvent: (
    event: RuntimeDeploymentProgressEvent,
  ) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) throw abortErrorV2();
  const response = await fetchPath(
    path,
    {
      method: 'GET',
      headers: requestHeadersV2(config, 'text/event-stream'),
      signal,
    },
    { responseType: 'event-stream', maxBytes: MAX_DEPLOYMENT_PROGRESS_BYTES_V2 },
  );
  if (!response.ok) {
    const payload = await response.text().catch(() => '');
    throw new DesktopApiError(
      errorMessageV2(response.status, payload),
      response.status,
      payload,
    );
  }
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('text/event-stream') || !response.body) {
    throw responseContractErrorV2();
  }

  const reader = response.body.getReader();
  const cancel = onceAsyncV2(() => reader.cancel().then(() => undefined));
  const decoder = new TextDecoder();
  let buffer = '';
  let receivedBytes = 0;
  try {
    while (true) {
      if (signal?.aborted) {
        await suppressV2(cancel());
        return;
      }
      const { done, value } = await reader.read();
      if (done) break;
      receivedBytes += value.byteLength;
      if (receivedBytes > MAX_DEPLOYMENT_PROGRESS_BYTES_V2) {
        throw responseContractErrorV2();
      }
      buffer += decoder.decode(value, { stream: true });
      const consumed = await consumeProgressEventsV2(buffer, onEvent);
      buffer = consumed.remainder;
      if (consumed.done) {
        await suppressV2(cancel());
        return;
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      const done = await consumeProgressEventV2(buffer, onEvent);
      if (done) {
        await suppressV2(cancel());
        return;
      }
    }
    if (signal?.aborted) {
      await suppressV2(cancel());
      return;
    }
    throw new RuntimeDeploymentsUnavailableError(
      'runtime_deployments_progress_disconnected',
    );
  } catch (error) {
    await suppressV2(cancel());
    throw error;
  }
}

async function consumeProgressEventsV2(
  input: string,
  onEvent: (
    event: RuntimeDeploymentProgressEvent,
  ) => void | Promise<void>,
): Promise<Readonly<{ remainder: string; done: boolean }>> {
  let buffer = input;
  let separator = findEventSeparatorV2(buffer);
  while (separator) {
    const rawEvent = buffer.slice(0, separator.index);
    buffer = buffer.slice(separator.index + separator.length);
    if (await consumeProgressEventV2(rawEvent, onEvent)) {
      return Object.freeze({ remainder: '', done: true });
    }
    separator = findEventSeparatorV2(buffer);
  }
  return Object.freeze({ remainder: buffer, done: false });
}

async function consumeProgressEventV2(
  rawEvent: string,
  onEvent: (
    event: RuntimeDeploymentProgressEvent,
  ) => void | Promise<void>,
): Promise<boolean> {
  const event = parseProgressEventV2(rawEvent);
  if (!event) return false;
  await onEvent(event);
  return event.type === 'done';
}

function parseProgressEventV2(rawEvent: string): RuntimeDeploymentProgressEvent | null {
  const data = rawEvent
    .split(/\r?\n/u)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
    .trim();
  if (!data) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data) as unknown;
  } catch {
    return null;
  }
  if (!isRecordV2(parsed) || !canonicalStringV2(parsed.type)) return null;
  return Object.freeze({
    type: parsed.type,
    status: canonicalStringV2(parsed.status) ? parsed.status : null,
    deployId: canonicalStringV2(parsed.deploy_id) ? parsed.deploy_id : null,
  });
}

function findEventSeparatorV2(
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

function requestHeadersV2(config: DesktopRuntimeConfig, accept: string): Headers {
  const headers = new Headers({ Accept: accept });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  return headers;
}

function parsePageV2(
  payload: unknown,
  scope: RuntimeDeploymentsScope,
): RuntimeDeploymentsPage {
  if (
    !isRecordV2(payload) ||
    !Array.isArray(payload.deploys) ||
    !nonnegativeIntegerV2(payload.total) ||
    !integerInRangeV2(payload.page, 1, 100_000) ||
    !integerInRangeV2(payload.page_size, 1, 100)
  ) {
    throw responseContractErrorV2();
  }
  const deployments = payload.deploys.map((value) => parseDeploymentV2(value, scope));
  if (deployments.length > payload.total || deployments.length > payload.page_size) {
    throw responseContractErrorV2();
  }
  return Object.freeze({
    deployments: Object.freeze(deployments),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseDeploymentV2(
  value: unknown,
  scope: RuntimeDeploymentsScope,
): RuntimeDeployment {
  if (
    !isRecordV2(value) ||
    !canonicalIdentifierV2(value.id) ||
    !canonicalIdentifierV2(value.instance_id) ||
    (scope.instanceId !== null && value.instance_id !== scope.instanceId) ||
    !canonicalStringV2(value.action) ||
    !nonnegativeIntegerV2(value.revision) ||
    !isDeploymentStatusV2(value.status) ||
    !nullableStringV2(value.message) ||
    !nullableStringV2(value.image_version) ||
    !nullableNonnegativeIntegerV2(value.replicas) ||
    !isRecordV2(value.config_snapshot) ||
    !nullableStringV2(value.triggered_by) ||
    !nullableStringV2(value.started_at) ||
    !nullableStringV2(value.finished_at) ||
    !canonicalStringV2(value.created_at)
  ) {
    throw responseContractErrorV2();
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

function capabilityV2(scope: RuntimeDeploymentsScope): DesktopCapabilityAvailability {
  const local = scope.authority === 'local';
  return Object.freeze({
    availability: local ? 'not_applicable' : 'degraded',
    reason_code: local ? RUNTIME_DEPLOYMENTS_LOCAL_REASON : RUNTIME_DEPLOYMENTS_CLOUD_REASON,
    service_version: local ? null : '0.1.0',
    contract_version: local ? null : '3.0.0',
    allowed_actions: local ? Object.freeze([]) : RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS,
    scope: Object.freeze({
      tenant_id: scope.tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
  });
}

function requireIdentifierV2(value: unknown): string {
  if (!canonicalIdentifierV2(value)) {
    throw new RuntimeDeploymentsUnavailableError('runtime_deployments_identifier_invalid');
  }
  return value;
}

function responseContractErrorV2(): RuntimeDeploymentsUnavailableError {
  return new RuntimeDeploymentsUnavailableError('runtime_deployments_contract_invalid');
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isRecordV2(payload) && typeof payload.detail === 'string') return payload.detail;
  return `Runtime Deployments request failed (${status})`;
}

function isDeploymentStatusV2(value: unknown): value is RuntimeDeployment['status'] {
  return (
    value === 'pending' ||
    value === 'running' ||
    value === 'success' ||
    value === 'failed' ||
    value === 'cancelled'
  );
}

function canonicalIdentifierV2(value: unknown): value is string {
  return canonicalStringV2(value) && !/\s/u.test(value);
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function nullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function nullableNonnegativeIntegerV2(value: unknown): value is number | null {
  return value === null || nonnegativeIntegerV2(value);
}

function nonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function integerInRangeV2(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function onceAsyncV2(operation: () => Promise<void>): () => Promise<void> {
  let pending: Promise<void> | null = null;
  return () => {
    pending ??= operation();
    return pending;
  };
}

async function suppressV2(operation: Promise<void>): Promise<void> {
  await operation.catch(() => undefined);
}

function abortErrorV2(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError');
}
