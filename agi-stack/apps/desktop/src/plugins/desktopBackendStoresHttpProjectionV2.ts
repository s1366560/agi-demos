import {
  desktopVaultBoundCloudRequestBroker,
  type VaultBoundCloudRequestBroker,
} from '../api/cloudRequestBroker';
import {
  BACKEND_STORES_LOCAL_REASON,
  backendStoreIdentifier,
  backendStorePath,
  backendStorePlaneRoot,
  backendStoreScopedPath,
  backendStoreTenantPath,
  cloneBackendStoreRecord,
  parseBackendStore,
  parseBackendStoreEnvelope,
  parseBackendStoreTestResult,
  parseBackendStoreType,
  rejectBackendStoreMaskedSecrets,
  type BackendStore,
  type BackendStoreCreateInput,
  type BackendStorePlane,
  type BackendStoresSnapshot,
  type BackendStoreTestInput,
  type BackendStoreTestResult,
  type BackendStoreType,
  type BackendStoreUpdateInput,
} from '../features/backend-stores/backendStoresClient';
import {
  requireIdentifier,
  tenantAdminError,
  type TenantAdminRole,
} from '../features/tenant-admin/tenantAdminHttp';
import {
  isRecord,
  requireRole,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopBackendStoresCapabilityV2 = Readonly<{
  availability: 'available' | 'not_applicable';
  reasonCode: string | null;
  allowedActions: readonly string[];
  authorityRevision: number | null;
}>;
export type DesktopBackendStoresHttpAuthorityV2 = Readonly<{
  load(options?: TenantManagementRequestOptions): Promise<BackendStoresSnapshot>;
  create(
    plane: BackendStorePlane,
    input: BackendStoreCreateInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStore>;
  update(
    plane: BackendStorePlane,
    id: string,
    input: BackendStoreUpdateInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStore>;
  remove(
    plane: BackendStorePlane,
    id: string,
    options?: TenantManagementRequestOptions,
  ): Promise<void>;
  testDraft(
    plane: BackendStorePlane,
    input: BackendStoreTestInput,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoreTestResult>;
  testExisting(
    plane: BackendStorePlane,
    id: string,
    options?: TenantManagementRequestOptions,
  ): Promise<BackendStoreTestResult>;
  probe(options?: TenantManagementRequestOptions): Promise<DesktopBackendStoresCapabilityV2>;
}>;

const MEMBER_ACTIONS = Object.freeze(['view', 'list']);
const ADMIN_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'create', 'update', 'delete', 'test']);
const TENANT_ROLES = new Set<TenantAdminRole>(['owner', 'admin', 'member', 'editor', 'viewer']);

export function createDesktopBackendStoresHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
): DesktopBackendStoresHttpAuthorityV2 {
  if (config.mode === 'local' || scope.authority === 'local') return localAuthority();
  const broker = requireBroker(desktopVaultBoundCloudRequestBroker());
  const currentScope = requireCloudScope(config, scope);
  return Object.freeze({
    load: (options) => loadSnapshot(broker, currentScope, options),
    async create(plane, input, options) {
      rejectBackendStoreMaskedSecrets(input.connectionConfig);
      await requireAdmin(broker, currentScope, options);
      const payload = await broker.requestJson({
        path: backendStoreScopedPath(plane, currentScope),
        signal: options?.signal,
        method: 'POST',
        body: {
          name: requireIdentifier(input.name, 'backend_store_name_required'),
          engine_type: requireIdentifier(input.engineType, 'backend_store_engine_type_required'),
          connection_config: cloneBackendStoreRecord(input.connectionConfig),
          index_config: cloneBackendStoreRecord(input.indexConfig ?? {}),
        },
      });
      return parseBackendStoreEnvelope(payload, currentScope.tenantId);
    },
    async update(plane, id, input, options) {
      if (input.connectionConfig !== undefined)
        rejectBackendStoreMaskedSecrets(input.connectionConfig);
      await requireAdmin(broker, currentScope, options);
      const body: Record<string, unknown> = {};
      if (input.name !== undefined)
        body.name = requireIdentifier(input.name, 'backend_store_name_required');
      if (input.connectionConfig !== undefined)
        body.connection_config = cloneBackendStoreRecord(input.connectionConfig);
      if (input.indexConfig !== undefined)
        body.index_config = cloneBackendStoreRecord(input.indexConfig);
      if (Object.keys(body).length === 0) throw tenantAdminError('backend_store_update_empty', 422);
      return parseBackendStoreEnvelope(
        await broker.requestJson({
          path: backendStorePath(plane, currentScope, id),
          signal: options?.signal,
          method: 'PUT',
          body,
        }),
        currentScope.tenantId,
      );
    },
    async remove(plane, id, options) {
      await requireAdmin(broker, currentScope, options);
      await broker.requestNoContent({
        path: backendStorePath(plane, currentScope, id),
        signal: options?.signal,
        method: 'DELETE',
      });
    },
    async testDraft(plane, input, options) {
      rejectBackendStoreMaskedSecrets(input.connectionConfig);
      await requireAdmin(broker, currentScope, options);
      return parseBackendStoreTestResult(
        await broker.requestJson({
          path: backendStoreTenantPath(
            `/api/v1/${backendStorePlaneRoot(plane)}/test`,
            currentScope,
          ),
          signal: options?.signal,
          method: 'POST',
          body: {
            engine_type: requireIdentifier(input.engineType, 'backend_store_engine_type_required'),
            connection_config: cloneBackendStoreRecord(input.connectionConfig),
          },
        }),
      );
    },
    async testExisting(plane, id, options) {
      await requireAdmin(broker, currentScope, options);
      const path = `/api/v1/${backendStorePlaneRoot(plane)}/${encodeURIComponent(backendStoreIdentifier(id))}/test`;
      return parseBackendStoreTestResult(
        await broker.requestJson({
          path: backendStoreTenantPath(path, currentScope),
          signal: options?.signal,
          method: 'POST',
          body: {},
        }),
      );
    },
    async probe(options) {
      const snapshot = await loadSnapshot(broker, currentScope, options);
      return Object.freeze({
        availability: 'available',
        reasonCode: null,
        allowedActions: Object.freeze([...snapshot.allowedActions]),
        authorityRevision: snapshot.scopeRevision,
      });
    },
  });
}

async function loadSnapshot(
  broker: VaultBoundCloudRequestBroker,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<BackendStoresSnapshot> {
  const observed = await observeScope(broker, scope, options);
  const [graphStores, graphTypes, retrievalStores, retrievalTypes] = await Promise.all([
    loadStores(broker, scope, 'graph', options),
    loadTypes(broker, 'graph', options),
    loadStores(broker, scope, 'retrieval', options),
    loadTypes(broker, 'retrieval', options),
  ]);
  const data = Object.freeze({
    scopeRevision: observed.scopeRevision,
    membershipRole: observed.membershipRole,
    graph: Object.freeze({ stores: graphStores, types: graphTypes }),
    retrieval: Object.freeze({ stores: retrievalStores, types: retrievalTypes }),
  });
  const allowedActions = canAdmin(observed.membershipRole) ? ADMIN_ACTIONS : MEMBER_ACTIONS;
  return Object.freeze({
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions,
    data,
    ...data,
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
  if (!isRecord(payload) || !isRecord(payload.context))
    throw tenantAdminError('backend_stores_workspace_context_contract_invalid');
  if (payload.context.tenant_id !== scope.tenantId)
    throw tenantAdminError('backend_stores_scope_conflict', 409);
  const role = payload.membership_role;
  const revision = payload.context.revision;
  if (
    typeof role !== 'string' ||
    !TENANT_ROLES.has(role as TenantAdminRole) ||
    typeof revision !== 'number' ||
    !Number.isSafeInteger(revision) ||
    revision < 0
  )
    throw tenantAdminError('backend_stores_workspace_context_contract_invalid');
  return Object.freeze({ membershipRole: role as TenantAdminRole, scopeRevision: revision });
}

async function requireAdmin(
  broker: VaultBoundCloudRequestBroker,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<void> {
  requireRole(
    (await observeScope(broker, scope, options)).membershipRole,
    ['owner', 'admin'],
    'backend_stores_admin_required',
  );
}

async function loadStores(
  broker: VaultBoundCloudRequestBroker,
  scope: TenantManagementScope,
  plane: BackendStorePlane,
  options?: TenantManagementRequestOptions,
): Promise<readonly BackendStore[]> {
  const payload = await broker.requestJson({
    path: backendStoreScopedPath(plane, scope),
    signal: options?.signal,
  });
  if (!isRecord(payload) || payload.success !== true || !Array.isArray(payload.data))
    throw tenantAdminError('backend_stores_list_contract_invalid');
  return Object.freeze(payload.data.map((item) => parseBackendStore(item, scope.tenantId)));
}

async function loadTypes(
  broker: VaultBoundCloudRequestBroker,
  plane: BackendStorePlane,
  options?: TenantManagementRequestOptions,
): Promise<readonly BackendStoreType[]> {
  const payload = await broker.requestJson({
    path: `/api/v1/${backendStorePlaneRoot(plane)}/types`,
    signal: options?.signal,
  });
  if (!isRecord(payload) || payload.success !== true || !Array.isArray(payload.data))
    throw tenantAdminError('backend_store_types_contract_invalid');
  return Object.freeze(payload.data.map(parseBackendStoreType));
}

function requireCloudScope(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
): TenantManagementScope {
  const tenantId = requireIdentifier(scope.tenantId, 'backend_stores_tenant_scope_invalid');
  if (config.mode !== 'cloud' || scope.authority !== 'cloud')
    throw tenantAdminError('backend_stores_authority_mode_mismatch', 409);
  if (requireIdentifier(config.tenantId, 'backend_stores_configured_tenant_invalid') !== tenantId)
    throw tenantAdminError('backend_stores_tenant_scope_mismatch', 409);
  return Object.freeze({ authority: 'cloud', tenantId });
}

function requireBroker(broker: VaultBoundCloudRequestBroker | null): VaultBoundCloudRequestBroker {
  if (broker === null) throw tenantAdminError('cloud_request_broker_missing', 501);
  return broker;
}

function canAdmin(role: TenantAdminRole): boolean {
  return role === 'owner' || role === 'admin';
}
function localAuthority(): DesktopBackendStoresHttpAuthorityV2 {
  const unavailable = (): never => {
    throw tenantAdminError(BACKEND_STORES_LOCAL_REASON, 503);
  };
  return Object.freeze({
    async load() {
      return unavailable();
    },
    async create() {
      return unavailable();
    },
    async update() {
      return unavailable();
    },
    async remove() {
      unavailable();
    },
    async testDraft() {
      return unavailable();
    },
    async testExisting() {
      return unavailable();
    },
    async probe() {
      return Object.freeze({
        availability: 'not_applicable',
        reasonCode: BACKEND_STORES_LOCAL_REASON,
        allowedActions: Object.freeze([]),
        authorityRevision: null,
      });
    },
  });
}
