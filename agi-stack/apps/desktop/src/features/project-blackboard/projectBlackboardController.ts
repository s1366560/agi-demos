import type {
  ProjectBlackboardAuthority,
  ProjectBlackboardClient,
  ProjectBlackboardScope,
} from './projectBlackboardClient';
import {
  buildProjectBlackboardPresentation,
  type ProjectBlackboardViewModel,
} from './projectBlackboardPresentationModel';

export type ProjectBlackboardController = Readonly<{
  getSnapshot: () => ProjectBlackboardViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectBlackboardScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createProjectBlackboardController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: ProjectBlackboardAuthority;
  client: ProjectBlackboardClient;
  initialScope: ProjectBlackboardScope;
}>): ProjectBlackboardController {
  let activeScope = freezeScope(initialScope);
  let model = buildProjectBlackboardPresentation({
    kind: 'loading',
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();
  const emit = (next: ProjectBlackboardViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: ProjectBlackboardScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(scope, activeScope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== authority) {
      emit(
        buildProjectBlackboardPresentation({
          kind: 'failure',
          scope,
          state: 'unavailable',
          reasonCode: 'project_blackboard_controller_authority_mismatch',
          retryable: false,
        }),
      );
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(buildProjectBlackboardPresentation({ kind: 'loading', scope, scopeSwitch }));
    try {
      const snapshot = await client.probe(scope, controller.signal);
      if (!currentRequest(revision, controller)) return;
      emit(buildProjectBlackboardPresentation({ kind: 'snapshot', snapshot }));
    } catch (error) {
      if (!currentRequest(revision, controller)) return;
      emit(failureModel(error, scope));
    } finally {
      if (currentRequest(revision, controller)) requestController = null;
    }
  };
  const currentRequest = (revision: number, controller: AbortController): boolean =>
    revision === requestRevision && requestController === controller && !controller.signal.aborted;
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

function failureModel(error: unknown, scope: ProjectBlackboardScope): ProjectBlackboardViewModel {
  const record = isRecord(error) ? error : null;
  const status = typeof record?.status === 'number' ? record.status : 0;
  const payload = isRecord(record?.payload) ? record.payload : null;
  const reasonCode =
    typeof payload?.reason_code === 'string' && payload.reason_code.trim()
      ? payload.reason_code
      : 'project_blackboard_request_failed';
  return buildProjectBlackboardPresentation({
    kind: 'failure',
    scope,
    state:
      status === 403
        ? 'forbidden'
        : status === 0 || status === 501 || status === 503
          ? 'unavailable'
          : 'error',
    reasonCode,
    retryable: status === 408 || status === 425 || status === 429 || status >= 500,
  });
}

function freezeScope(scope: ProjectBlackboardScope): ProjectBlackboardScope {
  return Object.freeze({ ...scope });
}

function sameScope(left: ProjectBlackboardScope, right: ProjectBlackboardScope): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId &&
    left.workspaceId === right.workspaceId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
