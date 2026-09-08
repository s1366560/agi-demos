import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import { projectKnowledgeError } from './projectKnowledgeClient';
import { PROJECT_GRAPH_LOCAL_REASON, type ProjectGraphClient } from './projectGraphClient';
import {
  buildProjectGraphPresentation,
  type ProjectGraphViewModel,
} from './projectGraphPresentationModel';
import { projectGraphSourceUuids, type ProjectGraphSelection } from './projectGraphNavigation';

export type ProjectGraphController = ReturnType<typeof createProjectGraphController>;
export function createProjectGraphController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectGraphClient;
  initialScope: ProjectKnowledgeScope;
}>) {
  let scope = Object.freeze({ ...initialScope });
  let model = buildProjectGraphPresentation({ kind: 'loading', scope, scopeSwitch: false });
  let epoch = 0;
  let stopped = false;
  let read: AbortController | null = null;
  let sourceRead: AbortController | null = null;
  const listeners = new Set<() => void>();
  const emit = (next: ProjectGraphViewModel) => {
    model = Object.freeze(next);
    for (const listener of [...listeners]) listener();
  };
  const clearSource = () => {
    sourceRead?.abort();
    sourceRead = null;
    return { source: null, sourceUuid: null, sourceState: 'idle' as const };
  };
  const cancel = () => {
    epoch += 1;
    read?.abort();
    read = null;
    clearSource();
  };
  const current = (revision: number, request: AbortController) =>
    !stopped && revision === epoch && !request.signal.aborted;
  const fail = (error: unknown) => {
    const status =
      error && typeof error === 'object' && 'status' in error ? Number(error.status) : 0;
    const reasonCode =
      status === 409
        ? 'project_graph_context_changed'
        : status === 401 || status === 403
          ? 'project_graph_forbidden'
          : 'project_graph_unavailable';
    emit(
      buildProjectGraphPresentation({
        kind: 'failure',
        scope,
        state: status === 401 || status === 403 ? 'forbidden' : 'unavailable',
        reasonCode,
        retryable: true,
      }),
    );
  };
  const load = async (nextScope: ProjectKnowledgeScope) => {
    const scopeSwitch = !sameScope(scope, nextScope);
    cancel();
    stopped = false;
    scope = Object.freeze({ ...nextScope });
    if (scope.authority !== 'cloud' || authority !== 'cloud') {
      emit(
        buildProjectGraphPresentation({
          kind: 'failure',
          scope,
          state: 'unavailable',
          reasonCode: PROJECT_GRAPH_LOCAL_REASON,
          retryable: false,
        }),
      );
      return;
    }
    const request = new AbortController();
    read = request;
    const revision = epoch;
    emit(buildProjectGraphPresentation({ kind: 'loading', scope, scopeSwitch }));
    try {
      const snapshot = await client.load(scope, { signal: request.signal });
      if (!current(revision, request)) return;
      if (!sameScope(scope, snapshot.scope))
        throw projectKnowledgeError('project_graph_context_changed', 409);
      emit(buildProjectGraphPresentation({ kind: 'snapshot', snapshot }));
    } catch (error) {
      if (current(revision, request)) fail(error);
    } finally {
      if (read === request) read = null;
    }
  };
  const select = (selection: ProjectGraphSelection) => {
    if (
      stopped ||
      !model.allowedActions.includes('view') ||
      !(selection.kind === 'node' ? model.nodes : model.edges).some(
        (item) => item.id === selection.id,
      )
    )
      return;
    emit({ ...model, ...clearSource(), selection: Object.freeze({ ...selection }) });
  };
  const openSource = async (episodeUuid: string) => {
    if (
      stopped ||
      model.scopeRevision === null ||
      !model.allowedActions.includes('view') ||
      !projectGraphSourceUuids(model, model.selection).includes(episodeUuid)
    )
      return;
    clearSource();
    const request = new AbortController();
    sourceRead = request;
    const revision = epoch;
    const expectedContextRevision = model.scopeRevision;
    emit({ ...model, sourceUuid: episodeUuid, source: null, sourceState: 'loading' });
    try {
      const snapshot = await client.loadSource(
        scope,
        { episodeUuid, expectedContextRevision },
        { signal: request.signal },
      );
      if (!current(revision, request) || sourceRead !== request) return;
      if (!sameScope(scope, snapshot.scope) || snapshot.scopeRevision !== expectedContextRevision)
        throw projectKnowledgeError('project_graph_context_changed', 409);
      if (
        snapshot.nodes.length > 1 ||
        snapshot.edges.length !== 0 ||
        snapshot.nodes.some(
          (node) =>
            node.uuid !== episodeUuid ||
            node.type !== 'Episodic' ||
            node.project_id !== scope.projectId ||
            node.tenant_id !== scope.tenantId,
        )
      )
        throw projectKnowledgeError('project_graph_source_invalid', 409);
      emit({ ...model, source: snapshot.nodes[0] ?? null, sourceState: 'ready' });
    } catch (error) {
      if (!current(revision, request) || sourceRead !== request) return;
      const status =
        error && typeof error === 'object' && 'status' in error ? Number(error.status) : 0;
      if ([401, 403, 409].includes(status)) fail(error);
      else emit({ ...model, source: null, sourceState: 'error' });
    } finally {
      if (sourceRead === request) sourceRead = null;
    }
  };
  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    load,
    retry: () => load(scope),
    cancel,
    stop: () => {
      stopped = true;
      cancel();
    },
    selectNode: (id: string) => select({ kind: 'node', id }),
    selectEdge: (id: string) => select({ kind: 'edge', id }),
    openSource,
  });
}
function sameScope(left: ProjectKnowledgeScope, right: ProjectKnowledgeScope) {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}
