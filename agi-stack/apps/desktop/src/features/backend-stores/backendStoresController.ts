import {
  createTenantManagementController,
  type TenantManagementControllerCore,
  type TenantManagementPresentationInput,
} from '../tenant-admin/tenantManagementController';
import type { TenantManagementScope } from '../tenant-admin/tenantManagementHttp';
import type {
  BackendStoreCreateInput,
  BackendStorePlane,
  BackendStoresClient,
  BackendStoresData,
  BackendStoreTestInput,
  BackendStoreTestResult,
  BackendStoreUpdateInput,
} from './backendStoresClient';

export type BackendStoresViewModel = Readonly<{
  routeId: 'backend-stores';
  state:
    | 'loading'
    | 'stale'
    | 'empty'
    | 'ready'
    | 'degraded'
    | 'forbidden'
    | 'conflict'
    | 'unavailable'
    | 'error';
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: string | null;
  graph: BackendStoresData['graph'];
  retrieval: BackendStoresData['retrieval'];
}>;

export type BackendStoresController = TenantManagementControllerCore<
  TenantManagementScope,
  BackendStoresViewModel
> &
  Readonly<{
    create(plane: BackendStorePlane, input: BackendStoreCreateInput): Promise<void>;
    update(
      plane: BackendStorePlane,
      storeId: string,
      input: BackendStoreUpdateInput,
    ): Promise<void>;
    remove(plane: BackendStorePlane, storeId: string): Promise<void>;
    testDraft(
      plane: BackendStorePlane,
      input: BackendStoreTestInput,
    ): Promise<BackendStoreTestResult>;
    testStore(plane: BackendStorePlane, storeId: string): Promise<BackendStoreTestResult>;
  }>;

const EMPTY_PLANE = Object.freeze({
  stores: Object.freeze([]),
  types: Object.freeze([]),
});

export function createBackendStoresController({
  client,
  initialScope,
}: Readonly<{
  client: BackendStoresClient;
  initialScope: TenantManagementScope;
}>): BackendStoresController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'backend_stores',
    loadAuthority: client.load,
    isEmpty: (data: BackendStoresData) =>
      data.graph.stores.length === 0 && data.retrieval.stores.length === 0,
    buildPresentation: buildBackendStoresPresentation,
  });
  return Object.freeze({
    ...core,
    create: (plane, input) =>
      core.runAction('create', async (scope, signal) => {
        await client.create(scope, plane, input, { signal });
      }),
    update: (plane, storeId, input) =>
      core.runAction('update', async (scope, signal) => {
        await client.update(scope, plane, storeId, input, { signal });
      }),
    remove: (plane, storeId) =>
      core.runAction('delete', (scope, signal) => client.remove(scope, plane, storeId, { signal })),
    testDraft: async (plane, input) => {
      let result: BackendStoreTestResult | null = null;
      await core.runAction('test', async (scope, signal) => {
        result = await client.testDraft(scope, plane, input, { signal });
      });
      if (!result) throw new Error('backend_store_test_result_unavailable');
      return result;
    },
    testStore: async (plane, storeId) => {
      let result: BackendStoreTestResult | null = null;
      await core.runAction('test', async (scope, signal) => {
        result = await client.testStore(scope, plane, storeId, { signal });
      });
      if (!result) throw new Error('backend_store_test_result_unavailable');
      return result;
    },
  });
}

export function buildBackendStoresPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, BackendStoresData>,
): BackendStoresViewModel {
  return Object.freeze({
    routeId: 'backend-stores',
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: Object.freeze([...(input.snapshot?.allowedActions ?? [])]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    graph: input.snapshot?.data.graph ?? EMPTY_PLANE,
    retrieval: input.snapshot?.data.retrieval ?? EMPTY_PLANE,
  });
}
