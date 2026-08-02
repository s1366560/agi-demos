import { DesktopApiError } from '../../api/client';
import type {
  TenantAnalyticsAuthority,
  TenantAnalyticsClient,
  TenantAnalyticsScope,
} from './tenantAnalyticsClient';
import {
  buildTenantAnalyticsPresentation,
  type TenantAnalyticsPresentationInput,
  type TenantAnalyticsPresentationModel,
} from './tenantAnalyticsPresentationModel';

export type TenantAnalyticsController = Readonly<{
  getSnapshot: () => TenantAnalyticsPresentationModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: TenantAnalyticsScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createTenantAnalyticsController(
  options: Readonly<{
    authority: TenantAnalyticsAuthority;
    client: TenantAnalyticsClient;
    initialScope: TenantAnalyticsScope;
  }>,
): TenantAnalyticsController {
  let activeScope = freezeScope(options.initialScope);
  let model = buildTenantAnalyticsPresentation({
    kind: 'loading',
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (input: TenantAnalyticsPresentationInput): void => {
    model = buildTenantAnalyticsPresentation(input);
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: TenantAnalyticsScope): Promise<void> => {
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
        reasonCode: 'tenant_analytics_controller_authority_mismatch',
        retryable: false,
      });
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit({ kind: 'loading', scope, scopeSwitch });
    try {
      const snapshot = await options.client.load(scope, {
        signal: controller.signal,
      });
      if (!isCurrent(revision, controller, requestRevision, requestController)) {
        return;
      }
      emit({ kind: 'ready', snapshot });
    } catch (error) {
      if (!isCurrent(revision, controller, requestRevision, requestController)) {
        return;
      }
      emit(errorPresentation(error, scope));
    } finally {
      if (isCurrent(revision, controller, requestRevision, requestController)) {
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
  scope: TenantAnalyticsScope,
): TenantAnalyticsPresentationInput {
  if (!(error instanceof DesktopApiError)) {
    return {
      kind: 'error',
      scope,
      reasonCode: 'tenant_analytics_request_failed',
      retryable: true,
    };
  }
  const reasonCode =
    payloadReasonCode(error.payload) ?? `tenant_analytics_http_${error.status}`;
  if (error.status === 403) return { kind: 'forbidden', scope, reasonCode };
  if (error.status === 409) {
    return { kind: 'conflict', scope, reasonCode, retryable: true };
  }
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

function freezeScope(scope: TenantAnalyticsScope): TenantAnalyticsScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    period: scope.period,
  });
}

function sameScope(
  left: TenantAnalyticsScope,
  right: TenantAnalyticsScope,
): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.period === right.period
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
