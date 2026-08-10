import { DesktopApiError } from '../../api/client';
import type {
  ProjectKnowledgeAuthority,
  ProjectKnowledgeScope,
} from '../project-knowledge/projectKnowledgeClient';
import type {
  ProjectPlaybooksClient,
  ProjectPlaybooksSnapshot,
  ProjectPlaybook,
  ProjectReflectionVerdict,
} from './projectPlaybooksClient';

export type ProjectPlaybooksViewModel = Readonly<{
  routeId: 'project-playbooks';
  state: 'loading' | 'stale' | 'empty' | 'ready' | 'forbidden' | 'unavailable' | 'error';
  scope: ProjectKnowledgeScope;
  reasonCode: string | null;
  retryVisible: boolean;
  allowedActions: readonly string[];
  playbooks: readonly ProjectPlaybook[];
  verdicts: readonly ProjectReflectionVerdict[];
}>;
export type ProjectPlaybooksController = Readonly<{
  getSnapshot(): ProjectPlaybooksViewModel;
  subscribe(listener: () => void): () => void;
  load(scope: ProjectKnowledgeScope): Promise<void>;
  retry(): Promise<void>;
  cancel(): void;
  stop(): void;
}>;

export function createProjectPlaybooksController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectPlaybooksClient;
  initialScope: ProjectKnowledgeScope;
}>): ProjectPlaybooksController {
  let activeScope = freezeScope(initialScope);
  let lastSnapshot: ProjectPlaybooksSnapshot | null = null;
  let model = loadingModel(activeScope, false, null);
  let activeRequest: AbortController | null = null;
  let requestRevision = 0;
  let stopped = false;
  const listeners = new Set<() => void>();
  const emit = (next: ProjectPlaybooksViewModel) => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = () => {
    requestRevision += 1;
    activeRequest?.abort();
    activeRequest = null;
  };
  const load = async (scopeInput: ProjectKnowledgeScope): Promise<void> => {
    if (stopped) return;
    const scope = freezeScope(scopeInput);
    const scopeSwitch = !sameScope(activeScope, scope);
    activeScope = scope;
    cancel();
    const revision = requestRevision;
    if (scope.authority !== authority) {
      emit(
        failureModel(
          scope,
          'unavailable',
          'project_playbooks_controller_authority_mismatch',
          false,
        ),
      );
      return;
    }
    const controller = new AbortController();
    activeRequest = controller;
    emit(loadingModel(scope, scopeSwitch, lastSnapshot));
    try {
      const snapshot = await client.load(scope, { signal: controller.signal });
      if (!current(revision, controller)) return;
      lastSnapshot = snapshot;
      emit(snapshotModel(snapshot));
    } catch (error) {
      if (!current(revision, controller)) return;
      emit(failureFor(error, scope));
    } finally {
      if (current(revision, controller)) activeRequest = null;
    }
  };
  const current = (revision: number, controller: AbortController) =>
    !stopped &&
    revision === requestRevision &&
    activeRequest === controller &&
    !controller.signal.aborted;
  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: () => load(activeScope),
    cancel,
    stop() {
      stopped = true;
      cancel();
      listeners.clear();
    },
  });
}

function loadingModel(
  scope: ProjectKnowledgeScope,
  scopeSwitch: boolean,
  previous: ProjectPlaybooksSnapshot | null,
): ProjectPlaybooksViewModel {
  const keepPrevious = !scopeSwitch && previous !== null && sameScope(previous.scope, scope);
  return Object.freeze({
    routeId: 'project-playbooks',
    state: keepPrevious ? 'stale' : 'loading',
    scope,
    reasonCode: null,
    retryVisible: false,
    allowedActions: Object.freeze([...(keepPrevious ? previous.allowedActions : [])]),
    playbooks: keepPrevious ? previous.playbooks : Object.freeze([]),
    verdicts: keepPrevious ? previous.verdicts : Object.freeze([]),
  });
}

function snapshotModel(snapshot: ProjectPlaybooksSnapshot): ProjectPlaybooksViewModel {
  return Object.freeze({
    routeId: 'project-playbooks',
    state: snapshot.playbooks.length === 0 && snapshot.verdicts.length === 0 ? 'empty' : 'ready',
    scope: snapshot.scope,
    reasonCode: snapshot.reasonCode,
    retryVisible: false,
    allowedActions: Object.freeze([...snapshot.allowedActions]),
    playbooks: snapshot.playbooks,
    verdicts: snapshot.verdicts,
  });
}

function failureFor(error: unknown, scope: ProjectKnowledgeScope): ProjectPlaybooksViewModel {
  const status = error instanceof DesktopApiError ? error.status : 0;
  const payload =
    error instanceof DesktopApiError && isRecord(error.payload) ? error.payload : null;
  const detail = isRecord(payload?.detail) ? payload.detail : null;
  const reasonCode =
    exactReason(payload?.reason_code) ??
    exactReason(payload?.code) ??
    exactReason(detail?.code) ??
    (error instanceof Error && error.message === 'cloud_request_broker_missing'
      ? error.message
      : 'project_playbooks_request_failed');
  return failureModel(
    scope,
    status === 403
      ? 'forbidden'
      : status === 0 || status === 501 || status === 503
        ? 'unavailable'
        : 'error',
    reasonCode,
    status === 408 || status === 425 || status === 429 || status >= 500,
  );
}

function failureModel(
  scope: ProjectKnowledgeScope,
  state: 'forbidden' | 'unavailable' | 'error',
  reasonCode: string,
  retryVisible: boolean,
): ProjectPlaybooksViewModel {
  return Object.freeze({
    routeId: 'project-playbooks',
    state,
    scope,
    reasonCode,
    retryVisible,
    allowedActions: Object.freeze([]),
    playbooks: Object.freeze([]),
    verdicts: Object.freeze([]),
  });
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

function exactReason(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
