import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig, ManagedSubAgent, ManagedSubAgentMutation } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantSubAgentDefinitionsHttpProjectionV2 } from './desktopTenantSubAgentDefinitionsHttpProjectionV2';
import {
  freezeDesktopTenantSubAgentDefinitionsConfigV2,
  prepareDesktopTenantSubAgentDefinitionsCreateV2,
  prepareDesktopTenantSubAgentDefinitionsDeleteV2,
  prepareDesktopTenantSubAgentDefinitionsEnabledV2,
  prepareDesktopTenantSubAgentDefinitionsImportV2,
  prepareDesktopTenantSubAgentDefinitionsLoadV2,
  prepareDesktopTenantSubAgentDefinitionsUpdateV2,
  requireDesktopTenantSubAgentDefinitionDeleteV2,
  requireDesktopTenantSubAgentDefinitionsV2,
  requireDesktopTenantSubAgentDefinitionV2,
  type DesktopTenantSubAgentDefinitionsAuthorityV2,
  type DesktopTenantSubAgentDefinitionsImportInputV2,
  type DesktopTenantSubAgentDefinitionsEnabledInputV2,
  type DesktopTenantSubAgentDefinitionsItemInputV2,
  type DesktopTenantSubAgentDefinitionsLoadInputV2,
  type DesktopTenantSubAgentDefinitionsMutationInputV2,
  type DesktopTenantSubAgentDefinitionsScopeV2,
  type DesktopTenantSubAgentDefinitionsUpdateInputV2,
} from './desktopTenantSubAgentDefinitionsOperationContractV2';

export const DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-subagent-definitions-authority';
export const DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-subagent-definitions-authority';
export const DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantSubAgentDefinitionsAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
  ): DesktopTenantSubAgentDefinitionsAuthorityV2;
}

export interface DesktopTenantSubAgentDefinitionsOperationsV2 {
  loadTenantSubAgentDefinitions(
    input: DesktopTenantSubAgentDefinitionsLoadInputV2,
  ): Promise<readonly ManagedSubAgent[]>;
  importTenantFilesystemSubAgentDefinition(
    input: DesktopTenantSubAgentDefinitionsImportInputV2,
  ): Promise<ManagedSubAgent>;
  createTenantSubAgentDefinition(
    input: DesktopTenantSubAgentDefinitionsMutationInputV2,
  ): Promise<ManagedSubAgent>;
  updateTenantSubAgentDefinition(
    input: DesktopTenantSubAgentDefinitionsUpdateInputV2,
  ): Promise<ManagedSubAgent>;
  setTenantSubAgentDefinitionEnabled(
    input: DesktopTenantSubAgentDefinitionsEnabledInputV2,
  ): Promise<ManagedSubAgent>;
  deleteTenantSubAgentDefinition(input: DesktopTenantSubAgentDefinitionsItemInputV2): Promise<void>;
}

export interface DesktopTenantSubAgentDefinitionsClientV2 {
  listManagedSubAgents(signal?: AbortSignal): Promise<ManagedSubAgent[]>;
  importManagedFilesystemSubAgent(
    name: string,
    projectId?: string,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  createManagedSubAgent(
    input: ManagedSubAgentMutation,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  updateManagedSubAgent(
    definitionId: string,
    input: ManagedSubAgentMutation,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  setManagedSubAgentEnabled(
    definitionId: string,
    enabled: boolean,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  deleteManagedSubAgent(
    definitionId: string,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantSubAgentDefinitionsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantSubAgentDefinitionsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantSubAgentDefinitionsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_subagent_definitions_authority_config_invalid',
      'desktop tenant SubAgent definitions authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantSubAgentDefinitionsHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopTenantSubAgentDefinitionsAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantSubAgentDefinitionsAuthorityV2,
  });

export function createDesktopTenantSubAgentDefinitionsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantSubAgentDefinitionsOperationsV2 {
  const operations: DesktopTenantSubAgentDefinitionsOperationsV2 = {
    loadTenantSubAgentDefinitions(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSubAgentDefinitionsV2(
          await authority.load(prepared.scope, prepared.signal),
          prepared.scope,
        ),
      );
    },
    importTenantFilesystemSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsImportV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSubAgentDefinitionV2(
          await authority.importFilesystem(prepared.scope, prepared.name, prepared.signal),
          prepared.scope,
        ),
      );
    },
    createTenantSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSubAgentDefinitionV2(
          await authority.create(prepared.scope, prepared.input, prepared.signal),
          prepared.scope,
        ),
      );
    },
    updateTenantSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSubAgentDefinitionV2(
          await authority.update(
            prepared.scope,
            prepared.definitionId,
            prepared.input,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
          prepared.definitionId,
        ),
      );
    },
    setTenantSubAgentDefinitionEnabled(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsEnabledV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSubAgentDefinitionV2(
          await authority.setEnabled(
            prepared.scope,
            prepared.definitionId,
            prepared.enabled,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
          prepared.definitionId,
        ),
      );
    },
    deleteTenantSubAgentDefinition(input) {
      const prepared = prepareDesktopTenantSubAgentDefinitionsDeleteV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSubAgentDefinitionDeleteV2(
          await authority.delete(
            prepared.scope,
            prepared.definitionId,
            prepared.expectedRevision,
            prepared.signal,
          ),
        ),
      );
    },
  };
  return Object.freeze(operations);
}

export function createDesktopTenantSubAgentDefinitionsClientV2(
  operations: DesktopTenantSubAgentDefinitionsOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantSubAgentDefinitionsClientV2 {
  const frozen = freezeDesktopTenantSubAgentDefinitionsConfigV2(config);
  const currentScope = () =>
    scopeFor(frozen, frozen.mode === 'cloud' ? null : frozen.projectId || null);
  const client: DesktopTenantSubAgentDefinitionsClientV2 = {
    listManagedSubAgents: async (signal) => [
      ...(await operations.loadTenantSubAgentDefinitions({
        config: frozen,
        scope: scopeFor(frozen, null),
        ...(signal === undefined ? {} : { signal }),
      })),
    ],
    importManagedFilesystemSubAgent: (name, projectId, signal) =>
      operations.importTenantFilesystemSubAgentDefinition({
        config: frozen,
        scope: scopeFor(frozen, projectId ?? null),
        name,
        ...(signal === undefined ? {} : { signal }),
      }),
    createManagedSubAgent: (input, signal) =>
      operations.createTenantSubAgentDefinition({
        config: frozen,
        scope: scopeFor(frozen, input.project_id),
        input,
        ...(signal === undefined ? {} : { signal }),
      }),
    updateManagedSubAgent: (definitionId, input, expectedRevision, signal) =>
      operations.updateTenantSubAgentDefinition({
        config: frozen,
        scope: scopeFor(frozen, input.project_id),
        definitionId,
        input,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      }),
    setManagedSubAgentEnabled: (definitionId, enabled, expectedRevision, signal) =>
      operations.setTenantSubAgentDefinitionEnabled({
        config: frozen,
        scope: currentScope(),
        definitionId,
        enabled,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      }),
    deleteManagedSubAgent: (definitionId, expectedRevision, signal) =>
      operations.deleteTenantSubAgentDefinition({
        config: frozen,
        scope: currentScope(),
        definitionId,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      }),
  };
  return Object.freeze(client);
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantSubAgentDefinitionsLoadInputV2,
  operation: (authority: DesktopTenantSubAgentDefinitionsAuthorityV2) => Promise<T>,
): Promise<T> {
  if (prepared.signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantSubAgentDefinitionsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const leaseScope =
    prepared.scope.projectId === null
      ? Object.freeze({
          kind: 'tenant' as const,
          tenant_id: prepared.scope.tenantId,
        })
      : Object.freeze({
          kind: 'project' as const,
          tenant_id: prepared.scope.tenantId,
          project_id: prepared.scope.projectId,
        });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantSubAgentDefinitionsAuthorityServiceV2>({
      service: DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_VERSION_V2,
      scope: leaseScope,
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantSubAgentDefinitionsAuthorityUnavailableErrorV2(admission);
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

function requireService(value: unknown): DesktopTenantSubAgentDefinitionsAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopTenantSubAgentDefinitionsAuthorityServiceV2;
}

function wrapAuthority(
  raw: unknown,
  active: () => boolean,
): DesktopTenantSubAgentDefinitionsAuthorityV2 {
  const methods = ['load', 'importFilesystem', 'create', 'update', 'setEnabled', 'delete'] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as DesktopTenantSubAgentDefinitionsAuthorityV2;
  const wrapped: DesktopTenantSubAgentDefinitionsAuthorityV2 = {
    load: (scope, signal) => invoke(active, authority.load, [scope, signal]),
    importFilesystem: (scope, name, signal) =>
      invoke(active, authority.importFilesystem, [scope, name, signal]),
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
): DesktopTenantSubAgentDefinitionsScopeV2 {
  return Object.freeze({
    authority: config.mode,
    tenantId: config.tenantId,
    projectId,
  });
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_subagent_definitions_operation_released',
      'desktop tenant SubAgent definitions operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_subagent_definitions_service_invalid',
    'desktop tenant SubAgent definitions authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_SUBAGENT_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_subagent_definitions_authority_catalog_missing',
      'desktop tenant SubAgent definitions authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
