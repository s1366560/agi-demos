import { fullDesktop } from '../desktopProfile';
import { authorizePackageEndpoint } from './cloudPluginSettingsEndpointPolicy';
import { readPackageCommandStream } from '../../../../packages/plugin-slots/src/packageCommandStream';
import {
  isCloudSandboxDownloadPath,
  requireCloudSandboxFileAuthority,
} from '../../src/api/cloudSandboxDownloadAuthority';
import { parseLocalRunRequest } from './localRunRequest';
import { allowsCloudSandboxImportBudget } from './cloudSandboxImportBudget';
import type { CloudSessionRefreshOutcome } from './cloudAuthenticationAuthority';
import { authorizeFullDesktopHostEndpoint } from './cloudProductEndpointPolicy';
import {
  assertCloudMemoryActor, assertCloudMemoryContext, requireCloudMemoryRequestScope,
  type CloudMemoryRequestScope,
} from '../../src/api/cloudMemoryScopeContract';
import {
  CLOUD_MEMORY_REVISION_HEADER,
  requireCloudMemoryMutation,
  type CloudMemoryMutation,
} from '../../src/api/cloudMemoryCommandContract';
import {
  cloudRunReviewTarget,
  requireCloudRunSummaryScope,
  requireCloudRunChangesScope,
} from './cloudRunReviewAuthority';

export type VaultBoundCloudRequestInput = Readonly<{
  path: string;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  form?: readonly VaultBoundCloudFormPart[];
  mutation?: VaultBoundCloudMutation;
  response?: VaultBoundCloudResponsePolicy;
  memory_scope?: CloudMemoryRequestScope;
}>;

type VaultBoundCloudMutation =
  | CloudMemoryMutation
  | Readonly<{
      expected_revision: number;
      idempotency_key: string;
    }>
  | Readonly<{
      kind: 'idempotency-only';
      idempotency_key: string;
    }>;

type VaultBoundCloudFormPart =
  | Readonly<{ kind: 'text'; name: string; value: string }>
  | Readonly<{
      kind: 'file';
      name: string;
      filename: string;
      mime_type: string;
      bytes_base64: string;
    }>;

type VaultBoundCloudResponsePolicy =
  | Readonly<{
      kind: 'binary';
      max_bytes: number;
    }>
  | Readonly<{
      kind: 'event-stream';
      max_bytes: number;
    }>;

export type VaultBoundCloudRequestResult = Readonly<{
  status: number;
  body: unknown;
}>;

export type VaultBoundCloudSessionProjection = Readonly<{
  status: 'authenticated';
  api_base_url: string;
  expires_at: string | null;
  user: Readonly<Record<string, unknown>>;
  workspace_context: Readonly<Record<string, unknown>>;
  tenants: readonly Readonly<Record<string, unknown>>[];
  projects: readonly Readonly<Record<string, unknown>>[];
}>;

type TrustedCloudSession = Readonly<{
  version: 1;
  api_base_url: string;
  runtime_mode: 'cloud';
  credential_kind: 'cloud_bearer';
  credential: string;
  expires_at: string | null;
}>;

export type CloudSessionRefreshState = {
  used: boolean;
  credential: string | null;
};

export type VaultBoundCloudRequestDependencies = Readonly<{
  loadTrustedSession(): Promise<unknown>;
  fetch(url: string, init: RequestInit): Promise<Response>;
  signal?: AbortSignal;
  refreshTrustedSession?(
    reason: 'proactive' | 'unauthorized',
  ): Promise<CloudSessionRefreshOutcome>;
  refreshState?: CloudSessionRefreshState;
  onPackageProgress?(value: unknown): void;
  onPackageStreamActivity?(): void;
  withContextSwitch?(
    operation: () => Promise<VaultBoundCloudRequestResult>,
  ): Promise<VaultBoundCloudRequestResult>;
}>;

export type CloudRequestExecutionLease = Readonly<{
  signal: AbortSignal;
  renewPackageStream(): void;
  release(): void;
}>;

export type CloudRequestExecutionRegistryOptions = Readonly<{
  timeoutMs: number;
  maxPackageStreamMs?: number;
}>;

type AuthorizedEndpoint = Readonly<{
  kind:
    | 'identity'
    | 'identity-catalog'
    | 'tenant-admin'
    | 'workspace-context'
    | 'workspace-context-switch'
    | 'project'
    | 'workspace';
  tenantId: string | null;
  projectId: string | null;
  workspaceId?: string | null;
  mcpServerId?: string;
  conversationId?: string;
  catalogProjectId?: string;
}>;

const REQUEST_KEYS = new Set(['path', 'method', 'body', 'form', 'mutation', 'response', 'memory_scope']);
const MUTATION_KEYS = new Set(['expected_revision', 'idempotency_key']);
const IDEMPOTENCY_MUTATION_KEYS = new Set(['kind', 'idempotency_key']);
const FORM_TEXT_KEYS = new Set(['kind', 'name', 'value']);
const FORM_FILE_KEYS = new Set(['kind', 'name', 'filename', 'mime_type', 'bytes_base64']);
const RESPONSE_KEYS = new Set(['kind', 'max_bytes']);
const WORKSPACE_CONTEXT_SWITCH_KEYS = new Set([
  'tenant_id',
  'project_id',
  'expected_revision',
  'idempotency_key',
]);
const MAX_REQUEST_BYTES = 512 * 1024;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_BINARY_RESPONSE_BYTES = 16 * 1024 * 1024;
const MAX_EVENT_STREAM_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_FORM_PARTS = 32;
const MAX_FORM_TEXT_BYTES = 64 * 1024;
const IDENTITY_CATALOG_PAGE_SIZE = 100;
const IDENTITY_CATALOG_MAX_PAGES = 100;
const CATALOG_PAGE_KEYS = new Set(['total', 'page', 'page_size']);
const METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);
const REQUEST_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const FORM_NAME = /^[A-Za-z0-9_.-]{1,128}$/u;
const MIME_TYPE = /^[A-Za-z0-9!#$&^_.+-]+\/[A-Za-z0-9!#$&^_.+-]+$/u;

type CloudRequestExecution = Readonly<{
  ownerId: number;
  controller: AbortController;
  clearTimers(): void;
}>;

export class CloudRequestExecutionRegistry {
  readonly #timeoutMs: number;
  readonly #maxPackageStreamMs: number;
  readonly #executions = new Map<string, CloudRequestExecution>();

  constructor(options: CloudRequestExecutionRegistryOptions) {
    if (!Number.isSafeInteger(options.timeoutMs) || options.timeoutMs < 1) {
      throw new Error('cloud request timeout is invalid');
    }
    const streamLimit = options.maxPackageStreamMs ?? options.timeoutMs;
    if (!Number.isSafeInteger(streamLimit) || streamLimit < options.timeoutMs) {
      throw new Error('cloud package stream limit is invalid');
    }
    this.#maxPackageStreamMs = streamLimit;
    this.#timeoutMs = options.timeoutMs;
  }

  begin(ownerId: number, requestId: unknown): CloudRequestExecutionLease {
    const id = validRequestId(requestId);
    if (!Number.isSafeInteger(ownerId) || ownerId < 0) {
      throw new Error('cloud request owner is invalid');
    }
    if (this.#executions.has(id)) throw new Error('cloud request id is already active');

    const controller = new AbortController();
    const started = performance.now();
    let hardTimer: ReturnType<typeof setTimeout> | undefined;
    const expire = () => {
      const execution = this.#executions.get(id);
      if (!execution || execution.controller !== controller) return;
      this.#executions.delete(id);
      execution.clearTimers();
      controller.abort(new Error('cloud request timed out'));
    };
    let idleTimer = setTimeout(expire, this.#timeoutMs);
    const clearTimers = () => {
      clearTimeout(idleTimer);
      clearTimeout(hardTimer);
    };
    const execution = Object.freeze({ ownerId, controller, clearTimers });
    this.#executions.set(id, execution);

    let released = false;
    return Object.freeze({
      signal: controller.signal,
      renewPackageStream: () => {
        if (this.#executions.get(id) !== execution) return;
        if (!hardTimer) {
          const remaining = this.#maxPackageStreamMs - (performance.now() - started);
          if (remaining <= 0) {
            expire();
            return;
          }
          hardTimer = setTimeout(expire, remaining);
        }
        clearTimeout(idleTimer);
        idleTimer = setTimeout(expire, this.#timeoutMs);
      },
      release: () => {
        if (released) return;
        released = true;
        const current = this.#executions.get(id);
        if (!current || current.controller !== controller) return;
        this.#executions.delete(id);
        current.clearTimers();
      },
    });
  }

  cancel(ownerId: number, requestId: unknown): boolean {
    const id = validRequestId(requestId);
    const execution = this.#executions.get(id);
    if (!execution || execution.ownerId !== ownerId) return false;
    this.#executions.delete(id);
    execution.clearTimers();
    execution.controller.abort(new Error('cloud request was cancelled'));
    return true;
  }

  cancelOwner(ownerId: number): number {
    let cancelled = 0;
    for (const [requestId, execution] of this.#executions) {
      if (execution.ownerId !== ownerId) continue;
      this.#executions.delete(requestId);
      execution.clearTimers();
      execution.controller.abort(new Error('cloud request owner was destroyed'));
      cancelled += 1;
    }
    return cancelled;
  }

  cancelAll(): number {
    let cancelled = 0;
    for (const [requestId, execution] of this.#executions) {
      this.#executions.delete(requestId);
      execution.clearTimers();
      execution.controller.abort(new Error('cloud request broker is shutting down'));
      cancelled += 1;
    }
    return cancelled;
  }
}

/** Main-only material; IPC callers must return opaque grants, never this value. */
export async function authorizeVaultBoundSandboxDesktopGrant(
  input: Readonly<{ tenantId: string; projectId: string }>,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<Readonly<{ apiBaseUrl: string; credential: string; expiresAt: string | null }>> {
  dependencies.signal?.throwIfAborted();
  const tenantId = identifier(input.tenantId, 'sandbox grant tenant scope is invalid');
  const projectId = identifier(input.projectId, 'sandbox grant project scope is invalid');
  const session = await adoptCloudSession(await dependencies.loadTrustedSession(), dependencies);
  dependencies.signal?.throwIfAborted();
  const response = await authorizedFetch(session, dependencies, {
    path: '/api/v1/workspace-context', method: 'GET',
  });
  dependencies.signal?.throwIfAborted();
  const body = await boundedJson(response, false, session.credential);
  dependencies.signal?.throwIfAborted();
  if (!response.ok) throw new Error('sandbox grant scope observation failed');
  const observed = parseObservedContext(body);
  if (observed.tenantId !== tenantId || observed.projectId !== projectId) {
    throw new Error('sandbox grant scope mismatch');
  }
  return Object.freeze({
    apiBaseUrl: session.api_base_url,
    credential: session.credential,
    expiresAt: session.expires_at,
  });
}

/** Main-only admission material for the private Sidecar control pipe. */
export async function authorizeDesktopLocalRun(
  command: 'local_run_execute' | 'local_run_stop',
  input: unknown,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<Record<string, unknown>> {
  const { args, conversationId, runId } = parseLocalRunRequest(command, input);
  const session = await adoptCloudSession(await dependencies.loadTrustedSession(), dependencies);
  const currentBearer = () => dependencies.refreshState?.credential ?? session.credential;
  const observe = async (path: string) => {
    const response = await authorizedFetch(session, dependencies, { path, method: 'GET' });
    const body = await boundedJson(response, false, currentBearer());
    dependencies.signal?.throwIfAborted();
    if (!response.ok) throw new Error('local run scope observation failed');
    return body;
  };
  // A 401 can rotate the token once. All accepted observations must use the same credential.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const context = parseObservedContext(await observe('/api/v1/workspace-context'));
    const bearer = currentBearer();
    const identity = await observe('/api/v1/auth/me');
    if (bearer !== currentBearer()) continue;
    if (!context.projectId || context.tenantId !== args.tenant_id ||
        !isRecord(identity) || identity.user_id !== args.user_id) {
      throw new Error('local run identity or tenant mismatch');
    }
    await observeEndpointWorkspaceScope({
      kind: 'project', tenantId: context.tenantId, projectId: context.projectId, conversationId,
    }, context, session, dependencies);
    if (runId !== null) {
      const summary = await observe(`/api/v1/agent/runs/${encodeURIComponent(runId)}/summary`);
      if (requireCloudRunSummaryScope(summary, runId, context).conversationId !== conversationId) {
        throw new Error('local run conversation mismatch');
      }
    }
    if (bearer !== currentBearer()) continue;
    const latest = parseTrustedCloudSession(await dependencies.loadTrustedSession());
    if (latest.api_base_url !== session.api_base_url || latest.credential !== bearer) {
      throw new Error('local run session changed');
    }
    dependencies.signal?.throwIfAborted();
    return { ...args, api_base_url: latest.api_base_url, authorization: `Bearer ${bearer}` };
  }
  throw new Error('local run session changed');
}

export function isIntentionalCloudCancel(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  if (error.message === 'cloud request was cancelled') return true;
  return error.name === 'AbortError' && /cancel/iu.test(error.message);
}

export function isCancelledCloudRequest(
  value: unknown,
): value is { cancelled: true; kind: 'cancelled' } {
  return Boolean(
    value &&
      typeof value === 'object' &&
      'cancelled' in value &&
      value.cancelled === true &&
      'kind' in value &&
      value.kind === 'cancelled',
  );
}

export async function settleCloudRequest<T>(operation: () => Promise<T>): Promise<
  T | { cancelled: true; kind: 'cancelled' }
> {
  try {
    return await operation();
  } catch (error) {
    if (isIntentionalCloudCancel(error)) {
      return { cancelled: true, kind: 'cancelled' };
    }
    throw error;
  }
}

export async function executeVaultBoundCloudRequest(
  input: unknown,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<VaultBoundCloudRequestResult> {
  dependencies.signal?.throwIfAborted();
  const request = parseRequest(input);
  const endpoint = authorizeEndpoint(request);
  const session = await adoptCloudSession(await dependencies.loadTrustedSession(), dependencies);
  dependencies.signal?.throwIfAborted();
  const projectCatalog = async () => {
    const response = await authorizedFetch(session, dependencies, {
      path: '/api/v1/project-packages/projects/', method: 'GET',
    });
    return {status: response.status, body: await boundedJson(response, false, session.credential)};
  };
  if (request.method === 'GET' && request.path === '/api/v1/project-packages/projects/') {
    return projectCatalog();
  }
  const tenantCatalog = async () => {
    const response = await authorizedFetch(session, dependencies, {
      path: '/api/v1/tenant-packages/tenants', method: 'GET',
    });
    return {status: response.status, body: await boundedJson(response, false, session.credential)};
  };
  if (request.method === 'GET' && request.path === '/api/v1/tenant-packages/tenants') {
    return tenantCatalog();
  }
  const contextResponse = await authorizedFetch(
    session,
    dependencies,
    Object.freeze({ path: '/api/v1/workspace-context', method: 'GET' }),
  );
  const contextBody = await boundedJson(contextResponse, false, session.credential);
  if (endpoint.kind === 'workspace-context-switch') {
    const noSelection = contextResponse.status === 404 && isRecord(contextBody) &&
      isRecord(contextBody.detail) && contextBody.detail.code === 'workspace_context_unavailable';
    if (!contextResponse.ok && !noSelection) return {status: contextResponse.status, body: contextBody};
    if (noSelection || parseObservedContext(contextBody).tenantId !== endpoint.tenantId) {
      // Only an explicit selection may cross the current tenant or initialize empty context.
      const projects = await projectCatalog();
      if (projects.status !== 200 || !Array.isArray(projects.body) || !projects.body.some(
        item => isRecord(item) && item.tenant_id === endpoint.tenantId && item.project_id === request.body?.project_id,
      )) throw new Error('cloud request tenant scope mismatch');
    }
    const switchContext = async (): Promise<VaultBoundCloudRequestResult> => {
      dependencies.signal?.throwIfAborted();
      const response = await authorizedFetch(session, dependencies, request);
      const body = await boundedJson(response, true, session.credential);
      dependencies.signal?.throwIfAborted();
      return Object.freeze({ status: response.status, body });
    };
    return dependencies.withContextSwitch
      ? dependencies.withContextSwitch(switchContext)
      : switchContext();
  }
  let selected: ReturnType<typeof parseObservedContext>;
  if (contextResponse.ok) selected = parseObservedContext(contextBody);
  else if (contextResponse.status === 404 && isRecord(contextBody) && isRecord(contextBody.detail)
      && contextBody.detail.code === 'workspace_context_unavailable'
      && request.path.startsWith('/api/v1/tenant-packages/') && endpoint.tenantId) {
    const catalog = await tenantCatalog();
    if (catalog.status !== 200 || !isRecord(catalog.body) || !Array.isArray(catalog.body.items)
        || !catalog.body.items.some(item => isRecord(item) && item.tenant_id === endpoint.tenantId)) {
      throw new Error('cloud request tenant scope mismatch');
    }
    selected = {tenantId:endpoint.tenantId, projectId:null, workspaceId:null};
  } else {
    return Object.freeze({ status: contextResponse.status, body: contextBody });
  }
  assertSingleProjectScope(request, endpoint);
  const adopted = await adoptVisibleProject(endpoint, selected, session, dependencies);
  const context = fullDesktop
    ? await observeEndpointWorkspaceScope(endpoint, adopted, session, dependencies) : adopted;
  assertEndpointScope(endpoint, context);
  if (fullDesktop && request.memory_scope !== undefined) {
    assertCloudMemoryContext(request.memory_scope, contextBody);
    const identityResponse = await authorizedFetch(session, dependencies, {
      path: '/api/v1/auth/me', method: 'GET',
    });
    const identityBody = await boundedJson(identityResponse, false, session.credential);
    dependencies.signal?.throwIfAborted();
    if (!identityResponse.ok) return Object.freeze({ status: identityResponse.status, body: identityBody });
    assertCloudMemoryActor(request.memory_scope, identityBody);
  }
  if (endpoint.kind === 'workspace-context') {
    return Object.freeze({ status: contextResponse.status, body: contextBody });
  }
  const runReview = fullDesktop ? cloudRunReviewTarget(request.path) : null;
  let summaryIdentity: Readonly<{ conversationId: string }> | null = null;
  if (fullDesktop && runReview?.action === 'changes') {
    const summaryResponse = await authorizedFetch(session, dependencies, {
      path: `/api/v1/agent/runs/${encodeURIComponent(runReview.runId)}/summary`, method: 'GET',
    });
    const summaryBody = await boundedJson(summaryResponse, true, session.credential);
    dependencies.signal?.throwIfAborted();
    if (!summaryResponse.ok) {
      return Object.freeze({ status: summaryResponse.status, body: summaryBody });
    }
    summaryIdentity = requireCloudRunSummaryScope(summaryBody, runReview.runId, context);
  }
  const response = await authorizedFetch(
    session, fullDesktop ? activityDeliveryDependencies(request, dependencies) : dependencies, request,
  );
  if (response.ok && request.method === 'POST' &&
      /^\/api\/v1\/(?:platform-plugins\/v2\/optional-business|tenant-packages)\/[a-z0-9][a-z0-9._-]{0,127}\/commands\?stream=true$/u.test(request.path)) {
    const check = (value: unknown) => {
      dependencies.signal?.throwIfAborted();
      const text = JSON.stringify(value);
      if ([session.credential, dependencies.refreshState?.credential].some(key => key && text?.includes(key)))
        throw new Error('cloud response contains protected credential');
    };
    const body = await readPackageCommandStream(response, value => {
      check(value);
      dependencies.onPackageProgress?.(value);
    }, dependencies.onPackageStreamActivity).catch((error: unknown) => {
      check(error instanceof Error ? error.message : String(error));
      throw error;
    });
    check(body);
    return {status: response.status, body};
  }
  if (fullDesktop && request.response?.kind === 'binary' && response.ok) {
    return Object.freeze({
      status: response.status,
      body: await boundedBinary(
        response,
        request.response.max_bytes,
        session.credential,
        request.path,
      ),
    });
  }
  if (fullDesktop && request.response?.kind === 'event-stream' && response.ok) {
    return Object.freeze({
      status: response.status,
      body: await boundedEventStream(
        response,
        request.response.max_bytes,
        session.credential,
      ),
    });
  }
  const resolvingArchive = request.method === 'POST' &&
    request.path === '/api/v1/platform-plugins/v2/optional-business/npm/resolve';
  const resourceUrl = new URL(request.path, 'https://cloud.invalid');
  const loadingSignedPage = response.ok && request.method === 'GET' &&
    /^\/api\/v1\/(?:platform-plugins\/v2\/optional-business|tenant-packages)\/[a-z0-9][a-z0-9._-]{0,127}\/ui$/u.test(resourceUrl.pathname) &&
    resourceUrl.searchParams.has('page_id') && resourceUrl.searchParams.has('expected_digest');
  const body = await boundedJson(response, true, session.credential,
    resolvingArchive || loadingSignedPage ? 16 * 1024 * 1024 + 65536 : MAX_RESPONSE_BYTES);
  dependencies.signal?.throwIfAborted();
  if (fullDesktop && response.ok && runReview?.action === 'summary') {
    requireCloudRunSummaryScope(body, runReview.runId, context);
  } else if (fullDesktop && response.ok && runReview?.action === 'changes' && summaryIdentity) {
    requireCloudRunChangesScope(body, runReview, summaryIdentity);
  }
  return Object.freeze({ status: response.status, body });
}

function activityDeliveryDependencies(
  request: VaultBoundCloudRequestInput,
  dependencies: VaultBoundCloudRequestDependencies,
): VaultBoundCloudRequestDependencies {
  const segments = new URL(request.path, 'https://desktop.invalid').pathname.split('/');
  if (request.method !== 'PUT' || segments.length !== 7 ||
    segments[1] !== 'api' || segments[2] !== 'v1' || segments[3] !== 'projects' ||
    segments[5] !== 'activity' || segments[6] !== 'read-state') return dependencies;
  return {
    ...dependencies,
    async fetch(url, init) {
      try {
        return await dependencies.fetch(url, init);
      } catch {
        dependencies.signal?.throwIfAborted();
        return new Response(JSON.stringify({
          reason_code: 'activity_read_state_transport_unavailable',
        }), { status: 503, headers: { 'content-type': 'application/json' } });
      }
    },
  };
}

export class CloudSessionAuthenticationInvalidError extends Error {
  constructor() {
    super('cloud session authentication is invalid');
    this.name = 'CloudSessionAuthenticationInvalidError';
  }
}

export async function projectVaultBoundCloudSession(
  dependencies: VaultBoundCloudRequestDependencies,
  retireLocalHistory?: () => Promise<void>,
): Promise<VaultBoundCloudSessionProjection | null> {
  dependencies.signal?.throwIfAborted();
  const storedSession = await dependencies.loadTrustedSession();
  if (storedSession === null || storedSession === undefined) return null;
  const session = await adoptCloudSession(storedSession, dependencies);
  dependencies.signal?.throwIfAborted();

  const contextResponse = await authorizedFetch(
    session,
    dependencies,
    Object.freeze({ path: '/api/v1/workspace-context', method: 'GET' }),
  );
  if (contextResponse.status === 401) throw new CloudSessionAuthenticationInvalidError();
  const contextBody = await boundedJson(contextResponse, false, session.credential);
  if (contextResponse.status === 404 && isRecord(contextBody) && isRecord(contextBody.detail) &&
      contextBody.detail.code === 'workspace_context_unavailable') throw new Error('cloud_project_selection_required');
  if (!contextResponse.ok || !isRecord(contextBody)) {
    throw new Error('cloud session scope observation failed');
  }
  const context = parseObservedContext(contextBody);

  const identityResponse = await authorizedFetch(
    session,
    dependencies,
    Object.freeze({ path: '/api/v1/auth/me', method: 'GET' }),
  );
  if (identityResponse.status === 401) throw new CloudSessionAuthenticationInvalidError();
  const identityBody = await boundedJson(identityResponse, false, session.credential);
  if (!identityResponse.ok || !isRecord(identityBody)) {
    throw new Error('cloud session identity observation failed');
  }

  const tenants = await loadProjectedIdentityCatalog(
    session,
    dependencies,
    'tenants',
    (page) => `/api/v1/tenants/?page=${page}&page_size=${IDENTITY_CATALOG_PAGE_SIZE}`,
    projectTenant,
  );
  if (!tenants.some((tenant) => tenant.id === context.tenantId)) {
    throw new Error('cloud session tenant catalog scope mismatch');
  }
  const projects = await loadProjectedIdentityCatalog(
    session,
    dependencies,
    'projects',
    (page) =>
      `/api/v1/projects/?page=${page}&page_size=${IDENTITY_CATALOG_PAGE_SIZE}&tenant_id=${encodeURIComponent(context.tenantId)}`,
    (value) => projectProject(value, context.tenantId),
  );
  if (context.projectId !== null && !projects.some((project) => project.id === context.projectId)) {
    throw new Error('cloud session project catalog scope mismatch');
  }

  if (retireLocalHistory && context.projectId !== null) {
    try {
      const query = new URLSearchParams({ project_id: context.projectId, limit: '1', offset: '0' });
      const response = await authorizedFetch(session, dependencies, {
        path: `/api/v1/agent/conversations?${query}`, method: 'GET',
      });
      if (response.ok) {
        const page = await boundedJson(response, false, session.credential);
        if (isRecord(page) && Array.isArray(page.items) && typeof page.total === 'number') {
          dependencies.signal?.throwIfAborted();
          const latest = parseTrustedCloudSession(await dependencies.loadTrustedSession());
          if (latest.api_base_url === session.api_base_url &&
              latest.credential === (dependencies.refreshState?.credential ?? session.credential)) {
            await retireLocalHistory();
          }
        }
      }
    } catch {
      // Login remains usable if history or local cleanup is temporarily unavailable.
      dependencies.signal?.throwIfAborted();
    }
  }
  return Object.freeze({
    status: 'authenticated',
    api_base_url: session.api_base_url,
    expires_at: session.expires_at,
    user: Object.freeze({ ...identityBody }),
    workspace_context: Object.freeze({ ...contextBody }),
    tenants,
    projects,
  });
}

async function loadProjectedIdentityCatalog(
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
  itemKey: 'tenants' | 'projects',
  pathForPage: (page: number) => string,
  projectItem: (value: unknown) => Readonly<Record<string, unknown>>,
): Promise<readonly Readonly<Record<string, unknown>>[]> {
  const responseKeys = new Set([
    ...CATALOG_PAGE_KEYS,
    itemKey,
    ...(itemKey === 'projects' ? ['owner_ids'] : []),
  ]);
  const items: Readonly<Record<string, unknown>>[] = [];
  const seenIds = new Set<string>();
  let expectedTotal: number | null = null;
  for (let page = 1; page <= IDENTITY_CATALOG_MAX_PAGES; page += 1) {
    dependencies.signal?.throwIfAborted();
    const response = await authorizedFetch(
      session,
      dependencies,
      Object.freeze({ path: pathForPage(page), method: 'GET' }),
    );
    if (response.status === 401) throw new CloudSessionAuthenticationInvalidError();
    const body = await boundedJson(response, false, session.credential);
    if (!response.ok) throw new Error('cloud session identity catalog request failed');
    const record = exactRecord(body, responseKeys, 'cloud session identity catalog is invalid');
    if (
      !Array.isArray(record[itemKey]) ||
      !Number.isSafeInteger(record.total) ||
      (record.total as number) < 0 ||
      record.page !== page ||
      record.page_size !== IDENTITY_CATALOG_PAGE_SIZE ||
      record[itemKey].length > IDENTITY_CATALOG_PAGE_SIZE
    ) {
      throw new Error('cloud session identity catalog is invalid');
    }
    if (itemKey === 'projects') validateProjectCatalogOwnerIds(record.owner_ids);
    if (expectedTotal === null) expectedTotal = record.total as number;
    if (record.total !== expectedTotal) {
      throw new Error('cloud session identity catalog revision drift');
    }
    for (const value of record[itemKey]) {
      const item = projectItem(value);
      const id = item.id as string;
      if (seenIds.has(id)) throw new Error('cloud session identity catalog is invalid');
      seenIds.add(id);
      items.push(item);
    }
    if (items.length === expectedTotal) {
      if (new TextEncoder().encode(JSON.stringify(items)).byteLength > MAX_RESPONSE_BYTES) {
        throw new Error('cloud session identity catalog is too large');
      }
      return Object.freeze(items);
    }
    if (
      items.length > expectedTotal ||
      record[itemKey].length === 0 ||
      record[itemKey].length < IDENTITY_CATALOG_PAGE_SIZE
    ) {
      throw new Error('cloud session identity catalog is invalid');
    }
  }
  throw new Error('cloud session identity catalog page limit exceeded');
}

function validateProjectCatalogOwnerIds(value: unknown): void {
  if (!Array.isArray(value)) throw new Error('cloud session project owner catalog is invalid');
  const seenOwnerIds = new Set<string>();
  for (const candidate of value) {
    const ownerId = identifier(candidate, 'cloud session project owner catalog is invalid');
    if (seenOwnerIds.has(ownerId)) {
      throw new Error('cloud session project owner catalog is invalid');
    }
    seenOwnerIds.add(ownerId);
  }
}

function projectTenant(value: unknown): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw new Error('cloud session tenant catalog is invalid');
  const id = identifier(value.id, 'cloud session tenant scope is invalid');
  const name = displayString(value.name, 'cloud session tenant name is invalid');
  const slug = optionalDisplayString(value.slug, 'cloud session tenant slug is invalid');
  const description = optionalNullableDisplayString(
    value.description,
    'cloud session tenant description is invalid',
  );
  return Object.freeze({
    id,
    name,
    ...(slug === undefined ? {} : { slug }),
    ...(description === undefined ? {} : { description }),
  });
}

function projectProject(value: unknown, tenantId: string): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw new Error('cloud session project catalog is invalid');
  const id = identifier(value.id, 'cloud session project scope is invalid');
  const observedTenantId = identifier(
    value.tenant_id,
    'cloud session project tenant scope is invalid',
  );
  if (observedTenantId !== tenantId) throw new Error('cloud session project scope mismatch');
  const name = displayString(value.name, 'cloud session project name is invalid');
  const description = optionalNullableDisplayString(
    value.description,
    'cloud session project description is invalid',
  );
  if (value.is_public !== undefined && typeof value.is_public !== 'boolean') {
    throw new Error('cloud session project visibility is invalid');
  }
  const stats = projectKnowledgeStats(value.stats);
  return Object.freeze({
    id,
    tenant_id: observedTenantId,
    name,
    ...(description === undefined ? {} : { description }),
    ...(value.is_public === undefined ? {} : { is_public: value.is_public }),
    ...(stats === undefined ? {} : { stats }),
  });
}

function projectKnowledgeStats(value: unknown): Readonly<Record<string, number>> | undefined {
  if (value === undefined || value === null) return undefined;
  if (!isRecord(value)) throw new Error('cloud session project stats are invalid');
  const stats: Record<string, number> = {};
  for (const key of ['memory_count', 'node_count', 'storage_used']) {
    if (!Object.hasOwn(value, key)) continue;
    const metric = value[key];
    if (typeof metric !== 'number' || !Number.isFinite(metric) || metric < 0) {
      throw new Error('cloud session project stats are invalid');
    }
    stats[key] = metric;
  }
  return Object.freeze(stats);
}

function displayString(value: unknown, reason: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 1024 ||
    value !== value.trim() ||
    hasControlCharacter(value)
  ) {
    throw new Error(reason);
  }
  return value;
}

function optionalDisplayString(value: unknown, reason: string): string | undefined {
  return value === undefined ? undefined : displayString(value, reason);
}

function optionalNullableDisplayString(
  value: unknown,
  reason: string,
): string | null | undefined {
  return value === undefined || value === null ? value : displayString(value, reason);
}

function parseRequest(input: unknown): VaultBoundCloudRequestInput {
  const record = exactRecord(input, REQUEST_KEYS, 'cloud request is invalid');
  const path = record.path;
  if (
    typeof path !== 'string' ||
    !path.startsWith('/api/v1/') ||
    path.length > 2048 ||
    path.includes('#') ||
    path.includes('://') ||
    hasControlCharacter(path)
  ) {
    throw new Error('cloud request path is invalid');
  }
  const method = record.method ?? 'GET';
  if (typeof method !== 'string' || !METHODS.has(method)) {
    throw new Error('cloud request method is invalid');
  }
  const body = record.body;
  if (body !== undefined && !isRecord(body)) {
    throw new Error('cloud request body is invalid');
  }
  if (method === 'GET' && body !== undefined) {
    throw new Error('cloud request body is not allowed');
  }
  if (body !== undefined) {
    const bodyBytes = new TextEncoder().encode(JSON.stringify(body)).byteLength;
    const packageUpload = record.method === 'POST' &&
      ['/api/v1/platform-plugins/v2/optional-business/inspect', '/api/v1/platform-plugins/v2/optional-business/install', '/api/v1/tenant-packages/inspect', '/api/v1/tenant-packages/install'].includes(String(record.path)) &&
      bodyBytes <= 16 * 1024 * 1024 + 8192;
    if (bodyBytes > MAX_REQUEST_BYTES && !packageUpload && !(fullDesktop && allowsCloudSandboxImportBudget(record, body, bodyBytes))) {
      throw new Error('cloud request body is too large');
    }
  }
  if (!fullDesktop && [record.form, record.response, record.mutation, record.memory_scope].some(value => value !== undefined)) {
    throw new Error('cloud request is invalid');
  }
  const form = fullDesktop ? parseForm(record.form, method) : null;
  if (body !== undefined && form !== null) {
    throw new Error('cloud request body is invalid');
  }
  const mutation = fullDesktop ? parseMutation(record.mutation, method) : null;
  const response = fullDesktop ? parseResponsePolicy(record.response) : null;
  return Object.freeze({
    path,
    method: method as VaultBoundCloudRequestInput['method'],
    ...(body === undefined ? {} : { body: Object.freeze({ ...body }) }),
    ...(form === null ? {} : { form }),
    ...(mutation === null ? {} : { mutation }),
    ...(response === null ? {} : { response }),
    ...(!fullDesktop || record.memory_scope === undefined ? {} : {
      memory_scope: requireCloudMemoryRequestScope(record.memory_scope),
    }),
  });
}

function parseForm(
  input: unknown,
  method: string,
): readonly VaultBoundCloudFormPart[] | null {
  if (input === undefined) return null;
  if (
    method === 'GET' ||
    !Array.isArray(input) ||
    input.length === 0 ||
    input.length > MAX_FORM_PARTS
  ) {
    throw new Error('cloud request form is invalid');
  }
  const parts: VaultBoundCloudFormPart[] = [];
  let totalBytes = 0;
  for (const inputPart of input) {
    if (!isRecord(inputPart) || !FORM_NAME.test(String(inputPart.name ?? ''))) {
      throw new Error('cloud request form is invalid');
    }
    const name = String(inputPart.name);
    totalBytes += utf8Length(name);
    if (inputPart.kind === 'text') {
      const part = exactRecord(inputPart, FORM_TEXT_KEYS, 'cloud request form is invalid');
      if (typeof part.value !== 'string' || utf8Length(part.value) > MAX_FORM_TEXT_BYTES) {
        throw new Error('cloud request form is invalid');
      }
      totalBytes += utf8Length(part.value);
      parts.push(Object.freeze({ kind: 'text', name, value: part.value }));
    } else if (inputPart.kind === 'file') {
      const part = exactRecord(inputPart, FORM_FILE_KEYS, 'cloud request form is invalid');
      const filename = validFilename(part.filename, 'cloud request filename is invalid');
      const mimeType = validMimeType(part.mime_type, 'cloud request MIME type is invalid');
      const bytes = decodeCanonicalBase64(
        part.bytes_base64,
        'cloud request file body is invalid',
      );
      totalBytes += utf8Length(filename) + utf8Length(mimeType) + bytes.byteLength;
      parts.push(
        Object.freeze({
          kind: 'file',
          name,
          filename,
          mime_type: mimeType,
          bytes_base64: String(part.bytes_base64),
        }),
      );
    } else {
      throw new Error('cloud request form is invalid');
    }
    if (totalBytes > MAX_REQUEST_BYTES) throw new Error('cloud request body is too large');
  }
  return Object.freeze(parts);
}

function parseResponsePolicy(input: unknown): VaultBoundCloudResponsePolicy | null {
  if (input === undefined) return null;
  const response = exactRecord(input, RESPONSE_KEYS, 'cloud request response is invalid');
  const maxAllowed = response.kind === 'binary'
    ? MAX_BINARY_RESPONSE_BYTES
    : response.kind === 'event-stream'
      ? MAX_EVENT_STREAM_RESPONSE_BYTES
      : null;
  if (
    maxAllowed === null ||
    !Number.isSafeInteger(response.max_bytes) ||
    Number(response.max_bytes) < 1 ||
    Number(response.max_bytes) > maxAllowed
  ) {
    throw new Error('cloud request response is invalid');
  }
  return Object.freeze({
    kind: response.kind as VaultBoundCloudResponsePolicy['kind'],
    max_bytes: Number(response.max_bytes),
  });
}

function parseMutation(
  input: unknown,
  method: string,
): VaultBoundCloudRequestInput['mutation'] | null {
  if (input === undefined) return null;
  if (isRecord(input) && input.kind === 'memory-command') {
    if (!['POST', 'PATCH', 'DELETE'].includes(method)) {
      throw new Error('cloud request mutation is invalid');
    }
    return requireCloudMemoryMutation(input);
  }
  if (isRecord(input) && input.kind === 'idempotency-only') {
    const mutation = exactRecord(
      input,
      IDEMPOTENCY_MUTATION_KEYS,
      'cloud request mutation is invalid',
    );
    if (method === 'GET') throw new Error('cloud request mutation is invalid');
    return Object.freeze({
      kind: 'idempotency-only',
      idempotency_key: identifier(
        mutation.idempotency_key,
        'cloud request mutation is invalid',
      ),
    });
  }
  const mutation = exactRecord(input, MUTATION_KEYS, 'cloud request mutation is invalid');
  if (
    method === 'GET' ||
    !Number.isSafeInteger(mutation.expected_revision) ||
    Number(mutation.expected_revision) < 0
  ) {
    throw new Error('cloud request mutation is invalid');
  }
  return Object.freeze({
    expected_revision: Number(mutation.expected_revision),
    idempotency_key: identifier(
      mutation.idempotency_key,
      'cloud request mutation is invalid',
    ),
  });
}

function authorizeEndpoint(request: VaultBoundCloudRequestInput): AuthorizedEndpoint {
  const target = new URL(request.path, 'https://desktop.invalid');
  if (
    target.origin !== 'https://desktop.invalid' ||
    target.username ||
    target.password ||
    target.hash
  ) {
    throw new Error('cloud request endpoint is not allowed');
  }
  // Memory commands belong to the signed knowledge package. fullDesktop is host
  // chrome, not a bypass back onto the old memory HTTP surface.
  if (
    fullDesktop &&
    (request.memory_scope !== undefined ||
      (request.mutation && 'kind' in request.mutation && request.mutation.kind === 'memory-command'))
  ) {
    throw new Error('cloud request memory endpoint is not allowed');
  }
  if (
    target.pathname === '/api/v1/workspace-context' &&
    request.method === 'GET' &&
    request.form === undefined &&
    request.response === undefined &&
    [...target.searchParams].length === 0
  ) {
    return Object.freeze({
      kind: 'workspace-context',
      tenantId: null,
      projectId: null,
    });
  }
  if (
    target.pathname === '/api/v1/workspace-context/switch' &&
    request.method === 'POST' &&
    request.mutation === undefined &&
    [...target.searchParams].length === 0
  ) {
    const body = exactRecord(
      request.body,
      WORKSPACE_CONTEXT_SWITCH_KEYS,
      'cloud request workspace context switch is invalid',
    );
    const tenantId = identifier(
      body.tenant_id,
      'cloud request workspace context switch is invalid',
    );
    identifier(body.project_id, 'cloud request workspace context switch is invalid');
    identifier(body.idempotency_key, 'cloud request workspace context switch is invalid');
    if (
      Object.keys(body).length !== WORKSPACE_CONTEXT_SWITCH_KEYS.size ||
      !Number.isSafeInteger(body.expected_revision) ||
      Number(body.expected_revision) < 0
    ) {
      throw new Error('cloud request workspace context switch is invalid');
    }
    return Object.freeze({
      kind: 'workspace-context-switch',
      tenantId,
      projectId: null,
    });
  }
  if (
    target.pathname === '/api/v1/auth/me' &&
    request.method === 'GET' &&
    request.form === undefined &&
    request.response === undefined &&
    [...target.searchParams].length === 0
  ) {
    return Object.freeze({
      kind: 'identity',
      tenantId: null,
      projectId: null,
    });
  }
  // Business calls are the signed contribution surface (package commands and
  // pages). fullDesktop does not open the old business HTTP allowlist.
  if (request.form === undefined && request.response === undefined) {
    const release = authorizePackageEndpoint(request, target);
    if (release) return release;
  }
  if (!fullDesktop) {
    // P5 permits the current project's history list for native retirement and replay.
    const query = target.searchParams;
    if (request.method === 'GET' && target.pathname === '/api/v1/agent/conversations' &&
        query.size === 4 && ['project_id', 'status', 'limit', 'offset'].every(key => query.has(key))) {
      return { kind: 'project', tenantId: null, projectId: identifier(query.get('project_id'), 'cloud request project scope is invalid') };
    }
    throw new Error('cloud request endpoint is not allowed');
  }
  const hostEndpoint = authorizeFullDesktopHostEndpoint(request, target);
  if (hostEndpoint) return hostEndpoint;
  throw new Error('cloud request endpoint is not allowed');
}

const ACCESS_REFRESH_WINDOW_MS = 60_000;

function ensureRefreshState(
  dependencies: VaultBoundCloudRequestDependencies,
): CloudSessionRefreshState {
  if (dependencies.refreshState) return dependencies.refreshState;
  const created: CloudSessionRefreshState = { used: false, credential: null };
  Object.defineProperty(dependencies, 'refreshState', { value: created });
  return created;
}

function rawRefreshToken(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null;
  const token = (value as { refresh_token?: unknown }).refresh_token;
  return typeof token === 'string' && token.trim() ? token : null;
}

function rawAccessExpiry(value: unknown): number | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as { access_expires_at?: unknown; expires_at?: unknown };
  const raw = typeof record.access_expires_at === 'string' ? record.access_expires_at : record.expires_at;
  if (typeof raw !== 'string') return null;
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

async function adoptCloudSession(
  stored: unknown,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<TrustedCloudSession> {
  ensureRefreshState(dependencies);
  let raw = stored;
  const expiry = rawAccessExpiry(raw);
  const refresh = rawRefreshToken(raw);
  const now = Date.now();
  if (
    refresh &&
    expiry !== null &&
    expiry - now <= ACCESS_REFRESH_WINDOW_MS &&
    dependencies.refreshTrustedSession
  ) {
    const outcome = await dependencies.refreshTrustedSession('proactive');
    if (outcome.status === 'invalid') throw new CloudSessionAuthenticationInvalidError();
    if (outcome.status !== 'refreshed' && outcome.status !== 'current') {
      throw new Error('cloud session refresh unavailable');
    }
    raw = outcome.record;
  } else if (expiry !== null && expiry <= now && !refresh) {
    throw new CloudSessionAuthenticationInvalidError();
  }
  return parseTrustedCloudSession(raw);
}

function parseTrustedCloudSession(input: unknown): TrustedCloudSession {
  if (
    !isRecord(input) ||
    input.version !== 1 ||
    input.runtime_mode !== 'cloud' ||
    input.credential_kind !== 'cloud_bearer' ||
    typeof input.api_base_url !== 'string' ||
    typeof input.credential !== 'string' ||
    !input.credential ||
    input.credential !== input.credential.trim() ||
    (input.expires_at !== null && typeof input.expires_at !== 'string')
  ) {
    throw new Error('trusted cloud session is unavailable');
  }
  const baseUrl = new URL(input.api_base_url);
  if (
    !secureOrigin(baseUrl) ||
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.pathname !== '/' ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    throw new Error('trusted cloud session origin is invalid');
  }
  if (input.expires_at !== null) {
    const expiresAt = Date.parse(input.expires_at);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      throw new Error('trusted cloud session is expired');
    }
  }
  return Object.freeze({
    version: 1,
    api_base_url: baseUrl.origin,
    runtime_mode: 'cloud',
    credential_kind: 'cloud_bearer',
    credential: input.credential,
    expires_at: input.expires_at,
  });
}

async function authorizedFetch(
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
  request: VaultBoundCloudRequestInput,
): Promise<Response> {
  const response = await sendAuthorizedFetch(session, dependencies, request);
  const refreshState = dependencies.refreshState;
  if (
    response.status !== 401 ||
    !dependencies.refreshTrustedSession ||
    !refreshState ||
    refreshState.used
  ) {
    return response;
  }
  refreshState.used = true;
  const outcome = await dependencies.refreshTrustedSession('unauthorized');
  if (outcome.status === 'invalid') throw new CloudSessionAuthenticationInvalidError();
  if (outcome.status !== 'refreshed' && outcome.status !== 'current') {
    throw new Error('cloud session refresh unavailable');
  }
  const refreshed = parseTrustedCloudSession(outcome.record);
  if (refreshed.api_base_url !== session.api_base_url) throw new Error('cloud session origin changed');
  refreshState.credential = refreshed.credential;
  return sendAuthorizedFetch(session, dependencies, request);
}

async function sendAuthorizedFetch(
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
  request: VaultBoundCloudRequestInput,
): Promise<Response> {
  const credential = dependencies.refreshState?.credential ?? session.credential;
  const target = new URL(request.path, `${session.api_base_url}/`);
  if (target.origin !== session.api_base_url) throw new Error('cloud request origin mismatch');
  const headers = new Headers({
    Accept: request.response?.kind === 'binary'
      ? 'application/octet-stream'
      : request.response?.kind === 'event-stream'
        ? 'text/event-stream'
        : 'application/json',
    Authorization: `Bearer ${credential}`,
  });
  if (request.body !== undefined) headers.set('Content-Type', 'application/json');
  if (fullDesktop && request.mutation) {
    if ('expected_revision' in request.mutation) {
      headers.set('kind' in request.mutation && request.mutation.kind === 'memory-command'
        ? CLOUD_MEMORY_REVISION_HEADER : 'X-Expected-Revision', String(request.mutation.expected_revision));
    }
    headers.set('Idempotency-Key', request.mutation.idempotency_key);
  }
  const form = fullDesktop && request.form ? reconstructFormData(request.form) : undefined;
  return dependencies.fetch(target.toString(), {
    method: request.method ?? 'GET',
    headers,
    credentials: 'omit',
    redirect: 'manual',
    body: form ?? (request.body === undefined ? undefined : JSON.stringify(request.body)),
    signal: dependencies.signal,
  });
}

function reconstructFormData(parts: readonly VaultBoundCloudFormPart[]): FormData {
  const form = new FormData();
  for (const part of parts) {
    if (part.kind === 'text') {
      form.append(part.name, part.value);
      continue;
    }
    const bytes = decodeCanonicalBase64(part.bytes_base64, 'cloud request file body is invalid');
    const body = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(body).set(bytes);
    form.append(part.name, new Blob([body], { type: part.mime_type }), part.filename);
  }
  return form;
}

async function boundedBinary(
  response: Response,
  maxBytes: number,
  protectedCredential: string,
  requestPath: string,
): Promise<Readonly<Record<string, unknown>>> {
  let fileAuthority;
  if (isCloudSandboxDownloadPath(requestPath)) {
    try {
      fileAuthority = requireCloudSandboxFileAuthority({
        contract_version:
          response.headers.get('x-memstack-file-contract-version') === '1' ? 1 : null,
        authority: response.headers.get('x-memstack-file-authority'),
        isolation: response.headers.get('x-memstack-file-isolation'),
      });
    } catch (error) {
      await cancelResponseBody(response);
      throw error;
    }
  }
  const declaredLengthHeader = response.headers.get('content-length');
  const declaredLength = Number(declaredLengthHeader ?? '0');
  if (
    declaredLengthHeader !== null &&
    (!/^\d+$/u.test(declaredLengthHeader) || !Number.isSafeInteger(declaredLength))
  ) {
    await cancelResponseBody(response);
    throw new Error('cloud binary response contract is invalid');
  }
  if (declaredLength > maxBytes) {
    await cancelResponseBody(response);
    throw new Error('cloud binary response is too large');
  }
  const mimeType = response.headers.get('content-type')?.split(';', 1)[0]?.trim();
  validMimeType(mimeType, 'cloud binary response MIME type is invalid');
  const filename = binaryFilename(response.headers.get('content-disposition'), requestPath);
  const bytes = await readBoundedResponseBytes(response, maxBytes);
  if (containsBytes(bytes, new TextEncoder().encode(protectedCredential))) {
    throw new Error('cloud response contains protected credential');
  }
  return Object.freeze({
    kind: 'binary',
    bytes_base64: Buffer.from(bytes).toString('base64'),
    size_bytes: bytes.byteLength,
    mime_type: mimeType,
    filename,
    ...(fileAuthority ? { file_authority: fileAuthority } : {}),
  });
}

async function boundedEventStream(
  response: Response,
  maxBytes: number,
  protectedCredential: string,
): Promise<Readonly<Record<string, unknown>>> {
  const declaredLengthHeader = response.headers.get('content-length');
  const declaredLength = Number(declaredLengthHeader ?? '0');
  if (
    declaredLengthHeader !== null &&
    (!/^\d+$/u.test(declaredLengthHeader) || !Number.isSafeInteger(declaredLength))
  ) {
    await cancelResponseBody(response);
    throw new Error('cloud event stream response contract is invalid');
  }
  if (declaredLength > maxBytes) {
    await cancelResponseBody(response);
    throw new Error('cloud event stream response is too large');
  }
  const mimeType = response.headers.get('content-type')?.split(';', 1)[0]?.trim();
  if (mimeType !== 'text/event-stream') {
    await cancelResponseBody(response);
    throw new Error('cloud event stream response MIME type is invalid');
  }
  const bytes = await readBoundedResponseBytes(
    response,
    maxBytes,
    'cloud event stream response is too large',
  );
  if (containsBytes(bytes, new TextEncoder().encode(protectedCredential))) {
    throw new Error('cloud response contains protected credential');
  }
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    throw new Error('cloud event stream response encoding is invalid');
  }
  return Object.freeze({
    kind: 'event-stream',
    text,
    size_bytes: bytes.byteLength,
    mime_type: 'text/event-stream',
  });
}

async function readBoundedResponseBytes(
  response: Response,
  maxBytes: number,
  tooLargeReason = 'cloud binary response is too large',
): Promise<Uint8Array> {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > maxBytes) {
        await reader.cancel(tooLargeReason);
        throw new Error(tooLargeReason);
      }
      chunks.push(chunk.value);
    }
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function binaryFilename(contentDisposition: string | null, requestPath: string): string {
  if (contentDisposition !== null) {
    const tokens = contentDisposition.split(';').map((token) => token.trim());
    if (tokens.shift()?.toLowerCase() !== 'attachment') {
      throw new Error('cloud binary response filename is invalid');
    }
    let filename: string | null = null;
    let encodedFilename: string | null = null;
    for (const token of tokens) {
      const separator = token.indexOf('=');
      if (separator < 1) throw new Error('cloud binary response filename is invalid');
      const key = token.slice(0, separator).trim().toLowerCase();
      const value = token.slice(separator + 1).trim();
      if (key === 'filename' && filename === null) {
        filename = value.startsWith('"') && value.endsWith('"')
          ? value.slice(1, -1)
          : value;
      } else if (key === 'filename*' && encodedFilename === null) {
        encodedFilename = decodeRfc5987Filename(value);
      } else {
        throw new Error('cloud binary response filename is invalid');
      }
    }
    const preferred = encodedFilename ?? filename;
    if (preferred !== null) {
      return validFilename(preferred, 'cloud binary response filename is invalid');
    }
  }
  const target = new URL(requestPath, 'https://desktop.invalid');
  const segments = target.pathname.split('/');
  const fallback = segments[3] === 'artifacts' ? segments[4] : 'download';
  return validFilename(fallback, 'cloud binary response filename is invalid');
}

function decodeRfc5987Filename(value: string): string {
  if (!value.toUpperCase().startsWith("UTF-8''")) {
    throw new Error('cloud binary response filename is invalid');
  }
  try {
    return decodeURIComponent(value.slice(7));
  } catch {
    throw new Error('cloud binary response filename is invalid');
  }
}

function containsBytes(haystack: Uint8Array, needle: Uint8Array): boolean {
  if (needle.byteLength === 0 || needle.byteLength > haystack.byteLength) return false;
  const body = Buffer.from(haystack.buffer, haystack.byteOffset, haystack.byteLength);
  const protectedValue = Buffer.from(needle.buffer, needle.byteOffset, needle.byteLength);
  return body.includes(protectedValue);
}

async function boundedJson(
  response: Response,
  allowNoContent = false,
  protectedCredential: string | null = null,
  maxBytes = MAX_RESPONSE_BYTES,
): Promise<unknown> {
  const declaredLengthHeader = response.headers.get('content-length');
  const declaredLength = Number(declaredLengthHeader ?? '0');
  if (
    declaredLengthHeader !== null &&
    (!/^\d+$/u.test(declaredLengthHeader) || !Number.isSafeInteger(declaredLength))
  ) {
    await cancelResponseBody(response);
    throw new Error('cloud response contract is invalid');
  }
  if (declaredLength > maxBytes) {
    await cancelResponseBody(response);
    throw new Error('cloud response is too large');
  }
  const text = await readBoundedResponseText(response, maxBytes);
  if (!text && allowNoContent && response.status === 204) return null;
  if (!(response.headers.get('content-type') ?? '').toLowerCase().includes('application/json')) {
    throw new Error('cloud response contract is invalid');
  }
  if (protectedCredential && text.includes(protectedCredential)) {
    throw new Error('cloud response contains protected credential');
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error('cloud response contract is invalid');
  }
}

async function readBoundedResponseText(response: Response, maxBytes: number): Promise<string> {
  if (!response.body) return '';
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let receivedBytes = 0;
  let text = '';
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > maxBytes) {
        await reader.cancel('cloud response is too large');
        throw new Error('cloud response is too large');
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    return text;
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    if (error instanceof TypeError) throw new Error('cloud response contract is invalid');
    throw error;
  } finally {
    reader.releaseLock();
  }
}

async function cancelResponseBody(response: Response): Promise<void> {
  await response.body?.cancel().catch(() => undefined);
}

function parseObservedContext(
  input: unknown,
): Readonly<{ tenantId: string; projectId: string | null; workspaceId: string | null }> {
  if (!isRecord(input) || !isRecord(input.context)) {
    throw new Error('cloud request scope contract is invalid');
  }
  return Object.freeze({
    tenantId: identifier(input.context.tenant_id, 'cloud request tenant scope is invalid'),
    projectId: identifierOrNull(input.context.project_id),
    workspaceId: identifierOrNull(input.context.workspace_id),
  });
}

async function observeEndpointWorkspaceScope(
  endpoint: AuthorizedEndpoint,
  context: Readonly<{ tenantId: string; projectId: string | null; workspaceId: string | null }>,
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<typeof context> {
  assertEndpointScope({ ...endpoint, workspaceId: null }, context);
  if (endpoint.catalogProjectId !== undefined) {
    const response = await authorizedFetch(session, dependencies, {
      path: `/api/v1/projects/${encodeURIComponent(endpoint.catalogProjectId)}?tenant_id=${encodeURIComponent(context.tenantId)}`,
      method: 'GET',
    });
    const body = await boundedJson(response, false, session.credential);
    dependencies.signal?.throwIfAborted();
    if (!response.ok || !isRecord(body) || body.id !== endpoint.catalogProjectId || body.tenant_id !== context.tenantId) {
      throw new Error('cloud request catalog project scope observation failed');
    }
  }
  if (endpoint.conversationId !== undefined) {
    if (context.projectId === null) throw new Error('cloud request conversation scope unavailable');
    const response = await authorizedFetch(session, dependencies, {
      path: `/api/v1/agent/conversations/${encodeURIComponent(endpoint.conversationId)}?project_id=${encodeURIComponent(context.projectId)}`,
      method: 'GET',
    });
    const body = await boundedJson(response, false, session.credential);
    dependencies.signal?.throwIfAborted();
    if (!response.ok || !isRecord(body) || body.id !== endpoint.conversationId ||
        body.project_id !== context.projectId || body.tenant_id !== context.tenantId) {
      throw new Error('cloud request conversation scope observation failed');
    }
  }
  if (endpoint.mcpServerId !== undefined) {
    const response = await authorizedFetch(session, dependencies, {
      path: `/api/v1/mcp/${encodeURIComponent(endpoint.mcpServerId)}`, method: 'GET',
    });
    const body = await boundedJson(response, false, session.credential);
    dependencies.signal?.throwIfAborted();
    if (!response.ok || !isRecord(body) || body.id !== endpoint.mcpServerId ||
      context.projectId === null || body.project_id !== context.projectId ||
      body.tenant_id !== context.tenantId) {
      throw new Error('cloud request MCP server scope observation failed');
    }
  }
  if (endpoint.workspaceId == null || context.workspaceId !== null) return context;
  if (context.projectId === null) throw new Error('cloud request workspace scope unavailable');
  const path = `/api/v1/tenants/${encodeURIComponent(context.tenantId)}/projects/${
    encodeURIComponent(context.projectId)
  }/workspaces/${encodeURIComponent(endpoint.workspaceId)}`;
  const response = await authorizedFetch(session, dependencies, { path, method: 'GET' });
  const body = await boundedJson(response, false, session.credential);
  dependencies.signal?.throwIfAborted();
  if (
    !response.ok || !isRecord(body) || body.id !== endpoint.workspaceId ||
    body.tenant_id !== context.tenantId || body.project_id !== context.projectId
  ) {
    throw new Error('cloud request workspace scope observation failed');
  }
  return Object.freeze({ ...context, workspaceId: endpoint.workspaceId });
}

function declaredProjectIds(
  request: VaultBoundCloudRequestInput,
  endpoint: AuthorizedEndpoint,
): Set<string> {
  const target = new URL(request.path, 'https://desktop.invalid');
  const names = new Set<string>();
  if (endpoint.projectId !== null) names.add(endpoint.projectId);
  for (const value of target.searchParams.getAll('project_id')) {
    if (value) names.add(value);
  }
  const bodyProject = request.body?.project_id;
  if (typeof bodyProject === 'string' && bodyProject.length > 0) names.add(bodyProject);
  const parts = target.pathname.split('/');
  if (parts[3] === 'tenants' && parts[5] === 'projects' && parts[6]) {
    names.add(decodeURIComponent(parts[6]));
  }
  return names;
}

/** Path, query, and body may name one project. Two different ids are a contradiction. */
function assertSingleProjectScope(
  request: VaultBoundCloudRequestInput,
  endpoint: AuthorizedEndpoint,
): void {
  if (declaredProjectIds(request, endpoint).size > 1) {
    throw new Error('cloud request project scope mismatch');
  }
}

/**
 * A catalog-visible project on the request is authoritative. The saved workspace
 * context is replaced for this call and no longer blocks the request by itself.
 */
async function adoptVisibleProject(
  endpoint: AuthorizedEndpoint,
  context: Readonly<{ tenantId: string; projectId: string | null; workspaceId: string | null }>,
  session: TrustedCloudSession,
  dependencies: VaultBoundCloudRequestDependencies,
): Promise<typeof context> {
  if (endpoint.tenantId !== null && endpoint.tenantId !== context.tenantId) {
    throw new Error('cloud request tenant scope mismatch');
  }
  if (endpoint.projectId === null || endpoint.projectId === context.projectId) return context;
  const response = await authorizedFetch(session, dependencies, {
    path: `/api/v1/projects/${encodeURIComponent(endpoint.projectId)}?tenant_id=${encodeURIComponent(context.tenantId)}`,
    method: 'GET',
  });
  const body = await boundedJson(response, false, session.credential);
  dependencies.signal?.throwIfAborted();
  if (
    !response.ok ||
    !isRecord(body) ||
    body.id !== endpoint.projectId ||
    body.tenant_id !== context.tenantId
  ) {
    throw new Error('cloud request project scope mismatch');
  }
  return Object.freeze({
    tenantId: context.tenantId,
    projectId: endpoint.projectId,
    workspaceId: null,
  });
}

function assertEndpointScope(
  endpoint: AuthorizedEndpoint,
  context: Readonly<{ tenantId: string; projectId: string | null; workspaceId: string | null }>,
): void {
  if (endpoint.tenantId !== null && endpoint.tenantId !== context.tenantId) {
    throw new Error('cloud request tenant scope mismatch');
  }
  if (endpoint.projectId !== null && endpoint.projectId !== context.projectId) {
    throw new Error('cloud request project scope mismatch');
  }
  if (endpoint.workspaceId != null && endpoint.workspaceId !== context.workspaceId) {
    throw new Error('cloud request workspace scope mismatch');
  }
}

function identifier(value: unknown, reason: string): string {
  const parsed = identifierOrNull(value);
  if (parsed === null) throw new Error(reason);
  return parsed;
}

function identifierOrNull(value: unknown): string | null {
  return typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 256 &&
    value === value.trim() &&
    !hasControlCharacter(value)
    ? value
    : null;
}

function validFilename(value: unknown, reason: string): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value !== value.trim() ||
    utf8Length(value) > 255 ||
    value === '.' ||
    value === '..' ||
    value.includes('/') ||
    value.includes('\\') ||
    hasControlCharacter(value)
  ) {
    throw new Error(reason);
  }
  return value;
}

function validMimeType(value: unknown, reason: string): string {
  if (
    typeof value !== 'string' ||
    value.length > 127 ||
    value !== value.trim() ||
    !MIME_TYPE.test(value)
  ) {
    throw new Error(reason);
  }
  return value;
}

function decodeCanonicalBase64(value: unknown, reason: string): Uint8Array {
  if (typeof value !== 'string') throw new Error(reason);
  const bytes = Buffer.from(value, 'base64');
  if (bytes.toString('base64') !== value) throw new Error(reason);
  return bytes;
}

function utf8Length(value: string): number {
  return Buffer.byteLength(value, 'utf8');
}

function secureOrigin(url: URL): boolean {
  return (
    url.protocol === 'https:' ||
    (url.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase()))
  );
}

function exactRecord(
  input: unknown,
  allowedKeys: ReadonlySet<string>,
  reason: string,
): Record<string, unknown> {
  if (!isRecord(input) || Object.keys(input).some((key) => !allowedKeys.has(key))) {
    throw new Error(reason);
  }
  return input;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasControlCharacter(value: string): boolean {
  return /[\u0000-\u001f\u007f]/u.test(value);
}

function validRequestId(value: unknown): string {
  if (typeof value !== 'string' || !REQUEST_ID.test(value)) {
    throw new Error('cloud request id is invalid');
  }
  return value;
}
