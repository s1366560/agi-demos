import { DesktopApiError } from '../../api/client';
import type {
  ProjectWorkspaceCreateInput,
  ProjectWorkspacesAuthority,
  ProjectWorkspacesClient,
  ProjectWorkspacesScope,
} from './projectWorkspacesClient';
import {
  buildProjectWorkspacesPresentation,
  withProjectWorkspacesBusyAction,
  type ProjectWorkspacesViewModel,
} from './projectWorkspacesPresentationModel';

export type ProjectWorkspacesController = Readonly<{
  getSnapshot: () => ProjectWorkspacesViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectWorkspacesScope) => Promise<void>;
  retry: () => Promise<void>;
  create: (input: ProjectWorkspaceCreateInput) => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createProjectWorkspacesController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: ProjectWorkspacesAuthority;
  client: Pick<ProjectWorkspacesClient, 'list' | 'create'>;
  initialScope: ProjectWorkspacesScope;
}>): ProjectWorkspacesController {
  let activeScope = freezeScope(initialScope);
  let model = buildProjectWorkspacesPresentation({
    kind: 'loading',
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: ProjectWorkspacesViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: ProjectWorkspacesScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== authority) {
      emit(
        buildProjectWorkspacesPresentation({
          kind: 'failure',
          scope,
          state: 'unavailable',
          reasonCode: 'project_workspaces_controller_authority_mismatch',
          retryable: false,
        }),
      );
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(buildProjectWorkspacesPresentation({ kind: 'loading', scope, scopeSwitch }));
    try {
      const snapshot = await client.list(scope, { signal: controller.signal });
      if (!currentRequest(revision, controller)) return;
      emit(buildProjectWorkspacesPresentation({ kind: 'snapshot', snapshot }));
    } catch (error) {
      if (!currentRequest(revision, controller)) return;
      emit(failureModel(error, scope));
    } finally {
      if (currentRequest(revision, controller)) requestController = null;
    }
  };
  const create = async (input: ProjectWorkspaceCreateInput): Promise<void> => {
    if (!model.allowedActions.includes('create')) {
      throw new DesktopApiError('project_workspaces_action_unavailable:create', 501, {
        reason_code: 'project_workspaces_action_unavailable:create',
      });
    }
    if (model.busyAction !== null) {
      throw new Error('project_workspaces_mutation_in_progress');
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(withProjectWorkspacesBusyAction(stable, 'create'));
    try {
      await client.create(activeScope, input, { signal: controller.signal });
      if (!currentRequest(revision, controller)) return;
      requestController = null;
      await load(activeScope);
    } catch (error) {
      if (!currentRequest(revision, controller)) throw error;
      requestController = null;
      emit(withProjectWorkspacesBusyAction(stable, null));
      throw error;
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
    create,
    cancel,
    stop: cancel,
  });
}

function failureModel(
  error: unknown,
  scope: ProjectWorkspacesScope,
): ProjectWorkspacesViewModel {
  const status = error instanceof DesktopApiError ? error.status : 0;
  const reasonCode =
    error instanceof DesktopApiError &&
    isRecord(error.payload) &&
    typeof error.payload.reason_code === 'string' &&
    error.payload.reason_code.trim()
      ? error.payload.reason_code
      : 'project_workspaces_request_failed';
  return buildProjectWorkspacesPresentation({
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

function freezeScope(scope: ProjectWorkspacesScope): ProjectWorkspacesScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function sameScope(left: ProjectWorkspacesScope, right: ProjectWorkspacesScope): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
