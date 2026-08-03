import { DesktopApiError } from '../../api/client';
import type {
  TenantAgentConfig,
  TenantAgentDashboardAction,
  TenantAgentDashboardAuthority,
  TenantAgentDashboardClient,
  TenantAgentDashboardScope,
  TenantAgentDashboardSnapshot,
  TenantAgentEditableConfig,
  TenantAgentRun,
  TenantAgentTrace,
  TenantRuntimeHookCatalogEntry,
} from './tenantAgentDashboardClient';

export type TenantAgentDashboardViewState =
  | 'loading'
  | 'empty'
  | 'ready'
  | 'stale'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type TenantAgentDashboardFilters = Readonly<{
  status: string | null;
  search: string;
}>;

export type TenantAgentDashboardViewModel = Readonly<{
  state: TenantAgentDashboardViewState;
  scope: TenantAgentDashboardScope;
  authority: TenantAgentDashboardAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: 'load' | 'update' | 'trace' | null;
  allowedActions: readonly TenantAgentDashboardAction[];
  authorityRevision: number | null;
  canModify: boolean;
  config: TenantAgentConfig | null;
  hookCatalog: readonly TenantRuntimeHookCatalogEntry[];
  runs: readonly TenantAgentRun[];
  visibleRuns: readonly TenantAgentRun[];
  activeRunCount: number;
  filters: TenantAgentDashboardFilters;
  selectedRunId: string | null;
  selectedTrace: TenantAgentTrace | null;
}>;

export type TenantAgentDashboardController = Readonly<{
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => TenantAgentDashboardViewModel;
  load: (scope: TenantAgentDashboardScope) => Promise<void>;
  retry: () => Promise<void>;
  setFilters: (filters: TenantAgentDashboardFilters) => void;
  inspectRun: (runId: string) => Promise<void>;
  clearSelection: () => void;
  updateConfig: (input: TenantAgentEditableConfig) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createTenantAgentDashboardController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: TenantAgentDashboardAuthority;
  client: TenantAgentDashboardClient;
  initialScope: TenantAgentDashboardScope;
}>): TenantAgentDashboardController {
  const listeners = new Set<() => void>();
  let requestGeneration = 0;
  let abortController: AbortController | null = null;
  let stopped = false;
  let model = createInitialView(authority, initialScope);

  const publish = (next: TenantAgentDashboardViewModel): void => {
    model = next;
    for (const listener of listeners) listener();
  };

  const load = async (scope: TenantAgentDashboardScope): Promise<void> => {
    validateScope(authority, scope);
    const generation = beginRequest();
    const hadData = model.config !== null || model.runs.length > 0;
    publish({
      ...model,
      scope,
      state: hadData ? model.state : 'loading',
      busyAction: 'load',
      reasonCode: null,
      retryVisible: false,
    });
    try {
      const snapshot = await client.load(scope, abortController?.signal);
      if (!isActive(generation)) return;
      publish(projectSnapshot(snapshot, model.filters));
    } catch (error) {
      if (!isActive(generation)) return;
      publish(projectFailure(model, error, hadData));
      throw error;
    }
  };

  const beginRequest = (): number => {
    abortController?.abort();
    abortController = new AbortController();
    requestGeneration += 1;
    return requestGeneration;
  };

  const isActive = (generation: number): boolean =>
    !stopped && generation === requestGeneration && !abortController?.signal.aborted;

  const controller: TenantAgentDashboardController = Object.freeze({
    subscribe(listener) {
      if (stopped) return () => {};
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot() {
      return model;
    },
    load,
    async retry() {
      await load(model.scope);
    },
    setFilters(filters) {
      validateFilters(filters);
      publish({
        ...model,
        filters: Object.freeze({ ...filters }),
        visibleRuns: filterRuns(model.runs, filters),
      });
    },
    async inspectRun(runId) {
      const run = model.runs.find((candidate) => candidate.runId === runId);
      if (!run) throw new Error('tenant_agent_dashboard_run_not_found');
      publish({ ...model, selectedRunId: runId, selectedTrace: null });
      if (!run.traceId) {
        publish({
          ...model,
          selectedRunId: runId,
          selectedTrace: Object.freeze({
            traceId: null,
            conversationId: run.conversationId,
            runs: Object.freeze([run]),
            total: 1,
          }),
        });
        return;
      }
      const generation = beginRequest();
      publish({ ...model, selectedRunId: runId, busyAction: 'trace' });
      try {
        const trace = await client.inspectTrace(
          model.scope,
          run.conversationId,
          run.traceId,
          abortController?.signal,
        );
        if (!isActive(generation)) return;
        publish({ ...model, busyAction: null, selectedTrace: trace });
      } catch (error) {
        if (!isActive(generation)) return;
        publish({
          ...model,
          busyAction: null,
          state: 'stale',
          reasonCode: errorReason(error, 'tenant_agent_dashboard_trace_unavailable'),
          retryVisible: true,
        });
        throw error;
      }
    },
    clearSelection() {
      abortController?.abort();
      requestGeneration += 1;
      publish({
        ...model,
        busyAction: null,
        selectedRunId: null,
        selectedTrace: null,
      });
    },
    async updateConfig(input) {
      if (
        !model.allowedActions.includes('update-config') ||
        model.authorityRevision === null
      ) {
        throw new Error('tenant_agent_dashboard_update_forbidden');
      }
      const generation = beginRequest();
      publish({ ...model, busyAction: 'update', reasonCode: null });
      try {
        const config = await client.updateConfig(
          model.scope,
          input,
          model.authorityRevision,
          abortController?.signal,
        );
        if (!isActive(generation)) return;
        publish({
          ...model,
          state: model.runs.length === 0 ? 'empty' : 'ready',
          busyAction: null,
          reasonCode: null,
          retryVisible: false,
          config,
          authorityRevision: config.authorityRevision,
        });
      } catch (error) {
        if (!isActive(generation)) return;
        publish({
          ...model,
          state:
            error instanceof DesktopApiError && error.status === 409
              ? 'conflict'
              : 'stale',
          busyAction: null,
          reasonCode: errorReason(error, 'tenant_agent_dashboard_update_unavailable'),
          retryVisible: true,
        });
        throw error;
      }
    },
    cancel() {
      abortController?.abort();
      requestGeneration += 1;
      publish({ ...model, busyAction: null });
    },
    stop() {
      if (stopped) return;
      stopped = true;
      abortController?.abort();
      requestGeneration += 1;
      listeners.clear();
    },
  });
  return controller;
}

export function createUnavailableTenantAgentDashboardView(
  scope: TenantAgentDashboardScope,
  reasonCode: string,
): TenantAgentDashboardViewModel {
  return Object.freeze({
    ...createInitialView(scope.authority, scope),
    state: 'unavailable',
    reasonCode,
    retryVisible: false,
  });
}

function createInitialView(
  authority: TenantAgentDashboardAuthority,
  scope: TenantAgentDashboardScope,
): TenantAgentDashboardViewModel {
  const filters = Object.freeze({ status: null, search: '' });
  return Object.freeze({
    state: 'loading',
    scope,
    authority,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    authorityRevision: null,
    canModify: false,
    config: null,
    hookCatalog: Object.freeze([]),
    runs: Object.freeze([]),
    visibleRuns: Object.freeze([]),
    activeRunCount: 0,
    filters,
    selectedRunId: null,
    selectedTrace: null,
  });
}

function projectSnapshot(
  snapshot: TenantAgentDashboardSnapshot,
  filters: TenantAgentDashboardFilters,
): TenantAgentDashboardViewModel {
  const state =
    snapshot.availability === 'unavailable' ||
    snapshot.availability === 'not_applicable'
      ? 'unavailable'
      : snapshot.runs.length === 0
        ? 'empty'
        : 'ready';
  return Object.freeze({
    state,
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: state === 'unavailable',
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    authorityRevision: snapshot.authorityRevision,
    canModify: snapshot.canModify,
    config: snapshot.config,
    hookCatalog: snapshot.hookCatalog,
    runs: snapshot.runs,
    visibleRuns: filterRuns(snapshot.runs, filters),
    activeRunCount: snapshot.activeRunCount,
    filters,
    selectedRunId: null,
    selectedTrace: null,
  });
}

function projectFailure(
  previous: TenantAgentDashboardViewModel,
  error: unknown,
  hadData: boolean,
): TenantAgentDashboardViewModel {
  const forbidden = error instanceof DesktopApiError && error.status === 403;
  return Object.freeze({
    ...previous,
    state: forbidden ? 'forbidden' : hadData ? 'stale' : 'unavailable',
    busyAction: null,
    reasonCode: errorReason(error, 'tenant_agent_dashboard_authority_unavailable'),
    retryVisible: !forbidden,
  });
}

function filterRuns(
  runs: readonly TenantAgentRun[],
  filters: TenantAgentDashboardFilters,
): readonly TenantAgentRun[] {
  const search = filters.search.trim().toLocaleLowerCase();
  return Object.freeze(
    runs.filter((run) => {
      if (filters.status && run.status !== filters.status) return false;
      if (!search) return true;
      return [run.subagentName, run.task, run.runId, run.conversationId]
        .join('\n')
        .toLocaleLowerCase()
        .includes(search);
    }),
  );
}

function validateScope(
  authority: TenantAgentDashboardAuthority,
  scope: TenantAgentDashboardScope,
): void {
  if (scope.authority !== authority || !scope.tenantId) {
    throw new Error('tenant_agent_dashboard_scope_invalid');
  }
}

function validateFilters(filters: TenantAgentDashboardFilters): void {
  if (
    (filters.status !== null && !filters.status.trim()) ||
    typeof filters.search !== 'string'
  ) {
    throw new Error('tenant_agent_dashboard_filters_invalid');
  }
}

function errorReason(error: unknown, fallback: string): string {
  if (
    error instanceof DesktopApiError &&
    typeof error.payload === 'object' &&
    error.payload !== null &&
    'reason_code' in error.payload &&
    typeof error.payload.reason_code === 'string'
  ) {
    return error.payload.reason_code;
  }
  return fallback;
}
