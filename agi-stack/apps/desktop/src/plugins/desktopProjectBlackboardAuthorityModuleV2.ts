import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type {
  ProjectBlackboardScope,
  ProjectBlackboardSnapshot,
} from '../features/project-blackboard/projectBlackboardClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from '../features/workspace/workspaceCollaborationClient';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  createDesktopProjectBlackboardAuthorityV2,
  type DesktopProjectBlackboardAuthorityV2,
  type DesktopWorkspaceSurfaceProjectionV2,
} from './desktopProjectBlackboardTransportV2';
import {
  cloneProjectionV2,
  prepareProjectBlackboardOperationV2,
  requireCapabilityV2,
  requireProjectBlackboardSnapshotV2,
  requireWorkspaceSurfaceStateV2,
  workspaceCollaborationScopeV2,
  type DesktopProjectBlackboardOperationInputV2,
  type DesktopProjectBlackboardProbeOperationInputV2,
  type DesktopWorkspaceCollaborationCapabilityOperationInputV2,
  type DesktopWorkspaceSurfaceMutationOperationInputV2,
  type DesktopWorkspaceSurfaceOperationInputV2,
  type DesktopWorkspaceSurfaceReadOperationInputV2,
  type PreparedProjectBlackboardOperationV2,
} from './desktopProjectBlackboardOperationContractV2';

export type {
  DesktopProjectBlackboardOperationInputV2,
  DesktopProjectBlackboardProbeOperationInputV2,
  DesktopWorkspaceCollaborationCapabilityOperationInputV2,
  DesktopWorkspaceSurfaceMutationOperationInputV2,
  DesktopWorkspaceSurfaceReadOperationInputV2,
} from './desktopProjectBlackboardOperationContractV2';

export const DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-blackboard-authority';
export const DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-blackboard-authority';
export const DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectBlackboardAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopProjectBlackboardAuthorityV2;
}

export interface DesktopProjectBlackboardOperationsV2 {
  readonly probeWorkspaceCollaborationCapability: (
    input: DesktopWorkspaceCollaborationCapabilityOperationInputV2,
  ) => Promise<DesktopCapabilityAvailability>;
  readonly probeProjectBlackboard: (
    input: DesktopProjectBlackboardProbeOperationInputV2,
  ) => Promise<ProjectBlackboardSnapshot>;
  readonly getWorkspaceSurface: (
    input: DesktopWorkspaceSurfaceReadOperationInputV2,
  ) => Promise<WorkspaceSurfaceState>;
  readonly refetchWorkspaceSurface: (
    input: DesktopWorkspaceSurfaceOperationInputV2,
  ) => Promise<WorkspaceSurfaceState>;
  readonly mutateWorkspaceSurface: (
    input: DesktopWorkspaceSurfaceMutationOperationInputV2,
  ) => Promise<WorkspaceSurfaceState>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;

export class DesktopProjectBlackboardAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: string;
  readonly runtimeCode: string | undefined;

  constructor(
    rejection:
      | ServiceAdmissionRejectionV2
      | GenerationActionsUnavailableV2
      | Readonly<{ reasonCode: string; runtimeCode?: string }>,
  ) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectBlackboardAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectBlackboardAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (!hasExactKeysV2(config, ['strategy']) || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_blackboard_authority_config_invalid',
      'desktop project blackboard authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectBlackboardAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectBlackboardAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectBlackboardAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectBlackboardAuthorityV2,
});

export function createDesktopProjectBlackboardOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectBlackboardOperationsV2 {
  const operations: DesktopProjectBlackboardOperationsV2 = {
    probeWorkspaceCollaborationCapability(input) {
      const prepared = prepareProjectBlackboardOperationV2({
        kind: 'probe-workspace-collaboration',
        ...input,
      });
      return runDesktopProjectBlackboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority
            .probeWorkspaceCollaborationCapability(
              workspaceCollaborationScopeV2(prepared.config),
              prepared.signal,
            )
            .then((capability) => requireCapabilityV2(capability, prepared.config)),
      );
    },
    probeProjectBlackboard(input) {
      const prepared = prepareProjectBlackboardOperationV2({
        kind: 'probe-project-blackboard',
        ...input,
      });
      return runDesktopProjectBlackboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority
            .probeProjectBlackboard(prepared.scope, prepared.signal)
            .then((snapshot) => requireProjectBlackboardSnapshotV2(snapshot, prepared.scope)),
      );
    },
    getWorkspaceSurface(input) {
      const prepared = prepareProjectBlackboardOperationV2({
        kind: 'get-workspace-surface',
        ...input,
      });
      return runDesktopProjectBlackboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority
            .getWorkspaceSurface(
              prepared.projection,
              prepared.workspaceId,
              prepared.surface,
              prepared.cursor,
              prepared.signal,
            )
            .then((state) => requireWorkspaceSurfaceStateV2(state, prepared)),
      );
    },
    refetchWorkspaceSurface(input) {
      const prepared = prepareProjectBlackboardOperationV2({
        kind: 'refetch-workspace-surface',
        ...input,
      });
      return runDesktopProjectBlackboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority
            .refetchWorkspaceSurface(
              prepared.projection,
              prepared.workspaceId,
              prepared.surface,
              prepared.signal,
            )
            .then((state) => requireWorkspaceSurfaceStateV2(state, prepared)),
      );
    },
    mutateWorkspaceSurface(input) {
      const prepared = prepareProjectBlackboardOperationV2({
        kind: 'mutate-workspace-surface',
        ...input,
      });
      return runDesktopProjectBlackboardAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority
            .mutateWorkspaceSurface(
              prepared.projection,
              prepared.workspaceId,
              prepared.surface,
              prepared.mutation,
              prepared.signal,
            )
            .then((state) => requireWorkspaceSurfaceStateV2(state, prepared)),
      );
    },
  };
  return Object.freeze(operations);
}

export function createDesktopWorkspaceCollaborationClientV2(
  operations: Pick<
    DesktopProjectBlackboardOperationsV2,
    'getWorkspaceSurface' | 'mutateWorkspaceSurface' | 'refetchWorkspaceSurface'
  >,
  resolveConfig: () => DesktopRuntimeConfig,
  projection: DesktopWorkspaceSurfaceProjectionV2,
): WorkspaceCollaborationClient {
  const operationProjection = cloneProjectionV2(projection);
  return Object.freeze({
    getSurface: (workspaceId, surface, cursor, signal) =>
      operations.getWorkspaceSurface({
        config: resolveConfig(),
        projection: operationProjection,
        workspaceId,
        surface,
        cursor,
        signal,
      }),
    refetchAuthority: (workspaceId, surface, signal) =>
      operations.refetchWorkspaceSurface({
        config: resolveConfig(),
        projection: operationProjection,
        workspaceId,
        surface,
        signal,
      }),
    mutateSurface: (workspaceId, surface, mutation, signal) =>
      operations.mutateWorkspaceSurface({
        config: resolveConfig(),
        projection: operationProjection,
        workspaceId,
        surface,
        mutation,
        signal,
      }),
  });
}

export function withDesktopProjectBlackboardAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectBlackboardOperationInputV2,
  operation: (
    authority: DesktopProjectBlackboardAuthorityV2,
    prepared: PreparedProjectBlackboardOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectBlackboardAuthorityOperationV2(
    actions,
    prepareProjectBlackboardOperationV2(input),
    operation,
  );
}

async function runDesktopProjectBlackboardAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedProjectBlackboardOperationV2,
  operation: (
    authority: DesktopProjectBlackboardAuthorityV2,
    prepared: PreparedProjectBlackboardOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectBlackboardAuthorityServiceV2>({
      service: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectBlackboardAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectBlackboardServiceV2(candidate);
      const authority = requireProjectBlackboardAuthorityV2(service.bindOperation(prepared.config));
      return operation(
        createRevocableProjectBlackboardAuthorityV2(authority, () => operationActive),
        prepared,
      );
    });
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    operationActive = false;
    try {
      await admission.release();
    } catch (releaseError) {
      if (!operationFailed) throw releaseError;
    }
  }
}

function createRevocableProjectBlackboardAuthorityV2(
  authority: DesktopProjectBlackboardAuthorityV2,
  isOperationActive: () => boolean,
): DesktopProjectBlackboardAuthorityV2 {
  const requireActive = (): void => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_project_blackboard_operation_released',
        'desktop project blackboard operation has been released',
      );
    }
  };
  const revocable: DesktopProjectBlackboardAuthorityV2 = {
    probeWorkspaceCollaborationCapability(scope, signal) {
      requireActive();
      return authority.probeWorkspaceCollaborationCapability(scope, signal);
    },
    probeProjectBlackboard(scope, signal) {
      requireActive();
      return authority.probeProjectBlackboard(scope, signal);
    },
    getWorkspaceSurface(projection, workspaceId, surface, cursor, signal) {
      requireActive();
      return authority.getWorkspaceSurface(projection, workspaceId, surface, cursor, signal);
    },
    refetchWorkspaceSurface(projection, workspaceId, surface, signal) {
      requireActive();
      return authority.refetchWorkspaceSurface(projection, workspaceId, surface, signal);
    },
    mutateWorkspaceSurface(projection, workspaceId, surface, mutation, signal) {
      requireActive();
      return authority.mutateWorkspaceSurface(projection, workspaceId, surface, mutation, signal);
    },
  };
  return Object.freeze(revocable);
}

function requireProjectBlackboardServiceV2(
  value: unknown,
): DesktopProjectBlackboardAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectBlackboardAuthorityServiceV2;
}

function requireProjectBlackboardAuthorityV2(value: unknown): DesktopProjectBlackboardAuthorityV2 {
  const methods = new Set([
    'getWorkspaceSurface',
    'mutateWorkspaceSurface',
    'probeProjectBlackboard',
    'probeWorkspaceCollaborationCapability',
    'refetchWorkspaceSurface',
  ]);
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => !methods.has(key)) ||
    [...methods].some((key) => typeof value[key] !== 'function')
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectBlackboardAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectBlackboardAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
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

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_BLACKBOARD_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_blackboard_authority_catalog_missing',
      'desktop project blackboard authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
