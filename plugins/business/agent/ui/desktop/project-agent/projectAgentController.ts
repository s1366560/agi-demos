import type {
  ProjectAgentAuthority,
  ProjectAgentScope,
  ProjectAgentSnapshotBase,
} from './projectAgentClient';
import type {
  ProjectAgentPresentationInput,
  ProjectAgentViewModel,
} from './projectAgentPresentationModel';

export type ProjectAgentController = Readonly<{
  getSnapshot: () => ProjectAgentViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectAgentScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export type ProjectAgentFailureReasonCodes = Readonly<{
  forbidden: string;
  unavailable: string;
  error: string;
}>;

export function createProjectAgentController<TSnapshot extends ProjectAgentSnapshotBase>({
  authority,
  client,
  failureReasonCodes,
  initialScope,
  buildPresentation,
}: Readonly<{
  authority: ProjectAgentAuthority;
  failureReasonCodes: ProjectAgentFailureReasonCodes;
  client: Readonly<{
    load(
      scope: ProjectAgentScope,
      options?: Readonly<{ signal?: AbortSignal }>,
    ): Promise<TSnapshot>;
  }>;
  initialScope: ProjectAgentScope;
  buildPresentation: (input: ProjectAgentPresentationInput<TSnapshot>) => ProjectAgentViewModel;
}>): ProjectAgentController {
  let activeScope = freezeScope(initialScope);
  let model = buildPresentation({
    kind: 'loading',
    scope: activeScope,
    scopeSwitch: false,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();
  const emit = (next: ProjectAgentViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: ProjectAgentScope): Promise<void> => {
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
          reasonCode: 'project_agent_controller_authority_mismatch',
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
      emit(buildPresentation(failureInput<TSnapshot>(error, scope, failureReasonCodes)));
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

function failureInput<TSnapshot extends ProjectAgentSnapshotBase>(
  error: unknown,
  scope: ProjectAgentScope,
  failureReasonCodes: ProjectAgentFailureReasonCodes,
): ProjectAgentPresentationInput<TSnapshot> {
  const record = isRecord(error) ? error : null;
  const status = typeof record?.status === 'number' ? record.status : 0;
  const payload = isRecord(record?.payload) ? record.payload : null;
  const detail = isRecord(payload?.detail) ? payload.detail : null;
  const structuredFailureReason =
    structuredReason(payload?.reason_code) ??
    structuredReason(payload?.code) ??
    structuredReason(detail?.code);
  const state =
    status === 403
      ? 'forbidden'
      : status === 0 || status === 501 || status >= 500
        ? 'unavailable'
        : 'error';
  return {
    kind: 'failure',
    scope,
    state,
    reasonCode: structuredFailureReason ?? failureReasonCodes[state],
    retryable:
      status === 0 || status === 408 || status === 425 || status === 429 || status >= 500,
  };
}

function freezeScope(scope: ProjectAgentScope): ProjectAgentScope {
  return Object.freeze({ ...scope });
}

function sameScope(left: ProjectAgentScope, right: ProjectAgentScope): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
