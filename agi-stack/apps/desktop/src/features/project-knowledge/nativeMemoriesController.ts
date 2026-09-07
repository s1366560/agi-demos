import type {
  NativeKnowledgeClient,
  NativeKnowledgeCommand,
  NativeKnowledgeMutationMemory,
  NativeKnowledgeScope,
  NativeKnowledgeStoredMemory,
} from './nativeKnowledgeContracts';
import { prepareNativeKnowledgeCommand } from './nativeKnowledgeValidation';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';

export type NativeMemoriesAuthority = Readonly<{
  scope: ProjectKnowledgeScope;
  userId: string | null;
  sessionId: string | null;
  contextRevision: number | null;
  generationDigest: string | null;
  available: boolean;
  allowedActions: readonly string[];
}>;
export type NativeMemoryDraft = Readonly<{ title: string; content: string }>;
export type NativeMemoryIntent = 'view' | 'edit' | 'delete';
export type NativeMemoriesModel = Readonly<{
  phase:
    | 'idle'
    | 'loading'
    | 'viewing'
    | 'creating'
    | 'editing'
    | 'confirming_delete'
    | 'saving'
    | 'uncertain'
    | 'conflict'
    | 'error'
    | 'unavailable';
  allowedActions: readonly string[];
  record: NativeKnowledgeStoredMemory | null;
  draft: NativeMemoryDraft | null;
  notice: 'accepted' | null;
  error: 'failed' | 'conflict' | 'contextChanged' | 'forbidden' | 'notFound' | 'uncertain' | null;
}>;
type Mutation = Extract<NativeKnowledgeCommand, { operation: 'create' | 'update' | 'delete' }>;
type PendingWrite = Readonly<{ command: Mutation; scope: NativeKnowledgeScope }>;
export type NativeMemoriesController = ReturnType<typeof createNativeMemoriesController>;

export function createNativeMemoriesController({
  client,
  authority: input,
  newId = () => crypto.randomUUID(),
  now = Date.now,
  onAccepted,
}: Readonly<{
  client: NativeKnowledgeClient;
  authority: NativeMemoriesAuthority;
  newId?: () => string;
  now?: () => number;
  onAccepted?: () => void;
}>) {
  const authority = Object.freeze({ ...input, scope: Object.freeze({ ...input.scope }) });
  const allowed =
    authority.available &&
    authority.scope.authority === 'local' &&
    authority.userId &&
    authority.sessionId &&
    authority.generationDigest &&
    Number.isSafeInteger(authority.contextRevision) &&
    Number(authority.contextRevision) >= 0
      ? Object.freeze([...input.allowedActions])
      : Object.freeze([]);
  let model: NativeMemoriesModel = Object.freeze({
    phase: allowed.length > 0 ? 'idle' : 'unavailable',
    allowedActions: allowed,
    record: null,
    draft: null,
    error: null,
    notice: null,
  });
  let baseline: NativeKnowledgeMutationMemory | null = null;
  let observed: NativeKnowledgeScope | null = null;
  let pending: PendingWrite | null = null;
  let active: AbortController | null = null;
  let epoch = 0;
  let stopped = false;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeMemoriesModel>) => {
    model = Object.freeze({ ...model, ...patch });
    for (const listener of [...listeners]) listener();
  };
  const permitted = (action: string) => !stopped && allowed.includes(action);
  const locked = () => model.phase === 'saving' || model.phase === 'uncertain';
  const cancel = () => {
    epoch += 1;
    active?.abort();
    active = null;
  };
  const clear = () => {
    baseline = null;
    observed = null;
    pending = null;
  };
  const begin = () => {
    cancel();
    active = new AbortController();
    return { epoch, signal: active.signal };
  };
  const current = (request: ReturnType<typeof begin>) =>
    !stopped && request.epoch === epoch && !request.signal.aborted;
  const finish = (request: ReturnType<typeof begin>) => {
    if (current(request)) active = null;
  };
  const observe = async (signal: AbortSignal) => {
    const response = await client.execute(
      authority.scope,
      { operation: 'sync_status' },
      { signal },
    );
    if (
      response.scope.context_revision !== authority.contextRevision ||
      response.scope.tenant_id !== authority.scope.tenantId ||
      response.scope.project_id !== authority.scope.projectId
    ) {
      throw Object.assign(new Error('project_knowledge_scope_conflict'), { status: 409 });
    }
    return response.scope;
  };
  const fail = (error: unknown, writing: boolean) => {
    const status =
      error !== null && typeof error === 'object' && 'status' in error ? error.status : 0;
    const message = error instanceof Error ? error.message : '';
    const contextChanged =
      message === 'project_knowledge_scope_conflict' ||
      message === 'knowledge_generation_mismatch' ||
      message === 'knowledge_scope_mismatch';
    if (contextChanged) {
      clear();
      emit({ phase: 'conflict', record: null, draft: null, error: 'contextChanged' });
    } else if (status === 409) {
      pending = null;
      emit({ phase: 'conflict', error: 'conflict' });
    } else if (writing && ![401, 403, 404, 422].includes(Number(status))) {
      emit({ phase: 'uncertain', error: 'uncertain' });
    } else {
      pending = null;
      emit({
        phase: 'error',
        error:
          status === 401 || status === 403 ? 'forbidden' : status === 404 ? 'notFound' : 'failed',
      });
    }
  };
  const create = async () => {
    if (!permitted('create') || locked()) return;
    const request = begin();
    clear();
    emit({ phase: 'loading', record: null, draft: null, error: null, notice: null });
    try {
      const scope = await observe(request.signal);
      if (!current(request)) return;
      observed = scope;
      baseline = Object.freeze({
        id: newId(),
        project_id: authority.scope.projectId,
        author_id: authority.userId!,
        title: '',
        content: '',
        content_type: 'text',
        version: 1,
        status: 'ENABLED',
        tags: Object.freeze([]),
        entities: Object.freeze([]),
        embedding: null,
        created_at_ms: now(),
      });
      emit({ phase: 'creating', draft: Object.freeze({ title: '', content: '' }) });
    } catch (error) {
      if (current(request)) fail(error, false);
    } finally {
      finish(request);
    }
  };
  const open = async (id: string, intent: NativeMemoryIntent) => {
    if (
      !permitted('view') ||
      locked() ||
      (intent === 'edit' && !permitted('update')) ||
      (intent === 'delete' && !permitted('delete'))
    )
      return;
    const request = begin();
    clear();
    emit({ phase: 'loading', record: null, draft: null, error: null, notice: null });
    try {
      const scope = await observe(request.signal);
      if (!current(request)) return;
      const response = await client.execute(
        authority.scope,
        { operation: 'get', id },
        {
          expectedScope: scope,
          signal: request.signal,
        },
      );
      if (!current(request)) return;
      observed = scope;
      baseline = response.result.memory;
      emit({
        phase:
          intent === 'edit' ? 'editing' : intent === 'delete' ? 'confirming_delete' : 'viewing',
        record: response.result.memory,
        draft:
          intent === 'edit'
            ? Object.freeze({ title: baseline.title, content: baseline.content })
            : null,
      });
    } catch (error) {
      if (current(request)) fail(error, false);
    } finally {
      finish(request);
    }
  };
  const write = async () => {
    if (!pending || stopped) return;
    const original = pending;
    if (!permitted(original.command.operation)) return;
    const request = begin();
    emit({ phase: 'saving', error: null, notice: null });
    try {
      const response = await client.execute(authority.scope, original.command, {
        expectedScope: original.scope,
        signal: request.signal,
      });
      if (!current(request)) return;
      clear();
      emit({
        phase: response.result.receipt.deleted ? 'idle' : 'viewing',
        record: response.result.receipt.deleted ? null : response.result.receipt.memory,
        draft: null,
        notice: 'accepted',
        error: null,
      });
      // A refresh failure cannot turn an acknowledged mutation into an unknown outcome.
      void Promise.resolve()
        .then(() => {
          if (current(request)) onAccepted?.();
        })
        .catch(() => undefined);
    } catch (error) {
      if (current(request)) fail(error, true);
    } finally {
      finish(request);
    }
  };
  const save = async () => {
    if (
      !baseline ||
      !observed ||
      !model.draft ||
      (model.phase !== 'creating' && model.phase !== 'editing')
    )
      return;
    const creating = model.phase === 'creating';
    if (!permitted(creating ? 'create' : 'update')) return;
    try {
      const memory = { ...baseline, ...model.draft };
      const command = prepareNativeKnowledgeCommand(
        creating
          ? { operation: 'create', memory, idempotency_key: newId() }
          : {
              operation: 'update',
              memory,
              expected_revision: baseline.version,
              idempotency_key: newId(),
            },
      );
      pending = Object.freeze({ command, scope: observed });
    } catch (error) {
      fail(error, false);
      return;
    }
    await write();
  };
  const confirmDelete = async () => {
    if (model.phase !== 'confirming_delete' || !baseline || !observed || !permitted('delete'))
      return;
    pending = Object.freeze({
      scope: observed,
      command: prepareNativeKnowledgeCommand({
        operation: 'delete',
        id: baseline.id,
        expected_revision: baseline.version,
        idempotency_key: newId(),
      }),
    });
    await write();
  };
  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    create,
    open,
    save,
    confirmDelete,
    activate() {
      stopped = false;
      emit({ phase: allowed.length > 0 ? 'idle' : 'unavailable', allowedActions: allowed });
    },
    setDraft(patch: Partial<NativeMemoryDraft>) {
      if ((model.phase !== 'creating' && model.phase !== 'editing') || !model.draft) return;
      emit({
        draft: Object.freeze({
          title: typeof patch.title === 'string' ? patch.title : model.draft.title,
          content: typeof patch.content === 'string' ? patch.content : model.draft.content,
        }),
      });
    },
    retryWrite: async () => {
      if (model.phase === 'uncertain') await write();
    },
    reload: async () => {
      if (!locked() && model.record) await open(model.record.id, 'view');
    },
    close() {
      if (stopped || locked()) return;
      cancel();
      clear();
      emit({ phase: 'idle', record: null, draft: null, error: null, notice: null });
    },
    stop() {
      stopped = true;
      cancel();
      clear();
      emit({
        phase: 'unavailable',
        record: null,
        draft: null,
        notice: null,
        error: null,
        allowedActions: Object.freeze([]),
      });
    },
  });
}
