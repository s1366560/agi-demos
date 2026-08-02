import { DesktopApiError } from '../../api/client';
import type {
  CreateTenantAgentBindingInput,
  TenantAgentBinding,
  TenantAgentBindingDefinition,
  TenantAgentBindingTestResult,
  TenantAgentBindingsAction,
  TenantAgentBindingsAuthority,
  TenantAgentBindingsClient,
  TenantAgentBindingsScope,
  TenantAgentBindingsSnapshot,
  TestTenantAgentBindingInput,
} from './tenantAgentBindingsClient';

export type TenantAgentBindingsViewState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'conflict'
  | 'forbidden'
  | 'unavailable'
  | 'error';

export type TenantAgentBindingsFilters = Readonly<{
  search: string;
  channelType: string | null;
  enabled: boolean | null;
}>;

export type TenantAgentBindingsViewModel = Readonly<{
  state: TenantAgentBindingsViewState;
  scope: TenantAgentBindingsScope;
  authority: TenantAgentBindingsAuthority;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: TenantAgentBindingsAction | null;
  allowedActions: readonly TenantAgentBindingsAction[];
  bindings: readonly TenantAgentBinding[];
  visibleBindings: readonly TenantAgentBinding[];
  definitions: readonly TenantAgentBindingDefinition[];
  filters: TenantAgentBindingsFilters;
  emptyReason: 'source' | 'filter' | null;
  testResult: TenantAgentBindingTestResult | null;
}>;

export type TenantAgentBindingsController = Readonly<{
  getSnapshot: () => TenantAgentBindingsViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TenantAgentBindingsScope) => Promise<void>;
  retry: () => Promise<void>;
  setFilters: (filters: Partial<TenantAgentBindingsFilters>) => void;
  create: (
    input: CreateTenantAgentBindingInput,
    idempotencyKey: string,
  ) => Promise<void>;
  delete: (bindingId: string) => Promise<void>;
  setEnabled: (bindingId: string, enabled: boolean) => Promise<void>;
  test: (input: TestTenantAgentBindingInput) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createTenantAgentBindingsController(
  options: Readonly<{
    authority: TenantAgentBindingsAuthority;
    client: TenantAgentBindingsClient;
    initialScope: TenantAgentBindingsScope;
  }>,
): TenantAgentBindingsController {
  let activeScope = freezeScope(options.initialScope);
  let authoritativeSnapshot: TenantAgentBindingsSnapshot | null = null;
  let model = baseModel(activeScope, 'loading');
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: TenantAgentBindingsViewModel): void => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: TenantAgentBindingsScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== options.authority) {
      authoritativeSnapshot = null;
      emit(
        unavailableModel(
          scope,
          'tenant_agent_bindings_controller_authority_mismatch',
          false,
        ),
      );
      return;
    }
    if (scopeSwitch) authoritativeSnapshot = null;
    const controller = new AbortController();
    requestController = controller;
    emit(
      scopeSwitch
        ? baseModel(scope, 'scope_switch')
        : {
            ...model,
            state: 'loading',
            scope,
            authority: scope.authority,
            reasonCode: null,
            retryVisible: false,
            busyAction: null,
          },
    );
    try {
      const snapshot = await options.client.list(scope, undefined, {
        signal: controller.signal,
      });
      if (!isCurrent(revision, controller, requestRevision, requestController)) {
        return;
      }
      authoritativeSnapshot = snapshot;
      emit(modelFromSnapshot(snapshot, model.filters, null));
    } catch (error) {
      if (!isCurrent(revision, controller, requestRevision, requestController)) {
        return;
      }
      const staleSnapshot =
        authoritativeSnapshot !== null &&
        sameScope(authoritativeSnapshot.scope, scope)
          ? authoritativeSnapshot
          : null;
      emit(errorModel(error, scope, model.filters, staleSnapshot));
    } finally {
      if (isCurrent(revision, controller, requestRevision, requestController)) {
        requestController = null;
      }
    }
  };

  const setFilters = (
    filters: Partial<TenantAgentBindingsFilters>,
  ): void => {
    const nextFilters = Object.freeze({
      ...model.filters,
      ...filters,
    });
    if (authoritativeSnapshot === null) {
      emit({ ...model, filters: nextFilters });
      return;
    }
    emit(modelFromSnapshot(authoritativeSnapshot, nextFilters, model.testResult));
  };

  const runMutation = async (
    action: TenantAgentBindingsAction,
    operation: () => Promise<void>,
  ): Promise<void> => {
    requireAction(model, action);
    emit({ ...model, busyAction: action, reasonCode: null });
    try {
      await operation();
    } catch (error) {
      emit(mutationErrorModel(error, model));
      throw error;
    } finally {
      if (model.busyAction === action) emit({ ...model, busyAction: null });
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
    setFilters,
    async create(input, idempotencyKey) {
      await runMutation('create', async () => {
        const created = await options.client.create(activeScope, input, {
          idempotencyKey,
        });
        const snapshot = requireSnapshot(authoritativeSnapshot);
        authoritativeSnapshot = Object.freeze({
          ...snapshot,
          bindings: Object.freeze([
            ...snapshot.bindings,
            withDefinitionName(created, snapshot.definitions),
          ]),
        });
        emit(modelFromSnapshot(authoritativeSnapshot, model.filters, model.testResult));
      });
    },
    async delete(bindingId) {
      await runMutation('delete', async () => {
        await options.client.delete(activeScope, bindingId);
        const snapshot = requireSnapshot(authoritativeSnapshot);
        authoritativeSnapshot = Object.freeze({
          ...snapshot,
          bindings: Object.freeze(
            snapshot.bindings.filter((binding) => binding.id !== bindingId),
          ),
        });
        emit(modelFromSnapshot(authoritativeSnapshot, model.filters, model.testResult));
      });
    },
    async setEnabled(bindingId, enabled) {
      await runMutation('set-enabled', async () => {
        const updated = await options.client.setEnabled(
          activeScope,
          bindingId,
          enabled,
        );
        const snapshot = requireSnapshot(authoritativeSnapshot);
        authoritativeSnapshot = Object.freeze({
          ...snapshot,
          bindings: Object.freeze(
            snapshot.bindings.map((binding) =>
              binding.id === bindingId
                ? {
                    ...withDefinitionName(updated, snapshot.definitions),
                    agentName:
                      binding.agentId === updated.agentId
                        ? binding.agentName
                        : withDefinitionName(updated, snapshot.definitions)
                            .agentName,
                  }
                : binding,
            ),
          ),
        });
        emit(modelFromSnapshot(authoritativeSnapshot, model.filters, model.testResult));
      });
    },
    async test(input) {
      await runMutation('test', async () => {
        const result = await options.client.test(activeScope, input);
        emit({ ...model, testResult: result });
      });
    },
    cancel,
    stop: cancel,
  });
}

export function createUnavailableTenantAgentBindingsView(
  scope: TenantAgentBindingsScope,
  reasonCode: string,
): TenantAgentBindingsViewModel {
  return unavailableModel(scope, reasonCode, false);
}

function modelFromSnapshot(
  snapshot: TenantAgentBindingsSnapshot,
  filters: TenantAgentBindingsFilters,
  testResult: TenantAgentBindingTestResult | null,
): TenantAgentBindingsViewModel {
  const visibleBindings = filterBindings(snapshot.bindings, filters);
  const unavailable =
    snapshot.availability === 'unavailable' ||
    snapshot.availability === 'not_applicable';
  const state: TenantAgentBindingsViewState = unavailable
    ? 'unavailable'
    : visibleBindings.length === 0
      ? 'empty'
      : 'ready';
  return Object.freeze({
    state,
    scope: snapshot.scope,
    authority: snapshot.authority,
    reasonCode: snapshot.reasonCode,
    retryVisible: snapshot.availability === 'degraded',
    busyAction: null,
    allowedActions: snapshot.allowedActions,
    bindings: snapshot.bindings,
    visibleBindings,
    definitions: snapshot.definitions,
    filters,
    emptyReason:
      state === 'empty'
        ? snapshot.bindings.length === 0
          ? 'source'
          : 'filter'
        : null,
    testResult,
  });
}

function errorModel(
  error: unknown,
  scope: TenantAgentBindingsScope,
  filters: TenantAgentBindingsFilters,
  staleSnapshot: TenantAgentBindingsSnapshot | null,
): TenantAgentBindingsViewModel {
  const reasonCode = reasonCodeForError(error);
  if (staleSnapshot !== null) {
    const stale = modelFromSnapshot(staleSnapshot, filters, null);
    return Object.freeze({
      ...stale,
      state: 'stale',
      reasonCode,
      retryVisible: true,
    });
  }
  if (error instanceof DesktopApiError && error.status === 403) {
    return {
      ...baseModel(scope, 'forbidden'),
      reasonCode,
    };
  }
  if (
    error instanceof DesktopApiError &&
    (error.status === 0 || error.status === 501 || error.status === 503)
  ) {
    return unavailableModel(scope, reasonCode, error.status === 503);
  }
  return {
    ...baseModel(scope, 'error'),
    reasonCode,
    retryVisible: isRetryable(error),
  };
}

function mutationErrorModel(
  error: unknown,
  current: TenantAgentBindingsViewModel,
): TenantAgentBindingsViewModel {
  const reasonCode = reasonCodeForError(error);
  if (error instanceof DesktopApiError && error.status === 409) {
    return {
      ...current,
      state: 'conflict',
      reasonCode,
      retryVisible: true,
      busyAction: null,
    };
  }
  if (error instanceof DesktopApiError && error.status === 403) {
    return {
      ...current,
      state: 'forbidden',
      reasonCode,
      retryVisible: false,
      busyAction: null,
    };
  }
  return {
    ...current,
    state: current.bindings.length > 0 ? 'stale' : 'error',
    reasonCode,
    retryVisible: isRetryable(error),
    busyAction: null,
  };
}

function baseModel(
  scope: TenantAgentBindingsScope,
  state: TenantAgentBindingsViewState,
): TenantAgentBindingsViewModel {
  return Object.freeze({
    state,
    scope,
    authority: scope.authority,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
    allowedActions: Object.freeze([]),
    bindings: Object.freeze([]),
    visibleBindings: Object.freeze([]),
    definitions: Object.freeze([]),
    filters: Object.freeze({ search: '', channelType: null, enabled: null }),
    emptyReason: null,
    testResult: null,
  });
}

function unavailableModel(
  scope: TenantAgentBindingsScope,
  reasonCode: string,
  retryVisible: boolean,
): TenantAgentBindingsViewModel {
  return Object.freeze({
    ...baseModel(scope, 'unavailable'),
    reasonCode,
    retryVisible,
  });
}

function filterBindings(
  bindings: readonly TenantAgentBinding[],
  filters: TenantAgentBindingsFilters,
): readonly TenantAgentBinding[] {
  const search = filters.search.trim().toLocaleLowerCase();
  return Object.freeze(
    bindings.filter((binding) => {
      if (
        filters.channelType === 'any'
          ? binding.channelType !== null
          : filters.channelType !== null &&
            binding.channelType !== filters.channelType
      ) {
        return false;
      }
      if (filters.enabled !== null && binding.enabled !== filters.enabled) {
        return false;
      }
      if (!search) return true;
      return [
        binding.agentName,
        binding.agentId,
        binding.channelType,
        binding.channelId,
        binding.accountId,
        binding.peerId,
        binding.groupId,
      ].some(
        (value) =>
          typeof value === 'string' &&
          value.toLocaleLowerCase().includes(search),
      );
    }),
  );
}

function requireAction(
  model: TenantAgentBindingsViewModel,
  action: TenantAgentBindingsAction,
): void {
  if (!model.allowedActions.includes(action)) {
    throw new Error(`tenant_agent_bindings_action_unavailable:${action}`);
  }
}

function requireSnapshot(
  snapshot: TenantAgentBindingsSnapshot | null,
): TenantAgentBindingsSnapshot {
  if (snapshot === null) {
    throw new Error('tenant_agent_bindings_authority_snapshot_unavailable');
  }
  return snapshot;
}

function withDefinitionName(
  binding: TenantAgentBinding,
  definitions: readonly TenantAgentBindingDefinition[],
): TenantAgentBinding {
  const definition = definitions.find((item) => item.id === binding.agentId);
  return definition === undefined
    ? binding
    : Object.freeze({ ...binding, agentName: definition.displayName });
}

function reasonCodeForError(error: unknown): string {
  if (error instanceof DesktopApiError) {
    const payloadReason = payloadReasonCode(error.payload);
    return (
      payloadReason ??
      (error.status > 0
        ? `tenant_agent_bindings_http_${error.status}`
        : 'tenant_agent_bindings_contract_invalid')
    );
  }
  return 'tenant_agent_bindings_request_failed';
}

function payloadReasonCode(payload: unknown): string | null {
  if (!isRecord(payload) || typeof payload.reason_code !== 'string') return null;
  return payload.reason_code.trim() ? payload.reason_code : null;
}

function isRetryable(error: unknown): boolean {
  return (
    !(error instanceof DesktopApiError) ||
    error.status === 408 ||
    error.status === 425 ||
    error.status === 429 ||
    error.status >= 500
  );
}

function isCurrent(
  revision: number,
  controller: AbortController,
  currentRevision: number,
  currentController: AbortController | null,
): boolean {
  return (
    revision === currentRevision &&
    currentController === controller &&
    !controller.signal.aborted
  );
}

function freezeScope(
  scope: TenantAgentBindingsScope,
): TenantAgentBindingsScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
  });
}

function sameScope(
  left: TenantAgentBindingsScope,
  right: TenantAgentBindingsScope,
): boolean {
  return (
    left.authority === right.authority && left.tenantId === right.tenantId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
