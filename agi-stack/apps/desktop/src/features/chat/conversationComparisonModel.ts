import type { AgentConversation, AgentTimelineItem } from '../../types';

export type ConversationComparisonScope = {
  tenantId: string;
  projectId: string;
  leftConversationId: string;
  rightConversationId: string;
};

export type ConversationComparisonMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestampMs: number;
};

export function conversationComparisonAvailable(
  currentConversation: AgentConversation | null,
  canLoadConversations: boolean,
): boolean {
  return Boolean(currentConversation) && canLoadConversations;
}

export function conversationComparisonCandidates(
  conversations: readonly AgentConversation[],
  currentConversation: AgentConversation,
  query: string,
): AgentConversation[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return conversations.filter((conversation) => {
    if (
      conversation.id === currentConversation.id ||
      conversation.tenant_id !== currentConversation.tenant_id ||
      conversation.project_id !== currentConversation.project_id
    ) {
      return false;
    }
    if (!normalizedQuery) return true;
    return `${conversation.title} ${conversation.id}`.toLocaleLowerCase().includes(normalizedQuery);
  });
}

export function conversationComparisonScope(
  left: AgentConversation,
  right: AgentConversation,
): ConversationComparisonScope | null {
  if (
    !left.id ||
    !right.id ||
    left.id === right.id ||
    !left.tenant_id ||
    left.tenant_id !== right.tenant_id ||
    !left.project_id ||
    left.project_id !== right.project_id
  ) {
    return null;
  }
  return {
    tenantId: left.tenant_id,
    projectId: left.project_id,
    leftConversationId: left.id,
    rightConversationId: right.id,
  };
}

export function conversationComparisonScopeKey(scope: ConversationComparisonScope | null): string {
  if (!scope) return '';
  return [
    scope.tenantId,
    scope.projectId,
    scope.leftConversationId,
    scope.rightConversationId,
  ].join(':');
}

export function conversationComparisonMessages(
  items: readonly AgentTimelineItem[],
): ConversationComparisonMessage[] {
  return items.flatMap((item) => {
    if (item.type !== 'user_message' && item.type !== 'assistant_message') {
      return [];
    }
    const timestampMs = Number.isFinite(item.eventTimeUs)
      ? Math.floor(item.eventTimeUs / 1_000)
      : typeof item.timestamp === 'number' && Number.isFinite(item.timestamp)
        ? item.timestamp
        : 0;
    return [
      {
        id: item.id,
        role: item.type === 'user_message' ? ('user' as const) : ('assistant' as const),
        content: item.content ?? '',
        timestampMs,
      },
    ];
  });
}

export function conversationComparisonRequestMatches({
  requestId,
  currentRequestId,
  expectedConversationId,
  responseConversationId,
  expectedScopeKey,
  currentScopeKey,
}: {
  requestId: number;
  currentRequestId: number;
  expectedConversationId: string;
  responseConversationId: string;
  expectedScopeKey: string;
  currentScopeKey: string;
}): boolean {
  return (
    requestId === currentRequestId &&
    Boolean(expectedScopeKey) &&
    expectedScopeKey === currentScopeKey &&
    expectedConversationId === responseConversationId
  );
}
