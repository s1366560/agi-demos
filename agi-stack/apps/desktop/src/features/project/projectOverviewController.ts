import { DesktopApiError } from '../../api/client';
import {
  readCloudProjectOverview,
  type CloudProjectOverviewClient,
  type CloudProjectOverviewScope,
} from './projectOverviewClient';
import type {
  LocalProjectOverviewClient,
  LocalProjectOverviewScope,
} from './projectOverviewLocalClient';
import {
  buildProjectOverviewPresentation,
  type ProjectOverviewPresentationInput,
  type ProjectOverviewPresentationModel,
  type ProjectOverviewPresentationScope,
} from './projectOverviewPresentationModel';

export type ProjectOverviewControllerOptions =
  | Readonly<{
      authority: 'cloud';
      cloudClient: CloudProjectOverviewClient;
      localClient?: never;
      initialScope: CloudProjectOverviewScope;
    }>
  | Readonly<{
      authority: 'local';
      cloudClient?: never;
      localClient: LocalProjectOverviewClient;
      initialScope: LocalProjectOverviewScope;
    }>;

export type ProjectOverviewController = Readonly<{
  getSnapshot: () => ProjectOverviewPresentationModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectOverviewPresentationScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

type ProjectOverviewReaderResult =
  | Readonly<{
      kind: 'cloud-ready';
      snapshot: Extract<
        ProjectOverviewPresentationInput,
        Readonly<{ kind: 'cloud-ready' }>
      >['snapshot'];
    }>
  | Readonly<{
      kind: 'local-ready';
      snapshot: Extract<
        ProjectOverviewPresentationInput,
        Readonly<{ kind: 'local-ready' }>
      >['snapshot'];
    }>
  | Readonly<{ kind: 'empty' }>;

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
): Promise<ProjectOverviewReaderResult> {
  if (options.authority === 'cloud' && scope.authority === 'cloud') {
    const cloudScope: CloudProjectOverviewScope = {
      authority: 'cloud',
      tenantId: scope.tenantId,
      projectId: scope.projectId,
    };
    const result = await readCloudProjectOverview(options.cloudClient, cloudScope, { signal });
    if (result.kind === 'empty') return result;
    return { kind: 'cloud-ready', snapshot: result.snapshot };
  }

  if (options.authority === 'local' && scope.authority === 'local') {
    const localScope: LocalProjectOverviewScope = {
      authority: 'local',
      tenantId: scope.tenantId,
      projectId: scope.projectId,
    };
    const snapshot = await options.localClient.load(localScope, { signal });
    return { kind: 'local-ready', snapshot };
  }

  throw new DesktopApiError(
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
