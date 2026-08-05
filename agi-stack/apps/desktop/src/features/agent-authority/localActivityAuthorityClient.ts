import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  parseActivityReadState,
  requireActivityReadUpdateRequest,
} from './agentAuthorityContract';
import type {
  ActivityReadRetryStore,
  ActivityReadUpdateResult,
  AgentAuthorityReadOptions,
  DesktopActivityAuthorityClient,
  LocalActivityAuthorityScope,
  UpdateActivityReadStateRequest,
} from './agentAuthorityTypes';

type FetchPort = typeof fetch;

export type LocalActivityAuthorityClientOptions = Readonly<{
  fetchImpl: FetchPort;
  retryStore: ActivityReadRetryStore;
}>;

export function createLocalActivityAuthorityClient(
  config: DesktopRuntimeConfig,
  options: LocalActivityAuthorityClientOptions,
): DesktopActivityAuthorityClient {
  const runtimeConfig = Object.freeze({ ...config });
  const { fetchImpl, retryStore } = options;

  const client: DesktopActivityAuthorityClient = {
    async getActivityReadState(scope, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        projectPath(currentScope),
        { signal: requestOptions?.signal },
      );
      return parseActivityReadState(
        payload,
        currentScope,
        'local_activity_read_state_contract_invalid',
      );
    },
    async putActivityReadState(scope, request, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const currentRequest = requireActivityReadUpdateRequest(
        request,
        'local_activity_read_state_request_invalid',
      );
      return putActivityReadState(
        runtimeConfig,
        fetchImpl,
        retryStore,
        currentScope,
        currentRequest,
        requestOptions,
      );
    },
    async flushPendingActivityReadState(scope, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const pending = retryStore.load(currentScope);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        projectPath(currentScope),
        { signal: requestOptions?.signal },
      );
      const state = parseActivityReadState(
        payload,
        currentScope,
        'local_activity_read_state_contract_invalid',
      );
      if (pending.length === 0) return { kind: 'synced' as const, state };
      return putActivityReadState(
        runtimeConfig,
        fetchImpl,
        retryStore,
        currentScope,
        {
          expected_authority_revision: state.authority_revision,
          entries: pending,
        },
        requestOptions,
      );
    },
  };
  return Object.freeze(client);
}

async function putActivityReadState(
  config: DesktopRuntimeConfig,
  fetchImpl: FetchPort,
  retryStore: ActivityReadRetryStore,
  scope: LocalActivityAuthorityScope,
  request: UpdateActivityReadStateRequest,
  options?: AgentAuthorityReadOptions,
): Promise<ActivityReadUpdateResult> {
  try {
    const payload = await requestJson(
      config,
      fetchImpl,
      projectPath(scope),
      { method: 'PUT', body: request, signal: options?.signal },
    );
    const state = parseActivityReadState(
      payload,
      scope,
      'local_activity_read_state_contract_invalid',
    );
    retryStore.clear(scope);
    return { kind: 'synced', state };
  } catch (error) {
    if (!isOfflineTransportError(error, options?.signal)) throw error;
    retryStore.save(scope, request.entries);
    return {
      kind: 'queued_offline',
      availability: 'degraded',
      reasonCode: 'local_activity_read_state_offline_retry_pending',
      expectedAuthorityRevision: request.expected_authority_revision,
      entries: retryStore.load(scope),
    };
  }
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: Parameters<DesktopActivityAuthorityClient['getActivityReadState']>[0],
): LocalActivityAuthorityScope {
  if (
    scope.authority !== 'local' ||
    !isIdentifier(scope.principalId) ||
    !isIdentifier(scope.tenantId) ||
    !isIdentifier(scope.projectId) ||
    config.mode !== 'local' ||
    config.tenantId !== scope.tenantId ||
    config.projectId !== scope.projectId
  ) {
    throw contractError('local_activity_authority_runtime_scope_mismatch');
  }
  return scope;
}

type RequestJsonOptions = Readonly<{
  method?: 'GET' | 'PUT';
  body?: unknown;
  signal?: AbortSignal;
}>;

async function requestJson(
  config: DesktopRuntimeConfig,
  fetchImpl: FetchPort,
  path: string,
  options: RequestJsonOptions,
): Promise<unknown> {
  const sessionCredential = desktopApiCredential(config);
  if (!sessionCredential) {
    throw contractError('local_activity_authority_session_credential_required');
  }
  const launchCapability = desktopLaunchCapability(config);
  if (!launchCapability) {
    throw contractError('local_activity_authority_launch_capability_required');
  }
  const headers = new Headers({
    Accept: 'application/json',
    Authorization: `Bearer ${sessionCredential}`,
    'x-agistack-launch': launchCapability,
  });
  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetchImpl(absoluteUrl(config.apiBaseUrl, path), {
      method: options.method ?? 'GET',
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw contractError('local_activity_authority_network_unavailable');
  }

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
  if (!isJson || payload === null) {
    throw contractError('local_activity_authority_response_invalid');
  }
  return payload;
}

function projectPath(scope: LocalActivityAuthorityScope): string {
  return `/api/v1/projects/${encodeURIComponent(scope.projectId)}/activity/read-state`;
}

function isOfflineTransportError(
  error: unknown,
  signal?: AbortSignal,
): boolean {
  return (
    !signal?.aborted &&
    error instanceof DesktopApiError &&
    error.status === 0 &&
    error.message === 'local_activity_authority_network_unavailable'
  );
}

function isIdentifier(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value === value.trim()
  );
}

function errorMessage(status: number, payload: unknown): string {
  if (
    payload !== null &&
    typeof payload === 'object' &&
    !Array.isArray(payload) &&
    typeof (payload as Record<string, unknown>).detail === 'string'
  ) {
    return String((payload as Record<string, unknown>).detail);
  }
  return `HTTP ${status}`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}
