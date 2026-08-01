import { DesktopApiError } from '../../api/client';
import {
  DeadLetterQueueUnavailableError,
  type DeadLetterQueueAuthority,
  type DeadLetterQueueClient,
  type DeadLetterQueueMessage,
  type DeadLetterQueueMessageStatus,
  type DeadLetterQueueQuery,
  type DeadLetterQueueScope,
  type DeadLetterQueueStats,
} from './deadLetterQueueClient';

export type DeadLetterQueueResourceState =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'forbidden'
  | 'unavailable';

export type DeadLetterQueueMutationState =
  | 'idle'
  | 'error'
  | 'conflict'
  | 'forbidden'
  | 'unavailable';

export type DeadLetterQueueViewModel = Readonly<{
  scope: DeadLetterQueueScope;
  authority: DeadLetterQueueAuthority;
  messagesState: DeadLetterQueueResourceState;
  statsState: DeadLetterQueueResourceState;
  messagesReasonCode: string | null;
  statsReasonCode: string | null;
  mutationState: DeadLetterQueueMutationState;
  mutationReasonCode: string | null;
  retryMessagesVisible: boolean;
  retryStatsVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  messages: readonly DeadLetterQueueMessage[];
  stats: DeadLetterQueueStats | null;
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
  selectedIds: readonly string[];
  detail: DeadLetterQueueMessage | null;
  detailState: 'idle' | 'loading' | 'ready' | 'error' | 'forbidden';
  query: Required<DeadLetterQueueQuery>;
  lastUpdatedAt: string | null;
}>;

export type DeadLetterQueueController = Readonly<{
  getSnapshot: () => DeadLetterQueueViewModel;
  subscribe: (listener: () => void) => () => void;
  load: (scope: DeadLetterQueueScope, query?: DeadLetterQueueQuery) => Promise<void>;
  retry: () => Promise<void>;
  retryMessage: (messageId: string) => Promise<void>;
  retryMessages: (messageIds: readonly string[]) => Promise<void>;
  retrySelected: () => Promise<void>;
  discardMessages: (messageIds: readonly string[], reason: string) => Promise<void>;
  discardMessage: (messageId: string, reason: string) => Promise<void>;
  discardSelected: (reason: string) => Promise<void>;
  cleanup: (kind: 'expired' | 'resolved', olderThanHours: number) => Promise<void>;
  setQuery: (query: DeadLetterQueueQuery) => Promise<void>;
  openDetail: (messageId: string) => Promise<void>;
  closeDetail: () => void;
  toggleSelection: (messageId: string) => void;
  clearSelection: () => void;
  cancel: () => void;
  stop: () => void;
}>;

const EMPTY_ACTIONS = Object.freeze([]) as readonly string[];
const DEFAULT_QUERY = Object.freeze({
  status: 'all' as DeadLetterQueueMessageStatus | 'all',
  eventType: '',
  errorType: '',
  routingKey: '',
  limit: 50,
  offset: 0,
});

export function createDeadLetterQueueController({
  authority,
  client,
  initialScope,
}: Readonly<{
  authority: DeadLetterQueueAuthority;
  client: DeadLetterQueueClient;
  initialScope: DeadLetterQueueScope;
}>): DeadLetterQueueController {
  let activeScope = freezeScope(initialScope);
  let activeQuery: Required<DeadLetterQueueQuery> = DEFAULT_QUERY;
  let model =
    authority === 'local'
      ? unavailableModel(activeScope, activeQuery)
      : loadingModel(activeScope, activeQuery);
  let requestController: AbortController | null = null;
  let requestRevision = 0;
  const listeners = new Set<() => void>();

  const emit = (next: DeadLetterQueueViewModel): void => {
    model = next;
    for (const listener of [...listeners]) listener();
  };
  const cancel = (): void => {
    requestRevision += 1;
    requestController?.abort();
    requestController = null;
  };
  const load = async (
    nextScope: DeadLetterQueueScope,
    query: DeadLetterQueueQuery = activeQuery,
  ): Promise<void> => {
    const scope = freezeScope(nextScope);
    const normalizedQuery = normalizeQuery(query);
    activeScope = scope;
    activeQuery = normalizedQuery;
    if (scope.authority !== authority) {
      cancel();
      emit(
        unavailableModel(scope, normalizedQuery, 'dead_letter_queue_controller_authority_mismatch'),
      );
      return;
    }
    if (scope.authority === 'local') {
      cancel();
      emit(unavailableModel(scope, normalizedQuery));
      return;
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({
      ...stable,
      scope,
      authority: scope.authority,
      messagesState: 'loading',
      statsState: 'loading',
      messagesReasonCode: null,
      statsReasonCode: null,
      mutationState: 'idle',
      mutationReasonCode: null,
      retryMessagesVisible: false,
      retryStatsVisible: false,
      busyAction: null,
      query: normalizedQuery,
      selectedIds: Object.freeze([]),
    });
    const [messagesResult, statsResult] = await Promise.allSettled([
      client.listMessages(scope, normalizedQuery, { signal: controller.signal }),
      client.getStats(scope, { signal: controller.signal }),
    ]);
    if (!requestIsCurrent(revision, controller)) return;
    requestController = null;
    const next = settleLoad(stable, scope, normalizedQuery, messagesResult, statsResult);
    emit(next);
  };
  const mutate = async (
    action: string,
    operation: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<void> => {
    if (model.busyAction !== null) {
      throw new Error('dead_letter_queue_mutation_in_progress');
    }
    const stable = model;
    const revision = ++requestRevision;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    emit({ ...stable, busyAction: action, mutationState: 'idle', mutationReasonCode: null });
    try {
      await operation(controller.signal);
      if (!requestIsCurrent(revision, controller)) return;
      requestController = null;
      emit({ ...model, busyAction: null, selectedIds: Object.freeze([]) });
      await load(activeScope, activeQuery);
    } catch (error) {
      if (!requestIsCurrent(revision, controller)) throw error;
      requestController = null;
      emit(mutationErrorModel(stable, error));
      throw error;
    }
  };

  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: () => load(activeScope, activeQuery),
    setQuery: (query) => load(activeScope, { ...activeQuery, ...query }),
    retryMessage: async (messageId) => {
      const message = requireVisibleMessage(model.messages, messageId);
      await mutate(`retry:${message.id}`, (signal) =>
        client.retryMessage(activeScope, message.id, { signal }),
      );
    },
    retryMessages: async (messageIds) =>
      await mutate('retry-selected', (signal) =>
        client.retryMessages(activeScope, messageIds, { signal }),
      ),
    retrySelected: async () => {
      const messageIds = requireSelection(model.selectedIds);
      await mutate('retry-selected', (signal) =>
        client.retryMessages(activeScope, messageIds, { signal }),
      );
    },
    discardMessages: async (messageIds, reason) => {
      const discardReason = requireDiscardReason(reason);
      await mutate('discard-selected', (signal) =>
        client.discardMessages(activeScope, messageIds, discardReason, { signal }),
      );
    },
    discardMessage: async (messageId, reason) => {
      const message = requireVisibleMessage(model.messages, messageId);
      const discardReason = requireDiscardReason(reason);
      await mutate(`discard:${message.id}`, (signal) =>
        client.discardMessage(activeScope, message.id, discardReason, { signal }),
      );
    },
    discardSelected: async (reason) => {
      const messageIds = requireSelection(model.selectedIds);
      const discardReason = requireDiscardReason(reason);
      await mutate('discard-selected', (signal) =>
        client.discardMessages(activeScope, messageIds, discardReason, { signal }),
      );
    },
    cleanup: (kind, olderThanHours) =>
      mutate(`cleanup-${kind}`, (signal) =>
        kind === 'expired'
          ? client.cleanupExpired(activeScope, olderThanHours, { signal })
          : client.cleanupResolved(activeScope, olderThanHours, { signal }),
      ),
    async openDetail(messageId) {
      const id = requireVisibleMessage(model.messages, messageId).id;
      if (model.busyAction !== null) return;
      const stable = model;
      const revision = ++requestRevision;
      requestController?.abort();
      const controller = new AbortController();
      requestController = controller;
      emit({ ...stable, detailState: 'loading', busyAction: `detail:${id}` });
      try {
        const detail = await client.getMessage(activeScope, id, { signal: controller.signal });
        if (!requestIsCurrent(revision, controller)) return;
        requestController = null;
        emit({ ...model, detail, detailState: 'ready', busyAction: null });
      } catch (error) {
        if (!requestIsCurrent(revision, controller)) return;
        requestController = null;
        emit({
          ...stable,
          detailState:
            error instanceof DesktopApiError && error.status === 403 ? 'forbidden' : 'error',
          busyAction: null,
          mutationReasonCode: reasonCode(error),
        });
      }
    },
    closeDetail() {
      emit({ ...model, detail: null, detailState: 'idle' });
    },
    toggleSelection(messageId) {
      requireVisibleMessage(model.messages, messageId);
      const selected = new Set(model.selectedIds);
      if (selected.has(messageId)) selected.delete(messageId);
      else selected.add(messageId);
      emit({ ...model, selectedIds: Object.freeze([...selected]) });
    },
    clearSelection() {
      emit({ ...model, selectedIds: Object.freeze([]) });
    },
    cancel,
    stop: cancel,
  });

  function requestIsCurrent(revision: number, controller: AbortController): boolean {
    return (
      revision === requestRevision && requestController === controller && !controller.signal.aborted
    );
  }
}

function settleLoad(
  stable: DeadLetterQueueViewModel,
  scope: DeadLetterQueueScope,
  query: Required<DeadLetterQueueQuery>,
  messagesResult: PromiseSettledResult<Awaited<ReturnType<DeadLetterQueueClient['listMessages']>>>,
  statsResult: PromiseSettledResult<DeadLetterQueueStats>,
): DeadLetterQueueViewModel {
  const messagesSuccess = messagesResult.status === 'fulfilled';
  const statsSuccess = statsResult.status === 'fulfilled';
  const messagesError = messagesResult.status === 'rejected' ? messagesResult.reason : null;
  const statsError = statsResult.status === 'rejected' ? statsResult.reason : null;
  const messages = messagesSuccess
    ? messagesResult.value.messages
    : sameScope(stable.scope, scope)
      ? stable.messages
      : Object.freeze([]);
  const stats = statsSuccess
    ? statsResult.value
    : sameScope(stable.scope, scope)
      ? stable.stats
      : null;
  const messageErrorState = resourceErrorState(messagesError, messages.length > 0);
  const statsErrorState = resourceErrorState(statsError, stats !== null);
  const now = new Date().toISOString();
  return Object.freeze({
    ...stable,
    scope,
    authority: scope.authority,
    messagesState: messagesSuccess
      ? messages.length === 0
        ? 'empty'
        : 'ready'
      : messageErrorState,
    statsState: statsSuccess ? 'ready' : statsErrorState,
    messagesReasonCode: messagesSuccess ? null : reasonCode(messagesError),
    statsReasonCode: statsSuccess ? null : reasonCode(statsError),
    mutationState: 'idle',
    mutationReasonCode: null,
    retryMessagesVisible: !messagesSuccess && isRetryable(messagesError),
    retryStatsVisible: !statsSuccess && isRetryable(statsError),
    busyAction: null,
    allowedActions: messagesSuccess ? messagesResult.value.allowedActions : stable.allowedActions,
    messages,
    stats,
    total: messagesSuccess ? messagesResult.value.total : stable.total,
    limit: messagesSuccess ? messagesResult.value.limit : query.limit,
    offset: messagesSuccess ? messagesResult.value.offset : query.offset,
    hasMore: messagesSuccess ? messagesResult.value.hasMore : stable.hasMore,
    selectedIds: Object.freeze([]),
    query,
    lastUpdatedAt: messagesSuccess || statsSuccess ? now : stable.lastUpdatedAt,
  });
}

function loadingModel(
  scope: DeadLetterQueueScope,
  query: Required<DeadLetterQueueQuery>,
): DeadLetterQueueViewModel {
  return Object.freeze({
    scope,
    authority: scope.authority,
    messagesState: 'loading',
    statsState: 'loading',
    messagesReasonCode: null,
    statsReasonCode: null,
    mutationState: 'idle',
    mutationReasonCode: null,
    retryMessagesVisible: false,
    retryStatsVisible: false,
    busyAction: null,
    allowedActions: EMPTY_ACTIONS,
    messages: Object.freeze([]),
    stats: null,
    total: 0,
    limit: query.limit,
    offset: query.offset,
    hasMore: false,
    selectedIds: Object.freeze([]),
    detail: null,
    detailState: 'idle',
    query,
    lastUpdatedAt: null,
  });
}

function unavailableModel(
  scope: DeadLetterQueueScope,
  query: Required<DeadLetterQueueQuery>,
  reason = 'cloud_message_bus_dlq_not_applicable',
): DeadLetterQueueViewModel {
  return Object.freeze({
    ...loadingModel(scope, query),
    messagesState: 'unavailable',
    statsState: 'unavailable',
    messagesReasonCode: reason,
    statsReasonCode: reason,
  });
}

function mutationErrorModel(
  stable: DeadLetterQueueViewModel,
  error: unknown,
): DeadLetterQueueViewModel {
  let state: DeadLetterQueueMutationState = 'error';
  if (error instanceof DeadLetterQueueUnavailableError) state = 'unavailable';
  if (error instanceof DesktopApiError && error.status === 403) state = 'forbidden';
  if (error instanceof DesktopApiError && error.status === 409) state = 'conflict';
  return Object.freeze({
    ...stable,
    mutationState: state,
    mutationReasonCode: reasonCode(error),
    busyAction: null,
  });
}

function resourceErrorState(error: unknown, hasStableValue: boolean): DeadLetterQueueResourceState {
  if (hasStableValue) return 'stale';
  if (error instanceof DeadLetterQueueUnavailableError) return 'unavailable';
  if (error instanceof DesktopApiError && error.status === 403) return 'forbidden';
  return 'error';
}

function reasonCode(error: unknown): string {
  if (error instanceof DeadLetterQueueUnavailableError) return error.reasonCode;
  if (error instanceof DesktopApiError && isRecord(error.payload)) {
    const reason = error.payload.reason_code;
    if (typeof reason === 'string' && reason.trim()) return reason;
  }
  return 'dead_letter_queue_request_failed';
}

function isRetryable(error: unknown): boolean {
  return !(
    error instanceof DeadLetterQueueUnavailableError ||
    (error instanceof DesktopApiError && error.status === 403)
  );
}

function normalizeQuery(query: DeadLetterQueueQuery): Required<DeadLetterQueueQuery> {
  return Object.freeze({
    status: query.status ?? 'all',
    eventType: query.eventType ?? '',
    errorType: query.errorType ?? '',
    routingKey: query.routingKey ?? '',
    limit: query.limit ?? 50,
    offset: query.offset ?? 0,
  });
}

function requireSelection(input: readonly string[]): readonly string[] {
  if (input.length === 0) {
    throw new Error('dead_letter_queue_selection_empty');
  }
  return input;
}

function requireDiscardReason(input: string): string {
  const reason = typeof input === 'string' ? input.trim() : '';
  if (!reason || reason.length > 500) {
    throw new Error('dead_letter_queue_discard_reason_invalid');
  }
  return reason;
}

function requireVisibleMessage(
  messages: readonly DeadLetterQueueMessage[],
  messageId: string,
): DeadLetterQueueMessage {
  const message = messages.find((candidate) => candidate.id === messageId);
  if (!message) throw new Error('dead_letter_queue_message_not_visible');
  return message;
}

function freezeScope(scope: DeadLetterQueueScope): DeadLetterQueueScope {
  return Object.freeze({ ...scope });
}

function sameScope(left: DeadLetterQueueScope, right: DeadLetterQueueScope): boolean {
  return left.authority === right.authority && left.tenantId === right.tenantId;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
