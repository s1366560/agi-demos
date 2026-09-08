import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import type {
  NativeKnowledgeClient,
  NativeKnowledgeCloudContext,
  NativeKnowledgeCommand,
  NativeKnowledgeContent,
  NativeKnowledgeGuard,
  NativeKnowledgePullContext,
  NativeKnowledgeResolutionRecord,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';
import { prepareNativeKnowledgeCommand } from './nativeKnowledgeValidation';
import {
  createNativeKnowledgeUiSession,
  nativeKnowledgeUiFailure,
} from './nativeKnowledgeUiSession';

export type NativeKnowledgeConflictSelection =
  | Readonly<{ kind: 'pull'; id: string }>
  | Readonly<{ kind: 'push'; localSequence: number }>
  | Readonly<{ kind: 'resolution'; id: string }>;
export type NativeKnowledgeDecision =
  | 'use_local'
  | 'use_remote'
  | 'keep_both'
  | 'merged'
  | 'keep_current'
  | 'use_proposed';
export type NativeKnowledgeConflictModel = Readonly<{
  phase:
    | 'idle'
    | 'loading'
    | 'reviewing'
    | 'checking'
    | 'saving'
    | 'uncertain'
    | 'accepted'
    | 'error';
  allowedActions: readonly string[];
  selection: NativeKnowledgeConflictSelection | null;
  context: NativeKnowledgePullContext | NativeKnowledgeCloudContext | null;
  record: NativeKnowledgeResolutionRecord | null;
  decision: NativeKnowledgeDecision | null;
  draft: NativeKnowledgeContent | null;
  error: 'failed' | 'conflict' | 'contextChanged' | 'uncertain' | 'reviewChanged' | null;
  pendingReconciliation: boolean;
}>;
type Write = Extract<
  NativeKnowledgeCommand,
  {
    operation: 'resolve_pull' | 'resolve_push' | 'resume_resolution' | 'reconcile_resolution';
  }
>;
type Preview = Readonly<{
  context: NativeKnowledgePullContext | NativeKnowledgeCloudContext | null;
  record: NativeKnowledgeResolutionRecord | null;
  scope: NativeKnowledgeScope;
}>;
export type NativeKnowledgeConflictController = ReturnType<
  typeof createNativeKnowledgeConflictController
>;
const sameJson = (left: unknown, right: unknown): boolean => {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  if (Array.isArray(left) || Array.isArray(right))
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJson(value, right[index]))
    );
  const a = left as Record<string, unknown>;
  const b = right as Record<string, unknown>;
  return (
    Object.keys(a).length === Object.keys(b).length &&
    Object.keys(a).every((key) => Object.hasOwn(b, key) && sameJson(a[key], b[key]))
  );
};
const guard = (context: NonNullable<Preview['context']>): NativeKnowledgeGuard => ({
  expected_local_revision: context.local.version,
  expected_remote_revision: context.remote?.revision ?? 0,
  expected_baseline_revision: context.baseline?.revision ?? 0,
  conflict_sequences: context.conflict_sequences,
});

export function createNativeKnowledgeConflictController({
  client,
  authority,
  newId = () => crypto.randomUUID(),
  onAccepted,
}: Readonly<{
  client: NativeKnowledgeClient;
  authority: NativeMemoriesAuthority;
  newId?: () => string;
  onAccepted?: () => void;
}>) {
  const session = createNativeKnowledgeUiSession(client, authority);
  const initial = (): NativeKnowledgeConflictModel =>
    Object.freeze({
      phase: 'idle',
      allowedActions: session.allowedActions,
      selection: null,
      context: null,
      record: null,
      decision: null,
      draft: null,
      error: null,
      pendingReconciliation: false,
    });
  let model = initial();
  let preview: Preview | null = null;
  let pending: Readonly<{ command: Write; scope: NativeKnowledgeScope }> | null = null;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeConflictModel>) => {
    model = Object.freeze({ ...model, ...patch });
    for (const listener of [...listeners]) listener();
  };
  const locked = () => ['checking', 'saving', 'uncertain'].includes(model.phase);
  const requiredRead = (selection: NativeKnowledgeConflictSelection) =>
    selection.kind === 'pull'
      ? 'pull_conflict_context'
      : selection.kind === 'push'
        ? 'cloud_conflict_context'
        : 'resolution';
  const read = async (
    selection: NativeKnowledgeConflictSelection,
    request: ReturnType<typeof session.begin>,
    scope?: NativeKnowledgeScope,
  ): Promise<Preview> => {
    if (selection.kind === 'pull') {
      const response = await session.execute(
        { operation: 'pull_conflict_context', id: selection.id },
        request,
        scope,
      );
      return { context: response.result.context, record: null, scope: response.scope };
    }
    if (selection.kind === 'push') {
      const response = await session.execute(
        { operation: 'cloud_conflict_context', local_sequence: selection.localSequence },
        request,
        scope,
      );
      return { context: response.result.context, record: null, scope: response.scope };
    }
    const response = await session.execute(
      { operation: 'resolution', resolution_id: selection.id },
      request,
      scope,
    );
    const record = response.result.record;
    if (record.receipt && !record.reconciliation && session.allowed('reconciliation_context')) {
      const result = await session.execute(
        { operation: 'reconciliation_context', resolution_id: selection.id },
        request,
        response.scope,
      );
      return { context: result.result.context, record, scope: result.scope };
    }
    return { context: null, record, scope: response.scope };
  };
  const show = (value: Preview) => {
    preview = value;
    emit({
      phase: 'reviewing',
      context: value.context,
      record: value.record,
      decision: null,
      draft: null,
      error: null,
      pendingReconciliation: !!value.record?.receipt && !value.record.reconciliation,
    });
  };
  const open = async (selection: NativeKnowledgeConflictSelection) => {
    if (locked() || !session.allowed(requiredRead(selection))) return;
    const request = session.begin();
    preview = null;
    pending = null;
    model = initial();
    emit({ phase: 'loading', selection: Object.freeze({ ...selection }) });
    try {
      const value = await read(selection, request);
      if (session.current(request)) show(value);
    } catch (error) {
      if (session.current(request))
        emit({
          phase: 'error',
          error: nativeKnowledgeUiFailure(error) === 'contextChanged' ? 'contextChanged' : 'failed',
        });
    }
  };
  const decisions = (): readonly NativeKnowledgeDecision[] => {
    if (!model.context || !model.selection) return [];
    if (model.selection.kind === 'push')
      return session.allowed('resolve_push') ? ['keep_current', 'use_proposed', 'merged'] : [];
    return session.allowed(
      model.selection.kind === 'pull' ? 'resolve_pull' : 'reconcile_resolution',
    )
      ? ['use_local', 'use_remote', 'keep_both', 'merged']
      : [];
  };
  const choose = (decision: NativeKnowledgeDecision) => {
    if (model.phase !== 'reviewing' || !decisions().includes(decision)) return;
    const context = model.context!;
    const source = context.remote?.content ?? context.baseline?.content;
    const draft: NativeKnowledgeContent = source
      ? { ...source, tags: [...source.tags], metadata: { ...source.metadata } }
      : {
          title: context.local.title,
          content: context.local.content,
          content_type: 'text',
          tags: [...context.local.tags],
          metadata: { ...context.local_metadata },
          status: 'ENABLED',
        };
    emit({ decision, draft: decision === 'merged' ? draft : null, error: null });
  };
  const setDraft = (patch: Readonly<{ title?: string; content?: string }>) => {
    if (model.phase !== 'reviewing' || model.decision !== 'merged' || !model.draft) return;
    emit({
      draft: {
        ...model.draft,
        ...(typeof patch.title === 'string' ? { title: patch.title } : {}),
        ...(typeof patch.content === 'string' ? { content: patch.content } : {}),
      },
    });
  };
  const run = async (request: ReturnType<typeof session.begin>) => {
    if (!pending) return;
    emit({ phase: 'saving', error: null });
    try {
      const response = await session.execute(pending.command, request, pending.scope);
      if (!session.current(request)) return;
      pending = null;
      emit({
        phase: 'accepted',
        decision: null,
        draft: null,
        error: null,
        pendingReconciliation:
          'pending_reconciliation' in response.result && response.result.pending_reconciliation,
      });
      void Promise.resolve()
        .then(() => {
          if (session.current(request)) onAccepted?.();
        })
        .catch(() => {});
    } catch (error) {
      if (!session.current(request)) return;
      const failure = nativeKnowledgeUiFailure(error);
      if (failure === 'uncertain') emit({ phase: 'uncertain', error: failure });
      else {
        pending = null;
        if (failure === 'contextChanged') {
          preview = null;
          model = initial();
        }
        emit({ phase: 'error', error: failure, decision: null, draft: null });
      }
    }
  };
  const submit = async () => {
    if (model.phase !== 'reviewing' || !model.selection || !preview) return;
    const selection = model.selection;
    const prior = preview;
    const decision = model.decision;
    const draft = model.draft;
    const resume =
      selection.kind === 'resolution' &&
      model.record &&
      !model.record.receipt &&
      !model.record.rejection &&
      session.allowed('resume_resolution');
    if (!resume && (!decision || !decisions().includes(decision))) return;
    const request = session.begin();
    emit({ phase: 'checking', error: null });
    try {
      const fresh = await read(selection, request, prior.scope);
      if (!session.current(request)) return;
      if (!sameJson(fresh, prior)) {
        show(fresh);
        emit({ error: 'reviewChanged' });
        return;
      }
      let command: Write;
      if (resume && selection.kind === 'resolution')
        command = {
          operation: 'resume_resolution',
          resolution_id: selection.id,
        };
      else {
        const context = fresh.context!;
        if (selection.kind === 'push') {
          if (decision !== 'keep_current' && decision !== 'use_proposed' && decision !== 'merged')
            return;
          const cloud = context as NativeKnowledgeCloudContext;
          command = {
            operation: 'resolve_push',
            idempotency_key: newId(),
            resolution: {
              local_sequence: cloud.local_sequence,
              memory_id: cloud.memory_id,
              conflict_id: cloud.conflict_id,
              guard: guard(context),
              choice: decision === 'merged' ? { decision, content: draft! } : { decision },
            },
          };
        } else {
          if (
            decision !== 'use_local' &&
            decision !== 'use_remote' &&
            decision !== 'keep_both' &&
            decision !== 'merged'
          )
            return;
          const choice =
            decision === 'merged' ? ({ decision, content: draft! } as const) : { decision };
          command =
            selection.kind === 'pull'
              ? {
                  operation: 'resolve_pull',
                  idempotency_key: newId(),
                  resolution: { ...guard(context), memory_id: context.memory_id, choice },
                }
              : {
                  operation: 'reconcile_resolution',
                  resolution_id: selection.id,
                  reconciliation: { guard: guard(context), choice },
                };
        }
      }
      pending = Object.freeze({
        command: prepareNativeKnowledgeCommand(command) as Write,
        scope: fresh.scope,
      });
      await run(request);
    } catch (error) {
      if (session.current(request)) {
        const failure = nativeKnowledgeUiFailure(error);
        if (failure === 'contextChanged') {
          preview = null;
          model = initial();
        }
        emit({
          phase: 'error',
          error: failure === 'uncertain' ? 'failed' : failure,
          decision: null,
          draft: null,
        });
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
    open,
    choose,
    setDraft,
    submit,
    decisions,
    retry: async () => {
      if (model.phase === 'uncertain' && pending) await run(session.begin());
    },
    reload: async () => {
      if (model.selection) await open(model.selection);
    },
    close: () => {
      if (!locked()) {
        session.cancel();
        preview = null;
        pending = null;
        model = initial();
        emit({});
      }
    },
    stop: () => {
      session.stop();
      preview = null;
      pending = null;
      model = initial();
      emit({});
    },
    activate: session.activate,
  });
}
