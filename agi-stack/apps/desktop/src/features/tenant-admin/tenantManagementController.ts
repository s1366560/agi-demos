import { DesktopApiError } from '../../api/client';
import type {
  TenantManagementAuthoritySnapshot,
  TenantManagementScope,
} from './tenantManagementHttp';

export type TenantManagementViewState =
  | 'loading'
  | 'stale'
  | 'empty'
  | 'ready'
  | 'degraded'
  | 'forbidden'
  | 'conflict'
  | 'unavailable'
  | 'error';

export type TenantManagementPresentationInput<
  TScope extends TenantManagementScope,
  TData,
> = Readonly<{
  state: TenantManagementViewState;
  scope: TScope;
  snapshot: TenantManagementAuthoritySnapshot<TScope, TData> | null;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
}>;

export type TenantManagementControllerCore<
  TScope extends TenantManagementScope,
  TModel,
> = Readonly<{
  getSnapshot: () => TModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export type TenantManagementMutableController<
  TScope extends TenantManagementScope,
  TModel,
  TData,
> = TenantManagementControllerCore<TScope, TModel> &
  Readonly<{
    runAction: (
      action: string,
      operation: (scope: TScope, signal: AbortSignal) => Promise<void>,
    ) => Promise<void>;
  }>;

export function createTenantManagementController<
  TScope extends TenantManagementScope,
  TData,
  TModel,
>({
  initialScope,
  reasonPrefix,
  loadAuthority,
  isEmpty,
  buildPresentation,
}: Readonly<{
  initialScope: TScope;
  reasonPrefix: string;
  loadAuthority: (
    scope: TScope,
    options?: Readonly<{ signal?: AbortSignal }>,
  ) => Promise<TenantManagementAuthoritySnapshot<TScope, TData>>;
  isEmpty: (data: TData) => boolean;
  buildPresentation: (input: TenantManagementPresentationInput<TScope, TData>) => TModel;
}>): TenantManagementMutableController<TScope, TModel, TData> {
  let activeScope = initialScope;
  let authoritySnapshot: TenantManagementAuthoritySnapshot<TScope, TData> | null = null;
  let requestGeneration = 0;
  let activeRequest: AbortController | null = null;
  let stopped = false;
  const listeners = new Set<() => void>();
  let model = buildPresentation({
    state: 'loading',
    scope: activeScope,
    snapshot: null,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
  });

  const publish = (
    state: TenantManagementViewState,
    reasonCode: string | null,
    retryVisible: boolean,
    busyAction: string | null,
  ) => {
    model = buildPresentation({
      state,
      scope: activeScope,
      snapshot: authoritySnapshot,
      reasonCode,
      retryVisible,
      busyAction,
    });
    for (const listener of listeners) listener();
  };

  const load = async (scope: TScope): Promise<void> => {
    if (stopped) return;
    activeScope = scope;
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    const generation = ++requestGeneration;
    publish(authoritySnapshot ? 'stale' : 'loading', authoritySnapshot?.reasonCode ?? null, false, null);
    try {
      const next = await loadAuthority(scope, { signal: controller.signal });
      if (stopped || controller.signal.aborted || generation !== requestGeneration) return;
      authoritySnapshot = next;
      publish(
        next.availability === 'degraded' ? 'degraded' : isEmpty(next.data) ? 'empty' : 'ready',
        next.reasonCode,
        false,
        null,
      );
    } catch (error) {
      if (stopped || controller.signal.aborted || generation !== requestGeneration) return;
      const failure = classifyFailure(error, reasonPrefix);
      publish(failure.state, failure.reasonCode, failure.retryVisible, null);
    } finally {
      if (generation === requestGeneration) activeRequest = null;
    }
  };

  const runAction = async (
    action: string,
    operation: (scope: TScope, signal: AbortSignal) => Promise<void>,
  ): Promise<void> => {
    if (stopped) return;
    if (!authoritySnapshot?.allowedActions.includes(action)) {
      const reasonCode = `${reasonPrefix}_action_forbidden`;
      publish('forbidden', reasonCode, false, null);
      throw new DesktopApiError(reasonCode, 403, { reason_code: reasonCode });
    }
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    const generation = ++requestGeneration;
    publish(modelState(model), authoritySnapshot.reasonCode, false, action);
    try {
      await operation(activeScope, controller.signal);
      if (stopped || controller.signal.aborted || generation !== requestGeneration) return;
      activeRequest = null;
      await load(activeScope);
    } catch (error) {
      if (stopped || controller.signal.aborted || generation !== requestGeneration) return;
      const failure = classifyFailure(error, reasonPrefix);
      publish(failure.state, failure.reasonCode, failure.retryVisible, null);
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
    runAction,
    cancel() {
      requestGeneration += 1;
      activeRequest?.abort();
      activeRequest = null;
    },
    stop() {
      stopped = true;
      requestGeneration += 1;
      activeRequest?.abort();
      activeRequest = null;
      listeners.clear();
    },
  });
}

function classifyFailure(
  error: unknown,
  reasonPrefix: string,
): Readonly<{ state: TenantManagementViewState; reasonCode: string; retryVisible: boolean }> {
  const status = error instanceof DesktopApiError ? error.status : null;
  const payloadReason =
    error instanceof DesktopApiError && isRecord(error.payload)
      ? (exactReason(error.payload.reason_code) ??
        exactReason(error.payload.code) ??
        (isRecord(error.payload.detail) ? exactReason(error.payload.detail.code) : null))
      : null;
  if (status === 403) {
    return Object.freeze({
      state: 'forbidden',
      reasonCode: payloadReason ?? `${reasonPrefix}_forbidden`,
      retryVisible: false,
    });
  }
  if (status === 409) {
    return Object.freeze({
      state: 'conflict',
      reasonCode: payloadReason ?? `${reasonPrefix}_conflict`,
      retryVisible: true,
    });
  }
  if (status === 401 || status === 404 || status === 501) {
    return Object.freeze({
      state: 'unavailable',
      reasonCode: payloadReason ?? `${reasonPrefix}_unavailable`,
      retryVisible: status === 404,
    });
  }
  return Object.freeze({
    state: 'error',
    reasonCode: payloadReason ?? `${reasonPrefix}_load_failed`,
    retryVisible: true,
  });
}

function exactReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function modelState(model: unknown): TenantManagementViewState {
  if (isRecord(model) && typeof model.state === 'string') {
    return model.state as TenantManagementViewState;
  }
  return 'ready';
}
