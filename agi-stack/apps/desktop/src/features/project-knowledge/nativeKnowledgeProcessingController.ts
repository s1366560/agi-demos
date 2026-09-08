import type {
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingCommandClient,
  NativeKnowledgeProcessingCommandResultMap,
  NativeKnowledgeIndexReceipt,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';
import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import type { NativeKnowledgeConfigurationSnapshot } from './nativeKnowledgeRetrievalController';

type SupportedOperation = 'index_one' | 'promote_index' | 'retry_index' | 'select_embedding';
type SupportedCommand = Extract<
  NativeKnowledgeProcessingCommand,
  { operation: SupportedOperation }
>;
type Outcome = {
  [K in SupportedOperation]: Readonly<{
    operation: K;
    result: NativeKnowledgeProcessingCommandResultMap[K];
  }>;
}[SupportedOperation];
type FailedTask = Readonly<{
  buildId: string;
  configRevision: number;
  receipt: NativeKnowledgeIndexReceipt;
}>;
export type NativeKnowledgeProcessingModel = Readonly<{
  phase:
    | 'idle'
    | 'loading'
    | 'reviewing'
    | 'executing'
    | 'accepted'
    | 'uncertain'
    | 'error'
    | 'unavailable';
  allowedActions: readonly string[];
  snapshot: NativeKnowledgeConfigurationSnapshot | null;
  selection: SupportedCommand | null;
  failedTask: FailedTask | null;
  outcome: Outcome | null;
  recoveryRequired: boolean;
  error:
    | 'failed'
    | 'refreshFailed'
    | 'contextChanged'
    | 'reviewChanged'
    | 'configurationRequired'
    | 'activeRequired'
    | 'failedReceiptRequired'
    | 'conflict'
    | 'unavailable'
    | 'embeddingUnavailable'
    | null;
  notice: 'recoveredUnknown' | null;
}>;
export type NativeKnowledgeProcessingController = ReturnType<
  typeof createNativeKnowledgeProcessingController
>;
const OPERATIONS = [
  'index_one',
  'promote_index',
  'retry_index',
  'select_embedding',
  'configure_embedding',
  'process_one',
];
const configurationKey = (snapshot: NativeKnowledgeConfigurationSnapshot) => {
  const c = snapshot.configuration;
  return JSON.stringify(
    c && [
      c.revision,
      c.build_id,
      c.provider_id,
      c.provider_revision,
      c.model_id,
      c.dimensions,
      c.input_contract_version,
      c.normalization_version,
    ],
  );
};
const freezeCommand = (command: SupportedCommand): SupportedCommand => {
  const freeze = (value: unknown): unknown => {
    if (value && typeof value === 'object') {
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }
    return value;
  };
  return freeze(structuredClone(command)) as SupportedCommand;
};

export function createNativeKnowledgeProcessingController({
  queryClient,
  commandClient,
  authority: input,
  onAccepted,
}: Readonly<{
  queryClient?: NativeKnowledgeProcessingClient;
  commandClient?: NativeKnowledgeProcessingCommandClient;
  authority: NativeMemoriesAuthority;
  onAccepted?: () => void | Promise<void>;
}>) {
  const scope = Object.freeze({ ...input.scope });
  const contextRevision = input.contextRevision;
  const valid =
    input.available &&
    scope.authority === 'local' &&
    input.userId &&
    input.sessionId &&
    input.generationDigest &&
    Number.isSafeInteger(contextRevision) &&
    Number(contextRevision) >= 0;
  const declared = Object.freeze(valid ? [...input.allowedActions] : []);
  const allowedActions = Object.freeze(
    queryClient && commandClient && declared.includes('configuration') ? [...declared] : [],
  );
  let stopped = false;
  let epoch = 0;
  let abort: AbortController | null = null;
  let observed: NativeKnowledgeScope | undefined;
  const listeners = new Set<() => void>();
  const initial = (): NativeKnowledgeProcessingModel =>
    Object.freeze({
      phase: allowedActions.some((action) => OPERATIONS.includes(action)) ? 'idle' : 'unavailable',
      allowedActions: declared,
      snapshot: null,
      selection: null,
      failedTask: null,
      outcome: null,
      recoveryRequired: false,
      error: null,
      notice: null,
    });
  let model = initial();
  const emit = (patch: Partial<NativeKnowledgeProcessingModel>) => {
    model = Object.freeze({ ...model, ...patch });
    [...listeners].forEach((listener) => listener());
  };
  const cancel = () => {
    epoch += 1;
    abort?.abort();
    abort = null;
  };
  const begin = () => {
    cancel();
    abort = new AbortController();
    return { epoch, signal: abort.signal };
  };
  const current = (request: ReturnType<typeof begin>) =>
    !stopped && epoch === request.epoch && !request.signal.aborted;
  const permitted = (operation: string) => !stopped && allowedActions.includes(operation);
  const locked = () =>
    model.phase === 'loading' || model.phase === 'executing' || model.recoveryRequired;
  const checkScope = (value: NativeKnowledgeScope) => {
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
  };
  const read = async (request: ReturnType<typeof begin>) => {
    const result = await queryClient!.query(
      scope,
      { operation: 'configuration' },
      { signal: request.signal, expectedScope: observed },
    );
    if (!current(request)) throw Error('request_cancelled');
    checkScope(result.scope);
    observed = Object.freeze({ ...result.scope });
    return structuredClone(result.result);
  };
  const contextFailure = (error: unknown) =>
    error instanceof Error &&
    [
      'knowledge_scope_mismatch',
      'knowledge_generation_mismatch',
      'project_knowledge_scope_conflict',
    ].includes(error.message);
  const fail = (error: unknown, writeStarted = false) => {
    const code = error instanceof Error ? error.message : '';
    if (contextFailure(error)) {
      observed = undefined;
      model = initial();
      emit({ phase: 'error', error: 'contextChanged' });
      return;
    }
    const status =
      typeof error === 'object' && error && 'status' in error ? error.status : undefined;
    const rejected =
      [
        'knowledge_revision_conflict',
        'knowledge_invalid_input',
        'knowledge_release_closed',
        'knowledge_embedding_provider_unavailable',
      ].includes(code) || [401, 403, 404, 409, 422].includes(Number(status));
    if (writeStarted && !rejected) {
      emit({
        phase: 'uncertain',
        selection: null,
        failedTask: null,
        outcome: null,
        recoveryRequired: true,
        error: null,
      });
      return;
    }
    emit({
      phase: model.recoveryRequired ? 'uncertain' : 'error',
      selection: null,
      outcome: null,
      failedTask:
        code === 'knowledge_revision_conflict' || status === 409 ? null : model.failedTask,
      error:
        code === 'knowledge_revision_conflict' || status === 409
          ? 'conflict'
          : code === 'knowledge_release_closed'
            ? 'unavailable'
            : code === 'knowledge_embedding_provider_unavailable'
              ? 'embeddingUnavailable'
              : model.recoveryRequired
                ? 'refreshFailed'
                : 'failed',
    });
  };
  const refresh = async () => {
    if (!permitted('configuration') || model.phase === 'executing' || model.phase === 'loading')
      return;
    const recovering = model.recoveryRequired;
    const request = begin();
    emit({ phase: 'loading', selection: null, error: null });
    try {
      const snapshot = await read(request);
      if (!current(request)) return;
      emit({
        phase: 'idle',
        snapshot,
        recoveryRequired: false,
        notice: recovering ? 'recoveredUnknown' : model.notice,
      });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const review = async (operation: SupportedOperation) => {
    if (
      !['index_one', 'promote_index', 'retry_index', 'select_embedding'].includes(operation) ||
      !permitted(operation) ||
      locked()
    )
      return;
    const failedTask = model.failedTask;
    const request = begin();
    emit({ phase: 'loading', selection: null, outcome: null, error: null, notice: null });
    try {
      const snapshot = await read(request);
      if (!current(request)) return;
      emit({ snapshot });
      const configuration = snapshot.configuration;
      let command: SupportedCommand;
      if (operation === 'select_embedding') {
        if (!snapshot.active_build_id) {
          emit({ phase: 'idle', error: 'activeRequired' });
          return;
        }
        command = {
          operation,
          build_id: snapshot.active_build_id,
          expected_config_revision: configuration?.revision ?? null,
        };
      } else {
        if (!configuration) {
          emit({ phase: 'idle', error: 'configurationRequired' });
          return;
        }
        const selected = {
          build_id: configuration.build_id,
          config_revision: configuration.revision,
        };
        if (operation === 'retry_index') {
          if (
            !failedTask ||
            failedTask.receipt.status !== 'failed' ||
            failedTask.buildId !== configuration.build_id ||
            failedTask.configRevision !== configuration.revision
          ) {
            emit({ phase: 'idle', failedTask: null, error: 'failedReceiptRequired' });
            return;
          }
          command = {
            operation,
            ...selected,
            input: failedTask.receipt.input,
            expected_attempt: failedTask.receipt.attempt,
          };
        } else if (operation === 'promote_index')
          command = { operation, ...selected, expected_active_build_id: snapshot.active_build_id };
        else command = { operation, ...selected };
      }
      emit({ phase: 'reviewing', selection: freezeCommand(command) });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const confirm = async () => {
    const command = model.selection;
    const previous = model.snapshot;
    if (
      !command ||
      !previous ||
      model.phase !== 'reviewing' ||
      !permitted(command.operation) ||
      model.recoveryRequired
    )
      return;
    const request = begin();
    let writeStarted = false;
    emit({ phase: 'executing', error: null });
    try {
      const snapshot = await read(request);
      if (!current(request)) return;
      emit({ snapshot });
      if (
        configurationKey(snapshot) !== configurationKey(previous) ||
        ((command.operation === 'promote_index' || command.operation === 'select_embedding') &&
          snapshot.active_build_id !== previous.active_build_id)
      ) {
        emit({ phase: 'idle', selection: null, failedTask: null, error: 'reviewChanged' });
        return;
      }
      writeStarted = true;
      const response = await commandClient!.execute(scope, command, {
        signal: request.signal,
        expectedScope: observed!,
      });
      if (!current(request)) return;
      checkScope(response.scope);
      const outcome = {
        operation: command.operation,
        result: structuredClone(response.result),
      } as Outcome;
      let failedTask = model.failedTask;
      if (outcome.operation === 'index_one')
        failedTask =
          outcome.result.receipt?.status === 'failed'
            ? {
                buildId: command.build_id,
                configRevision: snapshot.configuration!.revision,
                receipt: outcome.result.receipt,
              }
            : null;
      if (command.operation === 'retry_index' || command.operation === 'select_embedding')
        failedTask = null;
      const acknowledgedSnapshot =
        outcome.operation === 'select_embedding'
          ? { ...snapshot, configuration: outcome.result.configuration, index: null }
          : outcome.operation === 'promote_index'
            ? {
                ...snapshot,
                configuration: outcome.result.configuration,
                active_build_id: outcome.result.active_build_id,
              }
            : snapshot;
      emit({
        phase: 'accepted',
        snapshot: acknowledgedSnapshot,
        selection: null,
        outcome,
        failedTask,
        notice: null,
      });
      void Promise.resolve()
        .then(() => {
          if (current(request)) return onAccepted?.();
        })
        .catch(() => {});
    } catch (error) {
      if (current(request)) fail(error, writeStarted);
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
    review,
    confirm,
    cancelReview: () => {
      if (model.phase === 'reviewing') {
        cancel();
        emit({ phase: 'idle', selection: null, error: null });
      }
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
