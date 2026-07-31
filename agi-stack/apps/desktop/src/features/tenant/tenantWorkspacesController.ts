import { DesktopApiError } from '../../api/client';
import type {
  TenantWorkspaceCreateInput,
  TenantWorkspacesAuthority,
  TenantWorkspacesClient,
  TenantWorkspacesScope,
  TenantWorkspacesSnapshot,
} from './tenantWorkspacesClient';

export type TenantWorkspacesViewState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'degraded'
  | 'empty'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type TenantWorkspacesViewModel = Readonly<{
  state: TenantWorkspacesViewState;
  scope: TenantWorkspacesScope;
  authority: TenantWorkspacesAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: 'create' | null;
  allowedActions: readonly string[];
  workspaces: TenantWorkspacesSnapshot['workspaces'];
}>;

export type TenantWorkspacesController = Readonly<{
  getSnapshot: () => TenantWorkspacesViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TenantWorkspacesScope) => Promise<void>;
  retry: () => Promise<void>;
  create: (input: TenantWorkspaceCreateInput) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createTenantWorkspacesController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: TenantWorkspacesAuthority;
  client: TenantWorkspacesClient;
  initialScope: TenantWorkspacesScope;
}>): TenantWorkspacesController {
  let activeScope = freezeScope(initialScope);
  let model = loadingModel(activeScope, false);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: TenantWorkspacesViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: TenantWorkspacesScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== authority) {
      emit(terminalModel(scope, 'unavailable', 'tenant_workspaces_controller_authority_mismatch'));
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(loadingModel(scope, scopeSwitch));
    try {
      const snapshot = await client.list(scope, { signal: controller.signal });
      if (!requestIsCurrent(revision, controller)) return;
      emit(readyModel(snapshot));
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) return;
      emit(errorModel(error, scope));
    } finally {
      if (requestIsCurrent(revision, controller)) requestController = null;
    }
  };
  const create = async (input: TenantWorkspaceCreateInput): Promise<void> => {
    if (model.busyAction !== null) {
      throw new Error('tenant_workspaces_mutation_in_progress');
    }
    if (!model.allowedActions.includes('create') || typeof client.create !== 'function') {
      throw new Error('tenant_workspaces_action_unavailable:create');
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(Object.freeze({ ...stable, busyAction: 'create', reasonCode: null }));
    try {
      await client.create(activeScope, input, { signal: controller.signal });
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      await load(activeScope);
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
    retry: () => load(activeScope),
    create,
    cancel,
    stop: cancel,
  });

  function requestIsCurrent(revision: number, controller: AbortController): boolean {
    return (
      revision === requestRevision && requestController === controller && !controller.signal.aborted
    );
  }
}

function loadingModel(
  scope: TenantWorkspacesScope,
  scopeSwitch: boolean,
): TenantWorkspacesViewModel {
  return Object.freeze({
    state: scopeSwitch ? 'scope_switch' : 'loading',
    scope,
    authority: scope.authority,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    workspaces: Object.freeze([]),
  });
}

function readyModel(snapshot: TenantWorkspacesSnapshot): TenantWorkspacesViewModel {
  return Object.freeze({
    state:
      snapshot.availability === 'degraded'
        ? 'degraded'
        : snapshot.workspaces.length === 0
          ? 'empty'
          : 'ready',
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    workspaces: snapshot.workspaces,
  });
}

function terminalModel(
  scope: TenantWorkspacesScope,
  state: Extract<TenantWorkspacesViewState, 'error' | 'conflict' | 'forbidden' | 'unavailable'>,
  reasonCode: string,
  retryVisible = false,
): TenantWorkspacesViewModel {
  return Object.freeze({
    ...loadingModel(scope, false),
    state,
    reasonCode,
    retryVisible,
  });
}

function errorModel(error: unknown, scope: TenantWorkspacesScope): TenantWorkspacesViewModel {
  const reasonCode = errorReason(error, 'tenant_workspaces_request_failed');
  if (error instanceof DesktopApiError && error.status === 403) {
    return terminalModel(scope, 'forbidden', reasonCode);
  }
  if (
    error instanceof DesktopApiError &&
    (error.status === 0 || error.status === 501 || error.status === 503)
  ) {
    return terminalModel(scope, 'unavailable', reasonCode, error.status === 503);
  }
  return terminalModel(scope, 'error', reasonCode, isRetryable(error));
}

function mutationErrorModel(
  error: unknown,
  stable: TenantWorkspacesViewModel,
): TenantWorkspacesViewModel {
  return Object.freeze({
    ...stable,
    state:
      error instanceof DesktopApiError && error.status === 409
        ? 'conflict'
        : error instanceof DesktopApiError && error.status === 403
          ? 'forbidden'
          : 'error',
    reasonCode: errorReason(error, 'tenant_workspace_mutation_failed'),
    retryVisible: isRetryable(error),
    busyAction: null,
  });
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
    (error.status === 408 || error.status === 425 || error.status === 429 || error.status >= 500)
  );
}

function freezeScope(scope: TenantWorkspacesScope): TenantWorkspacesScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function sameScope(left: TenantWorkspacesScope, right: TenantWorkspacesScope): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
