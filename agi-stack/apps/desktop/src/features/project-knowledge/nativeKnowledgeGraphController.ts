import type { NativeMemoriesRouteBinding } from './NativeMemoriesRouteContext';
import type {
  NativeKnowledgeProcessingResultMap,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';

type EntityPage = NativeKnowledgeProcessingResultMap['entities'];
export type NativeKnowledgeGraphModel = Readonly<{
  phase: 'idle' | 'loading' | 'ready' | 'error' | 'unavailable';
  sources: EntityPage['items'];
  nextCursor: EntityPage['next_cursor'];
  graph: NativeKnowledgeProcessingResultMap['graph_source'] | null;
  selectedNode: number | null;
  error: 'failed' | 'changed' | null;
}>;
export type NativeKnowledgeGraphController = ReturnType<
  typeof createNativeKnowledgeGraphController
>;

export function createNativeKnowledgeGraphController(binding: NativeMemoriesRouteBinding) {
  const { processingClient: client } = binding;
  const authority = Object.freeze({
    ...binding.authority,
    scope: Object.freeze({ ...binding.authority.scope }),
    allowedActions: Object.freeze([...binding.authority.allowedActions]),
  });
  const available = Boolean(
    client &&
    authority.available &&
    authority.scope.authority === 'local' &&
    authority.userId &&
    authority.sessionId &&
    authority.generationDigest &&
    Number.isSafeInteger(authority.contextRevision) &&
    Number(authority.contextRevision) >= 0 &&
    ['entities', 'graph_source'].every((action) => authority.allowedActions.includes(action)),
  );
  let stopped = false;
  let epoch = 0;
  let active: AbortController | null = null;
  let observed: NativeKnowledgeScope | undefined;
  const initial = (): NativeKnowledgeGraphModel =>
    Object.freeze({
      phase: available ? 'idle' : 'unavailable',
      sources: [],
      nextCursor: null,
      graph: null,
      selectedNode: null,
      error: null,
    });
  let model = initial();
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeGraphModel>) => {
    model = Object.freeze({ ...model, ...patch });
    for (const listener of listeners) listener();
  };
  const cancel = () => {
    epoch += 1;
    active?.abort();
    active = null;
  };
  const begin = () => {
    cancel();
    active = new AbortController();
    return { epoch, signal: active.signal };
  };
  const current = (request: ReturnType<typeof begin>) =>
    !stopped && epoch === request.epoch && !request.signal.aborted;
  const check = (scope: NativeKnowledgeScope) => {
    if (
      scope.tenant_id !== authority.scope.tenantId ||
      scope.project_id !== authority.scope.projectId ||
      scope.context_revision !== authority.contextRevision ||
      scope.digest !== authority.generationDigest ||
      (observed &&
        (scope.profile_id !== observed.profile_id ||
          scope.generation !== observed.generation ||
          scope.digest !== observed.digest))
    )
      throw new Error('knowledge_scope_mismatch');
    observed = Object.freeze({ ...scope });
  };
  const fail = (error: unknown) => {
    const code = error instanceof Error ? error.message : '';
    const changed = [
      'knowledge_scope_mismatch',
      'knowledge_generation_mismatch',
      'project_knowledge_scope_conflict',
      'knowledge_revision_conflict',
    ].includes(code);
    observed = undefined;
    emit({
      phase: 'error',
      sources: [],
      nextCursor: null,
      graph: null,
      selectedNode: null,
      error: changed ? 'changed' : 'failed',
    });
  };
  const refresh = async (more = false) => {
    if (!available || stopped || (more && (!model.nextCursor || model.phase !== 'ready'))) return;
    const previous = more ? model.sources : [];
    const cursor = more ? model.nextCursor : null;
    const request = begin();
    if (!more) observed = undefined;
    emit({ phase: 'loading', graph: null, selectedNode: null, error: null, sources: previous });
    try {
      const response = await client!.query(
        authority.scope,
        {
          operation: 'entities',
          request: { limit: 50, ...(cursor ? { cursor } : {}) },
        },
        { signal: request.signal, ...(observed ? { expectedScope: observed } : {}) },
      );
      if (!current(request)) return;
      check(response.scope);
      emit({
        phase: 'ready',
        sources: [...previous, ...response.result.items],
        nextCursor: response.result.next_cursor,
      });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const open = async (row: EntityPage['items'][number]) => {
    if (!available || stopped || !observed || !model.sources.includes(row)) return;
    const expectedScope = observed;
    const request = begin();
    emit({ phase: 'loading', graph: null, selectedNode: null, error: null });
    try {
      const response = await client!.query(
        authority.scope,
        {
          operation: 'graph_source',
          source: row.reference.source,
          expected_audit_attempt: row.audit_attempt,
        },
        { signal: request.signal, expectedScope },
      );
      if (!current(request)) return;
      check(response.scope);
      const graph = response.result;
      const expected = row.reference.source;
      if (
        graph.audit_attempt !== row.audit_attempt ||
        graph.source.tenant_id !== expected.tenant_id ||
        graph.source.project_id !== expected.project_id ||
        graph.source.memory_id !== expected.memory_id ||
        graph.source.revision !== expected.revision ||
        graph.source.change_sequence !== expected.change_sequence
      )
        throw new Error('knowledge_revision_conflict');
      emit({ phase: 'ready', graph, selectedNode: null });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  return Object.freeze({
    getSnapshot: () => model,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    refresh: () => refresh(),
    nextPage: () => refresh(true),
    open,
    selectNode: (index: number | null) => {
      if (
        !stopped &&
        model.graph &&
        (index === null ||
          (Number.isInteger(index) && index >= 0 && index < model.graph.entities.length))
      )
        emit({ selectedNode: index });
    },
    stop: () => {
      stopped = true;
      cancel();
      observed = undefined;
      model = initial();
      emit({});
    },
    activate: () => {
      stopped = false;
    },
  });
}
