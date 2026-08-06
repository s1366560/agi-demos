import type {
  ProjectAdministrationScope,
  ProjectAdministrationSnapshotBase,
} from './projectAdministrationClient';
import type {
  ProjectAdministrationPresentationState,
  ProjectAdministrationState,
  ProjectAdministrationViewModelBase,
} from './projectAdministrationPresentationModel';

export type ProjectAdministrationController<
  TModel extends ProjectAdministrationViewModelBase = ProjectAdministrationViewModelBase,
> = Readonly<{
  getSnapshot: () => TModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: ProjectAdministrationScope) => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
  stop: () => void;
}>;

export function createProjectAdministrationController<
  TSnapshot extends ProjectAdministrationSnapshotBase,
  TModel extends ProjectAdministrationViewModelBase,
>({
  client,
  initialScope,
  buildPresentation,
}: Readonly<{
  client: Readonly<{
    load(
      scope: ProjectAdministrationScope,
      options?: Readonly<{ signal?: AbortSignal }>,
    ): Promise<TSnapshot>;
  }>;
  initialScope: ProjectAdministrationScope;
  buildPresentation: (input: ProjectAdministrationPresentationState<TSnapshot>) => TModel;
}>): ProjectAdministrationController<TModel> {
  let activeScope = freezeScope(initialScope);
  let snapshot: TSnapshot | null = null;
  let model = buildPresentation({
    state: 'loading',
    scope: activeScope,
    snapshot,
    reasonCode: null,
    retryVisible: false,
    busyAction: null,
  });
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();
  const emit = (next: TModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (nextScope: ProjectAdministrationScope): Promise<void> => {
    const scope = freezeScope(nextScope);
    const scopeSwitch = !sameScope(activeScope, scope);
    if (scopeSwitch) snapshot = null;
    activeScope = scope;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit(
      buildPresentation({
        state: snapshot ? 'stale' : scopeSwitch ? 'scope_switch' : 'loading',
        scope,
        snapshot,
        reasonCode: snapshot?.reasonCode ?? null,
        retryVisible: false,
        busyAction: null,
      }),
    );
    try {
      const nextSnapshot = await client.load(scope, { signal: controller.signal });
      if (!currentRequest(revision, controller)) return;
      if (!sameScope(scope, nextSnapshot.scope)) {
        throw authorityError('project_administration_controller_scope_conflict', 409);
      }
      snapshot = nextSnapshot;
      emit(
        buildPresentation({
          state: nextSnapshot.availability === 'degraded' ? 'degraded' : 'ready',
          scope,
          snapshot,
          reasonCode: nextSnapshot.reasonCode,
          retryVisible: false,
          busyAction: null,
        }),
      );
    } catch (error) {
      if (!currentRequest(revision, controller)) return;
      const failure = classifyFailure(error);
      emit(
        buildPresentation({
          state: failure.state,
          scope,
          snapshot,
          reasonCode: failure.reasonCode,
          retryVisible: failure.retryVisible,
          busyAction: null,
        }),
      );
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

function classifyFailure(error: unknown): Readonly<{
  state: ProjectAdministrationState;
  reasonCode: string;
  retryVisible: boolean;
}> {
  const record = isRecord(error) ? error : null;
  const status = typeof record?.status === 'number' ? record.status : 0;
  const payload = isRecord(record?.payload) ? record.payload : null;
  const detail = isRecord(payload?.detail) ? payload.detail : null;
  const reasonCode =
    structuredReason(payload?.reason_code) ??
    structuredReason(payload?.code) ??
    structuredReason(detail?.code) ??
    structuredReason(record?.message) ??
    'project_administration_request_failed';
  return Object.freeze({
    state:
      status === 403
        ? 'forbidden'
        : status === 409
          ? 'conflict'
          : status === 501
            ? 'unavailable'
            : 'error',
    reasonCode,
    retryVisible:
      status === 409 || status === 408 || status === 425 || status === 429 || status >= 500,
  });
}

function authorityError(
  reasonCode: string,
  status: number,
): Error & Readonly<{ status: number; payload: Readonly<{ reason_code: string }> }> {
  return Object.assign(new Error(reasonCode), {
    status,
    payload: { reason_code: reasonCode },
  });
}

function sameScope(
  left: ProjectAdministrationScope,
  right: ProjectAdministrationScope,
): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function freezeScope(scope: ProjectAdministrationScope): ProjectAdministrationScope {
  return Object.freeze({ ...scope });
}

function structuredReason(value: unknown): string | null {
  return typeof value === 'string' && value && value.trim() === value ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
