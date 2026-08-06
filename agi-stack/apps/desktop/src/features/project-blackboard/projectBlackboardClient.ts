import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import { createHttpWorkspaceCollaborationClient } from '../workspace/httpWorkspaceCollaborationClient';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from '../workspace/workspaceCollaborationClient';

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export type ProjectBlackboardAuthority = 'cloud' | 'local';

export type ProjectBlackboardScope = Readonly<{
  authority: ProjectBlackboardAuthority;
  tenantId: string;
  projectId: string;
  workspaceId: string;
}>;

export type ProjectBlackboardSnapshot = Readonly<{
  scope: ProjectBlackboardScope;
  authority: ProjectBlackboardAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  initialSurface: WorkspaceCollaborationSurface;
  allowedActions: readonly string[];
  collaborationClient: WorkspaceCollaborationClient;
}>;

export interface ProjectBlackboardClient {
  probe(scope: ProjectBlackboardScope, signal?: AbortSignal): Promise<ProjectBlackboardSnapshot>;
}

export function createProjectBlackboardCloudClient(
  config: DesktopRuntimeConfig,
  dependencies: Readonly<{ collaborationClient?: WorkspaceCollaborationClient }> = {},
): ProjectBlackboardClient {
  if (config.mode !== 'cloud') throw contractError('cloud_project_blackboard_config_required');
  const runtimeConfig = Object.freeze({ ...config });
  requireCredential(runtimeConfig);
  const collaborationClient =
    dependencies.collaborationClient ?? createHttpWorkspaceCollaborationClient(runtimeConfig);
  const client: ProjectBlackboardClient = {
    async probe(scope, signal) {
      const currentScope = requireScope(runtimeConfig, scope, 'cloud');
      const state = await collaborationClient.getSurface(
        currentScope.workspaceId,
        'goals',
        null,
        signal,
      );
      requireObservedSurface(state, currentScope, 'goals', 'cloud');
      return Object.freeze({
        scope: currentScope,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        initialSurface: 'goals',
        allowedActions: Object.freeze([
          'view',
          'select-workspace',
          'read-surfaces',
          'mutate-surfaces',
        ]),
        collaborationClient,
      });
    },
  };
  return Object.freeze(client);
}

export function createProjectBlackboardLocalClient(
  config: DesktopRuntimeConfig,
): ProjectBlackboardClient {
  if (config.mode !== 'local') throw contractError('local_project_blackboard_config_required');
  const runtimeConfig = Object.freeze({ ...config });
  requireCredential(runtimeConfig);
  if (!desktopLaunchCapability(runtimeConfig)) {
    throw contractError('local_project_blackboard_launch_capability_required');
  }
  const collaborationClient = createLocalPlanCollaborationClient(runtimeConfig);
  const client: ProjectBlackboardClient = {
    async probe(scope, signal) {
      const currentScope = requireScope(runtimeConfig, scope, 'local');
      const state = await collaborationClient.getSurface(
        currentScope.workspaceId,
        'status',
        null,
        signal,
      );
      requireObservedSurface(state, currentScope, 'status', 'local');
      return Object.freeze({
        scope: currentScope,
        authority: 'local',
        availability: 'degraded',
        reasonCode: 'local_workspace_plan_read_only',
        initialSurface: 'status',
        allowedActions: Object.freeze(['view', 'select-workspace', 'review-plan']),
        collaborationClient,
      });
    },
  };
  return Object.freeze(client);
}

function createLocalPlanCollaborationClient(
  config: DesktopRuntimeConfig,
): WorkspaceCollaborationClient {
  const load = async (
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    signal?: AbortSignal,
  ): Promise<WorkspaceSurfaceState> => {
    requireRuntimeWorkspace(config, workspaceId);
    if (surface !== 'status') {
      return unavailableState(
        workspaceId,
        surface,
        'local_blackboard_surface_unavailable',
      );
    }
    const [plan, tasks] = await Promise.all([
      requestLocalJson(config, `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/plan`, signal),
      requestLocalJson(config, `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/tasks`, signal),
    ]);
    const planSnapshot = requireLocalPlan(plan, config, workspaceId);
    const taskItems = requireLocalTasks(tasks, workspaceId);
    return Object.freeze({
      workspace_id: workspaceId,
      surface,
      authority: 'local',
      status: 'ready',
      revision: null,
      cursor: null,
      data: Object.freeze({ diagnostics: planSnapshot, tasks: taskItems }),
      reason_code: 'local_workspace_plan_read_only',
    });
  };
  return Object.freeze({
    getSurface: (workspaceId, surface, _cursor, signal) =>
      load(workspaceId, surface, signal),
    refetchAuthority: (workspaceId, surface, signal) =>
      load(workspaceId, surface, signal),
    async mutateSurface(
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      _mutation: WorkspaceSurfaceMutation,
      _signal?: AbortSignal,
    ) {
      requireRuntimeWorkspace(config, workspaceId);
      return unavailableState(
        workspaceId,
        surface,
        'local_blackboard_mutation_unavailable',
      );
    },
  });
}

async function requestLocalJson(
  config: DesktopRuntimeConfig,
  path: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({
    Accept: 'application/json',
    Authorization: `Bearer ${desktopApiCredential(config)}`,
    'X-Agistack-Launch': desktopLaunchCapability(config),
  });
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: 'GET',
    headers,
    credentials: 'omit',
    signal,
  });
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw contractError('local_project_blackboard_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw contractError('local_project_blackboard_response_too_large');
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  const payload = contentType.includes('application/json') ? parseJson(text) : text;
  if (!response.ok) {
    throw new DesktopApiError(errorMessage(response.status, payload), response.status, payload);
  }
  if (!contentType.includes('application/json')) {
    throw contractError('local_project_blackboard_response_not_json');
  }
  return payload;
}

function requireLocalPlan(
  input: unknown,
  config: DesktopRuntimeConfig,
  workspaceId: string,
): Readonly<Record<string, unknown>> {
  if (
    !isRecord(input) ||
    input.workspace_id !== workspaceId ||
    input.project_id !== config.projectId ||
    !Array.isArray(input.conversation_plans) ||
    !Array.isArray(input.plan_history) ||
    !Array.isArray(input.run_health) ||
    !Array.isArray(input.pending_hitl) ||
    !Array.isArray(input.delivery) ||
    !Array.isArray(input.artifact_index)
  ) {
    throw contractError('local_project_blackboard_plan_contract_invalid');
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

function requireLocalTasks(input: unknown, workspaceId: string): readonly Record<string, unknown>[] {
  if (
    !isRecord(input) ||
    input.workspace_id !== workspaceId ||
    !Array.isArray(input.items) ||
    !Number.isSafeInteger(input.total) ||
    input.total !== input.items.length ||
    input.items.some((item) => !isRecord(item))
  ) {
    throw contractError('local_project_blackboard_tasks_contract_invalid');
  }
  return Object.freeze(input.items.map((item) => Object.freeze({ ...(item as Record<string, unknown>) })));
}

function requireObservedSurface(
  state: WorkspaceSurfaceState,
  scope: ProjectBlackboardScope,
  surface: WorkspaceCollaborationSurface,
  authority: ProjectBlackboardAuthority,
): void {
  if (
    state.workspace_id !== scope.workspaceId ||
    state.surface !== surface ||
    state.authority !== authority ||
    (state.status !== 'ready' && state.status !== 'empty')
  ) {
    throw contractError(`${authority}_project_blackboard_authority_invalid`);
  }
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: ProjectBlackboardScope,
  authority: ProjectBlackboardAuthority,
): ProjectBlackboardScope {
  if (
    scope.authority !== authority ||
    config.mode !== authority ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId ||
    scope.workspaceId !== config.workspaceId ||
    !validId(scope.tenantId) ||
    !validId(scope.projectId) ||
    !validId(scope.workspaceId)
  ) {
    throw contractError('project_blackboard_runtime_scope_mismatch');
  }
  return Object.freeze({ ...scope });
}

function requireRuntimeWorkspace(config: DesktopRuntimeConfig, workspaceId: string): void {
  if (!validId(workspaceId) || workspaceId !== config.workspaceId) {
    throw contractError('project_blackboard_runtime_scope_mismatch');
  }
}

function requireCredential(config: DesktopRuntimeConfig): void {
  if (!desktopApiCredential(config)) {
    throw contractError('project_blackboard_trusted_session_required');
  }
}

function unavailableState(
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

function validId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw contractError('local_project_blackboard_response_invalid_json');
  }
}

function errorMessage(status: number, payload: unknown): string {
  return isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()
    ? payload.detail
    : `HTTP ${status}`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}
