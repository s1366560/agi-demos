export type VisibleMessageKind = 'user' | 'agent' | 'runtime';

export type VisibleMessageActionAvailability = {
  copy: boolean;
  reply: boolean;
  edit: boolean;
  delete: boolean;
  retry: boolean;
  retryDisabled: boolean;
  saveTemplate: boolean;
};

export type VisibleMessageForRetry = {
  id: string;
  conversationId: string;
  kind: VisibleMessageKind;
  content: string;
};

export type RetryDispatchResolution = {
  accepted: boolean;
  lock: string | null;
};

export type LocalMessageVisibilityState = {
  scopeKey: string;
  hiddenMessageIds: readonly string[];
};

export type MessageDeletionTarget = {
  scopeKey: string;
  messageId: string;
};

const REPLY_EXCERPT_LENGTH = 500;
const DELETE_EXCERPT_LENGTH = 80;

export function messageActionsForVisibleMessage(
  kind: VisibleMessageKind,
  streaming: boolean,
): VisibleMessageActionAvailability {
  const isUser = kind === 'user';
  const isAgent = kind === 'agent';
  return {
    copy: true,
    reply: isUser || isAgent,
    edit: isUser,
    delete: isUser,
    retry: isAgent,
    retryDisabled: isAgent && streaming,
    saveTemplate: isAgent && !streaming,
  };
}

export function hideMessageInScope(
  state: LocalMessageVisibilityState | null,
  scopeKey: string,
  messageId: string,
): LocalMessageVisibilityState {
  if (state?.scopeKey !== scopeKey) {
    return { scopeKey, hiddenMessageIds: [messageId] };
  }
  if (state.hiddenMessageIds.includes(messageId)) return state;
  return {
    scopeKey,
    hiddenMessageIds: [...state.hiddenMessageIds, messageId],
  };
}

export function filterHiddenMessages<T extends { id: string }>(
  messages: readonly T[],
  state: LocalMessageVisibilityState | null,
  scopeKey: string,
): T[] {
  if (state?.scopeKey !== scopeKey || state.hiddenMessageIds.length === 0) {
    return [...messages];
  }
  const hiddenMessageIds = new Set(state.hiddenMessageIds);
  return messages.filter((message) => !hiddenMessageIds.has(message.id));
}

export function canConfirmMessageDeletion(
  target: MessageDeletionTarget | null,
  currentScopeKey: string,
  visibleMessages: readonly VisibleMessageForRetry[],
): boolean {
  if (!target || target.scopeKey !== currentScopeKey) return false;
  return visibleMessages.some(
    (message) => message.id === target.messageId && message.kind === 'user',
  );
}

export function messageDeletionFocusNeighborId(
  messages: readonly VisibleMessageForRetry[],
  targetMessageId: string,
): string | null {
  const targetIndex = messages.findIndex((message) => message.id === targetMessageId);
  if (targetIndex < 0) return null;
  return messages[targetIndex + 1]?.id ?? messages[targetIndex - 1]?.id ?? null;
}

export function messageDeletionExcerpt(content: string): string {
  return content.length > DELETE_EXCERPT_LENGTH
    ? `${content.slice(0, DELETE_EXCERPT_LENGTH)}…`
    : content;
}

export function quoteMessageForComposer(content: string): string | null {
  const trimmed = content.trim();
  if (!trimmed) return null;
  const excerpt =
    trimmed.length > REPLY_EXCERPT_LENGTH
      ? `${trimmed.slice(0, REPLY_EXCERPT_LENGTH)}…`
      : trimmed;
  return `${excerpt
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n')}\n\n`;
}

export function findRetryMessageContent(
  messages: readonly VisibleMessageForRetry[],
  targetMessageId: string,
  currentConversationId: string,
): string | null {
  const targetIndex = messages.findIndex(
    (message) =>
      message.id === targetMessageId &&
      message.conversationId === currentConversationId &&
      message.kind === 'agent',
  );
  if (targetIndex < 0) return null;
  for (let index = targetIndex - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (
      candidate?.conversationId === currentConversationId &&
      candidate.kind === 'user' &&
      candidate.content.trim()
    ) {
      return candidate.content.trim();
    }
  }
  return null;
}

export function resolveRetryDispatch(
  currentLock: string | null,
  targetMessageId: string,
  blocked: boolean,
): RetryDispatchResolution {
  if (blocked || currentLock) {
    return { accepted: false, lock: currentLock };
  }
  return { accepted: true, lock: targetMessageId };
}
