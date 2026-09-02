import { DesktopApiError } from '../../api/client';
import type {
  ProjectOverviewClient,
  ProjectOverviewReadResult,
  ProjectOverviewScope,
} from './projectOverviewClient';
import {
  buildProjectOverviewPresentation,
  type ProjectOverviewPresentationInput,
  type ProjectOverviewPresentationModel,
  type ProjectOverviewPresentationScope,
} from './projectOverviewPresentationModel';

export type ProjectOverviewControllerOptions = Readonly<{
  authority: ProjectOverviewScope['authority'];
  client: ProjectOverviewClient;
  initialScope: ProjectOverviewScope;
}>;

export type ProjectOverviewController = Readonly<{
  getSnapshot: () => ProjectOverviewPresentationModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectOverviewPresentationScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createProjectOverviewController(
  options: ProjectOverviewControllerOptions,
): ProjectOverviewController {
  let activeScope = freezeScope(options.initialScope);
  let model = buildProjectOverviewPresentation(
    scopeMatchesAuthority(options.authority, activeScope)
      ? {
          kind: 'loading',
          scope: activeScope,
          scopeSwitch: false,
        }
      : authorityMismatchPresentation(activeScope),
  );
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (input: ProjectOverviewPresentationInput): void => {
    model = buildProjectOverviewPresentation(input);
    for (const listener of [...listeners]) listener();
  };

  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };

  const load = async (nextScope: ProjectOverviewPresentationScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (!scopeMatchesAuthority(options.authority, scope)) {
      emit(authorityMismatchPresentation(scope));
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit({ kind: 'loading', scope, scopeSwitch });

    try {
      const result = await readProjectOverview(options, scope, controller.signal);
      if (!requestIsCurrent(revision, controller, requestRevision, requestController)) return;
      if (result.kind === 'empty') {
        emit({ kind: 'empty', scope });
      } else {
        emit(result);
      }
    } catch (error) {
      if (!requestIsCurrent(revision, controller, requestRevision, requestController)) return;
      emit(errorPresentation(error, scope));
    } finally {
      if (requestIsCurrent(revision, controller, requestRevision, requestController)) {
        requestController = null;
      }
    }
  };

  const controller: ProjectOverviewController = Object.freeze({
    getSnapshot: () => model,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: () => load(activeScope),
    cancel,
    stop: cancel,
  });
  return controller;
}

async function readProjectOverview(
  options: ProjectOverviewControllerOptions,
  scope: ProjectOverviewPresentationScope,
  signal: AbortSignal,
): Promise<ProjectOverviewReadResult> {
  const result = await options.client.load(scope as ProjectOverviewScope, { signal });
  if (
    (scope.authority === 'cloud' &&
      (result.kind === 'cloud-ready' || result.kind === 'empty')) ||
    (scope.authority === 'local' && result.kind === 'local-ready')
  ) {
    return result;
  }
  throw authorityMismatchError();
}

function authorityMismatchError(): DesktopApiError {
  return new DesktopApiError(
    'project_overview_controller_authority_mismatch',
    0,
    { reason_code: 'project_overview_controller_authority_mismatch' },
  );
}

function authorityMismatchPresentation(
  scope: ProjectOverviewPresentationScope,
): ProjectOverviewPresentationInput {
  return {
    kind: 'unavailable',
    scope,
    reasonCode: 'project_overview_controller_authority_mismatch',
    retryable: false,
  };
}

function scopeMatchesAuthority(
  authority: ProjectOverviewControllerOptions['authority'],
  scope: ProjectOverviewPresentationScope,
): boolean {
  return scope.authority === authority;
}

function errorPresentation(
  error: unknown,
  scope: ProjectOverviewPresentationScope,
): ProjectOverviewPresentationInput {
  if (!(error instanceof DesktopApiError)) {
    return {
      kind: 'error',
      scope,
      reasonCode: 'project_overview_request_failed',
      detail: null,
      retryable: true,
    };
  }

  const reasonCode =
    payloadReasonCode(error.payload) ?? `project_overview_http_${error.status}`;
  if (error.status === 403) {
    return {
      kind: 'forbidden',
      scope,
      reasonCode,
    };
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
    detail: null,
    retryable: retryableStatus(error.status),
  };
}

function payloadReasonCode(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const reasonCode = payload.reason_code;
  return typeof reasonCode === 'string' && reasonCode.trim() ? reasonCode : null;
}

function retryableStatus(status: number): boolean {
  return (
    status === 408 ||
    status === 425 ||
    status === 429 ||
    (status >= 500 && status <= 599)
  );
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

function freezeScope(
  scope: ProjectOverviewPresentationScope,
): ProjectOverviewPresentationScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function sameScope(
  left: ProjectOverviewPresentationScope,
  right: ProjectOverviewPresentationScope,
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
