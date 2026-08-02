import { DesktopApiError } from '../../api/client';
import {
  RuntimePoolUnavailableError,
  type RuntimePoolAuthority,
  type RuntimePoolClient,
  type RuntimePoolInstance,
  type RuntimePoolInstancePage,
  type RuntimePoolInstanceStatus,
  type RuntimePoolMetrics,
  type RuntimePoolQuery,
  type RuntimePoolScope,
  type RuntimePoolStatus,
  type RuntimePoolTier,
} from './runtimePoolClient';

export type RuntimePoolResourceState =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'forbidden'
  | 'unavailable';
export type RuntimePoolMutationState =
  | 'idle'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type RuntimePoolNormalizedQuery = Readonly<{
  tier: RuntimePoolTier | 'all';
  status: RuntimePoolInstanceStatus | 'all';
  page: number;
  pageSize: number;
}>;

export type RuntimePoolViewModel = Readonly<{
  scope: RuntimePoolScope;
  authority: RuntimePoolAuthority;
  statusState: RuntimePoolResourceState;
  instancesState: RuntimePoolResourceState;
  metricsState: RuntimePoolResourceState;
  statusReasonCode: string | null;
  instancesReasonCode: string | null;
  metricsReasonCode: string | null;
  mutationState: RuntimePoolMutationState;
  mutationReasonCode: string | null;
  retryStatusVisible: boolean;
  retryInstancesVisible: boolean;
  retryMetricsVisible: boolean;
  busyInstanceKey: string | null;
  allowedActions: readonly string[];
  status: RuntimePoolStatus | null;
  instances: readonly RuntimePoolInstance[];
  metrics: RuntimePoolMetrics | null;
  total: number;
  query: RuntimePoolNormalizedQuery;
  lastUpdatedAt: string | null;
}>;

export type RuntimePoolController = Readonly<{
  getSnapshot: () => RuntimePoolViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: RuntimePoolScope, query?: RuntimePoolQuery) => Promise<void>;
  retry: () => Promise<void>;
  setQuery: (query: RuntimePoolQuery) => Promise<void>;
  pauseInstance: (instanceKey: string) => Promise<void>;
  resumeInstance: (instanceKey: string) => Promise<void>;
  terminateInstance: (instanceKey: string) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

const DEFAULT_QUERY: RuntimePoolNormalizedQuery = Object.freeze({
  tier: 'all',
  status: 'all',
  page: 1,
  pageSize: 20,
});
const CLOUD_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'toggle-auto-refresh',
  'list-instances',
  'search-current-page',
  'filter-by-tier',
  'paginate-instances',
  'pause-instance',
  'resume-instance',
  'terminate-instance',
  'retry-list-instances',
  'inspect-pool-status',
]);

export function createRuntimePoolController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: RuntimePoolAuthority;
  client: RuntimePoolClient;
  initialScope: RuntimePoolScope;
}>): RuntimePoolController {
  let activeScope = freezeScope(initialScope);
  let activeQuery = DEFAULT_QUERY;
  let model =
    authority === 'local'
      ? unavailableModel(activeScope, activeQuery)
      : loadingModel(activeScope, activeQuery);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: RuntimePoolViewModel): void => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: RuntimePoolScope,
    query: RuntimePoolQuery = activeQuery,
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
          'runtime_pool_controller_authority_mismatch',
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
      authority: scope.authority,
      statusState: 'loading',
      instancesState: 'loading',
      metricsState: 'loading',
      statusReasonCode: null,
      instancesReasonCode: null,
      metricsReasonCode: null,
      mutationState: 'idle',
      mutationReasonCode: null,
      retryStatusVisible: false,
      retryInstancesVisible: false,
      retryMetricsVisible: false,
      busyInstanceKey: null,
      query: normalizedQuery,
    });
    const [statusResult, instancesResult, metricsResult] =
      await Promise.allSettled([
        client.getStatus(scope, { signal: controller.signal }),
        client.listInstances(scope, normalizedQuery, {
          signal: controller.signal,
        }),
        client.getMetrics(scope, { signal: controller.signal }),
      ]);
    if (!requestIsCurrent(revision, controller)) return;
    requestController = null;
    emit(
      settleLoad(
        stable,
        scope,
        normalizedQuery,
        statusResult,
        instancesResult,
        metricsResult,
      ),
    );
  };

  const mutate = async (
    instanceKey: string,
    operation: (signal: AbortSignal) => Promise<void>,
  ): Promise<void> => {
    const key = requireVisibleInstance(
      model.instances,
      instanceKey,
    ).instanceKey;
    if (model.busyInstanceKey !== null) {
      throw new Error('runtime_pool_mutation_in_progress');
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({
      ...stable,
      busyInstanceKey: key,
      mutationState: 'idle',
      mutationReasonCode: null,
    });
    try {
      await operation(controller.signal);
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      emit({ ...model, busyInstanceKey: null });
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
    pauseInstance: (instanceKey) =>
      mutate(instanceKey, (signal) =>
        client.pauseInstance(activeScope, instanceKey, { signal }),
      ),
    resumeInstance: (instanceKey) =>
      mutate(instanceKey, (signal) =>
        client.resumeInstance(activeScope, instanceKey, { signal }),
      ),
    terminateInstance: (instanceKey) =>
      mutate(instanceKey, (signal) =>
        client.terminateInstance(activeScope, instanceKey, true, { signal }),
      ),
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

function settleLoad(
  stable: RuntimePoolViewModel,
  scope: RuntimePoolScope,
  query: RuntimePoolNormalizedQuery,
  statusResult: PromiseSettledResult<RuntimePoolStatus>,
  instancesResult: PromiseSettledResult<RuntimePoolInstancePage>,
  metricsResult: PromiseSettledResult<RuntimePoolMetrics>,
): RuntimePoolViewModel {
  const status = settleResource(stable.status, statusResult);
  const instances = settleResource(
    Object.freeze({
      instances: stable.instances,
      total: stable.total,
      page: stable.query.page,
      pageSize: stable.query.pageSize,
    }),
    instancesResult,
    (value) => value.instances.length === 0,
  );
  const metrics = settleResource(stable.metrics, metricsResult);
  const verified = [statusResult, instancesResult, metricsResult].some(
    (result) => result.status === 'fulfilled',
  );
  return Object.freeze({
    scope,
    authority: scope.authority,
    statusState: status.state,
    instancesState: instances.state,
    metricsState: metrics.state,
    statusReasonCode: status.reasonCode,
    instancesReasonCode: instances.reasonCode,
    metricsReasonCode: metrics.reasonCode,
    mutationState: 'idle',
    mutationReasonCode: null,
    retryStatusVisible: status.state !== 'ready',
    retryInstancesVisible:
      instances.state !== 'ready' && instances.state !== 'empty',
    retryMetricsVisible: metrics.state !== 'ready',
    busyInstanceKey: null,
    allowedActions: CLOUD_ACTIONS,
    status: status.value,
    instances: instances.value?.instances ?? Object.freeze([]),
    metrics: metrics.value,
    total: instances.value?.total ?? 0,
    query,
    lastUpdatedAt: verified ? new Date().toISOString() : stable.lastUpdatedAt,
  });
}

function settleResource<T>(
  stable: T | null,
  result: PromiseSettledResult<T>,
  empty: (value: T) => boolean = () => false,
): Readonly<{
  state: RuntimePoolResourceState;
  reasonCode: string | null;
  value: T | null;
}> {
  if (result.status === 'fulfilled') {
    return Object.freeze({
      state: empty(result.value) ? 'empty' : 'ready',
      reasonCode: null,
      value: result.value,
    });
  }
  const error = result.reason;
  if (stable !== null) {
    return Object.freeze({
      state: 'stale',
      reasonCode: reasonCode(error),
      value: stable,
    });
  }
  return Object.freeze({
    state: resourceErrorState(error),
    reasonCode: reasonCode(error),
    value: null,
  });
}

function loadingModel(
  scope: RuntimePoolScope,
  query: RuntimePoolNormalizedQuery,
): RuntimePoolViewModel {
  return Object.freeze({
    ...baseModel(scope, query),
    statusState: 'loading',
    instancesState: 'loading',
    metricsState: 'loading',
  });
}

function unavailableModel(
  scope: RuntimePoolScope,
  query: RuntimePoolNormalizedQuery,
  reason = 'cloud_runtime_pool_not_applicable',
): RuntimePoolViewModel {
  return Object.freeze({
    ...baseModel(scope, query),
    statusState: 'unavailable',
    instancesState: 'unavailable',
    metricsState: 'unavailable',
    statusReasonCode: reason,
    instancesReasonCode: reason,
    metricsReasonCode: reason,
    mutationState: 'unavailable',
    mutationReasonCode: reason,
  });
}

function baseModel(
  scope: RuntimePoolScope,
  query: RuntimePoolNormalizedQuery,
): RuntimePoolViewModel {
  return {
    scope,
    authority: scope.authority,
    statusState: 'loading',
    instancesState: 'loading',
    metricsState: 'loading',
    statusReasonCode: null,
    instancesReasonCode: null,
    metricsReasonCode: null,
    mutationState: 'idle',
    mutationReasonCode: null,
    retryStatusVisible: false,
    retryInstancesVisible: false,
    retryMetricsVisible: false,
    busyInstanceKey: null,
    allowedActions: Object.freeze([]),
    status: null,
    instances: Object.freeze([]),
    metrics: null,
    total: 0,
    query,
    lastUpdatedAt: null,
  };
}

function mutationErrorModel(
  stable: RuntimePoolViewModel,
  error: unknown,
): RuntimePoolViewModel {
  return Object.freeze({
    ...stable,
    mutationState:
      error instanceof RuntimePoolUnavailableError
        ? 'unavailable'
        : error instanceof DesktopApiError && error.status === 403
          ? 'forbidden'
          : error instanceof DesktopApiError && error.status === 409
            ? 'conflict'
            : 'error',
    mutationReasonCode: reasonCode(error),
    busyInstanceKey: null,
  });
}

function resourceErrorState(error: unknown): RuntimePoolResourceState {
  if (error instanceof RuntimePoolUnavailableError) return 'unavailable';
  if (error instanceof DesktopApiError && error.status === 403) {
    return 'forbidden';
  }
  return 'error';
}

function reasonCode(error: unknown): string {
  if (
    error instanceof DesktopApiError &&
    isRecord(error.payload) &&
    typeof error.payload.reason_code === 'string' &&
    error.payload.reason_code
  ) {
    return error.payload.reason_code;
  }
  if (
    error instanceof DesktopApiError &&
    isRecord(error.payload) &&
    isRecord(error.payload.detail) &&
    typeof error.payload.detail.reason_code === 'string' &&
    error.payload.detail.reason_code
  ) {
    return error.payload.detail.reason_code;
  }
  if (error instanceof RuntimePoolUnavailableError) return error.reasonCode;
  return 'runtime_pool_authority_unavailable';
}

function normalizeQuery(query: RuntimePoolQuery): RuntimePoolNormalizedQuery {
  const tier = query.tier ?? 'all';
  const status = query.status ?? 'all';
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 20;
  if (
    !['all', 'hot', 'warm', 'cold'].includes(tier) ||
    !Number.isInteger(page) ||
    page < 1 ||
    !Number.isInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100
  ) {
    throw new Error('runtime_pool_query_invalid');
  }
  return Object.freeze({ tier, status, page, pageSize });
}

function requireVisibleInstance(
  instances: readonly RuntimePoolInstance[],
  instanceKey: string,
): RuntimePoolInstance {
  const instance = instances.find(
    (candidate) => candidate.instanceKey === instanceKey,
  );
  if (!instance) throw new Error('runtime_pool_instance_not_visible');
  return instance;
}

function freezeScope(scope: RuntimePoolScope): RuntimePoolScope {
  if (!scope.tenantId.trim() || scope.tenantId !== scope.tenantId.trim()) {
    throw new Error('runtime_pool_scope_invalid');
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
