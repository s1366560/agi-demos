import type {
  NativeKnowledgeClient,
  NativeKnowledgeEmbeddingConfiguration,
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingResultMap,
  NativeKnowledgeProcessingSource,
  NativeKnowledgeScope,
  NativeKnowledgeStoredMemory,
} from './nativeKnowledgeContracts';
import type { NativeMemoriesAuthority } from './nativeMemoriesController';

export type NativeKnowledgeRetrievalMode = Exclude<
  NativeKnowledgeProcessingQuery['operation'],
  'configuration'
>;
type RetrievalQuery = Exclude<NativeKnowledgeProcessingQuery, { operation: 'configuration' }>;
export type NativeKnowledgeRetrievalResult = {
  [K in NativeKnowledgeRetrievalMode]: Readonly<{
    operation: K;
    result: NativeKnowledgeProcessingResultMap[K];
  }>;
}[NativeKnowledgeRetrievalMode];
export type NativeKnowledgeConfigurationSnapshot =
  NativeKnowledgeProcessingResultMap['configuration'];
export type NativeKnowledgeRetrievalModel = Readonly<{
  phase: 'idle' | 'loading' | 'results' | 'error' | 'unavailable';
  allowedActions: readonly string[];
  mode: NativeKnowledgeRetrievalMode | null;
  draft: string;
  configuration: NativeKnowledgeConfigurationSnapshot | null;
  result: NativeKnowledgeRetrievalResult | null;
  source: NativeKnowledgeStoredMemory | null;
  sourceState: 'idle' | 'loading' | 'ready' | 'changed' | 'unavailable';
  error:
    | 'failed'
    | 'contextChanged'
    | 'configurationChanged'
    | 'configurationUnavailable'
    | 'embeddingUnavailable'
    | 'configurationRequired'
    | 'queryTooLong'
    | 'queryRequired'
    | 'unavailable'
    | null;
}>;
export type NativeKnowledgeRetrievalController = ReturnType<
  typeof createNativeKnowledgeRetrievalController
>;
const MODES = ['text', 'semantic', 'entities', 'relationships'] as const;
const sameConfiguration = (
  a: NativeKnowledgeEmbeddingConfiguration | null,
  b: NativeKnowledgeEmbeddingConfiguration | null,
) =>
  a !== null &&
  b !== null &&
  a.revision === b.revision &&
  a.build_id === b.build_id &&
  a.provider_id === b.provider_id &&
  a.provider_revision === b.provider_revision &&
  a.model_id === b.model_id &&
  a.dimensions === b.dimensions &&
  a.input_contract_version === b.input_contract_version &&
  a.normalization_version === b.normalization_version;
const sameSource = (a: NativeKnowledgeProcessingSource, b: NativeKnowledgeProcessingSource) =>
  a.tenant_id === b.tenant_id &&
  a.project_id === b.project_id &&
  a.memory_id === b.memory_id &&
  a.revision === b.revision &&
  a.change_sequence === b.change_sequence;

export function createNativeKnowledgeRetrievalController({
  client,
  sourceClient,
  authority: input,
}: Readonly<{
  client?: NativeKnowledgeProcessingClient;
  sourceClient: NativeKnowledgeClient;
  authority: NativeMemoriesAuthority;
}>) {
  const authority = Object.freeze({ ...input, scope: Object.freeze({ ...input.scope }) });
  const allowedActions: readonly string[] = Object.freeze(
    client &&
      input.available &&
      input.scope.authority === 'local' &&
      input.userId &&
      input.sessionId &&
      input.generationDigest &&
      Number.isSafeInteger(input.contextRevision) &&
      Number(input.contextRevision) >= 0
      ? [...input.allowedActions]
      : [],
  );
  let stopped = false;
  let epoch = 0;
  let active: AbortController | null = null;
  let observed: NativeKnowledgeScope | undefined;
  let submitted: RetrievalQuery | null = null;
  const permitted = (operation: string) => !stopped && allowedActions.includes(operation);
  const initial = (): NativeKnowledgeRetrievalModel =>
    Object.freeze({
      phase:
        client &&
        allowedActions.some(
          (action) =>
            action === 'configuration' || MODES.includes(action as NativeKnowledgeRetrievalMode),
        )
          ? 'idle'
          : 'unavailable',
      allowedActions,
      mode: MODES.find((mode) => allowedActions.includes(mode)) ?? null,
      draft: '',
      configuration: null,
      result: null,
      source: null,
      sourceState: 'idle',
      error: null,
    });
  let model = initial();
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeRetrievalModel>) => {
    model = Object.freeze({ ...model, ...patch });
    for (const listener of [...listeners]) listener();
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
    !stopped && request.epoch === epoch && !request.signal.aborted;
  const checkScope = (scope: NativeKnowledgeScope, expected?: NativeKnowledgeScope) => {
    if (
      scope.tenant_id !== authority.scope.tenantId ||
      scope.project_id !== authority.scope.projectId ||
      scope.context_revision !== authority.contextRevision ||
      (expected &&
        (scope.profile_id !== expected.profile_id ||
          scope.generation !== expected.generation ||
          scope.digest !== expected.digest))
    )
      throw new Error('knowledge_scope_mismatch');
  };
  const query = async <Q extends NativeKnowledgeProcessingQuery>(
    command: Q,
    request: ReturnType<typeof begin>,
  ) => {
    if (!client || !permitted(command.operation)) throw new Error('knowledge_release_closed');
    if (command.operation === 'semantic' && !observed) throw new Error('knowledge_scope_mismatch');
    const response = await client.query(authority.scope, command, {
      signal: request.signal,
      expectedScope: observed as NativeKnowledgeScope,
    });
    if (!current(request)) throw new Error('request_cancelled');
    checkScope(response.scope, observed);
    observed = response.scope;
    return response;
  };
  const fail = (error: unknown) => {
    const code = error instanceof Error ? error.message : '';
    if (
      [
        'knowledge_scope_mismatch',
        'project_knowledge_scope_conflict',
        'knowledge_generation_mismatch',
      ].includes(code)
    ) {
      observed = undefined;
      submitted = null;
      model = initial();
      emit({ phase: 'error', error: 'contextChanged' });
    } else
      emit({
        phase: 'error',
        result: null,
        source: null,
        sourceState: 'idle',
        error:
          code === 'knowledge_release_closed'
            ? 'unavailable'
            : code === 'knowledge_revision_conflict'
              ? 'configurationUnavailable'
              : code === 'knowledge_embedding_provider_unavailable'
                ? 'embeddingUnavailable'
                : 'failed',
      });
  };
  const refreshConfiguration = async () => {
    if (!permitted('configuration')) return;
    const request = begin();
    submitted = null;
    emit({ phase: 'loading', error: null, result: null, source: null, sourceState: 'idle' });
    try {
      const response = await query({ operation: 'configuration' }, request);
      if (current(request)) emit({ phase: 'idle', configuration: response.result });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const show = (
    command: RetrievalQuery,
    result: NativeKnowledgeProcessingResultMap[NativeKnowledgeRetrievalMode],
    previous: NativeKnowledgeRetrievalResult | null,
  ) => {
    let snapshot = { operation: command.operation, result } as NativeKnowledgeRetrievalResult;
    if (previous && previous.operation === snapshot.operation) {
      if (previous.operation === 'text' && snapshot.operation === 'text')
        snapshot = {
          ...snapshot,
          result: {
            ...snapshot.result,
            items: [...previous.result.items, ...snapshot.result.items],
          },
        };
      if (previous.operation === 'entities' && snapshot.operation === 'entities')
        snapshot = {
          ...snapshot,
          result: {
            ...snapshot.result,
            items: [...previous.result.items, ...snapshot.result.items],
          },
        };
      if (previous.operation === 'relationships' && snapshot.operation === 'relationships')
        snapshot = {
          ...snapshot,
          result: {
            ...snapshot.result,
            items: [...previous.result.items, ...snapshot.result.items],
          },
        };
    }
    submitted = command;
    emit({ phase: 'results', result: snapshot, error: null });
  };
  const submit = async () => {
    const mode = model.mode;
    if (!mode || !permitted(mode) || model.phase === 'loading') return;
    if ((mode === 'text' || mode === 'semantic') && !model.draft.length) {
      emit({ error: 'queryRequired' });
      return;
    }
    if (new TextEncoder().encode(model.draft).length > 4096) {
      emit({ error: 'queryTooLong' });
      return;
    }
    const draft = model.draft;
    const selected = model.configuration?.configuration ?? null;
    if (mode === 'semantic' && (!permitted('configuration') || !selected)) {
      emit({ error: 'configurationRequired' });
      return;
    }
    const request = begin();
    submitted = null;
    emit({ phase: 'loading', result: null, source: null, sourceState: 'idle', error: null });
    try {
      let command: RetrievalQuery;
      if (mode === 'semantic') {
        const response = await query({ operation: 'configuration' }, request);
        if (!current(request)) return;
        emit({ configuration: response.result });
        if (!sameConfiguration(selected, response.result.configuration)) {
          emit({ phase: 'idle', error: 'configurationChanged' });
          return;
        }
        command = {
          operation: 'semantic',
          build_id: selected!.build_id,
          config_revision: selected!.revision,
          query: draft,
          limit: 25,
        };
      } else
        command =
          mode === 'text'
            ? { operation: 'text', literal: draft, request: { limit: 25 } }
            : { operation: mode, request: { limit: 25 } };
      const response = await query(command, request);
      if (!current(request)) return;
      if (
        command.operation === 'semantic' &&
        'configuration' in response.result &&
        !sameConfiguration(selected, response.result.configuration)
      ) {
        emit({ phase: 'error', error: 'configurationChanged', result: null });
        return;
      }
      show(command, response.result, null);
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const nextPage = async () => {
    const previous = model.result;
    if (
      model.phase !== 'results' ||
      !previous ||
      previous.operation === 'semantic' ||
      !previous.result.next_cursor ||
      !submitted ||
      submitted.operation === 'semantic' ||
      !permitted(submitted.operation)
    )
      return;
    const command: RetrievalQuery = {
      ...submitted,
      request: { ...submitted.request, cursor: previous.result.next_cursor },
    };
    const request = begin();
    emit({ phase: 'loading', source: null, sourceState: 'idle', error: null });
    try {
      const response = await query(command, request);
      if (current(request)) show(command, response.result, previous);
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const viewSource = async (source: NativeKnowledgeProcessingSource) => {
    if (!permitted('view') || !model.result || !observed || model.phase === 'loading') return;
    const result = model.result;
    const sources =
      result.operation === 'semantic'
        ? result.result.hits.map((hit) => hit.input.source)
        : result.operation === 'entities'
          ? result.result.items.map((item) => item.reference.source)
          : result.result.items.map((item) => item.source);
    if (!sources.some((value) => sameSource(value, source))) return;
    const request = begin();
    emit({ source: null, sourceState: 'loading' });
    try {
      const response = await sourceClient.execute(
        authority.scope,
        { operation: 'get', id: source.memory_id },
        { signal: request.signal, expectedScope: observed },
      );
      if (!current(request)) return;
      checkScope(response.scope, observed);
      const memory = response.result.memory;
      if (
        memory.id !== source.memory_id ||
        memory.project_id !== source.project_id ||
        memory.version !== source.revision
      )
        emit({ source: null, sourceState: 'changed' });
      else emit({ source: memory, sourceState: 'ready' });
    } catch (error) {
      if (!current(request)) return;
      if (
        error instanceof Error &&
        [
          'knowledge_scope_mismatch',
          'knowledge_generation_mismatch',
          'project_knowledge_scope_conflict',
        ].includes(error.message)
      )
        fail(error);
      else emit({ source: null, sourceState: 'unavailable' });
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
    refreshConfiguration,
    submit,
    nextPage,
    viewSource,
    setMode: (mode: NativeKnowledgeRetrievalMode) => {
      if (!permitted(mode) || !MODES.includes(mode)) return;
      cancel();
      submitted = null;
      emit({
        mode,
        phase: 'idle',
        draft: '',
        result: null,
        source: null,
        sourceState: 'idle',
        error: null,
      });
    },
    setDraft: (draft: string) => {
      if (!model.mode || !permitted(model.mode)) return;
      cancel();
      submitted = null;
      emit({ draft, phase: 'idle', result: null, source: null, sourceState: 'idle', error: null });
    },
    stop: () => {
      stopped = true;
      cancel();
      observed = undefined;
      submitted = null;
      model = initial();
      emit({});
    },
    activate: () => {
      stopped = false;
    },
  });
}
