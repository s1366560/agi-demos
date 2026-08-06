import type {
  ProjectKnowledgeAuthority,
  ProjectKnowledgeClient,
  ProjectKnowledgeScope,
  ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';
import type {
  ProjectKnowledgePresentationInput,
  ProjectKnowledgeViewModel,
} from './projectKnowledgePresentationModel';

export type ProjectKnowledgeController = Readonly<{
  getSnapshot: () => ProjectKnowledgeViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectKnowledgeScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createProjectKnowledgeController<TSnapshot extends ProjectKnowledgeSnapshotBase>({
  authority,
  client,
  initialScope,
  buildPresentation,
}: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectKnowledgeClient<TSnapshot>;
  initialScope: ProjectKnowledgeScope;
  buildPresentation: (
    input: ProjectKnowledgePresentationInput<TSnapshot>,
  ) => ProjectKnowledgeViewModel;
}>): ProjectKnowledgeController {
  let activeScope = freezeScope(initialScope);
  let model = buildPresentation({ kind: 'loading', scope: activeScope, scopeSwitch: false });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();
  const emit = (next: ProjectKnowledgeViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: ProjectKnowledgeScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    requestController = null;
    if (scope.authority !== authority) {
      emit(
        buildPresentation({
          kind: 'failure',
          scope,
          state: 'unavailable',
          reasonCode: 'project_knowledge_controller_authority_mismatch',
          retryable: false,
        }),
      );
      return;
    }
    const controller = new AbortController();
    requestController = controller;
    emit(buildPresentation({ kind: 'loading', scope, scopeSwitch }));
    try {
      const snapshot = await client.load(scope, { signal: controller.signal });
      if (!currentRequest(revision, controller)) return;
      emit(buildPresentation({ kind: 'snapshot', snapshot }));
    } catch (error) {
      if (!currentRequest(revision, controller)) return;
      emit(buildPresentation(failureInput(error, scope)));
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

function failureInput<TSnapshot extends ProjectKnowledgeSnapshotBase>(
  error: unknown,
  scope: ProjectKnowledgeScope,
): ProjectKnowledgePresentationInput<TSnapshot> {
  const record = isRecord(error) ? error : null;
  const status = typeof record?.status === 'number' ? record.status : 0;
  const payload = isRecord(record?.payload) ? record.payload : null;
  const detail = isRecord(payload?.detail) ? payload.detail : null;
  const reasonCode =
    structuredReason(payload?.reason_code) ??
    structuredReason(payload?.code) ??
    structuredReason(detail?.code) ??
    'project_knowledge_request_failed';
  return {
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
  };
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

function freezeScope(scope: ProjectKnowledgeScope): ProjectKnowledgeScope {
  return Object.freeze({ ...scope });
}

function sameScope(left: ProjectKnowledgeScope, right: ProjectKnowledgeScope): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
