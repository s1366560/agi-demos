import type {
  CloudMemoryClient,
  CloudMemoryCommand,
  CloudMemoryOptions,
} from './cloudMemoryClient';
import type {
  ProjectMemoriesClient,
  ProjectMemoriesSnapshot,
  ProjectMemory,
} from './projectMemoriesClient';
import {
  checkCloudMemoryList,
  cloudMemoryUiCapabilities,
  cloudMemoryRowAction,
  validCloudMemoryUiAuthority,
  type CloudMemoryUiAuthority,
} from './cloudMemoryUiAuthority';

type Draft = Readonly<{ title: string; content: string }>;
type Intent = 'view' | 'edit' | 'delete' | 'create';
type WriteCommand = Exclude<CloudMemoryCommand, { operation: 'get' }>;
export type CloudMemoriesModel = Readonly<{
  phase:
    | 'idle'
    | 'loading'
    | 'viewing'
    | 'creating'
    | 'editing'
    | 'deleting'
    | 'saving'
    | 'uncertain'
    | 'conflict'
    | 'reviewing'
    | 'error'
    | 'unavailable';
  listState: 'idle' | 'loading' | 'ready' | 'error';
  list: ProjectMemoriesSnapshot | null;
  record: ProjectMemory | null;
  latest: ProjectMemory | null;
  draft: Draft | null;
  intent: Intent | null;
  error:
    | 'failed'
    | 'contextChanged'
    | 'conflict'
    | 'notFound'
    | 'permissionChanged'
    | 'invalidDraft'
    | null;
  notice: 'accepted' | 'reviewedLatest' | null;
  canCreate: boolean;
  readable: boolean;
}>;
export type CloudMemoriesController = ReturnType<typeof createCloudMemoriesController>;
function immutableCommand(command: WriteCommand): WriteCommand {
  const clone = structuredClone(command);
  if ('memory' in clone) Object.freeze(clone.memory);
  if ('patch' in clone) Object.freeze(clone.patch);
  return Object.freeze(clone);
}
export function createCloudMemoriesController({
  authority: input,
  listClient,
  client,
}: Readonly<{
  authority: CloudMemoryUiAuthority;
  listClient: ProjectMemoriesClient;
  client?: CloudMemoryClient;
}>) {
  const authority = Object.freeze({
    ...input,
    scope: Object.freeze({ ...input.scope }),
    allowedActions: Object.freeze([...input.allowedActions]),
  });
  const valid = validCloudMemoryUiAuthority(authority);
  const readable = valid && authority.allowedActions.includes('list');
  let stopped = false;
  let epoch = 0;
  let abort: AbortController | null = null;
  let pending: WriteCommand | null = null;
  let permissionsCurrent = false;
  const listeners = new Set<() => void>();
  const initial = (): CloudMemoriesModel =>
    Object.freeze({
      phase: readable ? 'idle' : 'unavailable',
      listState: 'idle',
      list: null,
      record: null,
      latest: null,
      draft: null,
      intent: null,
      error: null,
      notice: null,
      canCreate: false,
      readable,
    });
  let model = initial();
  const emit = (patch: Partial<CloudMemoriesModel>) => {
    model = Object.freeze({ ...model, ...patch });
    model = Object.freeze({
      ...model,
      canCreate: Boolean(
        client &&
        permissionsCurrent &&
        model.listState === 'ready' &&
        cloudMemoryUiCapabilities(authority, model.list)?.allowedActions.includes('create'),
      ),
    });
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
    !stopped && request.epoch === epoch && !request.signal.aborted;
  const locked = () => ['saving', 'uncertain'].includes(model.phase);
  const options = (signal: AbortSignal): CloudMemoryOptions => ({
    signal,
    expectedActorId: authority.actorId!,
    expectedContextRevision: authority.contextRevision!,
  });
  const rowAllowed = (record: ProjectMemory, action: 'update' | 'delete') =>
    Boolean(
      client &&
      permissionsCurrent &&
      model.listState === 'ready' &&
      cloudMemoryRowAction(cloudMemoryUiCapabilities(authority, model.list), record, action),
    );
  const canView = () =>
    !stopped && valid && Boolean(client) && authority.allowedActions.includes('view');
  const checkRecord = (record: ProjectMemory, id?: string) => {
    if (record.projectId !== authority.scope.projectId || (id && record.id !== id))
      throw Error('cloud_memory_ui_scope_conflict');
  };
  const scopeFailure = (error: unknown) =>
    error instanceof Error &&
    [
      'cloud_memory_scope_conflict',
      'desktop_project_memories_operation_released',
      'cloud_memory_ui_scope_conflict',
      'cloud_memory_capability_scope_conflict',
      'project_knowledge_scope_conflict',
      'project_memory_scope_conflict',
      'project_knowledge_configured_scope_mismatch',
      'project_knowledge_authority_mode_mismatch',
      'project_knowledge_trusted_session_required',
    ].includes(error.message);
  const fail = (error: unknown, write = false) => {
    const status =
      typeof error === 'object' && error && 'status' in error ? Number(error.status) : 0;
    if (scopeFailure(error) || status === 401) {
      pending = null;
      permissionsCurrent = false;
      model = initial();
      emit({ phase: 'error', listState: 'error', error: 'contextChanged' });
      return;
    }
    if (write && ![401, 403, 404, 409, 422].includes(status)) {
      emit({ phase: 'uncertain', error: null });
      return;
    }
    if (write) pending = null;
    if (status === 403) permissionsCurrent = false;
    emit({
      phase: status === 409 || status === 403 ? 'conflict' : 'error',
      error:
        status === 409
          ? 'conflict'
          : status === 404
            ? 'notFound'
            : status === 403
              ? 'permissionChanged'
              : 'failed',
    });
  };
  const readList = async (page: number, request: ReturnType<typeof begin>) => {
    const list = await listClient.load(authority.scope, {
      page,
      pageSize: 50,
      signal: request.signal,
    });
    if (!current(request)) throw Error('request_cancelled');
    checkCloudMemoryList(authority, list);
    const snapshot = structuredClone(list);
    const freeze = (value: unknown): void => {
      if (value && typeof value === 'object') {
        Object.values(value).forEach(freeze);
        Object.freeze(value);
      }
    };
    freeze(snapshot);
    permissionsCurrent = true;
    return snapshot;
  };
  const loadPage = async (page = 1) => {
    if (stopped || !readable || locked() || !Number.isSafeInteger(page) || page < 1) return;
    const request = begin();
    emit({ listState: 'loading', error: null });
    try {
      const list = await readList(page, request);
      if (current(request)) emit({ list, listState: 'ready' });
    } catch (error) {
      if (current(request)) {
        emit({ listState: 'error' });
        fail(error);
      }
    }
  };
  const readRecord = async (id: string, request: ReturnType<typeof begin>) => {
    const response = await client!.execute(
      authority.scope,
      { operation: 'get', id },
      options(request.signal),
    );
    if (!current(request)) throw Error('request_cancelled');
    checkRecord(response.result, id);
    return Object.freeze({ ...response.result });
  };
  const open = async (id: string, intent: 'view' | 'edit' | 'delete') => {
    if (stopped || !canView() || locked()) return;
    const row = model.list?.memories.find((memory) => memory.id === id);
    if (!row || (intent !== 'view' && !rowAllowed(row, intent === 'edit' ? 'update' : 'delete')))
      return;
    const request = begin();
    pending = null;
    emit({
      phase: 'loading',
      intent,
      record: null,
      latest: null,
      draft: null,
      error: null,
      notice: null,
    });
    try {
      const record = await readRecord(id, request);
      if (!current(request)) return;
      const allowed =
        intent === 'view' || rowAllowed(record, intent === 'edit' ? 'update' : 'delete');
      emit({
        record,
        intent: allowed ? intent : 'view',
        draft: intent === 'edit' ? { title: record.title, content: record.content } : null,
        phase:
          !allowed || intent === 'view' ? 'viewing' : intent === 'edit' ? 'editing' : 'deleting',
        error: allowed ? null : 'permissionChanged',
      });
    } catch (error) {
      if (current(request)) fail(error);
    }
  };
  const write = async () => {
    const command = pending;
    if (!command || stopped || !client) return;
    const request = begin();
    emit({ phase: 'saving', error: null });
    try {
      const response = await client.execute(authority.scope, command, options(request.signal));
      if (!current(request)) return;
      if (command.operation === 'delete') {
        if (
          !('memoryId' in response.result) ||
          response.result.memoryId !== command.id ||
          response.result.deleted !== true
        )
          throw Error('cloud_memory_response_invalid');
      } else {
        if (!('projectId' in response.result)) throw Error('cloud_memory_response_invalid');
        checkRecord(response.result, command.operation === 'update' ? command.id : undefined);
      }
      pending = null;
      emit({
        phase: command.operation === 'delete' ? 'idle' : 'viewing',
        record: command.operation === 'delete' ? null : (response.result as ProjectMemory),
        intent: command.operation === 'delete' ? null : 'view',
        draft: null,
        latest: null,
        notice: 'accepted',
      });
      const list = await readList(model.list?.page ?? 1, request);
      if (current(request)) emit({ list, listState: 'ready' });
    } catch (error) {
      if (current(request)) {
        // A failed list refresh cannot invalidate an already acknowledged mutation.
        if (pending) fail(error, true);
        else {
          emit({ listState: 'error' });
          if (scopeFailure(error)) fail(error);
        }
      }
    }
  };
  const save = async () => {
    if (
      stopped ||
      locked() ||
      !client ||
      !model.draft ||
      !['creating', 'editing'].includes(model.phase)
    )
      return;
    if (!model.draft.title.trim() || !model.draft.content.trim()) {
      emit({ error: 'invalidDraft' });
      return;
    }
    if (model.phase === 'creating') {
      if (!model.canCreate) return;
      pending = immutableCommand({
        operation: 'create',
        idempotencyKey: crypto.randomUUID(),
        memory: { title: model.draft.title, content: model.draft.content, contentType: 'text' },
      });
    } else {
      if (!model.record || !rowAllowed(model.record, 'update')) {
        emit({ error: 'permissionChanged' });
        return;
      }
      pending = immutableCommand({
        operation: 'update',
        id: model.record.id,
        expectedRevision: model.record.version,
        idempotencyKey: crypto.randomUUID(),
        patch: { title: model.draft.title, content: model.draft.content },
      });
    }
    await write();
  };
  const reloadConflict = async () => {
    if (stopped || locked() || !client || model.phase !== 'conflict') return;
    const request = begin();
    emit({ phase: 'loading', error: null });
    try {
      const latest = model.record ? await readRecord(model.record.id, request) : null;
      const list = await readList(model.list?.page ?? 1, request);
      if (current(request)) emit({ phase: 'reviewing', latest, list, listState: 'ready' });
    } catch (error) {
      if (current(request)) {
        fail(error);
        if (!scopeFailure(error)) emit({ phase: 'conflict' });
      }
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
    loadPage,
    open,
    save,
    reloadConflict,
    canView,
    canUpdate: (record: ProjectMemory) => !stopped && canView() && rowAllowed(record, 'update'),
    canDelete: (record: ProjectMemory) => !stopped && canView() && rowAllowed(record, 'delete'),
    create: () => {
      if (stopped || locked() || !model.canCreate) return;
      cancel();
      pending = null;
      emit({
        phase: 'creating',
        intent: 'create',
        record: null,
        latest: null,
        draft: { title: '', content: '' },
        error: null,
        notice: null,
      });
    },
    setDraft: (draft: Draft) => {
      if (stopped || !['creating', 'editing'].includes(model.phase)) return;
      emit({ draft: { title: draft.title, content: draft.content }, error: null });
    },
    confirmDelete: async () => {
      if (
        stopped ||
        locked() ||
        model.phase !== 'deleting' ||
        !model.record ||
        !rowAllowed(model.record, 'delete')
      )
        return;
      pending = immutableCommand({
        operation: 'delete',
        id: model.record.id,
        expectedRevision: model.record.version,
        idempotencyKey: crypto.randomUUID(),
      });
      await write();
    },
    retryWrite: async () => {
      if (model.phase === 'uncertain' && pending && !stopped) await write();
    },
    adoptLatest: () => {
      if (stopped || model.phase !== 'reviewing') return;
      if (model.intent === 'create' && model.canCreate) {
        emit({ phase: 'creating', latest: null, notice: 'reviewedLatest' });
        return;
      }
      if (
        !model.latest ||
        (model.intent !== 'edit' && model.intent !== 'delete') ||
        !rowAllowed(model.latest, model.intent === 'edit' ? 'update' : 'delete')
      ) {
        emit({ error: 'permissionChanged' });
        return;
      }
      emit({
        record: model.latest,
        latest: null,
        phase: model.intent === 'edit' ? 'editing' : 'deleting',
        notice: 'reviewedLatest',
        error: null,
      });
    },
    close: () => {
      if (stopped || locked()) return;
      cancel();
      pending = null;
      emit({
        phase: 'idle',
        intent: null,
        record: null,
        latest: null,
        draft: null,
        error: null,
        notice: null,
      });
    },
    goToPage: async (page: number) => {
      const list = model.list;
      if (!list || locked() || !Number.isSafeInteger(page) || page < 1 || page === list.page)
        return;
      const pages =
        list.total === null
          ? list.page + (list.hasMore ? 1 : 0)
          : Math.max(1, Math.ceil(list.total / list.pageSize));
      if (page > pages && page >= list.page) return;
      await loadPage(Math.min(page, pages));
    },
    stop: () => {
      stopped = true;
      cancel();
      pending = null;
      permissionsCurrent = false;
      model = initial();
      emit({});
    },
    activate: () => {
      stopped = false;
    },
  });
}
