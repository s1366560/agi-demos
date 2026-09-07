import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import type {
  ProjectBlackboardScope,
  ProjectBlackboardSnapshot,
} from '../features/project-blackboard/projectBlackboardClient';
import {
  normalizeWorkspaceCollaborationAuthorityContract,
  normalizeWorkspaceCollaborationCapabilityContract,
  type WorkspaceCollaborationCapabilityScope,
} from '../features/workspace/workspaceCollaborationCapabilityContract';
import { createHttpWorkspaceCollaborationClient } from '../features/workspace/httpWorkspaceCollaborationClient';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from '../features/workspace/workspaceCollaborationClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export type DesktopWorkspaceSurfaceProjectionV2 = 'project-blackboard' | 'workspace-collaboration';

export interface DesktopProjectBlackboardAuthorityV2 {
  readonly probeWorkspaceCollaborationCapability: (
    scope: WorkspaceCollaborationCapabilityScope,
    signal?: AbortSignal,
  ) => Promise<DesktopCapabilityAvailability>;
  readonly probeProjectBlackboard: (
    scope: ProjectBlackboardScope,
    signal?: AbortSignal,
  ) => Promise<ProjectBlackboardSnapshot>;
  readonly getWorkspaceSurface: (
    projection: DesktopWorkspaceSurfaceProjectionV2,
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    cursor?: string | null,
    signal?: AbortSignal,
  ) => Promise<WorkspaceSurfaceState>;
  readonly refetchWorkspaceSurface: (
    projection: DesktopWorkspaceSurfaceProjectionV2,
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    signal?: AbortSignal,
  ) => Promise<WorkspaceSurfaceState>;
  readonly mutateWorkspaceSurface: (
    projection: DesktopWorkspaceSurfaceProjectionV2,
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    mutation: WorkspaceSurfaceMutation,
    signal?: AbortSignal,
  ) => Promise<WorkspaceSurfaceState>;
}

export function createDesktopProjectBlackboardAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopProjectBlackboardAuthorityV2 {
  const runtimeConfig = Object.freeze({ ...config });
  const collaborationClient = createHttpWorkspaceCollaborationClient(runtimeConfig);
  const localBlackboardClient =
    runtimeConfig.mode === 'local' ? createLocalPlanCollaborationClientV2(runtimeConfig) : null;
  const clientFor = (
    projection: DesktopWorkspaceSurfaceProjectionV2,
  ): WorkspaceCollaborationClient =>
    projection === 'project-blackboard' && localBlackboardClient !== null
      ? localBlackboardClient
      : collaborationClient;

  const authority: DesktopProjectBlackboardAuthorityV2 = {
    probeWorkspaceCollaborationCapability: (scope, signal) =>
      probeWorkspaceCollaborationCapabilityV2(runtimeConfig, scope, signal),
    async probeProjectBlackboard(scope, signal) {
      const currentScope = requireProjectBlackboardScopeV2(runtimeConfig, scope);
      requireCredentialV2(runtimeConfig);
      const initialSurface = runtimeConfig.mode === 'local' ? 'status' : 'goals';
      const state = await clientFor('project-blackboard').getSurface(
        currentScope.workspaceId,
        initialSurface,
        null,
        signal,
      );
      requireObservedSurfaceV2(state, currentScope, initialSurface);
      return Object.freeze({
        scope: currentScope,
        authority: runtimeConfig.mode,
        availability: runtimeConfig.mode === 'local' ? 'degraded' : 'available',
        reasonCode: runtimeConfig.mode === 'local' ? 'local_workspace_plan_read_only' : null,
        initialSurface,
        allowedActions: Object.freeze(
          runtimeConfig.mode === 'local'
            ? ['view', 'select-workspace', 'review-plan']
            : ['view', 'select-workspace', 'read-surfaces', 'mutate-surfaces'],
        ),
        authorityRevision: runtimeConfig.mode === 'local' ? null : state.revision,
      });
    },
    getWorkspaceSurface: (projection, workspaceId, surface, cursor, signal) =>
      clientFor(projection).getSurface(workspaceId, surface, cursor, signal),
    refetchWorkspaceSurface: (projection, workspaceId, surface, signal) =>
      clientFor(projection).refetchAuthority(workspaceId, surface, signal),
    mutateWorkspaceSurface: (projection, workspaceId, surface, mutation, signal) =>
      clientFor(projection).mutateSurface(workspaceId, surface, mutation, signal),
  };
  return Object.freeze(authority);
}

async function probeWorkspaceCollaborationCapabilityV2(
  config: DesktopRuntimeConfig,
  scope: WorkspaceCollaborationCapabilityScope,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  requireWorkspaceCollaborationScopeV2(config, scope);
  const workspaceCoreFailure = await workspaceCoreStatusFailureV2(config, signal);
  if (workspaceCoreFailure !== null) return unavailableCapabilityV2(workspaceCoreFailure);

  try {
    const headers = authorityHeadersV2(config);
    const scopedPath =
      `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/projects/` +
      `${encodeURIComponent(scope.projectId)}/workspaces/` +
      `${encodeURIComponent(scope.workspaceId)}/collaboration`;
    const response = await desktopApiFetch(config, `${scopedPath}/capabilities`, {
      headers,
      signal,
    });
    if (!response.ok) {
      return unavailableCapabilityV2('workspace_collaboration_capability_contract_unavailable');
    }
    if (!response.headers.get('content-type')?.includes('application/json')) {
      return unavailableCapabilityV2('workspace_collaboration_capability_contract_invalid');
    }
    const capability = normalizeWorkspaceCollaborationCapabilityContract(
      await response.json().catch(() => null),
      scope,
      config.mode,
    );
    if (capability.availability !== 'available' && capability.availability !== 'degraded') {
      return capability;
    }

    const authorityResponse = await desktopApiFetch(config, `${scopedPath}/authority`, {
      headers,
      signal,
    });
    if (!authorityResponse.ok) {
      return closeCapabilityAuthorityV2(
        capability,
        'workspace_collaboration_authority_contract_unavailable',
      );
    }
    if (!authorityResponse.headers.get('content-type')?.includes('application/json')) {
      return closeCapabilityAuthorityV2(
        capability,
        'workspace_collaboration_authority_contract_invalid',
      );
    }
    const authorityRevision = normalizeWorkspaceCollaborationAuthorityContract(
      await authorityResponse.json().catch(() => null),
      scope,
    );
    if (authorityRevision === null) {
      return closeCapabilityAuthorityV2(
        capability,
        'workspace_collaboration_authority_contract_invalid',
      );
    }
    return Object.freeze({
      ...capability,
      scope: Object.freeze({
        tenant_id: scope.tenantId,
        project_id: scope.projectId,
        workspace_id: scope.workspaceId,
        instance_id: null,
      }),
      authority_revision: authorityRevision,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    return unavailableCapabilityV2('workspace_collaboration_capability_contract_unavailable');
  }
}

async function workspaceCoreStatusFailureV2(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<string | null> {
  if (
    config.mode !== 'local' ||
    typeof window === 'undefined' ||
    window.__MEMSTACK_DESKTOP__?.runtime !== 'electron'
  ) {
    return null;
  }
  const invoke = window.__MEMSTACK_DESKTOP__.core?.invoke;
  if (!invoke) return 'workspace_core_status_unavailable';
  try {
    const helper = await invoke<DesktopWorkspaceCoreHelperStatus>('workspace_core_status');
    if (
      !['legacy-only', 'importing', 'core-authoritative', 'core-unavailable'].includes(
        helper?.cutoverState,
      )
    ) {
      return 'workspace_core_status_invalid';
    }
    return helper.cutoverState !== 'legacy-only' && helper.state !== 'running'
      ? 'workspace_core_cutover_unavailable'
      : null;
  } catch (error) {
    if (signal?.aborted) throw error;
    return 'workspace_core_status_unavailable';
  }
}

function createLocalPlanCollaborationClientV2(
  config: DesktopRuntimeConfig,
): WorkspaceCollaborationClient {
  const load = async (
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    signal?: AbortSignal,
  ): Promise<WorkspaceSurfaceState> => {
    requireRuntimeWorkspaceV2(config, workspaceId);
    if (surface !== 'status') {
      return unavailableLocalStateV2(workspaceId, surface, 'local_blackboard_surface_unavailable');
    }
    const [plan, tasks] = await Promise.all([
      requestLocalJsonV2(
        config,
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/plan`,
        signal,
      ),
      requestLocalJsonV2(
        config,
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/tasks`,
        signal,
      ),
    ]);
    return Object.freeze({
      workspace_id: workspaceId,
      surface,
      authority: 'local',
      status: 'ready',
      revision: null,
      cursor: null,
      data: Object.freeze({
        diagnostics: requireLocalPlanV2(plan, config, workspaceId),
        tasks: requireLocalTasksV2(tasks, workspaceId),
      }),
      reason_code: 'local_workspace_plan_read_only',
    });
  };
  return Object.freeze({
    getSurface: (workspaceId, surface, _cursor, signal) => load(workspaceId, surface, signal),
    refetchAuthority: (workspaceId, surface, signal) => load(workspaceId, surface, signal),
    async mutateSurface(workspaceId, surface) {
      requireRuntimeWorkspaceV2(config, workspaceId);
      return unavailableLocalStateV2(workspaceId, surface, 'local_blackboard_mutation_unavailable');
    },
  });
}

async function requestLocalJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: 'GET',
    headers: authorityHeadersV2(config),
    credentials: 'omit',
    signal,
  });
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw contractErrorV2('local_project_blackboard_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw contractErrorV2('local_project_blackboard_response_too_large');
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  const payload = contentType.includes('application/json') ? parseJsonV2(text) : text;
  if (!response.ok) {
    throw new DesktopApiError(errorMessageV2(response.status, payload), response.status, payload);
  }
  if (!contentType.includes('application/json')) {
    throw contractErrorV2('local_project_blackboard_response_not_json');
  }
  return payload;
}

function requireLocalPlanV2(
  input: unknown,
  config: DesktopRuntimeConfig,
  workspaceId: string,
): Readonly<Record<string, unknown>> {
  if (
    !isRecordV2(input) ||
    input.workspace_id !== workspaceId ||
    input.project_id !== config.projectId ||
    !Array.isArray(input.conversation_plans) ||
    !Array.isArray(input.plan_history) ||
    !Array.isArray(input.run_health) ||
    !Array.isArray(input.pending_hitl) ||
    !Array.isArray(input.delivery) ||
    !Array.isArray(input.artifact_index)
  ) {
    throw contractErrorV2('local_project_blackboard_plan_contract_invalid');
  }
  return Object.freeze({
    id: workspaceId,
    workspace_id: workspaceId,
    project_id: config.projectId,
    status: 'local_workspace_plan_read_only',
    conversation_plans: Object.freeze([...input.conversation_plans]),
    plan_history: Object.freeze([...input.plan_history]),
    run_health: Object.freeze([...input.run_health]),
    pending_hitl: Object.freeze([...input.pending_hitl]),
    delivery: Object.freeze([...input.delivery]),
    artifact_index: Object.freeze([...input.artifact_index]),
  });
}

function requireLocalTasksV2(
  input: unknown,
  workspaceId: string,
): readonly Record<string, unknown>[] {
  if (
    !isRecordV2(input) ||
    input.workspace_id !== workspaceId ||
    !Array.isArray(input.items) ||
    !Number.isSafeInteger(input.total) ||
    input.total !== input.items.length ||
    input.items.some((item) => !isRecordV2(item))
  ) {
    throw contractErrorV2('local_project_blackboard_tasks_contract_invalid');
  }
  return Object.freeze(
    input.items.map((item) => Object.freeze({ ...(item as Record<string, unknown>) })),
  );
}

function requireObservedSurfaceV2(
  state: WorkspaceSurfaceState,
  scope: ProjectBlackboardScope,
  surface: WorkspaceCollaborationSurface,
): void {
  if (
    state.workspace_id !== scope.workspaceId ||
    state.surface !== surface ||
    state.authority !== scope.authority ||
    (state.status !== 'ready' && state.status !== 'empty') ||
    (scope.authority === 'cloud' &&
      (!Number.isSafeInteger(state.revision) || Number(state.revision) < 0))
  ) {
    throw contractErrorV2(`${scope.authority}_project_blackboard_authority_invalid`);
  }
}

function requireProjectBlackboardScopeV2(
  config: DesktopRuntimeConfig,
  scope: ProjectBlackboardScope,
): ProjectBlackboardScope {
  if (
    scope.authority !== config.mode ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId ||
    scope.workspaceId !== config.workspaceId ||
    !validIdV2(scope.tenantId) ||
    !validIdV2(scope.projectId) ||
    !validIdV2(scope.workspaceId)
  ) {
    throw contractErrorV2('project_blackboard_runtime_scope_mismatch');
  }
  return Object.freeze({ ...scope });
}

function requireWorkspaceCollaborationScopeV2(
  config: DesktopRuntimeConfig,
  scope: WorkspaceCollaborationCapabilityScope,
): void {
  if (
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId ||
    scope.workspaceId !== config.workspaceId ||
    !Object.values(scope).every(validIdV2)
  ) {
    throw contractErrorV2('workspace_collaboration_capability_scope_mismatch');
  }
}

function requireRuntimeWorkspaceV2(config: DesktopRuntimeConfig, workspaceId: string): void {
  if (!validIdV2(workspaceId) || workspaceId !== config.workspaceId) {
    throw contractErrorV2('project_blackboard_runtime_scope_mismatch');
  }
}

function requireCredentialV2(config: DesktopRuntimeConfig): void {
  if (!desktopApiAuthenticationAvailable(config)) {
    throw contractErrorV2('project_blackboard_trusted_session_required');
  }
}

function authorityHeadersV2(config: DesktopRuntimeConfig): Headers {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  return headers;
}

function closeCapabilityAuthorityV2(
  capability: DesktopCapabilityAvailability,
  reasonCode: string,
): DesktopCapabilityAvailability {
  return Object.freeze({
    ...capability,
    availability: 'unavailable',
    reason_code: reasonCode,
    allowed_actions: Object.freeze([]),
    authority_revision: null,
  });
}

function unavailableCapabilityV2(reasonCode: string): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope: Object.freeze({
      tenant_id: null,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: null,
  });
}

function unavailableLocalStateV2(
  workspaceId: string,
  surface: WorkspaceCollaborationSurface,
  reasonCode: string,
): WorkspaceSurfaceState {
  return Object.freeze({
    workspace_id: workspaceId,
    surface,
    authority: 'local',
    status: 'unavailable',
    revision: null,
    cursor: null,
    data: null,
    reason_code: reasonCode,
  });
}

function parseJsonV2(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw contractErrorV2('local_project_blackboard_response_invalid_json');
  }
}

function errorMessageV2(status: number, payload: unknown): string {
  return isRecordV2(payload) && typeof payload.detail === 'string' && payload.detail.trim()
    ? payload.detail
    : `HTTP ${status}`;
}

function contractErrorV2(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function validIdV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value;
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
