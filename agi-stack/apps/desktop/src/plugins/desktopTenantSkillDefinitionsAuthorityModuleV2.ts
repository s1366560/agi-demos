import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type {
  DesktopRuntimeConfig,
  ManagedSkill,
  ManagedSkillContent,
  ManagedSkillCreateMutation,
  ManagedSkillMutation,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantSkillDefinitionsHttpProjectionV2 } from './desktopTenantSkillDefinitionsHttpProjectionV2';
import {
  freezeDesktopTenantSkillDefinitionsConfigV2,
  prepareDesktopTenantSkillDefinitionsLoadV2,
  prepareDesktopTenantSkillDefinitionsItemV2,
  prepareDesktopTenantSkillDefinitionsCreateV2,
  prepareDesktopTenantSkillDefinitionsUpdateV2,
  prepareDesktopTenantSkillDefinitionsContentV2,
  prepareDesktopTenantSkillDefinitionsStatusV2,
  requireDesktopTenantSkillDefinitionsV2,
  requireDesktopTenantSkillDefinitionV2,
  requireDesktopTenantSkillContentV2,
  requireDesktopTenantSkillDeletionV2,
  type DesktopTenantSkillDefinitionsAuthorityV2,
  type DesktopTenantSkillDefinitionsScopeV2,
  type DesktopTenantSkillDefinitionsInputV2,
  type DesktopTenantSkillDefinitionsItemInputV2,
  type DesktopTenantSkillDefinitionsCreateInputV2,
  type DesktopTenantSkillDefinitionsUpdateInputV2,
  type DesktopTenantSkillDefinitionsContentInputV2,
  type DesktopTenantSkillDefinitionsStatusInputV2,
  type DesktopTenantSkillDefinitionsStatusV2,
} from './desktopTenantSkillDefinitionsOperationContractV2';

export const DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-skill-definitions-authority';
export const DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-skill-definitions-authority';
export const DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopTenantSkillDefinitionsAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopTenantSkillDefinitionsScopeV2,
  ): DesktopTenantSkillDefinitionsAuthorityV2;
}
export interface DesktopTenantSkillDefinitionsOperationsV2 {
  loadTenantSkillDefinitions(
    input: DesktopTenantSkillDefinitionsInputV2,
  ): Promise<readonly ManagedSkill[]>;
  createTenantSkillDefinition(
    input: DesktopTenantSkillDefinitionsCreateInputV2,
  ): Promise<ManagedSkill>;
  getTenantSkillContent(
    input: DesktopTenantSkillDefinitionsItemInputV2,
  ): Promise<ManagedSkillContent>;
  updateTenantSkillDefinition(
    input: DesktopTenantSkillDefinitionsUpdateInputV2,
  ): Promise<ManagedSkill>;
  updateTenantSkillContent(
    input: DesktopTenantSkillDefinitionsContentInputV2,
  ): Promise<ManagedSkill>;
  setTenantSkillStatus(input: DesktopTenantSkillDefinitionsStatusInputV2): Promise<ManagedSkill>;
  deleteTenantSkillDefinition(input: DesktopTenantSkillDefinitionsItemInputV2): Promise<void>;
}
export interface DesktopTenantSkillDefinitionsClientV2 {
  listManagedSkills(signal?: AbortSignal): Promise<ManagedSkill[]>;
  createManagedSkill(
    input: ManagedSkillCreateMutation,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  getManagedSkillContent(skillId: string, signal?: AbortSignal): Promise<ManagedSkillContent>;
  updateManagedSkill(
    skillId: string,
    input: Omit<ManagedSkillMutation, 'full_content'>,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  updateManagedSkillContent(
    skillId: string,
    fullContent: string,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  setManagedSkillStatus(
    skillId: string,
    status: DesktopTenantSkillDefinitionsStatusV2,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  deleteManagedSkill(
    skillId: string,
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
export class DesktopTenantSkillDefinitionsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantSkillDefinitionsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}
export function applyDesktopTenantSkillDefinitionsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_tenant_skill_definitions_authority_config_invalid',
      'desktop tenant skill definitions requires desktop-api-fetch strategy',
    );
  context.provide(
    DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantSkillDefinitionsHttpProjectionV2(configValue);
      },
    }),
  );
}
export const desktopTenantSkillDefinitionsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze(
  {
    moduleRef: DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantSkillDefinitionsAuthorityV2,
  },
);
export function createDesktopTenantSkillDefinitionsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantSkillDefinitionsOperationsV2 {
  const operations: DesktopTenantSkillDefinitionsOperationsV2 = {
    loadTenantSkillDefinitions(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillDefinitionsV2(
          await authority.load(prepared.scope, prepared.signal),
          prepared.scope,
        ),
      );
    },
    createTenantSkillDefinition(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillDefinitionV2(
          await authority.create(prepared.scope, prepared.input, prepared.signal),
          prepared.scope,
          undefined,
          prepared.input.scope,
        ),
      );
    },
    getTenantSkillContent(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsItemV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillContentV2(
          await authority.getContent(prepared.scope, prepared.skillId, prepared.signal),
          prepared.skillId,
        ),
      );
    },
    updateTenantSkillDefinition(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillDefinitionV2(
          await authority.update(
            prepared.scope,
            prepared.skillId,
            prepared.input,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
          prepared.skillId,
        ),
      );
    },
    updateTenantSkillContent(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsContentV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillDefinitionV2(
          await authority.updateContent(
            prepared.scope,
            prepared.skillId,
            prepared.fullContent,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
          prepared.skillId,
        ),
      );
    },
    setTenantSkillStatus(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsStatusV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillDefinitionV2(
          await authority.setStatus(
            prepared.scope,
            prepared.skillId,
            prepared.status,
            prepared.expectedRevision,
            prepared.signal,
          ),
          prepared.scope,
          prepared.skillId,
        ),
      );
    },
    deleteTenantSkillDefinition(input) {
      const prepared = prepareDesktopTenantSkillDefinitionsItemV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantSkillDeletionV2(
          await authority.delete(
            prepared.scope,
            prepared.skillId,
            prepared.expectedRevision,
            prepared.signal,
          ),
        ),
      );
    },
  };
  return Object.freeze(operations);
}
export function createDesktopTenantSkillDefinitionsClientV2(
  operations: DesktopTenantSkillDefinitionsOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantSkillDefinitionsClientV2 {
  const frozen = freezeDesktopTenantSkillDefinitionsConfigV2(config);
  const common = (signal?: AbortSignal) => ({
    config: frozen,
    scope: scopeFor(frozen, null),
    ...(signal === undefined ? {} : { signal }),
  });
  const item = (skillId: string, expectedRevision?: number, signal?: AbortSignal) => ({
    ...common(signal),
    skillId,
    ...(expectedRevision === undefined ? {} : { expectedRevision }),
  });
  const client: DesktopTenantSkillDefinitionsClientV2 = {
    async listManagedSkills(signal) {
      return [
        ...(await operations.loadTenantSkillDefinitions({
          ...common(signal),
          scope: scopeFor(frozen, frozen.projectId || null),
        })),
      ];
    },
    createManagedSkill(input, signal) {
      return operations.createTenantSkillDefinition({
        ...common(signal),
        scope: scopeFor(frozen, input.project_id),
        input,
      });
    },
    getManagedSkillContent(skillId, signal) {
      return operations.getTenantSkillContent(item(skillId, undefined, signal));
    },
    updateManagedSkill(skillId, input, expectedRevision, signal) {
      return operations.updateTenantSkillDefinition({
        ...item(skillId, expectedRevision, signal),
        input,
      });
    },
    updateManagedSkillContent(skillId, fullContent, expectedRevision, signal) {
      return operations.updateTenantSkillContent({
        ...item(skillId, expectedRevision, signal),
        fullContent,
      });
    },
    setManagedSkillStatus(skillId, status, expectedRevision, signal) {
      return operations.setTenantSkillStatus({
        ...item(skillId, expectedRevision, signal),
        status,
      });
    },
    deleteManagedSkill(skillId, expectedRevision, signal) {
      return operations.deleteTenantSkillDefinition(item(skillId, expectedRevision, signal));
    },
  };
  return Object.freeze(client);
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantSkillDefinitionsInputV2,
  operation: (authority: DesktopTenantSkillDefinitionsAuthorityV2) => Promise<T>,
): Promise<T> {
  if (prepared.signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantSkillDefinitionsAuthorityUnavailableErrorV2({
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
    await actions.acquireServiceOperationLease<DesktopTenantSkillDefinitionsAuthorityServiceV2>({
      service: DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_VERSION_V2,
      scope: leaseScope,
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantSkillDefinitionsAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      assertActive(active);
      if (prepared.signal?.aborted)
        throw new DOMException('The operation was aborted', 'AbortError');
      const service = requireService(candidate);
      const raw = service.bindOperation(prepared.config, prepared.scope);
      const result = await operation(wrapAuthority(raw, () => active));
      assertActive(active);
      if (prepared.signal?.aborted)
        throw new DOMException('The operation was aborted', 'AbortError');
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

function requireService(value: unknown): DesktopTenantSkillDefinitionsAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopTenantSkillDefinitionsAuthorityServiceV2;
}

function wrapAuthority(
  raw: unknown,
  active: () => boolean,
): DesktopTenantSkillDefinitionsAuthorityV2 {
  const methods = [
    'load',
    'create',
    'getContent',
    'update',
    'updateContent',
    'setStatus',
    'delete',
  ] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as DesktopTenantSkillDefinitionsAuthorityV2;
  const wrapped: DesktopTenantSkillDefinitionsAuthorityV2 = {
    load: (scope, signal) => invoke(active, authority.load, [scope, signal]),
    create: (scope, input, signal) => invoke(active, authority.create, [scope, input, signal]),
    getContent: (scope, id, signal) => invoke(active, authority.getContent, [scope, id, signal]),
    update: (scope, id, input, revision, signal) =>
      invoke(active, authority.update, [scope, id, input, revision, signal]),
    updateContent: (scope, id, content, revision, signal) =>
      invoke(active, authority.updateContent, [scope, id, content, revision, signal]),
    setStatus: (scope, id, status, revision, signal) =>
      invoke(active, authority.setStatus, [scope, id, status, revision, signal]),
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
): DesktopTenantSkillDefinitionsScopeV2 {
  return Object.freeze({
    authority: config.mode,
    tenantId: config.tenantId,
    projectId,
  });
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_skill_definitions_operation_released',
      'desktop tenant skill definitions operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_skill_definitions_service_invalid',
    'desktop tenant skill definitions authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_SKILL_DEFINITIONS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_skill_definitions_authority_catalog_missing',
      'desktop tenant skill definitions authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
