export type VisibleMessageKind = 'user' | 'agent' | 'runtime';

export type VisibleMessageActionAvailability = {
  copy: boolean;
  reply: boolean;
  edit: boolean;
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

const REPLY_EXCERPT_LENGTH = 500;

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
    retry: isAgent,
    retryDisabled: isAgent && streaming,
    saveTemplate: isAgent && !streaming,
  };
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
