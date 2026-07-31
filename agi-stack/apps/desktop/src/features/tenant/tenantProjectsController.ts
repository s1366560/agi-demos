import { DesktopApiError } from '../../api/client';
import type {
  TenantProjectsAuthority,
  TenantProjectsClient,
  TenantProjectsListQuery,
  TenantProjectsListSnapshot,
  TenantProjectsMutationInput,
  TenantProjectsScope,
} from './tenantProjectsClient';

export type TenantProjectsViewState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'degraded'
  | 'empty'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type TenantProjectsViewModel = Readonly<{
  state: TenantProjectsViewState;
  scope: TenantProjectsScope;
  authority: TenantProjectsAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: 'create' | 'update' | 'delete' | null;
  allowedActions: readonly string[];
  projects: TenantProjectsListSnapshot['projects'];
  total: number;
  page: number;
  pageSize: number;
  ownerIds: readonly string[];
}>;

export type TenantProjectsController = Readonly<{
  getSnapshot: () => TenantProjectsViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (
    scope: TenantProjectsScope,
    query?: TenantProjectsListQuery,
  ) => Promise<void>;
  retry: () => Promise<void>;
  create: (
    input: TenantProjectsMutationInput,
    idempotencyKey?: string,
  ) => Promise<void>;
  update: (
    projectId: string,
    input: TenantProjectsMutationInput,
    idempotencyKey?: string,
  ) => Promise<void>;
  delete: (projectId: string, idempotencyKey?: string) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createTenantProjectsController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: TenantProjectsAuthority;
  client: TenantProjectsClient;
  initialScope: TenantProjectsScope;
}>): TenantProjectsController {
  let activeScope = freezeScope(initialScope);
  let activeQuery: TenantProjectsListQuery = Object.freeze({});
  let model = loadingModel(activeScope, false);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: TenantProjectsViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: TenantProjectsScope,
    nextQuery: TenantProjectsListQuery = activeQuery,
  ): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    activeQuery = Object.freeze({ ...nextQuery });
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== authority) {
      emit(terminalModel(scope, 'unavailable', 'tenant_projects_controller_authority_mismatch'));
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(loadingModel(scope, scopeSwitch));
    try {
      const snapshot = await client.list(scope, activeQuery, {
        signal: controller.signal,
      });
      if (!requestIsCurrent(revision, controller)) return;
      emit(readyModel(snapshot));
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) return;
      emit(errorModel(error, scope));
    } finally {
      if (requestIsCurrent(revision, controller)) requestController = null;
    }
  };
  const mutate = async (
    action: 'create' | 'update' | 'delete',
    operation: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<void> => {
    if (model.busyAction !== null) {
      throw new Error('tenant_projects_mutation_in_progress');
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
    create: (input, idempotencyKey) =>
      mutate('create', (signal) =>
        requiredMutation(client.create, 'create')(activeScope, input, {
          signal,
          idempotencyKey,
        }),
      ),
    update: (projectId, input, idempotencyKey) =>
      mutate('update', (signal) =>
        requiredMutation(client.update, 'update')(
          activeScope,
          projectId,
          input,
          { signal, idempotencyKey },
        ),
      ),
    delete: (projectId, idempotencyKey) =>
      mutate('delete', (signal) =>
        requiredMutation(client.delete, 'delete')(activeScope, projectId, {
          signal,
          idempotencyKey,
        }),
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

function loadingModel(
  scope: TenantProjectsScope,
  scopeSwitch: boolean,
): TenantProjectsViewModel {
  return Object.freeze({
    state: scopeSwitch ? 'scope_switch' : 'loading',
    scope,
    authority: scope.authority,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    projects: Object.freeze([]),
    total: 0,
    page: 1,
    pageSize: 20,
    ownerIds: Object.freeze([]),
  });
}

function readyModel(snapshot: TenantProjectsListSnapshot): TenantProjectsViewModel {
  const empty = snapshot.projects.length === 0;
  return Object.freeze({
    state:
      snapshot.availability === 'degraded'
        ? 'degraded'
        : empty
          ? 'empty'
          : 'ready',
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    projects: snapshot.projects,
    total: snapshot.total,
    page: snapshot.page,
    pageSize: snapshot.pageSize,
    ownerIds: snapshot.ownerIds,
  });
}

function terminalModel(
  scope: TenantProjectsScope,
  state: Extract<
    TenantProjectsViewState,
    'error' | 'conflict' | 'forbidden' | 'unavailable'
  >,
  reasonCode: string,
  retryVisible = false,
): TenantProjectsViewModel {
  return Object.freeze({
    ...loadingModel(scope, false),
    state,
    reasonCode,
    retryVisible,
  });
}

function errorModel(
  error: unknown,
  scope: TenantProjectsScope,
): TenantProjectsViewModel {
  const reasonCode = errorReason(error, 'tenant_projects_request_failed');
  if (error instanceof DesktopApiError && error.status === 403) {
    return terminalModel(scope, 'forbidden', reasonCode);
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
  stable: TenantProjectsViewModel,
): TenantProjectsViewModel {
  const reasonCode = errorReason(error, 'tenant_project_mutation_failed');
  return Object.freeze({
    ...stable,
    state:
      error instanceof DesktopApiError && error.status === 409
        ? 'conflict'
        : error instanceof DesktopApiError && error.status === 403
          ? 'forbidden'
          : 'error',
    reasonCode,
    retryVisible: isRetryable(error),
    busyAction: null,
  });
}

function requireAction(
  model: TenantProjectsViewModel,
  action: 'create' | 'update' | 'delete',
): void {
  if (!model.allowedActions.includes(action)) {
    throw new Error(`tenant_projects_action_unavailable:${action}`);
  }
}

function requiredMutation<T>(
  mutation: T | undefined,
  action: string,
): NonNullable<T> {
  if (typeof mutation !== 'function') {
    throw new Error(`tenant_projects_action_unavailable:${action}`);
  }
  return mutation as NonNullable<T>;
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

function freezeScope(scope: TenantProjectsScope): TenantProjectsScope {
  return Object.freeze({ authority: scope.authority, tenantId: scope.tenantId });
}

function sameScope(left: TenantProjectsScope, right: TenantProjectsScope): boolean {
  return left.authority === right.authority && left.tenantId === right.tenantId;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
