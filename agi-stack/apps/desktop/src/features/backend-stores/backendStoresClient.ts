import type { VaultBoundCloudRequestBroker } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import {
  requireIdentifier,
  tenantAdminError,
  type TenantAdminRole,
} from '../tenant-admin/tenantAdminHttp';
import {
  isRecord,
  requireRole,
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from '../tenant-admin/tenantManagementHttp';

export const BACKEND_STORES_ROUTE_ID = 'backend-stores' as const;
export const BACKEND_STORES_LOCAL_REASON =
  'local_backend_stores_cloud_authority_unavailable' as const;

export type BackendStorePlane = 'graph' | 'retrieval';
export type BackendStoreField = Readonly<{
  name: string;
  type: string;
  required: boolean;
  sensitive: boolean;
  defaultValue?: unknown;
}>;
export type BackendStoreType = Readonly<{
  type: string;
  displayName: string;
  connectionFields: readonly BackendStoreField[];
  indexFields: readonly BackendStoreField[];
  status: string | null;
  source: string | null;
}>;
export type BackendStore = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  engineType: string;
  status: string;
  healthStatus: string | null;
  detectedVersion: string | null;
  connectionConfig: Readonly<Record<string, unknown>>;
  indexConfig: Readonly<Record<string, unknown>>;
  createdAt: string | null;
  updatedAt: string | null;
  source: 'env' | 'user';
  readonly: boolean;
}>;
export type BackendStorePlaneData = Readonly<{
  stores: readonly BackendStore[];
  types: readonly BackendStoreType[];
}>;
export type BackendStoresData = Readonly<{
  scopeRevision: number;
  membershipRole: TenantAdminRole;
  graph: BackendStorePlaneData;
  retrieval: BackendStorePlaneData;
}>;
export type BackendStoresSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  BackendStoresData
> &
  BackendStoresData;
export type BackendStoreCreateInput = Readonly<{
  name: string;
  engineType: string;
  connectionConfig: Readonly<Record<string, unknown>>;
  indexConfig?: Readonly<Record<string, unknown>>;
}>;
export type BackendStoreUpdateInput = Readonly<{
  name?: string;
  connectionConfig?: Readonly<Record<string, unknown>>;
  indexConfig?: Readonly<Record<string, unknown>>;
}>;
export type BackendStoreTestInput = Readonly<{
  engineType: string;
  connectionConfig: Readonly<Record<string, unknown>>;
}>;
export type BackendStoreTestResult = Readonly<{
  success: boolean;
  version: string | null;
  error: string | null;
}>;
export type BackendStoresClient = Readonly<{
  load(
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoresSnapshot>;
  create(
    scope: TenantManagementScope,
    plane: BackendStorePlane,
    input: BackendStoreCreateInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStore>;
  update(
    scope: TenantManagementScope,
    plane: BackendStorePlane,
    storeId: string,
    input: BackendStoreUpdateInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStore>;
  remove(
    scope: TenantManagementScope,
    plane: BackendStorePlane,
    storeId: string,
    options?: TenantManagementRequestOptions,
  ): Promise<void>;
  testDraft(
    scope: TenantManagementScope,
    plane: BackendStorePlane,
    input: BackendStoreTestInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoreTestResult>;
  testStore(
    scope: TenantManagementScope,
    plane: BackendStorePlane,
    storeId: string,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoreTestResult>;
}>;

const MEMBER_ACTIONS = Object.freeze(['view', 'list']);
const ADMIN_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'create', 'update', 'delete', 'test']);
const TENANT_ROLES = new Set<TenantAdminRole>(['owner', 'admin', 'member', 'editor', 'viewer']);

export function createBackendStoresClient(
  config: DesktopRuntimeConfig,
  broker: VaultBoundCloudRequestBroker | null = null,
): BackendStoresClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireBackendStoresScope(runtimeConfig, scope, broker);

  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const observation = await observeScope(broker!, currentScope, options);
      const [graphStores, graphTypes, retrievalStores, retrievalTypes] = await Promise.all([
        loadStores(broker!, currentScope, 'graph', options),
        loadTypes(broker!, 'graph', options),
        loadStores(broker!, currentScope, 'retrieval', options),
        loadTypes(broker!, 'retrieval', options),
      ]);
      const data = Object.freeze({
        scopeRevision: observation.scopeRevision,
        membershipRole: observation.membershipRole,
        graph: Object.freeze({ stores: graphStores, types: graphTypes }),
        retrieval: Object.freeze({
          stores: retrievalStores,
          types: retrievalTypes,
        }),
      });
      const allowedActions = canAdmin(observation.membershipRole) ? ADMIN_ACTIONS : MEMBER_ACTIONS;
      return Object.freeze({
        scope: currentScope,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions,
        data,
        ...data,
      });
    },
    async create(scope, plane, input, options) {
      rejectMaskedSecrets(input.connectionConfig);
      const currentScope = scopeFor(scope);
      await requireAdmin(broker!, currentScope, options);
      const payload = await broker!.requestJson({
        path: scopedPath(plane, currentScope),
        signal: options?.signal,
        method: 'POST',
        body: {
          name: requireIdentifier(input.name, 'backend_store_name_required'),
          engine_type: requireIdentifier(input.engineType, 'backend_store_engine_type_required'),
          connection_config: cloneRecord(input.connectionConfig),
          index_config: cloneRecord(input.indexConfig ?? {}),
        },
      });
      return parseStoreEnvelope(payload, currentScope.tenantId);
    },
    async update(scope, plane, storeId, input, options) {
      if (input.connectionConfig !== undefined) rejectMaskedSecrets(input.connectionConfig);
      const currentScope = scopeFor(scope);
      await requireAdmin(broker!, currentScope, options);
      const body: Record<string, unknown> = {};
      if (input.name !== undefined) {
        body.name = requireIdentifier(input.name, 'backend_store_name_required');
      }
      if (input.connectionConfig !== undefined) {
        body.connection_config = cloneRecord(input.connectionConfig);
      }
      if (input.indexConfig !== undefined) body.index_config = cloneRecord(input.indexConfig);
      if (Object.keys(body).length === 0) throw tenantAdminError('backend_store_update_empty', 422);
      const payload = await broker!.requestJson({
        path: storePath(plane, currentScope, storeId),
        signal: options?.signal,
        method: 'PUT',
        body,
      });
      return parseStoreEnvelope(payload, currentScope.tenantId);
    },
    async remove(scope, plane, storeId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(broker!, currentScope, options);
      await broker!.requestNoContent({
        path: storePath(plane, currentScope, storeId),
        signal: options?.signal,
        method: 'DELETE',
      });
    },
    async testDraft(scope, plane, input, options) {
      rejectMaskedSecrets(input.connectionConfig);
      const currentScope = scopeFor(scope);
      await requireAdmin(broker!, currentScope, options);
      const payload = await broker!.requestJson({
        path: tenantPath(`/api/v1/${planeRoot(plane)}/test`, currentScope),
        signal: options?.signal,
        method: 'POST',
        body: {
          engine_type: requireIdentifier(input.engineType, 'backend_store_engine_type_required'),
          connection_config: cloneRecord(input.connectionConfig),
        },
      });
      return parseTestResult(payload);
    },
    async testStore(scope, plane, storeId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(broker!, currentScope, options);
      const payload = await broker!.requestJson({
        path: tenantPath(
          `/api/v1/${planeRoot(plane)}/${encodeURIComponent(storeIdentifier(storeId))}/test`,
          currentScope,
        ),
        signal: options?.signal,
        method: 'POST',
        body: {},
      });
      return parseTestResult(payload);
    },
  });
}

async function observeScope(
  broker: VaultBoundCloudRequestBroker,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<Readonly<{ membershipRole: TenantAdminRole; scopeRevision: number }>> {
  const payload = await broker.requestJson({
    path: '/api/v1/workspace-context',
    signal: options?.signal,
  });
  if (!isRecord(payload) || !isRecord(payload.context)) {
    throw tenantAdminError('backend_stores_workspace_context_contract_invalid');
  }
  if (payload.context.tenant_id !== scope.tenantId) {
    throw tenantAdminError('backend_stores_scope_conflict', 409);
  }
  const membershipRole = payload.membership_role;
  const revision = payload.context.revision;
  if (
    typeof membershipRole !== 'string' ||
    !TENANT_ROLES.has(membershipRole as TenantAdminRole) ||
    typeof revision !== 'number' ||
    !Number.isSafeInteger(revision) ||
    revision < 0
  ) {
    throw tenantAdminError('backend_stores_workspace_context_contract_invalid');
  }
  return Object.freeze({
    membershipRole: membershipRole as TenantAdminRole,
    scopeRevision: revision,
  });
}

async function requireAdmin(
  broker: VaultBoundCloudRequestBroker,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<void> {
  const observation = await observeScope(broker, scope, options);
  requireRole(observation.membershipRole, ['owner', 'admin'], 'backend_stores_admin_required');
}

async function loadStores(
  broker: VaultBoundCloudRequestBroker,
  scope: TenantManagementScope,
  plane: BackendStorePlane,
  options?: TenantManagementRequestOptions,
): Promise<readonly BackendStore[]> {
  const payload = await broker.requestJson({
    path: scopedPath(plane, scope),
    signal: options?.signal,
  });
  if (!isRecord(payload) || payload.success !== true || !Array.isArray(payload.data)) {
    throw tenantAdminError('backend_stores_list_contract_invalid');
  }
  return Object.freeze(payload.data.map((store) => parseStore(store, scope.tenantId)));
}

async function loadTypes(
  broker: VaultBoundCloudRequestBroker,
  plane: BackendStorePlane,
  options?: TenantManagementRequestOptions,
): Promise<readonly BackendStoreType[]> {
  const payload = await broker.requestJson({
    path: `/api/v1/${planeRoot(plane)}/types`,
    signal: options?.signal,
  });
  if (!isRecord(payload) || payload.success !== true || !Array.isArray(payload.data)) {
    throw tenantAdminError('backend_store_types_contract_invalid');
  }
  return Object.freeze(payload.data.map(parseStoreType));
}

function parseStoreEnvelope(payload: unknown, tenantId: string): BackendStore {
  if (!isRecord(payload) || payload.success !== true) {
    throw tenantAdminError('backend_store_mutation_contract_invalid');
  }
  return parseStore(payload.data, tenantId);
}

function parseStore(value: unknown, tenantId: string): BackendStore {
  if (!isRecord(value) || value.tenant_id !== tenantId) {
    throw tenantAdminError('backend_store_scope_conflict', 409);
  }
  const source = value.source;
  if (source !== 'env' && source !== 'user') {
    throw tenantAdminError('backend_store_contract_invalid');
  }
  if (typeof value.readonly !== 'boolean') {
    throw tenantAdminError('backend_store_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'backend_store_contract_invalid'),
    tenantId,
    name: requireIdentifier(value.name, 'backend_store_contract_invalid'),
    engineType: requireIdentifier(value.engine_type, 'backend_store_contract_invalid'),
    status: requireIdentifier(value.status, 'backend_store_contract_invalid'),
    healthStatus: optionalText(value.health_status),
    detectedVersion: optionalText(value.detected_version),
    connectionConfig: cloneUnknownRecord(value.connection_config),
    indexConfig: cloneUnknownRecord(value.index_config),
    createdAt: optionalText(value.created_at),
    updatedAt: optionalText(value.updated_at),
    source,
    readonly: value.readonly,
  });
}

function parseStoreType(value: unknown): BackendStoreType {
  if (
    !isRecord(value) ||
    !Array.isArray(value.connection_fields) ||
    !Array.isArray(value.index_fields)
  ) {
    throw tenantAdminError('backend_store_type_contract_invalid');
  }
  return Object.freeze({
    type: requireIdentifier(value.type, 'backend_store_type_contract_invalid'),
    displayName: requireIdentifier(value.display_name, 'backend_store_type_contract_invalid'),
    connectionFields: Object.freeze(value.connection_fields.map(parseField)),
    indexFields: Object.freeze(value.index_fields.map(parseField)),
    status: optionalText(value.status),
    source: optionalText(value.source),
  });
}

function parseField(value: unknown): BackendStoreField {
  if (!isRecord(value)) throw tenantAdminError('backend_store_field_contract_invalid');
  return Object.freeze({
    name: requireIdentifier(value.name, 'backend_store_field_contract_invalid'),
    type: requireIdentifier(value.type, 'backend_store_field_contract_invalid'),
    required: value.required === true,
    sensitive: value.sensitive === true,
    ...(value.default === undefined ? {} : { defaultValue: cloneJson(value.default) }),
  });
}

function parseTestResult(value: unknown): BackendStoreTestResult {
  if (!isRecord(value) || typeof value.success !== 'boolean') {
    throw tenantAdminError('backend_store_test_contract_invalid');
  }
  return Object.freeze({
    success: value.success,
    version: optionalText(value.version),
    error: optionalText(value.error ?? value.detail),
  });
}

function scopedPath(plane: BackendStorePlane, scope: TenantManagementScope): string {
  return tenantPath(`/api/v1/${planeRoot(plane)}`, scope);
}

function storePath(
  plane: BackendStorePlane,
  scope: TenantManagementScope,
  storeId: string,
): string {
  return tenantPath(
    `/api/v1/${planeRoot(plane)}/${encodeURIComponent(storeIdentifier(storeId))}`,
    scope,
  );
}

function tenantPath(path: string, scope: TenantManagementScope): string {
  return `${path}?tenant_id=${encodeURIComponent(scope.tenantId)}`;
}

function planeRoot(plane: BackendStorePlane): string {
  return plane === 'graph' ? 'graph-stores' : 'retrieval-stores';
}

function storeIdentifier(value: string): string {
  return requireIdentifier(value, 'backend_store_id_required');
}

function canAdmin(role: TenantAdminRole): boolean {
  return role === 'owner' || role === 'admin';
}

function requireBackendStoresScope(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  broker: VaultBoundCloudRequestBroker | null,
): TenantManagementScope {
  const configuredTenantId = requireIdentifier(
    config.tenantId,
    'backend_stores_configured_tenant_invalid',
  );
  const tenantId = requireIdentifier(scope.tenantId, 'backend_stores_tenant_scope_invalid');
  if (scope.authority === 'local') {
    throw tenantAdminError(BACKEND_STORES_LOCAL_REASON, 503);
  }
  if (scope.authority !== 'cloud') {
    throw tenantAdminError('backend_stores_authority_mode_mismatch', 409);
  }
  if (configuredTenantId !== tenantId) {
    throw tenantAdminError('backend_stores_tenant_scope_mismatch', 409);
  }
  if (!broker) throw tenantAdminError('cloud_request_broker_missing', 501);
  return Object.freeze({ authority: 'cloud', tenantId });
}

function rejectMaskedSecrets(value: unknown): void {
  if (containsMaskedSecret(value)) {
    throw tenantAdminError('backend_stores_masked_secret_rejected', 422);
  }
}

function containsMaskedSecret(value: unknown): boolean {
  if (value === '***') return true;
  if (Array.isArray(value)) return value.some(containsMaskedSecret);
  if (isRecord(value)) return Object.values(value).some(containsMaskedSecret);
  return false;
}

function optionalText(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string') throw tenantAdminError('backend_store_contract_invalid');
  return value;
}

function cloneUnknownRecord(value: unknown): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw tenantAdminError('backend_store_config_contract_invalid');
  return cloneRecord(value);
}

function cloneRecord(value: Readonly<Record<string, unknown>>): Readonly<Record<string, unknown>> {
  return Object.freeze(
    Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneJson(item)])),
  );
}

function cloneJson(value: unknown): unknown {
  if (Array.isArray(value)) return Object.freeze(value.map(cloneJson));
  if (isRecord(value)) return cloneRecord(value);
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }
  throw tenantAdminError('backend_store_config_contract_invalid', 422);
}
