import type { DiagnosticIndexSelection } from './nativeKnowledgeDiagnosticsController';
import type {
  NativeKnowledgeProcessingInputsClient,
  NativeKnowledgeProcessingInputs,
  NativeKnowledgeEmbeddingChoice,
  NativeKnowledgeWorkspaceChoice,
} from './nativeKnowledgeProcessingInputs';
import {
  validateNativeKnowledgeProcessingInputs,
  sameNativeKnowledgeEmbeddingChoice,
} from './nativeKnowledgeProcessingInputValidation';
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

type SupportedOperation = Exclude<NativeKnowledgeProcessingCommand['operation'], 'retry_processing'>;
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
  inputsAvailable: boolean;
  inputs: NativeKnowledgeProcessingInputs | null;
  inputOperation: 'configure_embedding' | 'process_one' | null;
  embeddingChoice: NativeKnowledgeEmbeddingChoice | null;
  workspaceChoice: NativeKnowledgeWorkspaceChoice | null;
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
    | 'inputRequired'
    | 'inputsChanged'
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
  inputsClient,
  authority: input,
  onAccepted,
}: Readonly<{
  inputsClient?: NativeKnowledgeProcessingInputsClient;
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
      inputsAvailable: Boolean(inputsClient),
      inputs: null,
      inputOperation: null,
      embeddingChoice: null,
      workspaceChoice: null,
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
    if (
      contextFailure(error) ||
      (typeof error === 'object' &&
        error &&
        'status' in error &&
        [401, 403].includes(Number(error.status)))
    ) {
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
        inputsAvailable: Boolean(inputsClient),
        inputs: null,
        inputOperation: null,
        embeddingChoice: null,
        workspaceChoice: null,
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
    emit({
      phase: 'loading',
      selection: null,
      inputs: null,
      inputOperation: null,
      embeddingChoice: null,
      workspaceChoice: null,
      error: null,
    });
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
  const readInputs = async (
    operation: 'configure_embedding' | 'process_one',
    request: ReturnType<typeof begin>,
  ) => {
    if (!inputsClient || !observed) throw Error('knowledge_inputs_unavailable');
    const result = validateNativeKnowledgeProcessingInputs(
      await inputsClient.load(scope, {
        operation,
        expectedScope: observed,
        signal: request.signal,
      }),
    );
    if (!current(request)) throw Error('request_cancelled');
    checkScope(result.scope);
    // A directory must bind to every field of the configuration observation.
    if (
      result.scope.profile_id !== observed.profile_id ||
      result.scope.generation !== observed.generation ||
      result.scope.digest !== observed.digest
    )
      throw Error('knowledge_scope_mismatch');
    return result;
  };
  const prepareInputs = async (operation: 'configure_embedding' | 'process_one') => {
    if (
      !['configure_embedding', 'process_one'].includes(operation) ||
      !permitted(operation) ||
      locked() ||
      !inputsClient
    )
      return;
    const request = begin();
    emit({
      phase: 'loading',
      inputs: null,
      inputOperation: null,
      embeddingChoice: null,
      workspaceChoice: null,
      selection: null,
      outcome: null,
      error: null,
    });
    try {
      const snapshot = await read(request);
      const inputs = await readInputs(operation, request);
      if (current(request)) emit({ phase: 'idle', snapshot, inputs, inputOperation: operation });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const inputMatches = (command: SupportedCommand, inputs: NativeKnowledgeProcessingInputs) =>
    command.operation === 'configure_embedding'
      ? inputs.embeddingModels.availability === 'available' &&
        inputs.embeddingModels.items.some(
          (item) =>
            item.providerId === command.provider_id &&
            item.providerRevision === command.provider_revision &&
            item.modelId === command.model_id,
        )
      : command.operation === 'process_one'
        ? inputs.workspaces.availability === 'available' &&
          inputs.workspaces.items.some((item) => item.id === command.workspace_id)
        : true;
  const review = async (operation: SupportedOperation) => {
    if (
      !OPERATIONS.includes(operation) ||
      ((operation === 'configure_embedding' || operation === 'process_one') && !inputsClient) ||
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
      if (operation === 'configure_embedding' || operation === 'process_one') {
        const selected =
          operation === 'configure_embedding' ? model.embeddingChoice : model.workspaceChoice;
        if (!selected || model.inputOperation !== operation) {
          emit({ phase: 'idle', error: 'inputRequired' });
          return;
        }
        const inputs = await readInputs(operation, request);
        if (!current(request)) return;
        emit({ inputs });
        if (operation === 'configure_embedding') {
          const choice = model.embeddingChoice!;
          if (
            !inputs.embeddingModels.items.some((item) =>
              sameNativeKnowledgeEmbeddingChoice(item, choice),
            )
          ) {
            emit({ phase: 'idle', embeddingChoice: null, error: 'inputsChanged' });
            return;
          }
          command = {
            operation,
            build_id: crypto.randomUUID(),
            provider_id: choice.providerId,
            provider_revision: choice.providerRevision,
            model_id: choice.modelId,
            expected_config_revision: configuration?.revision ?? null,
          };
        } else command = { operation, workspace_id: model.workspaceChoice!.id };
        if (!inputMatches(command, inputs)) {
          emit({
            phase: 'idle',
            workspaceChoice: null,
            embeddingChoice: null,
            error: 'inputsChanged',
          });
          return;
        }
      } else if (operation === 'select_embedding') {
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
  const selectDiagnosticFailure = async (selection: DiagnosticIndexSelection) => {
    if (locked() || !permitted('retry_index')) return;
    const selected = structuredClone(selection);
    const request = begin();
    emit({ phase: 'loading', failedTask: null, selection: null, error: null });
    try {
      checkScope(selected.scope);
      observed = Object.freeze({ ...selected.scope });
      const snapshot = await read(request);
      if (!current(request)) return;
      if (
        !snapshot.configuration ||
        configurationKey(snapshot) !==
          configurationKey({
            ...snapshot,
            configuration: selected.configuration,
          }) ||
        selected.failure.input.source.tenant_id !== scope.tenantId ||
        selected.failure.input.source.project_id !== scope.projectId
      ) {
        emit({ phase: 'idle', snapshot, error: 'reviewChanged' });
        return;
      }
      emit({
        phase: 'idle',
        snapshot,
        failedTask: {
          buildId: snapshot.configuration.build_id,
          configRevision: snapshot.configuration.revision,
          receipt: { ...selected.failure, status: 'failed' },
        },
      });
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
      if (command.operation === 'configure_embedding' || command.operation === 'process_one') {
        const inputs = await readInputs(command.operation, request);
        if (!current(request)) return;
        emit({ inputs });
        if (!inputMatches(command, inputs)) {
          emit({
            phase: 'idle',
            selection: null,
            embeddingChoice: null,
            workspaceChoice: null,
            error: 'inputsChanged',
          });
          return;
        }
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
                buildId: snapshot.configuration!.build_id,
                configRevision: snapshot.configuration!.revision,
                receipt: outcome.result.receipt,
              }
            : null;
      if (
        command.operation === 'retry_index' ||
        command.operation === 'select_embedding' ||
        command.operation === 'configure_embedding'
      )
        failedTask = null;
      const acknowledgedSnapshot =
        outcome.operation === 'select_embedding' || outcome.operation === 'configure_embedding'
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
        inputsAvailable: Boolean(inputsClient),
        inputs: null,
        inputOperation: null,
        embeddingChoice: null,
        workspaceChoice: null,
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
    selectDiagnosticFailure,
    invalidateSources: () => {
      if (stopped || model.phase === 'executing' || model.recoveryRequired) return;
      cancel();
      model = initial();
      emit({});
      void refresh();
    },
    prepareInputs,
    chooseEmbedding: (providerId: string, modelId: string) => {
      if (
        locked() ||
        model.inputOperation !== 'configure_embedding' ||
        !permitted('configure_embedding')
      )
        return;
      const choice =
        model.inputs?.embeddingModels.items.find(
          (item) => item.providerId === providerId && item.modelId === modelId,
        ) ?? null;
      emit({ phase: 'idle', selection: null, embeddingChoice: choice, error: null });
    },
    chooseWorkspace: (id: string) => {
      if (locked() || model.inputOperation !== 'process_one' || !permitted('process_one')) return;
      const choice = model.inputs?.workspaces.items.find((item) => item.id === id) ?? null;
      emit({ phase: 'idle', selection: null, workspaceChoice: choice, error: null });
    },
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
