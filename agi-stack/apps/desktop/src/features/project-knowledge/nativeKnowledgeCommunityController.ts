import type {
  NativeKnowledgeCommunityAuditSummary,
  NativeKnowledgeCommunityBuildPage,
  NativeKnowledgeCommunityBuildHistoryPage,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingResultMap,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';
import type { NativeMemoriesRouteBinding } from './NativeMemoriesRouteContext';
import type { NativeKnowledgeWorkspaceChoice } from './nativeKnowledgeProcessingInputs';
import { sameJson } from './nativeKnowledgeRelationships';
import { nativeKnowledgeUiFailure } from './nativeKnowledgeUiSession';

type Command = Extract<
  NativeKnowledgeProcessingCommand,
  {
    operation:
      | 'create_community_build'
      | 'select_community_build'
      | 'process_community_one'
      | 'retry_community'
      | 'activate_community_build';
  }
>;
type Active = NativeKnowledgeProcessingResultMap['community_active'];
export type NativeKnowledgeCommunityModel = Readonly<{
  phase: 'idle' | 'loading' | 'reviewing' | 'executing' | 'error' | 'unavailable';
  allowedActions: readonly string[];
  active: Active | null;
  history: NativeKnowledgeCommunityBuildHistoryPage | null;
  page: NativeKnowledgeCommunityBuildPage | null;
  viewedBuildId: string | null;
  audit: NativeKnowledgeCommunityAuditSummary | null;
  command: Command | null;
  workspaces: readonly NativeKnowledgeWorkspaceChoice[];
  recoveryRequired: boolean;
  recoverableCreate: boolean;
  recoveredUnknown: boolean;
  outcome: 'accepted' | 'noWork' | 'notActivated' | null;
  error: 'failed' | 'conflict' | 'contextChanged' | null;
}>;
export type NativeKnowledgeCommunityController = ReturnType<
  typeof createNativeKnowledgeCommunityController
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

/** Explicit community commands; reads never dispatch a provider or repeat an uncertain write. */
export function createNativeKnowledgeCommunityController(binding: NativeMemoriesRouteBinding) {
  const authority = immutable(binding.authority);
  const scope = authority.scope;
  const available = Boolean(
    binding.processingClient &&
    authority.available &&
    scope.authority === 'local' &&
    authority.userId &&
    authority.sessionId &&
    authority.generationDigest &&
    Number.isSafeInteger(authority.contextRevision) &&
    Number(authority.contextRevision) >= 0 &&
    ['community_active', 'community_build'].every((action) =>
      authority.allowedActions.includes(action),
    ),
  );
  const initial = (): NativeKnowledgeCommunityModel => ({
    phase: available ? 'idle' : 'unavailable',
    allowedActions: available ? authority.allowedActions : [],
    active: null,
    history: null,
    page: null,
    viewedBuildId: null,
    audit: null,
    command: null,
    workspaces: [],
    recoveryRequired: false,
    recoverableCreate: false,
    recoveredUnknown: false,
    outcome: null,
    error: null,
  });
  let model = immutable(initial());
  let stopped = false;
  let invalid = false;
  let unknownOutcome = false;
  let unknownCreate: Extract<Command, { operation: 'create_community_build' }> | null = null;
  let epoch = 0;
  let controller: AbortController | null = null;
  let observed: NativeKnowledgeScope | undefined;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeCommunityModel>) => {
    model = immutable({ ...model, ...patch });
    [...listeners].forEach((listener) => listener());
  };
  const cancelRequest = () => {
    epoch += 1;
    controller?.abort();
    controller = null;
  };
  const begin = () => {
    cancelRequest();
    controller = new AbortController();
    return { epoch, signal: controller.signal };
  };
  const current = (request: ReturnType<typeof begin>) =>
    !stopped && request.epoch === epoch && !request.signal.aborted;
  const busy = () => model.phase === 'loading' || model.phase === 'executing';
  const permitted = (operation: string) =>
    available && !stopped && !invalid && authority.allowedActions.includes(operation);
  const locked = () => !available || stopped || invalid || busy() || model.recoveryRequired;
  const check = (value: NativeKnowledgeScope) => {
    if (
      value.tenant_id !== scope.tenantId ||
      value.project_id !== scope.projectId ||
      value.context_revision !== authority.contextRevision ||
      value.digest !== authority.generationDigest ||
      (observed && !sameJson(observed, value))
    )
      throw Error('knowledge_scope_mismatch');
    observed = immutable(value);
  };
  const read = async <
    Q extends Extract<
      NativeKnowledgeProcessingQuery,
      { operation: 'community_active' | 'community_build' | 'community_audit' | 'community_builds' }
    >,
  >(
    query: Q,
    request: ReturnType<typeof begin>,
  ) => {
    if (!permitted(query.operation)) throw Object.assign(Error('forbidden'), { status: 403 });
    const response = await binding.processingClient!.query(scope, query, {
      expectedScope: observed,
      signal: request.signal,
    });
    if (!current(request)) throw Error('request_cancelled');
    check(response.scope);
    return immutable(response.result);
  };
  const readPage = async (buildId: string, offset: number, request: ReturnType<typeof begin>) => {
    const result = await read(
      { operation: 'community_build', build_id: buildId, offset, limit: 20 },
      request,
    );
    if (
      result.page &&
      (result.page.build.build_id !== buildId ||
        result.page.offset !== offset ||
        result.page.limit !== 20 ||
        result.page.build.tenant_id !== scope.tenantId ||
        result.page.build.project_id !== scope.projectId)
    )
      throw Error('knowledge_scope_mismatch');
    return result.page;
  };
  const fail = (error: unknown, writeStarted = false) => {
    const kind = nativeKnowledgeUiFailure(error);
    if (kind === 'contextChanged') {
      unknownCreate = null;
      invalid = true;
      observed = undefined;
      emit({
        ...initial(),
        phase: 'unavailable',
        allowedActions: [],
        error: kind,
      });
    } else {
      unknownOutcome ||= writeStarted && kind === 'uncertain';
      emit({
        phase: 'error',
        command: null,
        workspaces: [],
        audit: null,
        recoveryRequired: model.recoveryRequired || (writeStarted && kind === 'uncertain'),
        error: kind === 'uncertain' ? 'failed' : kind,
      });
    }
  };
  const refresh = async (buildId?: string, offset = 0) => {
    if (!available || stopped || invalid || busy() || !Number.isSafeInteger(offset) || offset < 0)
      return;
    const request = begin();
    const recovering = unknownOutcome;
    const previousBuild = buildId ?? model.viewedBuildId ?? model.page?.build.build_id;
    emit({
      phase: 'loading',
      viewedBuildId: previousBuild ?? null,
      page: previousBuild === model.page?.build.build_id ? model.page : null,
      command: null,
      audit: null,
      workspaces: [],
      error: null,
    });
    try {
      const active = await read({ operation: 'community_active' }, request);
      const id =
        previousBuild ?? active.selection.requested_build_id ?? active.selection.active_build_id;
      const page = id ? await readPage(id, offset, request) : null;
      if (!current(request)) return;
      if (!unknownCreate) unknownOutcome = false;
      emit({
        phase: 'idle',
        active,
        page,
        viewedBuildId: id ?? null,
        recoveryRequired: Boolean(unknownCreate),
        recoverableCreate: Boolean(unknownCreate),
        recoveredUnknown: !unknownCreate && (recovering || model.recoveredUnknown),
      });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const loadHistory = async (offset = 0) => {
    if (!permitted('community_builds') || busy() || !Number.isSafeInteger(offset) || offset < 0)
      return;
    const request = begin();
    emit({ phase: 'loading', command: null, error: null });
    try {
      const { page } = await read({ operation: 'community_builds', offset, limit: 20 }, request);
      if (
        page.offset !== offset ||
        page.limit !== 20 ||
        page.items.some(
          (item) => item.tenant_id !== scope.tenantId || item.project_id !== scope.projectId,
        )
      )
        throw Error('knowledge_scope_mismatch');
      if (current(request)) emit({ phase: 'idle', history: page });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const review = async (
    operation: Command['operation'],
    options: Readonly<{
      minSize?: number;
      workspaceId?: string;
      candidateId?: string;
    }> = {},
  ) => {
    if (locked() || !binding.processingCommandClient || !permitted(operation)) return;
    if (operation !== 'create_community_build' && !model.page) return;
    const selected = model.page;
    const request = begin();
    emit({
      phase: 'loading',
      command: null,
      error: null,
      audit: null,
      recoveredUnknown: false,
      outcome: null,
    });
    try {
      const active = await read({ operation: 'community_active' }, request);
      const page = selected
        ? await readPage(selected.build.build_id, selected.offset, request)
        : null;
      let command: Command;
      if (operation === 'create_community_build') {
        const minSize = options.minSize ?? 2;
        if (!Number.isSafeInteger(minSize) || minSize < 2 || minSize > 4096)
          throw Object.assign(Error('invalid_size'), { status: 400 });
        command = {
          operation,
          idempotency_key: crypto.randomUUID(),
          min_community_size: minSize,
        };
      } else {
        if (!page || !page.current_graph)
          throw Object.assign(Error('stale_build'), { status: 409 });
        const build_id = page.build.build_id;
        if (operation === 'select_community_build' || operation === 'activate_community_build') {
          if (
            operation === 'activate_community_build' &&
            (active.selection.requested_build_id !== build_id ||
              !['completed', 'completed_empty'].includes(page.status.state))
          )
            throw Object.assign(Error('not_ready'), { status: 409 });
          command = {
            operation,
            build_id,
            expected_selection_revision: active.selection.revision,
          };
        } else if (operation === 'retry_community') {
          const candidate = page.items.find((item) => item.candidate_id === options.candidateId);
          if (
            !candidate ||
            candidate.job.state !== 'failed' ||
            candidate.job.attempt !==
              selected?.items.find((item) => item.candidate_id === options.candidateId)?.job.attempt
          )
            throw Object.assign(Error('not_failed'), { status: 409 });
          command = {
            operation,
            build_id,
            candidate_id: candidate.candidate_id,
            expected_attempt: candidate.job.attempt,
          };
        } else {
          if (!binding.processingInputsClient)
            throw Object.assign(Error('inputs_unavailable'), { status: 403 });
          const inputs = await binding.processingInputsClient.load(scope, {
            operation: 'process_community_one',
            expectedScope: observed!,
            signal: request.signal,
          });
          if (!current(request)) return;
          check(inputs.scope);
          const workspaces =
            inputs.workspaces.availability === 'available' ? inputs.workspaces.items : [];
          emit({ workspaces });
          if (!workspaces.some((workspace) => workspace.id === options.workspaceId)) {
            emit({ phase: 'idle', active, page, command: null });
            return;
          }
          command = { operation, build_id, workspace_id: options.workspaceId! };
        }
      }
      if (current(request)) emit({ phase: 'reviewing', active, page, command });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const confirm = async () => {
    if (
      locked() ||
      model.phase !== 'reviewing' ||
      !model.command ||
      !observed ||
      !binding.processingCommandClient
    )
      return;
    const command = model.command;
    if (!permitted(command.operation)) return;
    const request = begin();
    const reviewedPage = model.page;
    let writeStarted = false;
    emit({ phase: 'executing', error: null });
    try {
      const active = await read({ operation: 'community_active' }, request);
      const page =
        'build_id' in command
          ? await readPage(command.build_id, reviewedPage?.offset ?? 0, request)
          : null;
      if ('build_id' in command && (!page || !page.current_graph))
        throw Object.assign(Error('stale_build'), { status: 409 });
      if (
        'expected_selection_revision' in command &&
        active.selection.revision !== command.expected_selection_revision
      )
        throw Object.assign(Error('selection_changed'), { status: 409 });
      if (
        command.operation === 'activate_community_build' &&
        (active.selection.requested_build_id !== command.build_id ||
          !['completed', 'completed_empty'].includes(page!.status.state))
      )
        throw Object.assign(Error('not_ready'), { status: 409 });
      if (command.operation === 'retry_community') {
        const candidate = page!.items.find((item) => item.candidate_id === command.candidate_id);
        if (candidate?.job.state !== 'failed' || candidate.job.attempt !== command.expected_attempt)
          throw Object.assign(Error('attempt_changed'), { status: 409 });
      }
      if (command.operation === 'process_community_one') {
        const inputs = await binding.processingInputsClient!.load(scope, {
          operation: command.operation,
          expectedScope: observed!,
          signal: request.signal,
        });
        if (!current(request)) return;
        check(inputs.scope);
        if (
          inputs.workspaces.availability !== 'available' ||
          !inputs.workspaces.items.some((item) => item.id === command.workspace_id)
        )
          throw Object.assign(Error('workspace_changed'), { status: 409 });
      }
      if (!current(request)) return;
      writeStarted = true;
      const response = await binding.processingCommandClient.execute(scope, command, {
        expectedScope: observed!,
        signal: request.signal,
      });
      if (!current(request)) return;
      check(response.scope);
      const buildId =
        command.operation === 'create_community_build' && 'build' in response.result
          ? response.result.build.build_id
          : page?.build.build_id;
      // A successful command and failed following read still require refresh before another write.
      emit({
        phase: 'idle',
        command: null,
        recoveryRequired: true,
        outcome:
          command.operation === 'activate_community_build' &&
          'activated' in response.result &&
          !response.result.activated
            ? 'notActivated'
            : command.operation === 'process_community_one' &&
                'receipt' in response.result &&
                !response.result.receipt
              ? 'noWork'
              : 'accepted',
      });
      await refresh(buildId, page?.offset ?? 0);
    } catch (error) {
      if (current(request)) {
        if (
          writeStarted &&
          command.operation === 'create_community_build' &&
          nativeKnowledgeUiFailure(error) === 'uncertain'
        ) {
          unknownCreate = immutable(command);
          emit({ recoverableCreate: true });
        }
        fail(error, writeStarted);
      }
    }
  };
  const recoverCreate = async () => {
    if (
      !unknownCreate ||
      !model.recoveryRequired ||
      busy() ||
      !permitted('create_community_build') ||
      !binding.processingCommandClient
    )
      return;
    const command = unknownCreate;
    const request = begin();
    emit({ phase: 'executing', error: null });
    try {
      await read({ operation: 'community_active' }, request);
      if (!current(request)) return;
      const response = await binding.processingCommandClient.execute(scope, command, {
        expectedScope: observed!,
        signal: request.signal,
      });
      if (!current(request)) return;
      check(response.scope);
      unknownCreate = null;
      unknownOutcome = false;
      emit({
        phase: 'idle',
        recoverableCreate: false,
        recoveryRequired: true,
        outcome: 'accepted',
      });
      await refresh(response.result.build.build_id);
    } catch (error) {
      if (current(request)) fail(error, true);
    }
  };
  const loadAudit = async (candidateId: string, attempt: number) => {
    if (locked() || !model.page || !permitted('community_audit')) return;
    const candidate = model.page.items.find((item) => item.candidate_id === candidateId);
    if (!candidate || candidate.job.attempt !== attempt || attempt < 1) return;
    const buildId = model.page.build.build_id;
    const request = begin();
    emit({ phase: 'loading', audit: null, command: null, error: null });
    try {
      const { audit } = await read(
        {
          operation: 'community_audit',
          build_id: buildId,
          candidate_id: candidateId,
          attempt,
        },
        request,
      );
      if (
        audit &&
        (audit.build_id !== buildId ||
          audit.candidate_id !== candidateId ||
          audit.attempt !== attempt)
      )
        throw Error('knowledge_scope_mismatch');
      if (current(request)) emit({ phase: 'idle', audit });
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
    refresh,
    recoverCreate,
    loadHistory,
    review,
    confirm,
    loadAudit,
    cancel: () => {
      if (!locked()) emit({ phase: 'idle', command: null, workspaces: [] });
    },
    stop: () => {
      const recoveryRequired = model.recoveryRequired || model.phase === 'executing';
      unknownOutcome ||= model.phase === 'executing';
      if (model.phase === 'executing' && model.command?.operation === 'create_community_build')
        unknownCreate = immutable(model.command);
      stopped = true;
      cancelRequest();
      observed = undefined;
      emit({
        ...initial(),
        ...(invalid
          ? { phase: 'unavailable' as const, allowedActions: [], error: 'contextChanged' as const }
          : {}),
        recoveryRequired,
        recoverableCreate: Boolean(unknownCreate),
      });
    },
    activate: () => {
      stopped = false;
    },
  });
}
