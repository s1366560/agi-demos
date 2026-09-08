import type {
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingCommandClient,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingTaskSnapshot,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';
import type { DiagnosticProcessingSelection } from './nativeKnowledgeDiagnosticsController';
import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import { sameJson } from './nativeKnowledgeRelationships';
import { nativeKnowledgeUiFailure } from './nativeKnowledgeUiSession';

type Retry = Extract<NativeKnowledgeProcessingCommand, { operation: 'retry_processing' }>;
export type NativeKnowledgeProcessingRetryModel = Readonly<{
  phase:
    | 'idle'
    | 'loading'
    | 'selected'
    | 'reviewing'
    | 'executing'
    | 'accepted'
    | 'uncertain'
    | 'error'
    | 'unavailable';
  selection: DiagnosticProcessingSelection | null;
  snapshot: NativeKnowledgeProcessingTaskSnapshot | null;
  command: Retry | null;
  recoveryRequired: boolean;
  recoveredUnknown: boolean;
  error: 'failed' | 'conflict' | 'contextChanged' | null;
}>;
export type NativeKnowledgeProcessingRetryController = ReturnType<
  typeof createNativeKnowledgeProcessingRetryController
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

/** A retry queues one exact failed attempt; it never dispatches extraction. */
export function createNativeKnowledgeProcessingRetryController({
  queryClient,
  commandClient,
  authority,
  onRefresh,
}: Readonly<{
  queryClient?: NativeKnowledgeProcessingClient;
  commandClient?: NativeKnowledgeProcessingCommandClient;
  authority: NativeMemoriesAuthority;
  onRefresh?: () => void | Promise<void>;
}>) {
  const scope = Object.freeze({ ...authority.scope });
  const contextRevision = authority.contextRevision;
  const generationDigest = authority.generationDigest;
  const available = Boolean(
    queryClient &&
    commandClient &&
    authority.available &&
    scope.authority === 'local' &&
    authority.userId &&
    authority.sessionId &&
    authority.generationDigest &&
    Number.isSafeInteger(authority.contextRevision) &&
    Number(authority.contextRevision) >= 0 &&
    ['processing_task', 'retry_processing'].every((action) =>
      authority.allowedActions.includes(action),
    ),
  );
  const initial = (): NativeKnowledgeProcessingRetryModel => ({
    phase: available ? 'idle' : 'unavailable',
    selection: null,
    snapshot: null,
    command: null,
    recoveryRequired: false,
    recoveredUnknown: false,
    error: null,
  });
  let model = immutable(initial());
  let stopped = false;
  let epoch = 0;
  let active: AbortController | null = null;
  let observed: NativeKnowledgeScope | undefined;
  let unknown: Retry | null = null;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeProcessingRetryModel>) => {
    model = immutable({ ...model, ...patch });
    [...listeners].forEach((listener) => listener());
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
  const current = (r: ReturnType<typeof begin>) =>
    !stopped && r.epoch === epoch && !r.signal.aborted;
  const locked = () =>
    !available ||
    stopped ||
    model.phase === 'loading' ||
    model.phase === 'executing' ||
    model.recoveryRequired;
  const check = (value: NativeKnowledgeScope) => {
    if (
      value.tenant_id !== scope.tenantId ||
      value.project_id !== scope.projectId ||
      value.context_revision !== contextRevision ||
      value.digest !== generationDigest ||
      (observed && !sameJson(observed, value))
    )
      throw Error('knowledge_scope_mismatch');
  };
  const read = async (source: Retry['source'], r: ReturnType<typeof begin>) => {
    const response = await queryClient!.query(
      scope,
      { operation: 'processing_task', source },
      { expectedScope: observed, signal: r.signal },
    );
    if (!current(r)) throw Error('request_cancelled');
    check(response.scope);
    observed = immutable(response.scope);
    if (!sameJson(response.result.source, source)) throw Error('knowledge_scope_mismatch');
    return immutable(response.result);
  };
  const eligible = (snapshot: NativeKnowledgeProcessingTaskSnapshot, attempt: number) =>
    snapshot.current && snapshot.task?.state === 'failed' && snapshot.task.attempt === attempt;
  const fail = (error: unknown) => {
    const kind = nativeKnowledgeUiFailure(error);
    if (kind === 'contextChanged') {
      unknown = null;
      observed = undefined;
      emit({ ...initial(), phase: 'error', error: kind });
    } else
      emit({
        phase: model.recoveryRequired ? 'uncertain' : 'error',
        selection: null,
        command: null,
        error: kind === 'uncertain' ? 'failed' : kind,
      });
  };
  const changed = (snapshot: NativeKnowledgeProcessingTaskSnapshot) => {
    emit({
      phase: 'idle',
      snapshot,
      selection: null,
      command: null,
      error: 'conflict',
    });
  };
  const notify = (r: ReturnType<typeof begin>) => {
    void Promise.resolve()
      .then(() => {
        if (current(r)) return onRefresh?.();
      })
      .catch(() => {});
  };
  const select = async (input: DiagnosticProcessingSelection) => {
    if (locked()) return;
    const selection = immutable(input);
    const r = begin();
    emit({
      phase: 'loading',
      selection: null,
      snapshot: null,
      command: null,
      error: null,
      recoveredUnknown: false,
    });
    try {
      check(selection.scope);
      observed = immutable(selection.scope);
      const snapshot = await read(selection.failure.source, r);
      if (!current(r)) return;
      if (!eligible(snapshot, selection.failure.attempt)) return changed(snapshot);
      emit({ phase: 'selected', selection, snapshot });
    } catch (error) {
      if (current(r)) fail(error);
    }
  };
  const review = async () => {
    if (locked() || model.phase !== 'selected' || !model.selection) return;
    const selection = model.selection;
    const r = begin();
    emit({ phase: 'loading', error: null });
    try {
      const snapshot = await read(selection.failure.source, r);
      if (!current(r)) return;
      if (!eligible(snapshot, selection.failure.attempt)) return changed(snapshot);
      emit({
        phase: 'reviewing',
        snapshot,
        command: {
          operation: 'retry_processing',
          source: selection.failure.source,
          expected_attempt: selection.failure.attempt,
        },
      });
    } catch (error) {
      if (current(r)) fail(error);
    }
  };
  const confirm = async () => {
    if (locked() || model.phase !== 'reviewing' || !model.command) return;
    const command = model.command;
    const r = begin();
    let writeStarted = false;
    emit({ phase: 'executing', error: null });
    try {
      const snapshot = await read(command.source, r);
      if (!current(r)) return;
      if (!eligible(snapshot, command.expected_attempt)) return changed(snapshot);
      writeStarted = true;
      const response = await commandClient!.execute(scope, command, {
        expectedScope: observed!,
        signal: r.signal,
      });
      if (!current(r)) return;
      check(response.scope);
      if (
        !response.result.accepted ||
        response.result.attempt !== command.expected_attempt ||
        !sameJson(response.result.source, command.source)
      )
        throw Error('invalid_retry_response');
      emit({
        phase: 'accepted',
        selection: null,
        command: null,
        snapshot: null,
      });
      notify(r);
    } catch (error) {
      if (!current(r)) return;
      if (writeStarted && nativeKnowledgeUiFailure(error) === 'uncertain') {
        unknown = command;
        emit({
          phase: 'uncertain',
          recoveryRequired: true,
          command: null,
          selection: null,
          snapshot: null,
          error: null,
        });
      } else fail(error);
    }
  };
  const recover = async () => {
    if (stopped || !available || !unknown || !model.recoveryRequired || model.phase === 'loading')
      return;
    const command = unknown;
    const r = begin();
    emit({ phase: 'loading', error: null });
    try {
      const snapshot = await read(command.source, r);
      if (!current(r)) return;
      unknown = null;
      // Current state permits a fresh decision, but never proves who changed it.
      emit({
        phase: 'idle',
        snapshot,
        selection: null,
        command: null,
        recoveryRequired: false,
        recoveredUnknown: true,
      });
      notify(r);
    } catch (error) {
      if (current(r)) fail(error);
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
    select,
    review,
    confirm,
    recover,
    invalidateSources: () => {
      if (stopped || model.phase === 'executing' || model.recoveryRequired) return;
      cancel();
      emit(initial());
    },
    cancel: () => {
      if (!locked()) {
        cancel();
        emit(initial());
      }
    },
    stop: () => {
      stopped = true;
      cancel();
      unknown = null;
      observed = undefined;
      emit(initial());
    },
    activate: () => {
      stopped = false;
    },
  });
}
