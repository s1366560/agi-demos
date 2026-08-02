import { DesktopApiError } from '../../api/client';
import {
  RUNTIME_CLUSTERS_CLOUD_ACTIONS,
} from './runtimeClustersCapability';
import { RuntimeClustersUnavailableError } from './runtimeClustersClient';
import type {
  RuntimeClusterSummary,
  RuntimeClustersAuthority,
  RuntimeClustersClient,
  RuntimeClustersHealthState,
  RuntimeClustersModel,
  RuntimeClustersNormalizedQuery,
  RuntimeClustersPage,
  RuntimeClustersQuery,
  RuntimeClustersResourceState,
  RuntimeClustersScope,
} from './runtimeClustersTypes';

export type RuntimeClustersController = Readonly<{
  getSnapshot(): RuntimeClustersModel;
  subscribe(listener: () => void): () => void;
  load(scope: RuntimeClustersScope, query?: RuntimeClustersQuery): Promise<void>;
  retry(): Promise<void>;
  setQuery(query: RuntimeClustersQuery): Promise<void>;
  setFilters(query: RuntimeClustersQuery): Promise<void>;
  inspectHealth(clusterId: string): Promise<void>;
  closeHealth(): void;
  cancel(): void;
  stop(): void;
}>;

const DEFAULT_QUERY: RuntimeClustersNormalizedQuery = Object.freeze({
  page: 1,
  pageSize: 20,
  search: '',
  status: 'all',
});

export function createRuntimeClustersController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: RuntimeClustersAuthority;
  client: RuntimeClustersClient;
  initialScope: RuntimeClustersScope;
}>): RuntimeClustersController {
  let activeScope = freezeScope(initialScope);
  let activeQuery = DEFAULT_QUERY;
  let model =
    authority === 'local'
      ? unavailableModel(activeScope, activeQuery)
      : loadingModel(activeScope, activeQuery);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: RuntimeClustersModel): void => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: RuntimeClustersScope,
    query: RuntimeClustersQuery = activeQuery,
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
          'runtime_clusters_controller_authority_mismatch',
        ),
      );
      return;
    }
    if (scope.authority === 'local') {
      cancel();
      emit(unavailableModel(scope, normalizedQuery));
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
      reasonCode: cloudReasonCode(),
      healthState: 'idle',
      healthReasonCode: null,
      selectedClusterId: null,
      retryVisible: false,
      health: null,
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
  const setFilters = async (query: RuntimeClustersQuery): Promise<void> => {
    activeQuery = normalizeQuery({ ...activeQuery, ...query });
    emit({
      ...model,
      query: activeQuery,
      visibleClusters: visibleClusters(model.clusters, activeQuery),
    });
  };
  const inspectHealth = async (clusterId: string): Promise<void> => {
    if (authority !== 'cloud') {
      throw new RuntimeClustersUnavailableError(
        'cloud_cluster_control_not_applicable',
      );
    }
    const id = visibleCluster(model.clusters, clusterId).id;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({
      ...model,
      selectedClusterId: id,
      healthState: 'loading',
      healthReasonCode: null,
      health: null,
    });
    try {
      const health = await client.getHealth(activeScope, id, {
        signal: controller.signal,
      });
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      emit({
        ...model,
        selectedClusterId: id,
        healthState: 'ready',
        healthReasonCode: null,
        health,
      });
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) throw error;
      requestController = null;
      const classified = classifyError(
        error,
        'runtime_clusters_health_failed',
      );
      emit({
        ...model,
        selectedClusterId: id,
        healthState: healthState(classified.resourceState),
        healthReasonCode: classified.reasonCode,
        health: null,
      });
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
    setFilters,
    inspectHealth,
    closeHealth() {
      emit({
        ...model,
        selectedClusterId: null,
        healthState: 'idle',
        healthReasonCode: null,
        health: null,
      });
    },
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

function loadingModel(
  scope: RuntimeClustersScope,
  query: RuntimeClustersNormalizedQuery,
): RuntimeClustersModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'loading',
    reasonCode: cloudReasonCode(),
    healthState: 'idle',
    healthReasonCode: null,
    selectedClusterId: null,
    retryVisible: false,
    allowedActions: RUNTIME_CLUSTERS_CLOUD_ACTIONS,
    clusters: Object.freeze([]),
    visibleClusters: Object.freeze([]),
    health: null,
    total: 0,
    query,
    lastUpdatedAt: null,
  });
}

function unavailableModel(
  scope: RuntimeClustersScope,
  query: RuntimeClustersNormalizedQuery,
  reasonCode = 'cloud_cluster_control_not_applicable',
): RuntimeClustersModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: 'unavailable',
    reasonCode,
    healthState: 'unavailable',
    healthReasonCode: reasonCode,
    selectedClusterId: null,
    retryVisible: false,
    allowedActions: Object.freeze([]),
    clusters: Object.freeze([]),
    visibleClusters: Object.freeze([]),
    health: null,
    total: 0,
    query,
    lastUpdatedAt: null,
  });
}

function loadedModel(
  scope: RuntimeClustersScope,
  query: RuntimeClustersNormalizedQuery,
  page: RuntimeClustersPage,
): RuntimeClustersModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    state: page.clusters.length === 0 ? 'empty' : 'ready',
    reasonCode: cloudReasonCode(),
    healthState: 'idle',
    healthReasonCode: null,
    selectedClusterId: null,
    retryVisible: false,
    allowedActions: RUNTIME_CLUSTERS_CLOUD_ACTIONS,
    clusters: page.clusters,
    visibleClusters: visibleClusters(page.clusters, query),
    health: null,
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
  stable: RuntimeClustersModel,
  scope: RuntimeClustersScope,
  query: RuntimeClustersNormalizedQuery,
  error: unknown,
): RuntimeClustersModel {
  const classified = classifyError(error, 'runtime_clusters_load_failed');
  const hasStableRows =
    stable.scope.authority === scope.authority &&
    stable.scope.tenantId === scope.tenantId &&
    stable.clusters.length > 0;
  const clusters = hasStableRows ? stable.clusters : Object.freeze([]);
  return Object.freeze({
    ...stable,
    scope,
    authority: scope.authority,
    state: hasStableRows ? 'stale' : classified.resourceState,
    reasonCode: hasStableRows
      ? 'runtime_clusters_load_failed'
      : classified.reasonCode,
    healthState: 'idle',
    healthReasonCode: null,
    selectedClusterId: null,
    retryVisible: true,
    allowedActions: RUNTIME_CLUSTERS_CLOUD_ACTIONS,
    clusters,
    visibleClusters: visibleClusters(clusters, query),
    health: null,
    total: hasStableRows ? stable.total : 0,
    query,
  });
}

function visibleClusters(
  clusters: readonly RuntimeClusterSummary[],
  query: RuntimeClustersNormalizedQuery,
): readonly RuntimeClusterSummary[] {
  const search = query.search.toLocaleLowerCase();
  return Object.freeze(
    clusters.filter((cluster) => {
      if (query.status !== 'all' && cluster.status !== query.status) return false;
      if (!search) return true;
      return `${cluster.name} ${cluster.computeProvider}`
        .toLocaleLowerCase()
        .includes(search);
    }),
  );
}

function visibleCluster(
  clusters: readonly RuntimeClusterSummary[],
  clusterId: string,
): RuntimeClusterSummary {
  const id = clusterId.trim();
  const cluster = clusters.find((candidate) => candidate.id === id);
  if (!cluster) {
    throw new RuntimeClustersUnavailableError(
      'runtime_clusters_cluster_not_visible',
    );
  }
  return cluster;
}

function normalizeQuery(
  query: RuntimeClustersQuery,
): RuntimeClustersNormalizedQuery {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 20;
  const search = (query.search ?? '').trim();
  const status = (query.status ?? 'all').trim();
  if (
    !Number.isInteger(page) ||
    page < 1 ||
    !Number.isInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100 ||
    search.length > 200 ||
    !status
  ) {
    throw new RuntimeClustersUnavailableError(
      'runtime_clusters_query_invalid',
    );
  }
  return Object.freeze({ page, pageSize, search, status });
}

function classifyError(
  error: unknown,
  fallback: string,
): Readonly<{
  resourceState: RuntimeClustersResourceState;
  reasonCode: string;
}> {
  if (error instanceof DesktopApiError && error.status === 403) {
    return Object.freeze({
      resourceState: 'forbidden',
      reasonCode: 'runtime_clusters_forbidden',
    });
  }
  if (error instanceof DesktopApiError && error.status === 409) {
    return Object.freeze({
      resourceState: 'conflict',
      reasonCode: 'runtime_clusters_conflict',
    });
  }
  if (error instanceof RuntimeClustersUnavailableError) {
    return Object.freeze({
      resourceState: 'unavailable',
      reasonCode: error.reasonCode,
    });
  }
  return Object.freeze({ resourceState: 'error', reasonCode: fallback });
}

function healthState(
  resourceState: RuntimeClustersResourceState,
): RuntimeClustersHealthState {
  if (
    resourceState === 'conflict' ||
    resourceState === 'forbidden' ||
    resourceState === 'unavailable'
  ) {
    return resourceState;
  }
  return 'error';
}

function freezeScope(scope: RuntimeClustersScope): RuntimeClustersScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
  });
}

function cloudReasonCode(): string {
  return 'runtime_clusters_detail_and_mutations_partial';
}
