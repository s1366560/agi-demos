import {
  requireIdentifier,
  tenantAdminError,
  type TenantAdminRole,
} from '../tenant-admin/tenantAdminHttp';
import {
  isRecord,
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

export function parseBackendStoreEnvelope(payload: unknown, tenantId: string): BackendStore {
  if (!isRecord(payload) || payload.success !== true) {
    throw tenantAdminError('backend_store_mutation_contract_invalid');
  }
  return parseBackendStore(payload.data, tenantId);
}

export function parseBackendStore(value: unknown, tenantId: string): BackendStore {
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

export function parseBackendStoreType(value: unknown): BackendStoreType {
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

export function parseBackendStoreTestResult(value: unknown): BackendStoreTestResult {
  if (!isRecord(value) || typeof value.success !== 'boolean') {
    throw tenantAdminError('backend_store_test_contract_invalid');
  }
  return Object.freeze({
    success: value.success,
    version: optionalText(value.version),
    error: optionalText(value.error ?? value.detail),
  });
}

export function backendStoreScopedPath(
  plane: BackendStorePlane,
  scope: TenantManagementScope,
): string {
  return backendStoreTenantPath(`/api/v1/${backendStorePlaneRoot(plane)}`, scope);
}

export function backendStorePath(
  plane: BackendStorePlane,
  scope: TenantManagementScope,
  storeId: string,
): string {
  return backendStoreTenantPath(
    `/api/v1/${backendStorePlaneRoot(plane)}/${encodeURIComponent(backendStoreIdentifier(storeId))}`,
    scope,
  );
}

export function backendStoreTenantPath(path: string, scope: TenantManagementScope): string {
  return `${path}?tenant_id=${encodeURIComponent(scope.tenantId)}`;
}

export function backendStorePlaneRoot(plane: BackendStorePlane): string {
  return plane === 'graph' ? 'graph-stores' : 'retrieval-stores';
}

export function backendStoreIdentifier(value: string): string {
  return requireIdentifier(value, 'backend_store_id_required');
}

export function rejectBackendStoreMaskedSecrets(value: unknown): void {
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
  return cloneBackendStoreRecord(value);
}

export function cloneBackendStoreRecord(
  value: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  return Object.freeze(
    Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneJson(item)])),
  );
}

function cloneJson(value: unknown): unknown {
  if (Array.isArray(value)) return Object.freeze(value.map(cloneJson));
  if (isRecord(value)) return cloneBackendStoreRecord(value);
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
