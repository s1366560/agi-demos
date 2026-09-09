import type {
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingSource,
  NativeKnowledgeScope,
  NativeKnowledgeProcessingResultMap,
  NativeKnowledgeIndexFailureDetail,
  NativeKnowledgeProcessingFailureDetail,
  NativeKnowledgeEmbeddingConfiguration,
  NativeKnowledgeDiagnosticsExport,
} from './nativeKnowledgeContracts';
import type { NativeMemoriesAuthority } from './nativeMemoriesController';

export type DiagnosticIndexSelection = Readonly<{
  scope: NativeKnowledgeScope;
  configuration: NativeKnowledgeEmbeddingConfiguration;
  failure: NativeKnowledgeIndexFailureDetail;
}>;
export type DiagnosticProcessingSelection = Readonly<{
  scope: NativeKnowledgeScope;
  failure: NativeKnowledgeProcessingFailureDetail;
}>;
type Mode = 'failed_processing' | 'failed_index';
export type NativeKnowledgeDiagnosticsModel = Readonly<{
  phase: 'idle' | 'loading' | 'ready' | 'error' | 'unavailable';
  allowedActions: readonly string[];
  mode: Mode;
  processing: NativeKnowledgeProcessingResultMap['failed_processing'] | null;
  index: NativeKnowledgeProcessingResultMap['failed_index'] | null;
  audits: NativeKnowledgeProcessingResultMap['processing_audits'] | null;
  auditSource: NativeKnowledgeProcessingSource | null;
  configuration: NativeKnowledgeEmbeddingConfiguration | null;
  error: 'failed' | 'contextChanged' | 'configurationRequired' | null;
}>;
export type NativeKnowledgeDiagnosticsController = ReturnType<
  typeof createNativeKnowledgeDiagnosticsController
>;
const immutable = <T>(value: T): T => {
  const copy = structuredClone(value);
  const freeze = (item: unknown) => {
    if (item && typeof item === 'object') {
      Object.values(item).forEach(freeze);
      Object.freeze(item);
    }
  };
  freeze(copy);
  return copy;
};
export function createNativeKnowledgeDiagnosticsController({
  client,
  authority,
}: Readonly<{
  client?: NativeKnowledgeProcessingClient;
  authority: NativeMemoriesAuthority;
}>) {
  const scope = Object.freeze({ ...authority.scope });
  const contextRevision = authority.contextRevision;
  const allowedActions = Object.freeze(
    client &&
      authority.available &&
      scope.authority === 'local' &&
      authority.userId &&
      authority.sessionId &&
      authority.generationDigest &&
      Number.isSafeInteger(contextRevision) &&
      Number(contextRevision) >= 0
      ? [...authority.allowedActions]
      : [],
  );
  const permitted = (action: string) => allowedActions.includes(action);
  const initial = (): NativeKnowledgeDiagnosticsModel => ({
    phase: permitted('failed_processing') || permitted('failed_index') ? 'idle' : 'unavailable',
    allowedActions,
    mode: permitted('failed_processing') ? 'failed_processing' : 'failed_index',
    processing: null,
    index: null,
    audits: null,
    auditSource: null,
    configuration: null,
    error: null,
  });
  let model = immutable(initial());
  let observed: NativeKnowledgeScope | undefined;
  let epoch = 0;
  let stopped = false;
  let abort: AbortController | null = null;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeDiagnosticsModel>) => {
    model = immutable({ ...model, ...patch });
    listeners.forEach((listener) => listener());
  };
  const cancel = () => {
    epoch++;
    abort?.abort();
    abort = null;
  };
  const begin = () => {
    cancel();
    abort = new AbortController();
    return { epoch, signal: abort.signal };
  };
  const current = (r: ReturnType<typeof begin>) =>
    !stopped && r.epoch === epoch && !r.signal.aborted;
  const check = (value: NativeKnowledgeScope) => {
    if (
      value.tenant_id !== scope.tenantId ||
      value.project_id !== scope.projectId ||
      value.context_revision !== contextRevision ||
      (observed &&
        (value.profile_id !== observed.profile_id ||
          value.generation !== observed.generation ||
          value.digest !== observed.digest))
    )
      throw Error('knowledge_scope_mismatch');
    observed = immutable(value);
  };
  const failed = (error: unknown) => {
    const status =
      error && typeof error === 'object' && 'status' in error ? Number(error.status) : 0;
    const message = error instanceof Error ? error.message : '';
    const context =
      [401, 403, 409].includes(status) ||
      [
        'knowledge_scope_mismatch',
        'knowledge_generation_mismatch',
        'project_knowledge_scope_conflict',
      ].includes(message);
    observed = undefined;
    emit({
      ...initial(),
      phase: 'error',
      error: context ? 'contextChanged' : 'failed',
    });
  };
  const refresh = async (mode: Mode = model.mode, next = false) => {
    if (stopped || !permitted(mode) || (mode === 'failed_index' && !permitted('configuration')))
      return;
    const cursor = next
      ? (mode === 'failed_processing' ? model.processing : model.index)?.next_cursor
      : null;
    if (next && !cursor) return;
    const previousConfiguration = model.configuration;
    const r = begin();
    emit({
      phase: 'loading',
      mode,
      processing: null,
      index: null,
      audits: null,
      auditSource: null,
      error: null,
    });
    try {
      if (mode === 'failed_processing') {
        const result = await client!.query(
          scope,
          { operation: mode, request: { limit: 20, cursor } },
          { signal: r.signal, expectedScope: observed },
        );
        if (!current(r)) return;
        check(result.scope);
        emit({
          phase: 'ready',
          processing: result.result,
          configuration: null,
        });
      } else {
        const config = await client!.query(
          scope,
          { operation: 'configuration' },
          { signal: r.signal, expectedScope: observed },
        );
        if (!current(r)) return;
        check(config.scope);
        const configuration = config.result.configuration;
        if (!configuration) {
          emit({
            phase: 'ready',
            configuration: null,
            error: 'configurationRequired',
          });
          return;
        }
        if (next && JSON.stringify(configuration) !== JSON.stringify(previousConfiguration))
          throw Error('knowledge_scope_mismatch');
        const result = await client!.query(
          scope,
          {
            operation: mode,
            build_id: configuration.build_id,
            config_revision: configuration.revision,
            request: { limit: 20, cursor },
          },
          { signal: r.signal, expectedScope: observed },
        );
        if (!current(r)) return;
        check(result.scope);
        emit({ phase: 'ready', index: result.result, configuration });
      }
    } catch (error) {
      if (current(r)) failed(error);
    }
  };
  const inspect = async (source: NativeKnowledgeProcessingSource, next = false) => {
    if (stopped || model.phase !== 'ready' || !permitted('processing_audits')) return;
    const same = (value: NativeKnowledgeProcessingSource) =>
      JSON.stringify(value) === JSON.stringify(source);
    const inPage =
      model.processing?.items.some((item) => same(item.source)) ||
      model.index?.items.some((item) => same(item.input.source));
    if (
      !inPage ||
      (next && (!model.auditSource || !same(model.auditSource) || !model.audits?.next_cursor))
    )
      return;
    const cursor = next ? model.audits!.next_cursor : null;
    const r = begin();
    emit({ phase: 'loading', audits: null, auditSource: source, error: null });
    try {
      const result = await client!.query(
        scope,
        {
          operation: 'processing_audits',
          source,
          request: { limit: 20, cursor },
        },
        { signal: r.signal, expectedScope: observed },
      );
      if (!current(r)) return;
      check(result.scope);
      emit({ phase: 'ready', audits: result.result });
    } catch (error) {
      if (current(r)) failed(error);
    }
  };
  const exportDiagnostics = async (): Promise<NativeKnowledgeDiagnosticsExport | null> => {
    if (stopped || !permitted('diagnostics_export')) return null;
    const r = begin();
    try {
      const result = await client!.query(
        scope,
        { operation: 'diagnostics_export' },
        { signal: r.signal, expectedScope: observed },
      );
      if (!current(r)) return null;
      check(result.scope);
      return result.result ? immutable(result.result) : null;
    } catch (error) {
      if (current(r)) failed(error);
      return null;
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
    refresh,
    inspect,
    exportDiagnostics,
    next: () => refresh(model.mode, true),
    processingSelection: (position: number): DiagnosticProcessingSelection | null => {
      const failure = model.processing?.items[position];
      return !stopped &&
        model.phase === 'ready' &&
        model.mode === 'failed_processing' &&
        permitted('retry_processing') &&
        permitted('processing_task') &&
        failure &&
        observed
        ? immutable({ scope: observed, failure })
        : null;
    },
    selection: (position: number): DiagnosticIndexSelection | null => {
      const failure = model.index?.items[position];
      return !stopped &&
        model.phase === 'ready' &&
        permitted('retry_index') &&
        failure &&
        model.configuration &&
        observed
        ? immutable({
            scope: observed,
            configuration: model.configuration,
            failure,
          })
        : null;
    },
    stop: () => {
      stopped = true;
      cancel();
      observed = undefined;
      emit(initial());
    },
    activate: () => {
      stopped = false;
    },
  });
}
