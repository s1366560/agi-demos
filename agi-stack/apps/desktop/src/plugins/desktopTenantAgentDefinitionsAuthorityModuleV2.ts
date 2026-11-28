import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  DesktopRuntimeConfig,
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedExternalAcpAgent,
} from '../types';
import type { ManagementRouteClient } from '../features/settings-routes/managementRouteTypes';
import { managementRouteObservation } from '../features/settings-routes/managementRouteTypes';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  createDesktopTenantAgentDefinitionsHttpProjectionV2,
} from './desktopTenantAgentDefinitionsHttpProjectionV2';
import {
  freezeDesktopTenantAgentDefinitionsConfigV2,
  prepareDesktopTenantAgentDefinitionsCreateV2,
  prepareDesktopTenantAgentDefinitionsDeleteV2,
  prepareDesktopTenantAgentDefinitionsEnabledV2,
  prepareDesktopTenantAgentDefinitionsExternalV2,
  prepareDesktopTenantAgentDefinitionsLoadV2,
  prepareDesktopTenantAgentDefinitionsUpdateV2,
  requireDesktopTenantAgentDefinitionDeleteV2,
  requireDesktopTenantAgentDefinitionExternalAcpAgentsV2,
  requireDesktopTenantAgentDefinitionsV2,
  requireDesktopTenantAgentDefinitionV2,
  type DesktopTenantAgentDefinitionsAuthorityV2,
  type DesktopTenantAgentDefinitionsEnabledInputV2,
  type DesktopTenantAgentDefinitionsItemInputV2,
  type DesktopTenantAgentDefinitionsLoadInputV2,
  type DesktopTenantAgentDefinitionsMutationInputV2,
  type DesktopTenantAgentDefinitionsScopeV2,
  type DesktopTenantAgentDefinitionsUpdateInputV2,
} from './desktopTenantAgentDefinitionsOperationContractV2';

export const DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-agent-definitions-authority';
export const DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-agent-definitions-authority';
export const DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantAgentDefinitionsAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopTenantAgentDefinitionsScopeV2,
  ): DesktopTenantAgentDefinitionsAuthorityV2;
}

export interface DesktopTenantAgentDefinitionsOperationsV2 {
  loadTenantAgentDefinitions(
    input: DesktopTenantAgentDefinitionsLoadInputV2,
  ): Promise<readonly ManagedAgentDefinition[]>;
  listTenantAgentDefinitionExternalAcpAgents(
    input: DesktopTenantAgentDefinitionsLoadInputV2,
  ): Promise<readonly ManagedExternalAcpAgent[]>;
  createTenantAgentDefinition(
    input: DesktopTenantAgentDefinitionsMutationInputV2,
  ): Promise<ManagedAgentDefinition>;
  updateTenantAgentDefinition(
    input: DesktopTenantAgentDefinitionsUpdateInputV2,
  ): Promise<ManagedAgentDefinition>;
  setTenantAgentDefinitionEnabled(
    input: DesktopTenantAgentDefinitionsEnabledInputV2,
  ): Promise<ManagedAgentDefinition>;
  deleteTenantAgentDefinition(
    input: DesktopTenantAgentDefinitionsItemInputV2,
  ): Promise<Readonly<{ deleted: true; id: string }>>;
}

export interface DesktopTenantAgentDefinitionsClientV2 {
  listManagedAgents(signal?: AbortSignal): Promise<ManagedAgentDefinition[]>;
  listManagedExternalAcpAgents(signal?: AbortSignal): Promise<ManagedExternalAcpAgent[]>;
  createManagedAgentDefinition(
    input: ManagedAgentDefinitionMutation,
    signal?: AbortSignal,
  ): Promise<ManagedAgentDefinition>;
  updateManagedAgentDefinition(
    definitionId: string,
    input: ManagedAgentDefinitionMutation,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedAgentDefinition>;
  setManagedAgentEnabled(
    definitionId: string,
    enabled: boolean,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedAgentDefinition>;
  deleteManagedAgentDefinition(
    definitionId: string,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<Readonly<{ deleted: true; id: string }>>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantAgentDefinitionsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantAgentDefinitionsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantAgentDefinitionsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_definitions_authority_config_invalid',
      'desktop tenant Agent definitions authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantAgentDefinitionsHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopTenantAgentDefinitionsAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantAgentDefinitionsAuthorityV2,
  });

export function createDesktopTenantAgentDefinitionsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantAgentDefinitionsOperationsV2 {
  const operations: DesktopTenantAgentDefinitionsOperationsV2 = {
    loadTenantAgentDefinitions(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantAgentDefinitionsV2(
          await authority.load(prepared.scope, prepared.signal),
          prepared.scope,
        ),
      );
    },
    listTenantAgentDefinitionExternalAcpAgents(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsExternalV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantAgentDefinitionExternalAcpAgentsV2(
          await authority.listExternal(prepared.scope, prepared.signal),
        ),
      );
    },
    createTenantAgentDefinition(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantAgentDefinitionV2(
          await authority.create(prepared.scope, prepared.input, prepared.signal),
          prepared.scope,
        ),
      );
    },
    updateTenantAgentDefinition(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantAgentDefinitionV2(
          await authority.update(
            prepared.scope,
            prepared.definitionId,
            prepared.input,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
        ),
      );
    },
    setTenantAgentDefinitionEnabled(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsEnabledV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantAgentDefinitionV2(
          await authority.setEnabled(
            prepared.scope,
            prepared.definitionId,
            prepared.enabled,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
        ),
      );
    },
    deleteTenantAgentDefinition(input) {
      const prepared = prepareDesktopTenantAgentDefinitionsDeleteV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantAgentDefinitionDeleteV2(
          await authority.delete(
            prepared.scope,
            prepared.definitionId,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.definitionId,
        ),
      );
    },
  };
  return Object.freeze(operations);
}

export function createDesktopTenantAgentDefinitionsClientV2(
  operations: DesktopTenantAgentDefinitionsOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantAgentDefinitionsClientV2 {
  const frozen = freezeDesktopTenantAgentDefinitionsConfigV2(config);
  const currentScope = () => scopeFor(frozen, frozen.projectId || null);
  const client: DesktopTenantAgentDefinitionsClientV2 = {
    listManagedAgents: async (signal) => [
      ...(await operations.loadTenantAgentDefinitions({
        config: frozen,
        scope: currentScope(),
        ...(signal === undefined ? {} : { signal }),
      })),
    ],
    listManagedExternalAcpAgents: async (signal) => [
      ...(await operations.listTenantAgentDefinitionExternalAcpAgents({
        config: frozen,
        scope: scopeFor(frozen, null),
        ...(signal === undefined ? {} : { signal }),
      })),
    ],
    createManagedAgentDefinition: (input, signal) =>
      operations.createTenantAgentDefinition({
        config: frozen,
        scope: scopeFor(frozen, input.project_id),
        input,
        ...(signal === undefined ? {} : { signal }),
      }),
    updateManagedAgentDefinition: (definitionId, input, expectedRevision, signal) =>
      operations.updateTenantAgentDefinition({
        config: frozen,
        scope: scopeFor(frozen, input.project_id),
        definitionId,
        input,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      }),
    setManagedAgentEnabled: (definitionId, enabled, expectedRevision, signal) =>
      operations.setTenantAgentDefinitionEnabled({
        config: frozen,
        scope: currentScope(),
        definitionId,
        enabled,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      }),
    deleteManagedAgentDefinition: (definitionId, expectedRevision, signal) =>
      operations.deleteTenantAgentDefinition({
        config: frozen,
        scope: currentScope(),
        definitionId,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      }),
  };
  return Object.freeze(client);
}

export function createDesktopTenantAgentDefinitionsRouteClientV2(
  operations: DesktopTenantAgentDefinitionsOperationsV2,
  config: DesktopRuntimeConfig,
): ManagementRouteClient {
  const frozen = freezeDesktopTenantAgentDefinitionsConfigV2(config);
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const definitions = await operations.loadTenantAgentDefinitions({
        config: frozen,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
      return managementRouteObservation(scope, definitions.length);
    },
  };
  return Object.freeze(client);
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantAgentDefinitionsLoadInputV2,
  operation: (authority: DesktopTenantAgentDefinitionsAuthorityV2) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantAgentDefinitionsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const leaseScope = prepared.scope.projectId === null
    ? Object.freeze({ kind: 'tenant' as const, tenant_id: prepared.scope.tenantId })
    : Object.freeze({
        kind: 'project' as const,
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantAgentDefinitionsAuthorityServiceV2>({
      service: DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_VERSION_V2,
      scope: leaseScope,
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantAgentDefinitionsAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      assertActive(active);
      const service = requireService(candidate);
      const raw = service.bindOperation(prepared.config, prepared.scope);
      const result = await operation(wrapAuthority(raw, () => active));
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}

function requireService(value: unknown): DesktopTenantAgentDefinitionsAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopTenantAgentDefinitionsAuthorityServiceV2;
}

function wrapAuthority(
  raw: unknown,
  active: () => boolean,
): DesktopTenantAgentDefinitionsAuthorityV2 {
  const methods = ['load', 'listExternal', 'create', 'update', 'setEnabled', 'delete'] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as DesktopTenantAgentDefinitionsAuthorityV2;
  const wrapped: DesktopTenantAgentDefinitionsAuthorityV2 = {
    load: (scope, signal) => invoke(active, authority.load, [scope, signal]),
    listExternal: (scope, signal) => invoke(active, authority.listExternal, [scope, signal]),
    create: (scope, input, signal) => invoke(active, authority.create, [scope, input, signal]),
    update: (scope, id, input, revision, signal) =>
      invoke(active, authority.update, [scope, id, input, revision, signal]),
    setEnabled: (scope, id, enabled, revision, signal) =>
      invoke(active, authority.setEnabled, [scope, id, enabled, revision, signal]),
    delete: (scope, id, revision, signal) =>
      invoke(active, authority.delete, [scope, id, revision, signal]),
  };
  return Object.freeze(wrapped);
}

function invoke<TArgs extends readonly unknown[], TResult>(
  active: () => boolean,
  operation: (...args: TArgs) => TResult,
  args: TArgs,
): TResult {
  assertActive(active());
  return operation(...args);
}

function scopeFor(
  config: DesktopRuntimeConfig,
  projectId: string | null,
): DesktopTenantAgentDefinitionsScopeV2 {
  return Object.freeze({
    authority: config.mode,
    tenantId: config.tenantId,
    projectId,
  });
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_definitions_operation_released',
      'desktop tenant Agent definitions operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_agent_definitions_service_invalid',
    'desktop tenant Agent definitions authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_AGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_agent_definitions_authority_catalog_missing',
      'desktop tenant Agent definitions authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
