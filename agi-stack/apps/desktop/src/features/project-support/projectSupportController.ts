import { DesktopApiError } from '../../api/client';
import type {
  ProjectSupportAuthority,
  ProjectSupportClient,
  ProjectSupportCreateInput,
  ProjectSupportListQuery,
  ProjectSupportListSnapshot,
  ProjectSupportScope,
} from './projectSupportTypes';

export type ProjectSupportViewState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'conflict'
  | 'forbidden'
  | 'unavailable'
  | 'not_applicable'
  | 'error';

export type ProjectSupportViewModel = Readonly<{
  state: ProjectSupportViewState;
  scope: ProjectSupportScope;
  authority: ProjectSupportAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: 'create' | 'close' | null;
  allowedActions: readonly string[];
  tickets: ProjectSupportListSnapshot['tickets'];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}>;

export type ProjectSupportController = Readonly<{
  getSnapshot: () => ProjectSupportViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (
    scope: ProjectSupportScope,
    query?: ProjectSupportListQuery,
  ) => Promise<void>;
  retry: () => Promise<void>;
  create: (input: ProjectSupportCreateInput) => Promise<void>;
  close: (ticketId: string) => Promise<void>;
  goToOffset: (offset: number) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createProjectSupportController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: ProjectSupportAuthority;
  client: ProjectSupportClient;
  initialScope: ProjectSupportScope;
}>): ProjectSupportController {
  let activeScope = freezeScope(initialScope);
  let activeQuery: ProjectSupportListQuery = Object.freeze({
    limit: 25,
    offset: 0,
  });
  let model = loadingModel(activeScope, false);
  let lastVerified: ProjectSupportViewModel | null = null;
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: ProjectSupportViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: ProjectSupportScope,
    nextQuery: ProjectSupportListQuery = activeQuery,
  ): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    activeQuery = Object.freeze({ ...nextQuery });
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== authority) {
      emit(terminalModel(scope, 'unavailable', 'project_support_controller_authority_mismatch'));
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(loadingModel(scope, scopeSwitch));
    try {
      const snapshot = await client.list(scope, activeQuery, {
        signal: controller.signal,
      });
      if (!isCurrent(revision, controller)) return;
      const next = readyModel(snapshot);
      lastVerified = next;
      emit(next);
    } catch (error) {
      if (!isCurrent(revision, controller)) return;
      emit(errorModel(error, scope, lastVerified));
    } finally {
      if (isCurrent(revision, controller)) requestController = null;
    }
  };
  const mutate = async (
    action: 'create' | 'close',
    operation: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<void> => {
    if (model.busyAction !== null) {
      throw new Error('project_support_mutation_in_progress');
    }
    requireAction(model, action);
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(Object.freeze({ ...stable, busyAction: action, reasonCode: null }));
    try {
      await operation(controller.signal);
      if (!isCurrent(revision, controller)) return;
      requestController = null;
      await load(activeScope, activeQuery);
    } catch (error) {
      if (!isCurrent(revision, controller)) throw error;
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
    create: (input) =>
      mutate('create', (signal) =>
        client.create(activeScope, input, { signal }),
      ),
    close: (ticketId) =>
      mutate('close', (signal) =>
        client.close(activeScope, ticketId, { signal }),
      ),
    goToOffset: (offset) =>
      load(activeScope, { ...activeQuery, offset }),
    cancel,
    stop: cancel,
  });

  function isCurrent(
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
  scope: ProjectSupportScope,
  scopeSwitch: boolean,
): ProjectSupportViewModel {
  return Object.freeze({
    state: scopeSwitch ? 'scope_switch' : 'loading',
    scope,
    authority: scope.authority,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    tickets: Object.freeze([]),
    total: 0,
    limit: 25,
    offset: 0,
    hasMore: false,
  });
}

function readyModel(
  snapshot: ProjectSupportListSnapshot,
): ProjectSupportViewModel {
  const state =
    snapshot.availability === 'not_applicable'
      ? 'not_applicable'
      : snapshot.availability === 'unavailable'
        ? 'unavailable'
        : snapshot.tickets.length === 0
          ? 'empty'
          : 'ready';
  return Object.freeze({
    state,
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    tickets: snapshot.tickets,
    total: snapshot.total,
    limit: snapshot.limit,
    offset: snapshot.offset,
    hasMore: snapshot.hasMore,
  });
}

function terminalModel(
  scope: ProjectSupportScope,
  state: Extract<
    ProjectSupportViewState,
    'conflict' | 'forbidden' | 'unavailable' | 'error'
  >,
  reasonCode: string,
  retryVisible = false,
): ProjectSupportViewModel {
  return Object.freeze({
    ...loadingModel(scope, false),
    state,
    reasonCode,
    retryVisible,
  });
}

function errorModel(
  error: unknown,
  scope: ProjectSupportScope,
  stable: ProjectSupportViewModel | null,
): ProjectSupportViewModel {
  const reasonCode = errorReason(error, 'project_support_request_failed');
  if (error instanceof DesktopApiError && error.status === 403) {
    return terminalModel(scope, 'forbidden', reasonCode);
  }
  if (stable && sameScope(stable.scope, scope)) {
    return Object.freeze({
      ...stable,
      state: 'stale',
      reasonCode,
      retryVisible: true,
      busyAction: null,
    });
  }
  if (
    error instanceof DesktopApiError &&
    (error.status === 0 || error.status === 501 || error.status === 503)
  ) {
    return terminalModel(
      scope,
      'unavailable',
      reasonCode,
      error.status === 503,
    );
  }
  return terminalModel(scope, 'error', reasonCode, isRetryable(error));
}

function mutationErrorModel(
  error: unknown,
  stable: ProjectSupportViewModel,
): ProjectSupportViewModel {
  const reasonCode = errorReason(error, 'project_support_mutation_failed');
  const state =
    error instanceof DesktopApiError && error.status === 409
      ? 'conflict'
      : error instanceof DesktopApiError && error.status === 403
        ? 'forbidden'
        : 'error';
  return Object.freeze({
    ...stable,
    state,
    reasonCode,
    retryVisible: isRetryable(error),
    busyAction: null,
  });
}

function requireAction(
  model: ProjectSupportViewModel,
  action: 'create' | 'close',
): void {
  if (!model.allowedActions.includes(action)) {
    throw new Error(`project_support_action_unavailable:${action}`);
  }
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
    !(error instanceof DesktopApiError) ||
    error.status === 0 ||
    error.status === 408 ||
    error.status === 425 ||
    error.status === 429 ||
    error.status >= 500
  );
}

function freezeScope(scope: ProjectSupportScope): ProjectSupportScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function sameScope(
  left: ProjectSupportScope,
  right: ProjectSupportScope,
): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return input !== null && typeof input === 'object' && !Array.isArray(input);
}
