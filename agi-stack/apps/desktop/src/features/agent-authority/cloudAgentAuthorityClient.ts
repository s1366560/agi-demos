import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import {
  parseActivityReadState,
  parsePromoteRunInputResponse,
  parseProjectMyWorkResponse,
  parseRunInputAck,
  parseRunInputListResponse,
  parseRunChanges,
  parseRunSummary,
  requireActivityReadUpdateRequest,
  requireCloudAuthorityScope,
  requireCreateRunInputRequest,
  requirePromoteRunInputRequest,
  requireRunChangesOptions,
} from './agentAuthorityContract';
import { createLocalStorageActivityReadRetryStore } from './activityReadRetryStore';
import { createLocalActivityAuthorityClient } from './localActivityAuthorityClient';
import type {
  ActivityReadRetryStore,
  ActivityReadUpdateResult,
  ActivityAuthorityScope,
  AgentAuthorityReadOptions,
  CloudAgentAuthorityScope,
  DesktopAgentAuthorityAdapter,
  DesktopAgentAuthorityAction,
  DesktopCloudAgentAuthorityClient,
  GetRunChangesOptions,
  UpdateActivityReadStateRequest,
} from './agentAuthorityTypes';

const CLOUD_ALLOWED_ACTIONS: readonly DesktopAgentAuthorityAction[] = Object.freeze([
  'list_my_work',
  'read_activity',
  'write_activity',
  'review_run_summary',
  'review_run_changes',
  'create_run_input',
  'list_run_inputs',
  'promote_run_input',
] as const);
const LOCAL_ACTIVITY_ALLOWED_ACTIONS: readonly DesktopAgentAuthorityAction[] =
  Object.freeze(['read_activity', 'write_activity']);

type FetchPort = typeof fetch;

export type DesktopAgentAuthorityClientOptions = Readonly<{
  fetchImpl?: FetchPort;
  retryStore?: ActivityReadRetryStore;
}>;

export function createDesktopAgentAuthorityAdapter(
  config: DesktopRuntimeConfig,
  options: DesktopAgentAuthorityClientOptions = {},
): DesktopAgentAuthorityAdapter {
  if (config.mode === 'local') {
    const retryStore =
      options.retryStore ?? createLocalStorageActivityReadRetryStore();
    const activityClient = createLocalActivityAuthorityClient(config, {
      fetchImpl: options.fetchImpl ?? fetch,
      retryStore,
    });
    return Object.freeze({
      authority: 'local',
      availability: 'available',
      reasonCode: null,
      allowedActions: LOCAL_ACTIVITY_ALLOWED_ACTIONS,
      client: null,
      activityClient,
      activityScope: Object.freeze({
        authority: 'local',
        principalId: 'local-user',
        tenantId: config.tenantId,
        projectId: config.projectId,
      }),
    });
  }
  const client = createCloudAgentAuthorityClient(config, options);
  return Object.freeze({
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    allowedActions: CLOUD_ALLOWED_ACTIONS,
    client,
    activityClient: client,
    activityScope: null,
  });
}

function createCloudAgentAuthorityClient(
  config: DesktopRuntimeConfig,
  options: DesktopAgentAuthorityClientOptions,
): DesktopCloudAgentAuthorityClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchImpl = options.fetchImpl ?? fetch;
  const retryStore =
    options.retryStore ?? createLocalStorageActivityReadRetryStore();

  const client: DesktopCloudAgentAuthorityClient = {
    async listMyWork(scope, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        projectPath(currentScope, '/my-work'),
        { signal: requestOptions?.signal },
      );
      return parseProjectMyWorkResponse(payload, currentScope);
    },
    async getActivityReadState(scope, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        projectPath(currentScope, '/activity/read-state'),
        { signal: requestOptions?.signal },
      );
      return parseActivityReadState(payload, currentScope);
    },
    async putActivityReadState(scope, request, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const currentRequest = requireActivityReadUpdateRequest(request);
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
      const statePayload = await requestJson(
        runtimeConfig,
        fetchImpl,
        projectPath(currentScope, '/activity/read-state'),
        { signal: requestOptions?.signal },
      );
      const state = parseActivityReadState(statePayload, currentScope);
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
    async getRunSummary(scope, runId, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const currentRunId = requireIdentifier(
        runId,
        'cloud_run_summary_run_id_invalid',
      );
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        runPath(currentRunId, '/summary'),
        { signal: requestOptions?.signal },
      );
      return parseRunSummary(payload, currentScope, currentRunId);
    },
    async getRunChanges(scope, runId, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const currentRunId = requireIdentifier(
        runId,
        'cloud_run_changes_run_id_invalid',
      );
      const currentRequest = requireRunChangesOptions(requestOptions);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        runChangesPath(currentRunId, currentRequest),
        { signal: currentRequest.signal },
      );
      return parseRunChanges(payload, currentRunId, currentRequest);
    },
    async createRunInput(scope, runId, request, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const currentRunId = requireIdentifier(
        runId,
        'cloud_run_input_run_id_invalid',
      );
      const currentRequest = requireCreateRunInputRequest(request);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        runPath(currentRunId, '/inputs'),
        {
          method: 'POST',
          body: currentRequest,
          signal: requestOptions?.signal,
        },
      );
      return parseRunInputAck(payload, currentRunId, currentRequest);
    },
    async listRunInputs(scope, runId, requestOptions) {
      requireRuntimeScope(runtimeConfig, scope);
      const currentRunId = requireIdentifier(
        runId,
        'cloud_run_input_run_id_invalid',
      );
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        runPath(currentRunId, '/inputs'),
        { signal: requestOptions?.signal },
      );
      return parseRunInputListResponse(payload, currentRunId);
    },
    async promoteRunInput(scope, runId, inputId, request, requestOptions) {
      const currentScope = requireRuntimeScope(runtimeConfig, scope);
      const currentRunId = requireIdentifier(
        runId,
        'cloud_run_input_run_id_invalid',
      );
      const currentInputId = requireIdentifier(
        inputId,
        'cloud_run_input_id_invalid',
      );
      const currentRequest = requirePromoteRunInputRequest(request);
      const payload = await requestJson(
        runtimeConfig,
        fetchImpl,
        runPath(
          currentRunId,
          `/inputs/${encodeURIComponent(currentInputId)}/promote`,
        ),
        {
          method: 'POST',
          body: currentRequest,
          signal: requestOptions?.signal,
        },
      );
      return parsePromoteRunInputResponse(
        payload,
        currentScope,
        currentRunId,
        currentRequest,
      );
    },
  };
  return Object.freeze(client);
}

async function putActivityReadState(
  config: DesktopRuntimeConfig,
  fetchImpl: FetchPort,
  retryStore: ActivityReadRetryStore,
  scope: CloudAgentAuthorityScope,
  request: UpdateActivityReadStateRequest,
  options?: AgentAuthorityReadOptions,
): Promise<ActivityReadUpdateResult> {
  try {
    const payload = await requestJson(
      config,
      fetchImpl,
      projectPath(scope, '/activity/read-state'),
      {
        method: 'PUT',
        body: request,
        signal: options?.signal,
      },
    );
    const state = parseActivityReadState(payload, scope);
    retryStore.clear(scope);
    return { kind: 'synced', state };
  } catch (error) {
    if (!isOfflineTransportError(error, options?.signal)) throw error;
    retryStore.save(scope, request.entries);
    return {
      kind: 'queued_offline',
      availability: 'degraded',
      reasonCode: 'cloud_activity_read_state_offline_retry_pending',
      expectedAuthorityRevision: request.expected_authority_revision,
      entries: retryStore.load(scope),
    };
  }
}

type RequestJsonOptions = Readonly<{
  method?: 'GET' | 'POST' | 'PUT';
  body?: unknown;
  signal?: AbortSignal;
}>;

async function requestJson(
  config: DesktopRuntimeConfig,
  fetchImpl: FetchPort,
  path: string,
  options: RequestJsonOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  if (options.body !== undefined)
    headers.set('Content-Type', 'application/json');

  let response: Response;
  try {
    const init: RequestInit = {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    };
    response = fetchImpl === fetch
      ? await desktopApiFetch(config, path, init)
      : await fetchImpl(absoluteUrl(config.apiBaseUrl, path), init);
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new DesktopApiError('cloud_agent_authority_network_unavailable', 0, {
      reason_code: 'cloud_agent_authority_network_unavailable',
    });
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
    throw new DesktopApiError('cloud_agent_authority_response_invalid', 0, {
      reason_code: 'cloud_agent_authority_response_invalid',
    });
  }
  return payload;
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: ActivityAuthorityScope,
): CloudAgentAuthorityScope {
  const currentScope = requireCloudAuthorityScope(scope);
  if (
    config.mode !== 'cloud' ||
    config.tenantId !== currentScope.tenantId ||
    config.projectId !== currentScope.projectId
  ) {
    throw new DesktopApiError(
      'cloud_agent_authority_runtime_scope_mismatch',
      0,
      {
        reason_code: 'cloud_agent_authority_runtime_scope_mismatch',
      },
    );
  }
  return currentScope;
}

function projectPath(scope: CloudAgentAuthorityScope, suffix: string): string {
  return `/api/v1/projects/${encodeURIComponent(scope.projectId)}${suffix}`;
}

function runPath(runId: string, suffix: string): string {
  return `/api/v1/agent/runs/${encodeURIComponent(runId)}${suffix}`;
}

function runChangesPath(runId: string, options: GetRunChangesOptions): string {
  const params = new URLSearchParams({
    scope: options.scope,
    expected_revision: String(options.expected_revision),
  });
  if (options.turn_id) params.set('turn_id', options.turn_id);
  return `${runPath(runId, '/changes')}?${params.toString()}`;
}

function requireIdentifier(value: string, reasonCode: string): string {
  if (!value || value !== value.trim()) {
    throw new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
  }
  return value;
}

function isOfflineTransportError(
  error: unknown,
  signal?: AbortSignal,
): boolean {
  return (
    !signal?.aborted &&
    error instanceof DesktopApiError &&
    error.status === 0 &&
    error.message === 'cloud_agent_authority_network_unavailable'
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
