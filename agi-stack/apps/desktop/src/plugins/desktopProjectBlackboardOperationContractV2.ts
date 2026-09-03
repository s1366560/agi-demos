import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type {
  ProjectBlackboardScope,
  ProjectBlackboardSnapshot,
} from '../features/project-blackboard/projectBlackboardClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { WorkspaceCollaborationCapabilityScope } from '../features/workspace/workspaceCollaborationCapabilityContract';
import type {
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from '../features/workspace/workspaceCollaborationClient';
import type { DesktopWorkspaceSurfaceProjectionV2 } from './desktopProjectBlackboardTransportV2';

export type DesktopProjectBlackboardOperationInputV2 =
  | Readonly<{
      kind: 'probe-workspace-collaboration';
      config: DesktopRuntimeConfig;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'probe-project-blackboard';
      config: DesktopRuntimeConfig;
      scope: ProjectBlackboardScope;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'get-workspace-surface';
      config: DesktopRuntimeConfig;
      projection: DesktopWorkspaceSurfaceProjectionV2;
      workspaceId: string;
      surface: WorkspaceCollaborationSurface;
      cursor?: string | null;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'refetch-workspace-surface';
      config: DesktopRuntimeConfig;
      projection: DesktopWorkspaceSurfaceProjectionV2;
      workspaceId: string;
      surface: WorkspaceCollaborationSurface;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'mutate-workspace-surface';
      config: DesktopRuntimeConfig;
      projection: DesktopWorkspaceSurfaceProjectionV2;
      workspaceId: string;
      surface: WorkspaceCollaborationSurface;
      mutation: WorkspaceSurfaceMutation;
      signal?: AbortSignal;
    }>;

export type DesktopWorkspaceCollaborationCapabilityOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  signal?: AbortSignal;
}>;

export type DesktopProjectBlackboardProbeOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectBlackboardScope;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceSurfaceOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  projection: DesktopWorkspaceSurfaceProjectionV2;
  workspaceId: string;
  surface: WorkspaceCollaborationSurface;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceSurfaceReadOperationInputV2 =
  DesktopWorkspaceSurfaceOperationInputV2 & Readonly<{ cursor?: string | null }>;

export type DesktopWorkspaceSurfaceMutationOperationInputV2 =
  DesktopWorkspaceSurfaceOperationInputV2 & Readonly<{ mutation: WorkspaceSurfaceMutation }>;

export type PreparedProjectBlackboardOperationV2 = DesktopProjectBlackboardOperationInputV2;

export function prepareProjectBlackboardOperationV2(
  input: Extract<
    DesktopProjectBlackboardOperationInputV2,
    { kind: 'probe-workspace-collaboration' }
  >,
): Extract<PreparedProjectBlackboardOperationV2, { kind: 'probe-workspace-collaboration' }>;
export function prepareProjectBlackboardOperationV2(
  input: Extract<DesktopProjectBlackboardOperationInputV2, { kind: 'probe-project-blackboard' }>,
): Extract<PreparedProjectBlackboardOperationV2, { kind: 'probe-project-blackboard' }>;
export function prepareProjectBlackboardOperationV2(
  input: Extract<DesktopProjectBlackboardOperationInputV2, { kind: 'get-workspace-surface' }>,
): Extract<PreparedProjectBlackboardOperationV2, { kind: 'get-workspace-surface' }>;
export function prepareProjectBlackboardOperationV2(
  input: Extract<DesktopProjectBlackboardOperationInputV2, { kind: 'refetch-workspace-surface' }>,
): Extract<PreparedProjectBlackboardOperationV2, { kind: 'refetch-workspace-surface' }>;
export function prepareProjectBlackboardOperationV2(
  input: Extract<DesktopProjectBlackboardOperationInputV2, { kind: 'mutate-workspace-surface' }>,
): Extract<PreparedProjectBlackboardOperationV2, { kind: 'mutate-workspace-surface' }>;
export function prepareProjectBlackboardOperationV2(
  input: DesktopProjectBlackboardOperationInputV2,
): PreparedProjectBlackboardOperationV2;
export function prepareProjectBlackboardOperationV2(
  input: DesktopProjectBlackboardOperationInputV2,
): PreparedProjectBlackboardOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidInputV2();
  const allowedKeys = operationInputKeysV2(input.kind);
  if (allowedKeys === null || Object.keys(input).some((key) => !allowedKeys.has(key))) {
    throw invalidInputV2();
  }
  const config = cloneRuntimeConfigV2(input.config);
  const signal = cloneOptionalSignalV2(input.signal);
  const common = signal === undefined ? { config } : { config, signal };
  switch (input.kind) {
    case 'probe-workspace-collaboration':
      return Object.freeze({ kind: input.kind, ...common });
    case 'probe-project-blackboard':
      return Object.freeze({
        kind: input.kind,
        ...common,
        scope: cloneProjectBlackboardScopeV2(input.scope, config),
      });
    case 'get-workspace-surface':
      return Object.freeze({
        kind: input.kind,
        ...common,
        projection: cloneProjectionV2(input.projection),
        workspaceId: cloneWorkspaceIdV2(input.workspaceId, config),
        surface: cloneSurfaceV2(input.surface),
        cursor: cloneCursorV2(input.cursor),
      });
    case 'refetch-workspace-surface':
      return Object.freeze({
        kind: input.kind,
        ...common,
        projection: cloneProjectionV2(input.projection),
        workspaceId: cloneWorkspaceIdV2(input.workspaceId, config),
        surface: cloneSurfaceV2(input.surface),
      });
    case 'mutate-workspace-surface':
      return Object.freeze({
        kind: input.kind,
        ...common,
        projection: cloneProjectionV2(input.projection),
        workspaceId: cloneWorkspaceIdV2(input.workspaceId, config),
        surface: cloneSurfaceV2(input.surface),
        mutation: cloneMutationV2(input.mutation),
      });
    default:
      throw invalidInputV2();
  }
}

export function workspaceCollaborationScopeV2(
  config: DesktopRuntimeConfig,
): WorkspaceCollaborationCapabilityScope {
  return Object.freeze({
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
  });
}

export function requireCapabilityV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, [
      'allowed_actions',
      'authority_revision',
      'availability',
      'contract_version',
      'reason_code',
      'scope',
      'service_version',
    ]) ||
    !['available', 'degraded', 'unavailable', 'not_applicable'].includes(
      String(value.availability),
    ) ||
    (value.reason_code !== null && !canonicalStringV2(value.reason_code)) ||
    (value.service_version !== null && !canonicalStringV2(value.service_version)) ||
    (value.contract_version !== null && !canonicalStringV2(value.contract_version)) ||
    !Array.isArray(value.allowed_actions) ||
    value.allowed_actions.some((action) => !canonicalStringV2(action)) ||
    !isPlainRecordV2(value.scope) ||
    !hasExactKeysV2(value.scope, ['instance_id', 'project_id', 'tenant_id', 'workspace_id']) ||
    !validCapabilityScopeV2(value.scope, value.availability, config) ||
    (value.authority_revision !== null &&
      (!Number.isSafeInteger(value.authority_revision) || Number(value.authority_revision) < 0))
  ) {
    throw invalidServiceV2();
  }
  return deepFreezeV2(structuredClone(value)) as DesktopCapabilityAvailability;
}

export function requireProjectBlackboardSnapshotV2(
  value: unknown,
  scope: ProjectBlackboardScope,
): ProjectBlackboardSnapshot {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).sort().join(',') !==
      'allowedActions,authority,authorityRevision,availability,initialSurface,reasonCode,scope' ||
    value.authority !== scope.authority ||
    (value.availability !== 'available' && value.availability !== 'degraded') ||
    (value.reasonCode !== null && !canonicalStringV2(value.reasonCode)) ||
    !WORKSPACE_SURFACES_V2.has(value.initialSurface as WorkspaceCollaborationSurface) ||
    !Array.isArray(value.allowedActions) ||
    value.allowedActions.some((action) => !canonicalStringV2(action)) ||
    !isPlainRecordV2(value.scope) ||
    !hasExactKeysV2(value.scope, ['authority', 'projectId', 'tenantId', 'workspaceId']) ||
    value.scope.tenantId !== scope.tenantId ||
    value.scope.projectId !== scope.projectId ||
    value.scope.workspaceId !== scope.workspaceId ||
    value.scope.authority !== scope.authority ||
    (value.authorityRevision !== null &&
      (!Number.isSafeInteger(value.authorityRevision) || Number(value.authorityRevision) < 0))
  ) {
    throw invalidServiceV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectBlackboardSnapshot;
}

export function requireWorkspaceSurfaceStateV2(
  value: unknown,
  prepared: Extract<
    PreparedProjectBlackboardOperationV2,
    {
      kind: 'get-workspace-surface' | 'mutate-workspace-surface' | 'refetch-workspace-surface';
    }
  >,
): WorkspaceSurfaceState {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, [
      'authority',
      'cursor',
      'data',
      'reason_code',
      'revision',
      'status',
      'surface',
      'workspace_id',
    ]) ||
    value.workspace_id !== prepared.workspaceId ||
    value.surface !== prepared.surface ||
    value.authority !== prepared.config.mode ||
    !['loading', 'ready', 'empty', 'stale', 'error', 'unavailable'].includes(
      String(value.status),
    ) ||
    (value.revision !== null &&
      (!Number.isSafeInteger(value.revision) || Number(value.revision) < 0)) ||
    (value.cursor !== null && !canonicalStringV2(value.cursor)) ||
    (value.reason_code !== null && !canonicalStringV2(value.reason_code))
  ) {
    throw invalidServiceV2();
  }
  return deepFreezeV2(structuredClone(value)) as WorkspaceSurfaceState;
}

function cloneRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !canonicalStringV2(copy.apiBaseUrl) ||
    !canonicalStringV2(copy.tenantId) ||
    !canonicalStringV2(copy.projectId) ||
    !canonicalStringV2(copy.workspaceId)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze(copy);
}

function cloneProjectBlackboardScopeV2(
  scope: ProjectBlackboardScope,
  config: DesktopRuntimeConfig,
): ProjectBlackboardScope {
  if (
    !isPlainRecordV2(scope) ||
    scope.authority !== config.mode ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId ||
    scope.workspaceId !== config.workspaceId
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({ ...scope });
}

export function cloneProjectionV2(value: unknown): DesktopWorkspaceSurfaceProjectionV2 {
  if (value !== 'project-blackboard' && value !== 'workspace-collaboration') {
    throw invalidInputV2();
  }
  return value;
}

function cloneWorkspaceIdV2(value: unknown, config: DesktopRuntimeConfig): string {
  if (!canonicalStringV2(value) || value !== config.workspaceId) throw invalidInputV2();
  return value;
}

const WORKSPACE_SURFACES_V2 = new Set<WorkspaceCollaborationSurface>([
  'goals',
  'discussion',
  'status',
  'collaboration',
  'members',
  'genes',
  'files',
  'notes',
  'topology',
  'settings',
]);

function cloneSurfaceV2(value: unknown): WorkspaceCollaborationSurface {
  if (
    typeof value !== 'string' ||
    !WORKSPACE_SURFACES_V2.has(value as WorkspaceCollaborationSurface)
  ) {
    throw invalidInputV2();
  }
  return value as WorkspaceCollaborationSurface;
}

function cloneCursorV2(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return value;
  if (!canonicalStringV2(value) || value.length > 512) throw invalidInputV2();
  return value;
}

function cloneMutationV2(value: unknown): WorkspaceSurfaceMutation {
  if (
    !isPlainRecordV2(value) ||
    !canonicalStringV2(value.action) ||
    value.action.length > 128 ||
    !Number.isSafeInteger(value.expected_revision) ||
    Number(value.expected_revision) < 0 ||
    !canonicalStringV2(value.idempotency_key) ||
    value.idempotency_key.length < 8 ||
    value.idempotency_key.length > 128 ||
    !isPlainRecordV2(value.payload)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({
    action: value.action,
    expected_revision: Number(value.expected_revision),
    idempotency_key: value.idempotency_key,
    payload: freezeCloneV2(value.payload),
  });
}

function freezeCloneV2(value: Record<string, unknown>): Record<string, unknown> {
  let clone: unknown;
  try {
    clone = structuredClone(value);
  } catch {
    throw invalidInputV2();
  }
  if (!isPlainRecordV2(clone)) throw invalidInputV2();
  return deepFreezeV2(clone) as Record<string, unknown>;
}

function deepFreezeV2(value: unknown): unknown {
  if (Array.isArray(value)) {
    value.forEach(deepFreezeV2);
    return Object.freeze(value);
  }
  if (isPlainRecordV2(value)) {
    Object.values(value).forEach(deepFreezeV2);
    return Object.freeze(value);
  }
  return value;
}

function cloneOptionalSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw invalidInputV2();
  }
  return value;
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_blackboard_input_invalid',
    'desktop project blackboard operation input is invalid',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_blackboard_service_invalid',
    'desktop project blackboard authority service is invalid',
  );
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function operationInputKeysV2(kind: unknown): ReadonlySet<string> | null {
  switch (kind) {
    case 'probe-workspace-collaboration':
      return new Set(['kind', 'config', 'signal']);
    case 'probe-project-blackboard':
      return new Set(['kind', 'config', 'scope', 'signal']);
    case 'get-workspace-surface':
      return new Set([
        'kind',
        'config',
        'projection',
        'workspaceId',
        'surface',
        'cursor',
        'signal',
      ]);
    case 'refetch-workspace-surface':
      return new Set(['kind', 'config', 'projection', 'workspaceId', 'surface', 'signal']);
    case 'mutate-workspace-surface':
      return new Set([
        'kind',
        'config',
        'projection',
        'workspaceId',
        'surface',
        'mutation',
        'signal',
      ]);
    default:
      return null;
  }
}

function validCapabilityScopeV2(
  scope: Record<string, unknown>,
  availability: unknown,
  config: DesktopRuntimeConfig,
): boolean {
  if (
    scope.tenant_id === config.tenantId &&
    scope.project_id === config.projectId &&
    scope.workspace_id === config.workspaceId &&
    scope.instance_id === null
  ) {
    return true;
  }
  return (
    (availability === 'unavailable' || availability === 'not_applicable') &&
    scope.tenant_id === null &&
    scope.project_id === null &&
    scope.workspace_id === null &&
    scope.instance_id === null
  );
}

function hasExactKeysV2(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    keys.length === sortedExpected.length &&
    keys.every((key, index) => key === sortedExpected[index])
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
