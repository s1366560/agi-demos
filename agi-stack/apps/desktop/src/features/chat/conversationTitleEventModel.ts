import type { AgentConversation } from '../../types';

export type ConversationTitleUpdate = {
  conversationId: string;
  title: string;
  generatedAt?: string;
};

type ConversationSession = {
  scopeKey: string;
  conversation: AgentConversation;
};

export function readConversationTitleStreamEvent(event: unknown): {
  handled: boolean;
  update: ConversationTitleUpdate | null;
} {
  const envelope = recordValue(event);
  const eventType = stringValue(envelope?.type ?? envelope?.event_type);
  if (eventType !== 'title_generated') return { handled: false, update: null };
  const data = recordValue(envelope?.data) ?? recordValue(envelope?.payload) ?? envelope;
  const conversationId = stringValue(data?.conversation_id ?? data?.conversationId);
  const title = stringValue(data?.title);
  if (!conversationId || !title) return { handled: true, update: null };
  const generatedAt = stringValue(data?.generated_at ?? data?.generatedAt);
  return {
    handled: true,
    update: {
      conversationId,
      title,
      ...(generatedAt ? { generatedAt } : {}),
    },
  };
}

export function applyConversationTitleUpdate(
  session: ConversationSession | null,
  conversationsByWorkspace: Record<string, AgentConversation[]>,
  update: ConversationTitleUpdate,
): {
  session: ConversationSession | null;
  conversationsByWorkspace: Record<string, AgentConversation[]>;
} {
  const nextSession =
    session?.conversation.id === update.conversationId &&
    session.conversation.title !== update.title
      ? {
          ...session,
          conversation: { ...session.conversation, title: update.title },
        }
      : session;

  let catalogChanged = false;
  const entries = Object.entries(conversationsByWorkspace).map(([workspaceId, conversations]) => {
    let workspaceChanged = false;
    const nextConversations = conversations.map((conversation) => {
      if (conversation.id !== update.conversationId || conversation.title === update.title) {
        return conversation;
      }
      workspaceChanged = true;
      return { ...conversation, title: update.title };
    });
    catalogChanged ||= workspaceChanged;
    return [workspaceId, workspaceChanged ? nextConversations : conversations] as const;
  });

  return {
    session: nextSession,
    conversationsByWorkspace: catalogChanged
      ? Object.fromEntries(entries)
      : conversationsByWorkspace,
  };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
