import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  BackendStore,
  BackendStoreCreateInput,
  BackendStorePlane,
  BackendStoresClient,
  BackendStoresSnapshot,
  BackendStoreTestInput,
  BackendStoreTestResult,
  BackendStoreUpdateInput,
} from '../features/backend-stores/backendStoresClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import {
  createDesktopBackendStoresHttpAuthorityV2,
  type DesktopBackendStoresCapabilityV2,
} from './desktopBackendStoresHttpProjectionV2';
import {
  cloneDesktopBackendStoresConfigV2,
  prepareDesktopBackendStoresAuthorityOperationV2,
  type DesktopBackendStoreCreateOperationInputV2,
  type DesktopBackendStoreRemoveOperationInputV2,
  type DesktopBackendStoresAuthorityOperationInputV2,
  type DesktopBackendStoresOperationInputV2,
  type DesktopBackendStoreTestDraftOperationInputV2,
  type DesktopBackendStoreTestExistingOperationInputV2,
  type DesktopBackendStoreUpdateOperationInputV2,
  type PreparedDesktopBackendStoresAuthorityOperationV2,
} from './desktopBackendStoresOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_BACKEND_STORES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/backend-stores-authority';
export const DESKTOP_BACKEND_STORES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.backend-stores-authority';
export const DESKTOP_BACKEND_STORES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopBackendStoresAuthorityV2 {
  load(options?: TenantManagementRequestOptions): Promise<BackendStoresSnapshot>;
  create(
    plane: BackendStorePlane,
    input: BackendStoreCreateInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStore>;
  update(
    plane: BackendStorePlane,
    storeId: string,
    input: BackendStoreUpdateInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStore>;
  remove(
    plane: BackendStorePlane,
    storeId: string,
    options?: TenantManagementRequestOptions,
  ): Promise<void>;
  testDraft(
    plane: BackendStorePlane,
    input: BackendStoreTestInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoreTestResult>;
  testExisting(
    plane: BackendStorePlane,
    storeId: string,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoreTestResult>;
  probe(options?: TenantManagementRequestOptions): Promise<DesktopBackendStoresCapabilityV2>;
}
export interface DesktopBackendStoresAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: TenantManagementScope,
  ): DesktopBackendStoresAuthorityV2;
}
export interface DesktopBackendStoresOperationsV2 {
  loadBackendStores(input: DesktopBackendStoresOperationInputV2): Promise<BackendStoresSnapshot>;
  createBackendStore(input: DesktopBackendStoreCreateOperationInputV2): Promise<BackendStore>;
  updateBackendStore(input: DesktopBackendStoreUpdateOperationInputV2): Promise<BackendStore>;
  removeBackendStore(input: DesktopBackendStoreRemoveOperationInputV2): Promise<void>;
  testBackendStoreDraft(
    input: DesktopBackendStoreTestDraftOperationInputV2,
  ): Promise<BackendStoreTestResult>;
  testBackendStoreExisting(
    input: DesktopBackendStoreTestExistingOperationInputV2,
  ): Promise<BackendStoreTestResult>;
  probeBackendStores(
    input: DesktopBackendStoresOperationInputV2,
  ): Promise<DesktopBackendStoresCapabilityV2>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;
export class DesktopBackendStoresAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopBackendStoresAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopBackendStoresAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-vault-broker')
    throw new RuntimeV2Error(
      'desktop_backend_stores_authority_config_invalid',
      'desktop backend stores authority requires desktop-vault-broker strategy',
    );
  context.provide(
    DESKTOP_BACKEND_STORES_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopBackendStoresHttpAuthorityV2 }),
  );
}
export const desktopBackendStoresAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_BACKEND_STORES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopBackendStoresAuthorityV2,
});

export function createDesktopBackendStoresOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopBackendStoresOperationsV2 {
  const run = <T>(
    input: DesktopBackendStoresAuthorityOperationInputV2,
    operation: (
      authority: DesktopBackendStoresAuthorityV2,
      prepared: PreparedDesktopBackendStoresAuthorityOperationV2,
    ) => Promise<T>,
  ): Promise<T> =>
    runOperation(
      requireActions(resolveActions()),
      prepareDesktopBackendStoresAuthorityOperationV2(input),
      operation,
    );
  const operations: DesktopBackendStoresOperationsV2 = {
    loadBackendStores: (input) =>
      run({ kind: 'load', ...input }, (authority, prepared) => authority.load(prepared.options)),
    createBackendStore: (input) =>
      run({ kind: 'create', ...input }, (authority, prepared) =>
        authority.create(
          prepared.plane!,
          prepared.input! as BackendStoreCreateInput,
          prepared.options,
        ),
      ),
    updateBackendStore: (input) =>
      run({ kind: 'update', ...input }, (authority, prepared) =>
        authority.update(
          prepared.plane!,
          prepared.storeId!,
          prepared.input! as BackendStoreUpdateInput,
          prepared.options,
        ),
      ),
    removeBackendStore: (input) =>
      run({ kind: 'remove', ...input }, (authority, prepared) =>
        authority.remove(prepared.plane!, prepared.storeId!, prepared.options),
      ),
    testBackendStoreDraft: (input) =>
      run({ kind: 'testDraft', ...input }, (authority, prepared) =>
        authority.testDraft(
          prepared.plane!,
          prepared.input! as BackendStoreTestInput,
          prepared.options,
        ),
      ),
    testBackendStoreExisting: (input) =>
      run({ kind: 'testExisting', ...input }, (authority, prepared) =>
        authority.testExisting(prepared.plane!, prepared.storeId!, prepared.options),
      ),
    probeBackendStores: (input) =>
      run({ kind: 'probe', ...input }, (authority, prepared) => authority.probe(prepared.options)),
  };
  return Object.freeze(operations);
}

export function createDesktopBackendStoresClientV2(
  operations: DesktopBackendStoresOperationsV2,
  config: DesktopRuntimeConfig,
): BackendStoresClient {
  const operationConfig = cloneDesktopBackendStoresConfigV2(config);
  const client: BackendStoresClient = {
    load: (scope: TenantManagementScope, options?: TenantManagementRequestOptions) =>
      operations.loadBackendStores({
        config: operationConfig,
        scope,
        ...(options ? { options } : {}),
      }),
    create: (
      scope: TenantManagementScope,
      plane: BackendStorePlane,
      input: BackendStoreCreateInput,
      options?: TenantManagementRequestOptions,
    ) =>
      operations.createBackendStore({
        config: operationConfig,
        scope,
        plane,
        input,
        ...(options ? { options } : {}),
      }),
    update: (
      scope: TenantManagementScope,
      plane: BackendStorePlane,
      storeId: string,
      input: BackendStoreUpdateInput,
      options?: TenantManagementRequestOptions,
    ) =>
      operations.updateBackendStore({
        config: operationConfig,
        scope,
        plane,
        storeId,
        input,
        ...(options ? { options } : {}),
      }),
    remove: (
      scope: TenantManagementScope,
      plane: BackendStorePlane,
      storeId: string,
      options?: TenantManagementRequestOptions,
    ) =>
      operations.removeBackendStore({
        config: operationConfig,
        scope,
        plane,
        storeId,
        ...(options ? { options } : {}),
      }),
    testDraft: (
      scope: TenantManagementScope,
      plane: BackendStorePlane,
      input: BackendStoreTestInput,
      options?: TenantManagementRequestOptions,
    ) =>
      operations.testBackendStoreDraft({
        config: operationConfig,
        scope,
        plane,
        input,
        ...(options ? { options } : {}),
      }),
    testStore: (
      scope: TenantManagementScope,
      plane: BackendStorePlane,
      storeId: string,
      options?: TenantManagementRequestOptions,
    ) =>
      operations.testBackendStoreExisting({
        config: operationConfig,
        scope,
        plane,
        storeId,
        ...(options ? { options } : {}),
      }),
  };
  return Object.freeze(client);
}

export function withDesktopBackendStoresAuthorityOperationV2<T>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopBackendStoresAuthorityOperationInputV2,
  operation: (
    authority: DesktopBackendStoresAuthorityV2,
    prepared: PreparedDesktopBackendStoresAuthorityOperationV2,
  ) => Promise<T>,
): Promise<T> {
  return runOperation(actions, prepareDesktopBackendStoresAuthorityOperationV2(input), operation);
}

async function runOperation<T>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopBackendStoresAuthorityOperationV2,
  operation: (
    authority: DesktopBackendStoresAuthorityV2,
    prepared: PreparedDesktopBackendStoresAuthorityOperationV2,
  ) => Promise<T>,
): Promise<T> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopBackendStoresAuthorityServiceV2>({
      service: DESKTOP_BACKEND_STORES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_BACKEND_STORES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'tenant',
        tenant_id: prepared.scope.tenantId,
      }),
    });
  if (admission.status === 'rejected')
    throw new DesktopBackendStoresAuthorityUnavailableErrorV2(admission);
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      const service = requireService(candidate);
      const authority = revocable(
        requireAuthority(service.bindOperation(prepared.config, prepared.scope)),
        prepared.scope,
        () => active,
      );
      return operation(authority, prepared);
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

function revocable(
  authority: DesktopBackendStoresAuthorityV2,
  scope: TenantManagementScope,
  active: () => boolean,
): DesktopBackendStoresAuthorityV2 {
  const run = async <T>(
    operation: () => Promise<T>,
    validate: (value: unknown) => T,
  ): Promise<T> => {
    requireActive(active);
    const value = await operation();
    requireActive(active);
    return validate(value);
  };
  const wrapped: DesktopBackendStoresAuthorityV2 = {
    load: (options) =>
      run(
        () => authority.load(options),
        (value) => requireSnapshot(value, scope),
      ),
    create: (plane, input, options) =>
      run(
        () => authority.create(plane, input, options),
        (value) => requireStore(value, scope),
      ),
    update: (plane, id, input, options) =>
      run(
        () => authority.update(plane, id, input, options),
        (value) => requireStore(value, scope),
      ),
    remove: (plane, id, options) => run(() => authority.remove(plane, id, options), requireVoid),
    testDraft: (plane, input, options) =>
      run(() => authority.testDraft(plane, input, options), requireTestResult),
    testExisting: (plane, id, options) =>
      run(() => authority.testExisting(plane, id, options), requireTestResult),
    probe: (options) => run(() => authority.probe(options), requireProbe),
  };
  return Object.freeze(wrapped);
}

function requireService(value: unknown): DesktopBackendStoresAuthorityServiceV2 {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  )
    throw invalidService();
  return value as unknown as DesktopBackendStoresAuthorityServiceV2;
}
function requireAuthority(value: unknown): DesktopBackendStoresAuthorityV2 {
  const keys = ['load', 'create', 'update', 'remove', 'testDraft', 'testExisting', 'probe'];
  if (
    !isRecord(value) ||
    Object.keys(value).length !== keys.length ||
    keys.some((key) => typeof value[key] !== 'function')
  )
    throw invalidService();
  return value as unknown as DesktopBackendStoresAuthorityV2;
}
function requireSnapshot(value: unknown, scope: TenantManagementScope): BackendStoresSnapshot {
  if (
    !isRecord(value) ||
    value.authority !== 'cloud' ||
    !isRecord(value.scope) ||
    value.scope.tenantId !== scope.tenantId ||
    value.scope.authority !== scope.authority ||
    !isRecord(value.data) ||
    !isRecord(value.graph) ||
    !isRecord(value.retrieval) ||
    !Array.isArray(value.graph.stores) ||
    !Array.isArray(value.graph.types) ||
    !Array.isArray(value.retrieval.stores) ||
    !Array.isArray(value.retrieval.types) ||
    !Array.isArray(value.allowedActions)
  )
    throw invalidResponse();
  return value as unknown as BackendStoresSnapshot;
}
function requireStore(value: unknown, scope: TenantManagementScope): BackendStore {
  const keys = new Set([
    'id',
    'tenantId',
    'name',
    'engineType',
    'status',
    'healthStatus',
    'detectedVersion',
    'connectionConfig',
    'indexConfig',
    'createdAt',
    'updatedAt',
    'source',
    'readonly',
  ]);
  if (
    !isRecord(value) ||
    Object.keys(value).length !== keys.size ||
    Object.keys(value).some((key) => !keys.has(key)) ||
    typeof value.id !== 'string' ||
    value.tenantId !== scope.tenantId ||
    typeof value.readonly !== 'boolean' ||
    !isRecord(value.connectionConfig) ||
    !isRecord(value.indexConfig)
  )
    throw invalidResponse();
  return value as unknown as BackendStore;
}
function requireTestResult(value: unknown): BackendStoreTestResult {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== 3 ||
    typeof value.success !== 'boolean' ||
    (value.version !== null && typeof value.version !== 'string') ||
    (value.error !== null && typeof value.error !== 'string')
  )
    throw invalidResponse();
  return value as unknown as BackendStoreTestResult;
}
function requireProbe(value: unknown): DesktopBackendStoresCapabilityV2 {
  const keys = new Set(['availability', 'reasonCode', 'allowedActions', 'authorityRevision']);
  if (
    !isRecord(value) ||
    Object.keys(value).length !== keys.size ||
    Object.keys(value).some((key) => !keys.has(key)) ||
    (value.availability !== 'available' && value.availability !== 'not_applicable') ||
    (value.reasonCode !== null && typeof value.reasonCode !== 'string') ||
    !Array.isArray(value.allowedActions) ||
    value.allowedActions.some((item) => typeof item !== 'string') ||
    (value.authorityRevision !== null &&
      (!Number.isSafeInteger(value.authorityRevision) || (value.authorityRevision as number) < 0))
  )
    throw invalidResponse();
  return Object.freeze({
    availability: value.availability,
    reasonCode: value.reasonCode as string | null,
    allowedActions: Object.freeze([...value.allowedActions]),
    authorityRevision: value.authorityRevision as number | null,
  });
}
function requireVoid(value: unknown): void {
  if (value !== undefined) throw invalidResponse();
}
function requireActive(active: () => boolean): void {
  if (!active())
    throw new RuntimeV2Error(
      'desktop_backend_stores_operation_released',
      'desktop backend stores operation has been released',
    );
}
function requireActions(
  value: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (value) return value;
  throw new DesktopBackendStoresAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_backend_stores_service_invalid',
    'desktop backend stores authority service is invalid',
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_backend_stores_response_invalid',
    'desktop backend stores authority response is invalid',
  );
}
function isRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_BACKEND_STORES_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_backend_stores_authority_catalog_missing',
      'desktop backend stores authority is absent from the generated catalog',
    );
  return entry.contract_digest;
}
