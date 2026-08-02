import { DesktopApiError } from '../../api/client';
import { RuntimeInstancesUnavailableError } from './runtimeInstancesClient';
import {
  RUNTIME_INSTANCES_CLOUD_ACTIONS,
  RUNTIME_INSTANCES_LOCAL_ACTIONS,
} from './runtimeInstancesCapability';
import type {
  RuntimeInstanceSummary,
  RuntimeInstancesAuthority,
  RuntimeInstancesClient,
  RuntimeInstancesModel,
  RuntimeInstancesMutationState,
  RuntimeInstancesNormalizedQuery,
  RuntimeInstancesPage,
  RuntimeInstancesQuery,
  RuntimeInstancesResourceState,
  RuntimeInstancesScope,
} from './runtimeInstancesTypes';

export type RuntimeInstancesController = Readonly<{
  getSnapshot(): RuntimeInstancesModel;
  subscribe(listener: () => void): () => void;
  load(
    scope: RuntimeInstancesScope,
    query?: RuntimeInstancesQuery,
  ): Promise<void>;
  retry(): Promise<void>;
  setQuery(query: RuntimeInstancesQuery): Promise<void>;
  restart(instanceId: string): Promise<void>;
  delete(instanceId: string): Promise<void>;
  cancel(): void;
  stop(): void;
}>;

const DEFAULT_QUERY: RuntimeInstancesNormalizedQuery = Object.freeze({
  page: 1,
  pageSize: 20,
  search: '',
  status: 'all',
});

export function createRuntimeInstancesController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: RuntimeInstancesAuthority;
  client: RuntimeInstancesClient;
  initialScope: RuntimeInstancesScope;
}>): RuntimeInstancesController {
  let activeScope = freezeScope(initialScope);
  let activeQuery = DEFAULT_QUERY;
  let model = initialModel(activeScope);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: RuntimeInstancesModel): void => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: RuntimeInstancesScope,
    query: RuntimeInstancesQuery = activeQuery,
  ): Promise<void> => {
    const scope = freezeScope(nextScope);
    const normalizedQuery = normalizeQuery(query);
    activeScope = scope;
    activeQuery = normalizedQuery;
    if (scope.authority !== authority) {
      cancel();
      emit(
        unavailableModel(
          scope,
          normalizedQuery,
          'runtime_instances_controller_authority_mismatch',
        ),
      );
      return;
    }

    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({
      ...stable,
      scope,
      authority,
      state: 'loading',
      reasonCode: reasonCodeFor(authority),
      mutationState: 'idle',
      mutationReasonCode: null,
      busyInstanceId: null,
      retryVisible: false,
      query: normalizedQuery,
    });
    try {
      const page = await client.list(scope, normalizedQuery, {
        signal: controller.signal,
      });
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      emit(loadedModel(scope, normalizedQuery, page));
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      emit(loadErrorModel(stable, scope, normalizedQuery, error));
    }
  };

  const mutate = async (
    action: 'restart' | 'delete',
    instanceId: string,
  ): Promise<void> => {
    if (authority !== 'cloud') {
      throw new RuntimeInstancesUnavailableError(
        'runtime_instances_mutation_not_allowed',
      );
    }
    const id = visibleInstance(model.instances, instanceId).id;
    if (model.busyInstanceId !== null) {
      throw new RuntimeInstancesUnavailableError(
        'runtime_instances_mutation_in_progress',
      );
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({
      ...stable,
      busyInstanceId: id,
      mutationState: 'idle',
      mutationReasonCode: null,
    });
    try {
      if (action === 'restart') {
        await client.restart(activeScope, id, { signal: controller.signal });
      } else {
        await client.delete(activeScope, id, { signal: controller.signal });
      }
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      emit({ ...model, busyInstanceId: null });
      await load(activeScope, activeQuery);
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) throw error;
      requestController = null;
      emit(mutationErrorModel(stable, error));
      throw error;
    }
  };

  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: () => load(activeScope, activeQuery),
    setQuery: (query) => load(activeScope, { ...activeQuery, ...query }),
    restart: (instanceId) => mutate('restart', instanceId),
    delete: (instanceId) => mutate('delete', instanceId),
    cancel,
    stop: cancel,
  });

  function requestIsCurrent(
    revision: number,
    controller: AbortController,
  ): boolean {
    return (
      revision === requestRevision &&
      requestController === controller &&
      !controller.signal.aborted
    );
  }
}
function initialModel(scope: RuntimeInstancesScope): RuntimeInstancesModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'loading',
    reasonCode: reasonCodeFor(scope.authority),
    mutationState: 'idle',
    mutationReasonCode: null,
    busyInstanceId: null,
    retryVisible: false,
    allowedActions: actionsFor(scope.authority),
    instances: Object.freeze([]),
    total: 0,
    query: DEFAULT_QUERY,
    lastUpdatedAt: null,
  });
}

function loadedModel(
  scope: RuntimeInstancesScope,
  query: RuntimeInstancesNormalizedQuery,
  page: RuntimeInstancesPage,
): RuntimeInstancesModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: page.instances.length === 0 ? 'empty' : 'ready',
    reasonCode: reasonCodeFor(scope.authority),
    mutationState: 'idle',
    mutationReasonCode: null,
    busyInstanceId: null,
    retryVisible: false,
    allowedActions: actionsFor(scope.authority),
    instances: page.instances,
    total: page.total,
    query: Object.freeze({
      ...query,
      page: page.page,
      pageSize: page.pageSize,
    }),
    lastUpdatedAt: new Date().toISOString(),
  });
}

function loadErrorModel(
  stable: RuntimeInstancesModel,
  scope: RuntimeInstancesScope,
  query: RuntimeInstancesNormalizedQuery,
  error: unknown,
): RuntimeInstancesModel {
  const classified = classifyError(error, 'runtime_instances_load_failed');
  const hasStableRows =
    stable.scope.authority === scope.authority &&
    stable.scope.tenantId === scope.tenantId &&
    stable.instances.length > 0;
  return Object.freeze({
    ...stable,
    scope,
    authority: scope.authority,
    state: hasStableRows ? 'stale' : classified.resourceState,
    reasonCode: hasStableRows
      ? 'runtime_instances_load_failed'
      : classified.reasonCode,
    mutationState: 'idle',
    mutationReasonCode: null,
    busyInstanceId: null,
    retryVisible: true,
    allowedActions: actionsFor(scope.authority),
    instances: hasStableRows ? stable.instances : Object.freeze([]),
    total: hasStableRows ? stable.total : 0,
    query,
  });
}

function mutationErrorModel(
  stable: RuntimeInstancesModel,
  error: unknown,
): RuntimeInstancesModel {
  const classified = classifyError(error, 'runtime_instances_mutation_failed');
  return Object.freeze({
    ...stable,
    mutationState: classified.mutationState,
    mutationReasonCode: classified.reasonCode,
    busyInstanceId: null,
  });
}

function classifyError(
  error: unknown,
  fallback: string,
): Readonly<{
  resourceState: RuntimeInstancesResourceState;
  mutationState: RuntimeInstancesMutationState;
  reasonCode: string;
}> {
  if (error instanceof RuntimeInstancesUnavailableError) {
    return Object.freeze({
      resourceState: 'unavailable',
      mutationState: 'unavailable',
      reasonCode: error.reasonCode,
    });
  }
  if (error instanceof DesktopApiError && error.status === 403) {
    return Object.freeze({
      resourceState: 'forbidden',
      mutationState: 'forbidden',
      reasonCode: 'runtime_instances_forbidden',
    });
  }
  if (error instanceof DesktopApiError && error.status === 409) {
    return Object.freeze({
      resourceState: 'error',
      mutationState: 'conflict',
      reasonCode: 'runtime_instances_conflict',
    });
  }
  return Object.freeze({
    resourceState: 'error',
    mutationState: 'error',
    reasonCode: fallback,
  });
}

function unavailableModel(
  scope: RuntimeInstancesScope,
  query: RuntimeInstancesNormalizedQuery,
  reasonCode: string,
): RuntimeInstancesModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'unavailable',
    reasonCode,
    mutationState: 'unavailable',
    mutationReasonCode: reasonCode,
    busyInstanceId: null,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    instances: Object.freeze([]),
    total: 0,
    query,
    lastUpdatedAt: null,
  });
}

function visibleInstance(
  instances: readonly RuntimeInstanceSummary[],
  instanceId: string,
): RuntimeInstanceSummary {
  const instance = instances.find((candidate) => candidate.id === instanceId);
  if (!instance) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_instance_not_visible',
    );
  }
  return instance;
}

function normalizeQuery(
  query: RuntimeInstancesQuery,
): RuntimeInstancesNormalizedQuery {
  const page = query.page ?? DEFAULT_QUERY.page;
  const pageSize = query.pageSize ?? DEFAULT_QUERY.pageSize;
  const search = (query.search ?? DEFAULT_QUERY.search).trim();
  const status = (query.status ?? DEFAULT_QUERY.status).trim();
  if (
    !Number.isInteger(page) ||
    page < 1 ||
    !Number.isInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100 ||
    search.length > 200 ||
    !status
  ) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_query_invalid',
    );
  }
  return Object.freeze({ page, pageSize, search, status });
}

function freezeScope(scope: RuntimeInstancesScope): RuntimeInstancesScope {
  if (!scope.tenantId || scope.tenantId !== scope.tenantId.trim()) {
    throw new RuntimeInstancesUnavailableError(
      'runtime_instances_tenant_scope_invalid',
    );
  }
  return Object.freeze({ ...scope });
}

function actionsFor(authority: RuntimeInstancesAuthority): readonly string[] {
  return authority === 'cloud'
    ? RUNTIME_INSTANCES_CLOUD_ACTIONS
    : RUNTIME_INSTANCES_LOCAL_ACTIONS;
}

function reasonCodeFor(authority: RuntimeInstancesAuthority): string {
  return authority === 'cloud'
    ? 'runtime_instances_nested_routes_partial'
    : 'local_instance_sidecar_projection_partial';
}
