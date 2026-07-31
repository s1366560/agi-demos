import { DesktopApiError } from '../../api/client';
import type {
  TenantTaskRecord,
  TenantTaskStats,
  TenantTasksAuthority,
  TenantTasksClient,
  TenantTasksQuery,
  TenantTasksScope,
  TenantTasksSnapshot,
} from './tenantTasksClient';

export type TenantTasksViewState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'degraded'
  | 'empty'
  | 'stale'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type TenantTasksViewModel = Readonly<{
  state: TenantTasksViewState;
  scope: TenantTasksScope;
  authority: TenantTasksAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  stats: TenantTaskStats;
  queue: TenantTasksSnapshot['queue'];
  tasks: TenantTasksSnapshot['tasks'];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
  query: Required<TenantTasksQuery>;
  lastUpdatedAt: string | null;
}>;

export type TenantTasksController = Readonly<{
  getSnapshot: () => TenantTasksViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TenantTasksScope, query?: TenantTasksQuery) => Promise<void>;
  retry: () => Promise<void>;
  setQuery: (query: TenantTasksQuery) => Promise<void>;
  retryTask: (taskId: string) => Promise<void>;
  stopTask: (taskId: string) => Promise<void>;
  retryPending: (limit?: number) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

const EMPTY_STATS: TenantTaskStats = Object.freeze({
  total: 0,
  pending: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  throughputPerMinute: 0,
  errorRate: 0,
});
const EMPTY_QUEUE = Object.freeze({ current: 0, history: Object.freeze([]) });
const DEFAULT_QUERY = Object.freeze({
  search: '',
  status: 'all',
  limit: 50,
  offset: 0,
});

export function createTenantTasksController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: TenantTasksAuthority;
  client: TenantTasksClient;
  initialScope: TenantTasksScope;
}>): TenantTasksController {
  let activeScope = freezeScope(initialScope);
  let activeQuery: Required<TenantTasksQuery> = DEFAULT_QUERY;
  let model = loadingModel(activeScope, activeQuery, false);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: TenantTasksViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: TenantTasksScope,
    query: TenantTasksQuery = activeQuery,
  ) => {
    const scope = freezeScope(nextScope);
    const normalizedQuery = normalizeQuery(query);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    activeQuery = normalizedQuery;
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    if (scope.authority !== authority) {
      requestController = null;
      emit(
        terminalModel(
          scope,
          normalizedQuery,
          'unavailable',
          'tenant_tasks_controller_authority_mismatch',
        ),
      );
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(loadingModel(scope, normalizedQuery, scopeSwitch));
    try {
      const snapshot = await client.load(scope, normalizedQuery, {
        signal: controller.signal,
      });
      if (!requestIsCurrent(revision, controller)) return;
      emit(readyModel(snapshot, normalizedQuery));
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) return;
      emit(loadErrorModel(error, scope, normalizedQuery, stable));
    } finally {
      if (requestIsCurrent(revision, controller)) requestController = null;
    }
  };
  const mutate = async (
    action: 'retry-task' | 'stop-task',
    taskId: string,
  ): Promise<void> => {
    if (model.busyAction !== null)
      throw new Error('tenant_tasks_mutation_in_progress');
    if (!model.allowedActions.includes(action)) {
      throw new Error(`tenant_tasks_action_unavailable:${action}`);
    }
    const task = requiredTask(model.tasks, taskId);
    if (
      (action === 'retry-task' && !task.canRetry) ||
      (action === 'stop-task' && !task.canStop)
    ) {
      throw new Error(`tenant_tasks_action_unavailable:${action}`);
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(
      Object.freeze({
        ...stable,
        busyAction: `${action}:${taskId}`,
        reasonCode: null,
      }),
    );
    try {
      if (action === 'retry-task') {
        await client.retryTask(activeScope, task, {
          signal: controller.signal,
        });
      } else {
        await client.stopTask(activeScope, task, { signal: controller.signal });
      }
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      await load(activeScope, activeQuery);
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) throw error;
      requestController = null;
      emit(mutationErrorModel(error, stable));
      throw error;
    }
  };
  const retryPending = async (limit = 5): Promise<void> => {
    if (model.busyAction !== null)
      throw new Error('tenant_tasks_mutation_in_progress');
    if (!model.allowedActions.includes('retry-pending')) {
      throw new Error('tenant_tasks_action_unavailable:retry-pending');
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(
      Object.freeze({
        ...stable,
        busyAction: 'retry-pending',
        reasonCode: null,
      }),
    );
    try {
      await client.retryPending(activeScope, limit, {
        signal: controller.signal,
      });
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      await load(activeScope, activeQuery);
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) throw error;
      requestController = null;
      emit(mutationErrorModel(error, stable));
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
    retryTask: (taskId) => mutate('retry-task', taskId),
    stopTask: (taskId) => mutate('stop-task', taskId),
    retryPending,
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
  scope: TenantTasksScope,
  query: Required<TenantTasksQuery>,
  scopeSwitch: boolean,
): TenantTasksViewModel {
  return Object.freeze({
    state: scopeSwitch ? 'scope_switch' : 'loading',
    scope,
    authority: scope.authority,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    stats: EMPTY_STATS,
    queue: EMPTY_QUEUE,
    tasks: Object.freeze([]),
    total: 0,
    limit: query.limit,
    offset: query.offset,
    hasMore: false,
    query,
    lastUpdatedAt: null,
  });
}

function readyModel(
  snapshot: TenantTasksSnapshot,
  query: Required<TenantTasksQuery>,
): TenantTasksViewModel {
  return Object.freeze({
    state:
      snapshot.availability === 'degraded'
        ? 'degraded'
        : snapshot.tasks.length === 0
          ? 'empty'
          : 'ready',
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    stats: snapshot.stats,
    queue: snapshot.queue,
    tasks: snapshot.tasks,
    total: snapshot.total,
    limit: snapshot.limit,
    offset: snapshot.offset,
    hasMore: snapshot.hasMore,
    query,
    lastUpdatedAt: new Date().toISOString(),
  });
}

function terminalModel(
  scope: TenantTasksScope,
  query: Required<TenantTasksQuery>,
  state: Extract<
    TenantTasksViewState,
    'error' | 'conflict' | 'forbidden' | 'unavailable'
  >,
  reasonCode: string,
  retryVisible = false,
): TenantTasksViewModel {
  return Object.freeze({
    ...loadingModel(scope, query, false),
    state,
    reasonCode,
    retryVisible,
  });
}

function loadErrorModel(
  error: unknown,
  scope: TenantTasksScope,
  query: Required<TenantTasksQuery>,
  stable: TenantTasksViewModel,
): TenantTasksViewModel {
  const reasonCode = errorReason(error, 'tenant_tasks_request_failed');
  if (stable.lastUpdatedAt !== null && sameScope(stable.scope, scope)) {
    return Object.freeze({
      ...stable,
      state: 'stale',
      reasonCode,
      retryVisible: true,
      busyAction: null,
      query,
    });
  }
  if (error instanceof DesktopApiError && error.status === 403) {
    return terminalModel(scope, query, 'forbidden', reasonCode);
  }
  if (
    error instanceof DesktopApiError &&
    (error.status === 0 || error.status === 501 || error.status === 503)
  ) {
    return terminalModel(
      scope,
      query,
      'unavailable',
      reasonCode,
      error.status === 503,
    );
  }
  return terminalModel(scope, query, 'error', reasonCode, isRetryable(error));
}

function mutationErrorModel(
  error: unknown,
  stable: TenantTasksViewModel,
): TenantTasksViewModel {
  return Object.freeze({
    ...stable,
    state:
      error instanceof DesktopApiError && error.status === 409
        ? 'conflict'
        : error instanceof DesktopApiError && error.status === 403
          ? 'forbidden'
          : stable.state,
    reasonCode: errorReason(error, 'tenant_task_mutation_failed'),
    retryVisible: isRetryable(error),
    busyAction: null,
  });
}

function requiredTask(
  tasks: readonly TenantTaskRecord[],
  taskId: string,
): TenantTaskRecord {
  const task = tasks.find((candidate) => candidate.id === taskId);
  if (!task) throw new Error('tenant_tasks_task_not_found');
  return task;
}

function errorReason(error: unknown, fallback: string): string {
  if (
    error instanceof DesktopApiError &&
    isRecord(error.payload) &&
    typeof error.payload.reason_code === 'string' &&
    error.payload.reason_code.trim()
  ) {
    return error.payload.reason_code;
  }
  return fallback;
}

function isRetryable(error: unknown): boolean {
  return (
    error instanceof DesktopApiError &&
    (error.status === 408 ||
      error.status === 425 ||
      error.status === 429 ||
      error.status >= 500)
  );
}

function normalizeQuery(query: TenantTasksQuery): Required<TenantTasksQuery> {
  return Object.freeze({
    search: query.search?.trim() ?? '',
    status: query.status?.trim().toLocaleLowerCase() || 'all',
    limit: query.limit ?? 50,
    offset: query.offset ?? 0,
  });
}

function freezeScope(scope: TenantTasksScope): TenantTasksScope {
  return Object.freeze({ ...scope });
}

function sameScope(left: TenantTasksScope, right: TenantTasksScope): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
