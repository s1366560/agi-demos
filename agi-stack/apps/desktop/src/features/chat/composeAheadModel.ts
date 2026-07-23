import type {
  AgentConversation,
  AgentTimelineItem,
  ComposerContextItem,
} from '../../types';
import type { SessionActivityPresence } from '../session/sessionNarrativeModel';
import type { AgentTaskSignal } from './agentTaskSignalModel';

export type ComposeAheadPromptStatus = 'queued' | 'dispatching' | 'failed';

export type ComposeAheadPrompt = Readonly<{
  id: string;
  text: string;
  contextItems: readonly ComposerContextItem[];
  createdAt: number;
  status: ComposeAheadPromptStatus;
}>;

export type ComposeAheadQueueStore = Readonly<{
  getSnapshot: (scope: string) => readonly ComposeAheadPrompt[];
  subscribe: (listener: () => void) => () => void;
  enqueue: (
    scope: string,
    prompt: Pick<ComposeAheadPrompt, 'text' | 'contextItems'>,
  ) => ComposeAheadPrompt;
  remove: (scope: string, promptId: string) => boolean;
  claimHead: (scope: string) => ComposeAheadPrompt | undefined;
  accept: (scope: string, promptId: string) => boolean;
  fail: (scope: string, promptId: string) => boolean;
  retry: (scope: string, promptId: string) => boolean;
}>;

type ComposeAheadQueueStoreOptions = Readonly<{
  now?: () => number;
  createId?: () => string;
}>;

export type ComposeAheadEligibilityReason =
  | 'not_streaming'
  | 'disabled'
  | 'empty'
  | 'uploading'
  | 'references'
  | 'unsupported_context';

export type ComposeAheadEligibility = Readonly<{
  canQueue: boolean;
  reason: ComposeAheadEligibilityReason | null;
}>;

export const EMPTY_COMPOSE_AHEAD_QUEUE: readonly ComposeAheadPrompt[] = Object.freeze([]);
let composeAheadPromptSequence = 0;

function defaultPromptId(): string {
  composeAheadPromptSequence += 1;
  return `desktop-prompt-${Date.now()}-${composeAheadPromptSequence}`;
}

export function createComposeAheadQueueStore(
  options: ComposeAheadQueueStoreOptions = {},
): ComposeAheadQueueStore {
  const now = options.now ?? Date.now;
  const createId = options.createId ?? defaultPromptId;
  const queues = new Map<string, readonly ComposeAheadPrompt[]>();
  const listeners = new Set<() => void>();

  const emit = () => {
    for (const listener of listeners) listener();
  };

  const replaceQueue = (scope: string, queue: readonly ComposeAheadPrompt[]) => {
    if (queue.length) queues.set(scope, queue);
    else queues.delete(scope);
    emit();
  };

  const updatePrompt = (
    scope: string,
    promptId: string,
    update: (prompt: ComposeAheadPrompt) => ComposeAheadPrompt | null,
  ): boolean => {
    const current = queues.get(scope);
    if (!current) return false;
    const index = current.findIndex((prompt) => prompt.id === promptId);
    if (index < 0) return false;
    const nextPrompt = update(current[index]);
    if (nextPrompt === current[index]) return false;
    const next = nextPrompt
      ? current.map((prompt, promptIndex) => (promptIndex === index ? nextPrompt : prompt))
      : current.filter((_, promptIndex) => promptIndex !== index);
    replaceQueue(scope, next);
    return true;
  };

  return {
    getSnapshot: (scope) => queues.get(scope) ?? EMPTY_COMPOSE_AHEAD_QUEUE,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    enqueue: (scope, prompt) => {
      const queuedPrompt: ComposeAheadPrompt = Object.freeze({
        id: createId(),
        text: prompt.text.trim(),
        contextItems: Object.freeze(prompt.contextItems.map(cloneContextItem)),
        createdAt: now(),
        status: 'queued',
      });
      replaceQueue(scope, [
        ...(queues.get(scope) ?? EMPTY_COMPOSE_AHEAD_QUEUE),
        queuedPrompt,
      ]);
      return queuedPrompt;
    },
    remove: (scope, promptId) => updatePrompt(scope, promptId, () => null),
    claimHead: (scope) => {
      const head = queues.get(scope)?.[0];
      if (!head || head.status !== 'queued') return undefined;
      const claimed = Object.freeze({ ...head, status: 'dispatching' as const });
      updatePrompt(scope, head.id, () => claimed);
      return claimed;
    },
    accept: (scope, promptId) => updatePrompt(scope, promptId, () => null),
    fail: (scope, promptId) =>
      updatePrompt(scope, promptId, (prompt) =>
        prompt.status === 'dispatching'
          ? Object.freeze({ ...prompt, status: 'failed' as const })
          : prompt,
      ),
    retry: (scope, promptId) =>
      updatePrompt(scope, promptId, (prompt) =>
        prompt.status === 'failed'
          ? Object.freeze({ ...prompt, status: 'queued' as const })
          : prompt,
      ),
  };
}

export const composeAheadQueueStore = createComposeAheadQueueStore();

export function composeAheadContextSnapshot(
  contextItems: readonly ComposerContextItem[],
): Readonly<{
  contextItems: readonly ComposerContextItem[];
  hasUnsupportedContext: boolean;
}> {
  const queueable = contextItems.filter(isQueueableComposeAheadContext);
  return {
    contextItems: Object.freeze(queueable.map(cloneContextItem)),
    hasUnsupportedContext: queueable.length !== contextItems.length,
  };
}

export function composeAheadEligibility(input: {
  content: string;
  streaming: boolean;
  disabled: boolean;
  uploading: boolean;
  contextItems: readonly ComposerContextItem[];
  referenceCount: number;
}): ComposeAheadEligibility {
  if (!input.streaming) return { canQueue: false, reason: 'not_streaming' };
  if (input.disabled) return { canQueue: false, reason: 'disabled' };
  if (!input.content.trim()) return { canQueue: false, reason: 'empty' };
  if (input.uploading) return { canQueue: false, reason: 'uploading' };
  if (input.referenceCount > 0) return { canQueue: false, reason: 'references' };
  if (composeAheadContextSnapshot(input.contextItems).hasUnsupportedContext) {
    return { canQueue: false, reason: 'unsupported_context' };
  }
  return { canQueue: true, reason: null };
}

export function composeAheadConversationScope(
  conversation: Pick<
    AgentConversation,
    'id' | 'tenant_id' | 'project_id' | 'workspace_id'
  > | null,
): string | null {
  if (!conversation?.id.trim()) return null;
  return [
    conversation.tenant_id.trim(),
    conversation.project_id.trim(),
    conversation.workspace_id?.trim() ?? '',
    conversation.id.trim(),
  ].join('\u0000');
}

export function conversationResponseIsStreaming(input: {
  activeConversationId: string;
  sending: boolean;
  activityPresence: SessionActivityPresence;
  signals: readonly AgentTaskSignal[];
  timelineItems: readonly AgentTimelineItem[];
}): boolean {
  if (input.sending) return true;
  if (!input.activeConversationId) return false;
  if (
    input.signals.some(
      (signal) =>
        signal.conversationId === input.activeConversationId &&
        signal.status !== 'failed' &&
        signal.eventType !== 'complete',
    )
  ) {
    return true;
  }

  const latestUserIndex = findLatestUserIndex(input.timelineItems);
  const currentTurn =
    latestUserIndex >= 0 ? input.timelineItems.slice(latestUserIndex + 1) : input.timelineItems;
  if (currentTurn.some((item) => item.metadata?.streaming === true)) return true;
  if (currentTurn.some(isTerminalConversationItem)) return false;
  return latestUserIndex >= 0 && input.activityPresence === 'live';
}

function findLatestUserIndex(items: readonly AgentTimelineItem[]): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role === 'user' || item.type === 'user_message') return index;
  }
  return -1;
}

function isTerminalConversationItem(item: AgentTimelineItem): boolean {
  if (item.isError || item.error || item.type === 'error') return true;
  if (
    item.type === 'complete' ||
    item.type === 'agent_conversation_finished' ||
    item.type === 'conversation_finished'
  ) {
    return true;
  }
  return (
    (item.role === 'assistant' || item.type === 'assistant_message') &&
    item.metadata?.streaming !== true
  );
}

function isQueueableComposeAheadContext(item: ComposerContextItem): boolean {
  const executionSlot = item.metadata?.execution_slot;
  return executionSlot === 'skill' || executionSlot === 'subagent';
}

function cloneContextItem(item: ComposerContextItem): ComposerContextItem {
  return {
    ...item,
    ...(item.metadata ? { metadata: { ...item.metadata } } : {}),
  };
}
