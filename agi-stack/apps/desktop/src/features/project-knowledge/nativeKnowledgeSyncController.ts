import type { NativeMemoriesAuthority } from './nativeMemoriesController';
import type {
  NativeKnowledgeClient,
  NativeKnowledgeResultMap,
  NativeKnowledgeScope,
} from './nativeKnowledgeContracts';
import {
  createNativeKnowledgeUiSession,
  nativeKnowledgeUiFailure,
} from './nativeKnowledgeUiSession';

export type NativeKnowledgeSyncModel = Readonly<{
  phase: 'idle' | 'loading' | 'syncing' | 'ready' | 'uncertain' | 'error';
  allowedActions: readonly string[];
  status: NativeKnowledgeResultMap['sync_status']['status'] | null;
  outbox: NativeKnowledgeResultMap['sync_outbox'] | null;
  pullConflicts: NativeKnowledgeResultMap['pull_conflicts']['items'];
  pushConflicts: NativeKnowledgeResultMap['push_conflicts']['items'];
  pending: NativeKnowledgeResultMap['pending_resolutions'] | null;
  resolutions: NativeKnowledgeResultMap['resolutions']['items'];
  error: 'failed' | 'conflict' | 'contextChanged' | 'uncertain' | null;
  lastOperation: 'sync_pull' | 'sync_push' | null;
  result: NativeKnowledgeResultMap['sync_pull'] | NativeKnowledgeResultMap['sync_push'] | null;
  recoveryRequired: boolean;
  outboxHasMore: boolean;
}>;
export type NativeKnowledgeSyncController = ReturnType<typeof createNativeKnowledgeSyncController>;

export function createNativeKnowledgeSyncController({
  client,
  authority,
  onAccepted,
  canSync = () => true,
}: Readonly<{
  client: NativeKnowledgeClient;
  authority: NativeMemoriesAuthority;
  onAccepted?: () => void;
  canSync?: () => boolean;
}>) {
  const session = createNativeKnowledgeUiSession(client, authority);
  const initial = (): NativeKnowledgeSyncModel =>
    Object.freeze({
      phase: 'idle',
      allowedActions: session.allowedActions,
      status: null,
      outbox: null,
      pullConflicts: [],
      pushConflicts: [],
      pending: null,
      resolutions: [],
      error: null,
      lastOperation: null,
      result: null,
      recoveryRequired: false,
      outboxHasMore: false,
    });
  let model = initial();
  let observed: NativeKnowledgeScope | undefined;
  const listeners = new Set<() => void>();
  const emit = (patch: Partial<NativeKnowledgeSyncModel>) => {
    model = Object.freeze({ ...model, ...patch });
    for (const listener of [...listeners]) listener();
  };
  const busy = () => model.phase === 'loading' || model.phase === 'syncing';
  const collect = async (request: ReturnType<typeof session.begin>) => {
    const patch: Partial<NativeKnowledgeSyncModel> = {};
    if (session.allowed('sync_status')) {
      const response = await session.execute({ operation: 'sync_status' }, request, observed);
      observed = response.scope;
      Object.assign(patch, { status: response.result.status });
    }
    if (session.allowed('sync_outbox')) {
      const outbox = (
        await session.execute(
          { operation: 'sync_outbox', after_sequence: 0, limit: 50 },
          request,
          observed,
        )
      ).result;
      Object.assign(patch, { outbox, outboxHasMore: outbox.items.length === 50 });
    }
    if (session.allowed('pull_conflicts'))
      Object.assign(patch, {
        pullConflicts: (
          await session.execute({ operation: 'pull_conflicts', limit: 50 }, request, observed)
        ).result.items,
      });
    if (session.allowed('push_conflicts'))
      Object.assign(patch, {
        pushConflicts: (
          await session.execute({ operation: 'push_conflicts', limit: 50 }, request, observed)
        ).result.items,
      });
    if (session.allowed('pending_resolutions'))
      Object.assign(patch, {
        pending: (
          await session.execute({ operation: 'pending_resolutions', limit: 50 }, request, observed)
        ).result,
      });
    if (session.allowed('resolutions'))
      Object.assign(patch, {
        resolutions: (
          await session.execute({ operation: 'resolutions', limit: 50 }, request, observed)
        ).result.items,
      });
    return patch;
  };
  const refresh = async () => {
    if (
      busy() ||
      !(
        [
          'sync_status',
          'sync_outbox',
          'pull_conflicts',
          'push_conflicts',
          'pending_resolutions',
          'resolutions',
        ] as const
      ).some(session.allowed)
    )
      return;
    const request = session.begin();
    emit({ phase: 'loading', error: null });
    try {
      const patch = await collect(request);
      if (session.current(request)) emit({ ...patch, phase: 'ready', recoveryRequired: false });
    } catch (error) {
      if (session.current(request)) {
        const failure = nativeKnowledgeUiFailure(error);
        if (failure === 'contextChanged') {
          observed = undefined;
          model = initial();
        }
        emit({ phase: 'error', error: failure === 'uncertain' ? 'failed' : failure });
      }
    }
  };
  const sync = async (operation: 'sync_pull' | 'sync_push') => {
    if (!canSync()) return;
    if (
      model.phase !== 'ready' ||
      model.recoveryRequired ||
      !session.allowed(operation) ||
      !session.allowed('sync_status') ||
      !observed ||
      !model.status?.link
    )
      return;
    const request = session.begin();
    emit({ phase: 'syncing', error: null, lastOperation: operation, result: null });
    let accepted = false;
    try {
      const response = await session.execute({ operation }, request, observed);
      if (!session.current(request)) return;
      accepted = true;
      emit({ result: response.result });
      // Accepted source changes invalidate other readers even when this follow-up read fails.
      void Promise.resolve()
        .then(() => {
          if (session.current(request)) onAccepted?.();
        })
        .catch(() => {});
      const patch = await collect(request);
      if (session.current(request)) {
        emit({ ...patch, phase: 'ready' });
      }
    } catch (error) {
      if (!session.current(request)) return;
      const failure = nativeKnowledgeUiFailure(error);
      if (failure === 'contextChanged') {
        observed = undefined;
        model = initial();
      }
      emit({
        phase: !accepted && failure === 'uncertain' ? 'uncertain' : 'error',
        recoveryRequired: !accepted && failure === 'uncertain',
        error: accepted && failure === 'uncertain' ? 'failed' : failure,
      });
    }
  };
  const moreOutbox = async () => {
    if (
      busy() ||
      model.recoveryRequired ||
      !session.allowed('sync_outbox') ||
      !model.outbox?.items.length ||
      !model.outboxHasMore
    )
      return;
    const request = session.begin();
    const previous = model.outbox;
    emit({ phase: 'loading', error: null });
    try {
      const response = await session.execute(
        { operation: 'sync_outbox', after_sequence: previous.next_sequence, limit: 50 },
        request,
        observed,
      );
      if (session.current(request))
        emit({
          phase: 'ready',
          outboxHasMore: response.result.items.length === 50,
          outbox: {
            ...response.result,
            items: [...previous.items, ...response.result.items],
          },
        });
    } catch (error) {
      if (session.current(request)) {
        const failure = nativeKnowledgeUiFailure(error);
        if (failure === 'contextChanged') {
          observed = undefined;
          model = initial();
        }
        emit({ phase: 'error', error: failure === 'uncertain' ? 'failed' : failure });
      }
    }
  };
  const morePending = async () => {
    if (
      busy() ||
      model.recoveryRequired ||
      !session.allowed('pending_resolutions') ||
      !model.pending?.next_before_resolution_id
    )
      return;
    const request = session.begin();
    const previous = model.pending;
    emit({ phase: 'loading', error: null });
    try {
      const response = await session.execute(
        {
          operation: 'pending_resolutions',
          before_resolution_id: previous.next_before_resolution_id,
          limit: 50,
        },
        request,
        observed,
      );
      if (session.current(request))
        emit({
          phase: 'ready',
          pending: {
            ...response.result,
            items: [...previous.items, ...response.result.items],
          },
        });
    } catch (error) {
      if (session.current(request)) {
        const failure = nativeKnowledgeUiFailure(error);
        if (failure === 'contextChanged') {
          observed = undefined;
          model = initial();
        }
        emit({ phase: 'error', error: failure === 'uncertain' ? 'failed' : failure });
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
    refresh,
    invalidateSources: () => {
      if (
        model.phase === 'syncing' ||
        model.recoveryRequired ||
        !([
          'sync_status',
          'sync_outbox',
          'pull_conflicts',
          'push_conflicts',
          'pending_resolutions',
          'resolutions',
        ] as const).some(session.allowed)
      ) {
        return;
      }
      session.cancel();
      const { result, lastOperation } = model;
      model = initial();
      emit({ result, lastOperation });
      void refresh();
    },
    sync,
    moreOutbox,
    morePending,
    stop: () => {
      session.stop();
      observed = undefined;
      model = initial();
      emit({});
    },
    activate: session.activate,
  });
}
