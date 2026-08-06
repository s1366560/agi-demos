import {
  buildManagementRoutePresentation,
  type ManagementRoutePresentationInput,
  type ManagementRoutePresentationModel,
} from './managementRoutePresentationModel';
import {
  managementRouteReasonPrefix,
  type ManagementRouteCapability,
  type ManagementRouteClient,
  type ManagementRouteScope,
} from './managementRouteTypes';

export type ManagementRouteControllerOptions = Readonly<{
  capability: ManagementRouteCapability;
  client: ManagementRouteClient;
  initialScope: ManagementRouteScope;
}>;

export type ManagementRouteController = Readonly<{
  getSnapshot: () => ManagementRoutePresentationModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ManagementRouteScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createManagementRouteController({
  capability,
  client,
  initialScope,
}: ManagementRouteControllerOptions): ManagementRouteController {
  let activeScope = freezeScope(initialScope);
  let model = buildManagementRoutePresentation({
    kind: 'loading',
    capability,
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (input: ManagementRoutePresentationInput): void => {
    model = buildManagementRoutePresentation(input);
    for (const listener of [...listeners]) listener();
  };

  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };

  const load = async (nextScope: ManagementRouteScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({ kind: 'loading', capability, scope, scopeSwitch });

    try {
      const observation = await client.observe(scope, {
        signal: controller.signal,
      });
      if (!requestIsCurrent(revision, controller)) return;
      emit({ kind: 'observed', capability, observation });
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) return;
      emit(errorPresentation(capability, scope, error));
    } finally {
      if (requestIsCurrent(revision, controller)) requestController = null;
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

function errorPresentation(
  capability: ManagementRouteCapability,
  scope: ManagementRouteScope,
  error: unknown,
): ManagementRoutePresentationInput {
  const prefix = managementRouteReasonPrefix(capability);
  const status = errorStatus(error);
  if (status === 401 || status === 403) {
    return {
      kind: 'terminal',
      capability,
      scope,
      state: 'forbidden',
      reasonCode: `${prefix}_forbidden`,
      retryable: false,
    };
  }
  if (status === 409 || status === 412 || status === 428) {
    return {
      kind: 'terminal',
      capability,
      scope,
      state: 'conflict',
      reasonCode: `${prefix}_conflict`,
      retryable: true,
    };
  }
  if (status === 0 || status === 501 || status === 503) {
    return {
      kind: 'terminal',
      capability,
      scope,
      state: 'unavailable',
      reasonCode: errorReasonCode(error) ?? `${prefix}_unavailable`,
      retryable: status === 503,
    };
  }
  return {
    kind: 'terminal',
    capability,
    scope,
    state: 'error',
    reasonCode: `${prefix}_request_failed`,
    retryable:
      status === 408 ||
      status === 425 ||
      status === 429 ||
      (status >= 500 && status <= 599),
  };
}

function errorStatus(error: unknown): number {
  if (!isRecord(error) || typeof error.status !== 'number') return -1;
  return Number.isSafeInteger(error.status) ? error.status : -1;
}

function errorReasonCode(error: unknown): string | null {
  if (!isRecord(error) || typeof error.reasonCode !== 'string') return null;
  const reasonCode = error.reasonCode.trim();
  return reasonCode.length > 0 ? reasonCode : null;
}

function freezeScope(scope: ManagementRouteScope): ManagementRouteScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function sameScope(
  left: ManagementRouteScope,
  right: ManagementRouteScope,
): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
