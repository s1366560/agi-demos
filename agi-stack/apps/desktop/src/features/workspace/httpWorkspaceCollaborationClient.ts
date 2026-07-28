import {
  absoluteUrl,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from './workspaceCollaborationClient';
import {
  isWorkspaceRecord,
  requireWorkspaceRecord,
  scopedWorkspacePath,
  workspaceContractError,
  workspaceRootPath,
  type WorkspaceHttpScope,
} from './workspaceCollaborationHttpContract';
import {
  buildWorkspaceMutationRequest,
  isAllowedWorkspaceMutation,
  requireWorkspaceMutationAuthority,
} from './workspaceCollaborationHttpMutations';

export { WorkspaceCollaborationContractError } from './workspaceCollaborationHttpContract';
export { WORKSPACE_HTTP_MUTATION_ACTIONS } from './workspaceCollaborationHttpMutations';

type WorkspaceAuthorityResponse = {
  payload: unknown;
  revision: number | null;
  payloadCursor: string | null;
  etag: string | null;
};

type WorkspaceRequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: Record<string, unknown> | FormData;
  mutation?: WorkspaceSurfaceMutation;
  signal?: AbortSignal;
};

export function createHttpWorkspaceCollaborationClient(
  config: DesktopRuntimeConfig,
): WorkspaceCollaborationClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    getSurface: (
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      _cursor?: string | null,
      signal?: AbortSignal,
    ) => loadWorkspaceSurface(runtimeConfig, workspaceId, surface, signal),
    refetchAuthority: (
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      signal?: AbortSignal,
    ) => loadWorkspaceSurface(runtimeConfig, workspaceId, surface, signal),
    mutateSurface: (
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      mutation: WorkspaceSurfaceMutation,
      signal?: AbortSignal,
    ) => mutateWorkspaceSurface(runtimeConfig, workspaceId, surface, mutation, signal),
  });
}

async function loadWorkspaceSurface(
  config: DesktopRuntimeConfig,
  workspaceId: string,
  surface: WorkspaceCollaborationSurface,
  signal?: AbortSignal,
): Promise<WorkspaceSurfaceState> {
  const scope = requireWorkspaceScope(config, workspaceId);
  const scopedBase = scopedWorkspacePath(scope);
  const workspaceRoot = workspaceRootPath(scope);
  let data: Record<string, unknown>;
  let responses: WorkspaceAuthorityResponse[];
  let empty = false;

  switch (surface) {
    case 'goals': {
      const [objectives, tasks] = await Promise.all([
        getScopedCollection(config, `${scopedBase}/objectives`, scope, ['items'], signal),
        getScopedCollection(config, `${workspaceRoot}/tasks`, scope, [], signal),
      ]);
      data = { objectives: objectives.items, tasks: tasks.items };
      responses = [objectives.response, tasks.response];
      empty = objectives.items.length === 0 && tasks.items.length === 0;
      break;
    }
    case 'discussion': {
      const posts = await getScopedCollection(
        config,
        `${scopedBase}/blackboard/posts`,
        scope,
        ['items'],
        signal,
      );
      data = { posts: posts.items };
      responses = [posts.response];
      empty = posts.items.length === 0;
      break;
    }
    case 'status': {
      const [diagnostics, tasks] = await Promise.all([
        getScopedRecord(
          config,
          `${scopedBase}/blackboard/execution-diagnostics`,
          scope,
          signal,
        ),
        getScopedCollection(config, `${workspaceRoot}/tasks`, scope, [], signal),
      ]);
      data = { diagnostics: diagnostics.record, tasks: tasks.items };
      responses = [diagnostics.response, tasks.response];
      break;
    }
    case 'collaboration': {
      const [agents, members, tasks] = await Promise.all([
        getScopedCollection(config, `${scopedBase}/agents`, scope, ['items', 'agents'], signal),
        getScopedCollection(config, `${scopedBase}/members`, scope, ['items', 'members'], signal),
        getScopedCollection(config, `${workspaceRoot}/tasks`, scope, [], signal),
      ]);
      data = { agents: agents.items, members: members.items, tasks: tasks.items };
      responses = [agents.response, members.response, tasks.response];
      empty = agents.items.length === 0 && members.items.length === 0 && tasks.items.length === 0;
      break;
    }
    case 'members': {
      const members = await getScopedCollection(
        config,
        `${scopedBase}/members`,
        scope,
        ['items', 'members'],
        signal,
      );
      data = { members: members.items };
      responses = [members.response];
      empty = members.items.length === 0;
      break;
    }
    case 'genes': {
      const genes = await getScopedCollection(
        config,
        `${scopedBase}/genes`,
        scope,
        ['items'],
        signal,
      );
      data = { genes: genes.items };
      responses = [genes.response];
      empty = genes.items.length === 0;
      break;
    }
    case 'files': {
      const files = await getScopedCollection(
        config,
        `${scopedBase}/blackboard/files?parent_path=%2F`,
        scope,
        ['items'],
        signal,
      );
      data = { files: files.items };
      responses = [files.response];
      empty = files.items.length === 0;
      break;
    }
    case 'notes': {
      const [workspace, objectives, posts] = await Promise.all([
        getWorkspaceRecord(config, scopedBase, scope, signal),
        getScopedCollection(config, `${scopedBase}/objectives`, scope, ['items'], signal),
        getScopedCollection(
          config,
          `${scopedBase}/blackboard/posts`,
          scope,
          ['items'],
          signal,
        ),
      ]);
      data = {
        workspace: workspace.record,
        objectives: objectives.items,
        pinned_posts: posts.items.filter((post) => post.is_pinned === true),
      };
      responses = [workspace.response, objectives.response, posts.response];
      break;
    }
    case 'topology': {
      const [nodes, edges] = await Promise.all([
        getScopedCollection(config, `${workspaceRoot}/topology/nodes`, scope, [], signal),
        getScopedCollection(config, `${workspaceRoot}/topology/edges`, scope, ['items'], signal),
      ]);
      data = { nodes: nodes.items, edges: edges.items };
      responses = [nodes.response, edges.response];
      empty = nodes.items.length === 0 && edges.items.length === 0;
      break;
    }
    case 'settings': {
      const workspace = await getWorkspaceRecord(config, scopedBase, scope, signal);
      data = { workspace: workspace.record };
      responses = [workspace.response];
      break;
    }
    default:
      throw workspaceContractError('workspace_surface_contract_invalid');
  }

  const authority = combineAuthority(responses);
  return {
    workspace_id: scope.workspaceId,
    surface,
    authority: config.mode === 'local' ? 'local' : 'cloud',
    status: empty ? 'empty' : 'ready',
    revision: authority.revision,
    cursor: authority.cursor,
    data,
    reason_code: null,
  };
}

async function mutateWorkspaceSurface(
  config: DesktopRuntimeConfig,
  workspaceId: string,
  surface: WorkspaceCollaborationSurface,
  mutation: WorkspaceSurfaceMutation,
  signal?: AbortSignal,
): Promise<WorkspaceSurfaceState> {
  const scope = requireWorkspaceScope(config, workspaceId);
  if (!isAllowedWorkspaceMutation(surface, mutation.action)) {
    return unavailableMutationState(config, scope.workspaceId, surface);
  }
  requireWorkspaceMutationAuthority(mutation);
  const request = buildWorkspaceMutationRequest(scope, surface, mutation);
  await requestWorkspaceAuthority(config, request.path, {
    method: request.method,
    body: request.body,
    mutation,
    signal,
  });
  return loadWorkspaceSurface(config, scope.workspaceId, surface, signal);
}

async function getScopedCollection(
  config: DesktopRuntimeConfig,
  path: string,
  scope: WorkspaceHttpScope,
  wrapperKeys: readonly string[],
  signal?: AbortSignal,
): Promise<{ items: Record<string, unknown>[]; response: WorkspaceAuthorityResponse }> {
  const response = await requestWorkspaceAuthority(config, path, { signal });
  requireOptionalEnvelopeScope(response.payload, scope);
  const items = readCollection(response.payload, wrapperKeys);
  for (const item of items) requireScopedRecordValue(item, scope);
  return { items, response };
}

async function getScopedRecord(
  config: DesktopRuntimeConfig,
  path: string,
  scope: WorkspaceHttpScope,
  signal?: AbortSignal,
): Promise<{ record: Record<string, unknown>; response: WorkspaceAuthorityResponse }> {
  const response = await requestWorkspaceAuthority(config, path, { signal });
  const record = requireWorkspaceRecord(
    response.payload,
    'workspace_surface_contract_invalid',
  );
  requireScopedRecordValue(record, scope);
  return { record, response };
}

async function getWorkspaceRecord(
  config: DesktopRuntimeConfig,
  path: string,
  scope: WorkspaceHttpScope,
  signal?: AbortSignal,
): Promise<{ record: Record<string, unknown>; response: WorkspaceAuthorityResponse }> {
  const response = await requestWorkspaceAuthority(config, path, { signal });
  const record = requireWorkspaceRecord(
    response.payload,
    'workspace_surface_contract_invalid',
  );
  if (
    record.id !== scope.workspaceId ||
    record.tenant_id !== scope.tenantId ||
    record.project_id !== scope.projectId
  ) {
    throw workspaceContractError('workspace_surface_scope_mismatch');
  }
  return { record, response };
}

async function requestWorkspaceAuthority(
  config: DesktopRuntimeConfig,
  path: string,
  options: WorkspaceRequestOptions = {},
): Promise<WorkspaceAuthorityResponse> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.mutation) {
    headers.set('X-Expected-Revision', String(options.mutation.expected_revision));
    headers.set('Idempotency-Key', options.mutation.idempotency_key);
  }

  const formData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body !== undefined && !formData) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method ?? 'GET',
    headers,
    body:
      options.body === undefined
        ? undefined
        : formData
          ? (options.body as FormData)
          : JSON.stringify(options.body),
    signal: options.signal,
  });

  const contentType = response.headers.get('content-type') ?? '';
  let payload: unknown = null;
  if (response.status !== 204 && contentType.includes('application/json')) {
    payload = await response.json().catch(() => null);
  }
  if (!response.ok) {
    throw workspaceContractError('workspace_surface_request_failed', response.status, payload);
  }
  if (response.status !== 204 && !contentType.includes('application/json')) {
    throw workspaceContractError('workspace_surface_contract_invalid', response.status);
  }

  const authority = readPayloadAuthority(payload);
  return {
    payload,
    revision: authority.revision,
    payloadCursor: authority.cursor,
    etag: readEtag(response.headers),
  };
}

function readCollection(
  payload: unknown,
  wrapperKeys: readonly string[],
): Record<string, unknown>[] {
  const candidate = Array.isArray(payload)
    ? payload
    : readWrappedCollection(payload, wrapperKeys);
  if (!candidate) throw workspaceContractError('workspace_surface_contract_invalid');
  return candidate.map((item) =>
    requireWorkspaceRecord(item, 'workspace_surface_contract_invalid'),
  );
}

function readWrappedCollection(
  payload: unknown,
  wrapperKeys: readonly string[],
): unknown[] | null {
  if (!isWorkspaceRecord(payload)) return null;
  for (const key of wrapperKeys) {
    if (Array.isArray(payload[key])) return payload[key] as unknown[];
  }
  return null;
}

function requireScopedRecordValue(
  record: Record<string, unknown>,
  scope: WorkspaceHttpScope,
): void {
  if (record.workspace_id !== scope.workspaceId) {
    throw workspaceContractError('workspace_surface_scope_mismatch');
  }
  if (
    (Object.hasOwn(record, 'tenant_id') && record.tenant_id !== scope.tenantId) ||
    (Object.hasOwn(record, 'project_id') && record.project_id !== scope.projectId)
  ) {
    throw workspaceContractError('workspace_surface_scope_mismatch');
  }
}

function requireOptionalEnvelopeScope(
  payload: unknown,
  scope: WorkspaceHttpScope,
): void {
  if (!isWorkspaceRecord(payload)) return;
  if (
    (Object.hasOwn(payload, 'workspace_id') &&
      payload.workspace_id !== scope.workspaceId) ||
    (Object.hasOwn(payload, 'tenant_id') && payload.tenant_id !== scope.tenantId) ||
    (Object.hasOwn(payload, 'project_id') && payload.project_id !== scope.projectId)
  ) {
    throw workspaceContractError('workspace_surface_scope_mismatch');
  }
}

function combineAuthority(
  responses: readonly WorkspaceAuthorityResponse[],
): { revision: number | null; cursor: string | null } {
  const revisions = responses
    .map(({ revision }) => revision)
    .filter((revision): revision is number => revision !== null);
  if (new Set(revisions).size > 1) {
    throw workspaceContractError('workspace_surface_revision_conflict');
  }

  const payloadCursors = responses
    .map(({ payloadCursor }) => payloadCursor)
    .filter((cursor): cursor is string => cursor !== null);
  if (new Set(payloadCursors).size > 1) {
    throw workspaceContractError('workspace_surface_cursor_conflict');
  }
  if (payloadCursors.length > 0) {
    return { revision: revisions[0] ?? null, cursor: payloadCursors[0] };
  }

  const etags = responses.map(({ etag }) => etag);
  const commonEtag =
    etags.length > 0 &&
    etags.every((etag): etag is string => etag !== null && etag === etags[0])
      ? etags[0]
      : null;
  return { revision: revisions[0] ?? null, cursor: commonEtag };
}

function readPayloadAuthority(payload: unknown): {
  revision: number | null;
  cursor: string | null;
} {
  if (!isWorkspaceRecord(payload)) return { revision: null, cursor: null };
  let revision: number | null = null;
  let cursor: string | null = null;
  if (Object.hasOwn(payload, 'revision')) {
    if (
      payload.revision !== null &&
      (!Number.isSafeInteger(payload.revision) || Number(payload.revision) < 0)
    ) {
      throw workspaceContractError('workspace_surface_contract_invalid');
    }
    revision = payload.revision === null ? null : Number(payload.revision);
  }
  if (Object.hasOwn(payload, 'cursor')) {
    if (
      payload.cursor !== null &&
      (typeof payload.cursor !== 'string' ||
        payload.cursor.length === 0 ||
        payload.cursor.length > 512)
    ) {
      throw workspaceContractError('workspace_surface_contract_invalid');
    }
    cursor = payload.cursor === null ? null : String(payload.cursor);
  }
  return { revision, cursor };
}

function readEtag(headers: Headers): string | null {
  const etag = headers.get('etag')?.trim() ?? '';
  if (!etag) return null;
  if (etag.length > 512) {
    throw workspaceContractError('workspace_surface_contract_invalid');
  }
  return etag;
}

function requireWorkspaceScope(
  config: DesktopRuntimeConfig,
  workspaceId: string,
): WorkspaceHttpScope {
  const tenantId = config.tenantId.trim();
  const projectId = config.projectId.trim();
  const configuredWorkspaceId = config.workspaceId.trim();
  const requestedWorkspaceId = workspaceId.trim();
  if (
    !config.apiBaseUrl.trim() ||
    !tenantId ||
    !projectId ||
    !configuredWorkspaceId ||
    !requestedWorkspaceId
  ) {
    throw workspaceContractError('workspace_surface_scope_unavailable');
  }
  if (configuredWorkspaceId !== requestedWorkspaceId) {
    throw workspaceContractError('workspace_surface_scope_mismatch');
  }
  return { tenantId, projectId, workspaceId: requestedWorkspaceId };
}

function unavailableMutationState(
  config: DesktopRuntimeConfig,
  workspaceId: string,
  surface: WorkspaceCollaborationSurface,
): WorkspaceSurfaceState {
  return {
    workspace_id: workspaceId,
    surface,
    authority: config.mode === 'local' ? 'local' : 'cloud',
    status: 'unavailable',
    revision: null,
    cursor: null,
    data: null,
    reason_code: 'workspace_surface_action_unavailable',
  };
}
