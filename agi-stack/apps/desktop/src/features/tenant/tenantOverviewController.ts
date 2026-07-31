import { DesktopApiError } from '../../api/client';
import type {
  TenantOverviewAuthority,
  TenantOverviewClient,
  TenantOverviewScope,
} from './tenantOverviewClient';
import {
  buildTenantOverviewPresentation,
  type TenantOverviewPresentationInput,
  type TenantOverviewPresentationModel,
} from './tenantOverviewPresentationModel';

export type TenantOverviewControllerOptions = Readonly<{
  authority: TenantOverviewAuthority;
  client: TenantOverviewClient;
  initialScope: TenantOverviewScope;
}>;

export type TenantOverviewController = Readonly<{
  getSnapshot: () => TenantOverviewPresentationModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TenantOverviewScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createTenantOverviewController(
  options: TenantOverviewControllerOptions,
): TenantOverviewController {
  let activeScope = freezeScope(options.initialScope);
  let model = buildTenantOverviewPresentation({
    kind: 'loading',
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (input: TenantOverviewPresentationInput): void => {
    model = buildTenantOverviewPresentation(input);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: TenantOverviewScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== options.authority) {
      emit({
        kind: 'unavailable',
        scope,
        reasonCode: 'tenant_overview_controller_authority_mismatch',
        retryable: false,
      });
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit({ kind: 'loading', scope, scopeSwitch });
    try {
      const snapshot = await options.client.load(scope, { signal: controller.signal });
      if (!requestIsCurrent(revision, controller, requestRevision, requestController)) return;
      emit({ kind: 'ready', snapshot });
    } catch (error) {
      if (!requestIsCurrent(revision, controller, requestRevision, requestController)) return;
      emit(errorPresentation(error, scope));
    } finally {
      if (requestIsCurrent(revision, controller, requestRevision, requestController)) {
        requestController = null;
      }
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
}

function errorPresentation(
  error: unknown,
  scope: TenantOverviewScope,
): TenantOverviewPresentationInput {
  if (!(error instanceof DesktopApiError)) {
    return {
      kind: 'error',
      scope,
      reasonCode: 'tenant_overview_request_failed',
      retryable: true,
    };
  }
  const reasonCode = payloadReasonCode(error.payload) ?? `tenant_overview_http_${error.status}`;
  if (error.status === 403) return { kind: 'forbidden', scope, reasonCode };
  if (error.status === 0 || error.status === 501 || error.status === 503) {
    return {
      kind: 'unavailable',
      scope,
      reasonCode,
      retryable: error.status === 503,
    };
  }
  return {
    kind: 'error',
    scope,
    reasonCode,
    retryable:
      error.status === 408 ||
      error.status === 425 ||
      error.status === 429 ||
      error.status >= 500,
  };
}

function payloadReasonCode(payload: unknown): string | null {
  if (!isRecord(payload) || typeof payload.reason_code !== 'string') return null;
  return payload.reason_code.trim() ? payload.reason_code : null;
}

function requestIsCurrent(
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

function freezeScope(scope: TenantOverviewScope): TenantOverviewScope {
  return Object.freeze({ authority: scope.authority, tenantId: scope.tenantId });
}

function sameScope(left: TenantOverviewScope, right: TenantOverviewScope): boolean {
  return left.authority === right.authority && left.tenantId === right.tenantId;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
