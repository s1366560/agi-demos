/**
 * Wrapper for the ConversationSummaryCard that reads store state.
 */

import { memo } from 'react';

import { useConversationsStore } from '@business/agent/ui/web/stores/agent/conversationsStore';
import { ConversationSummaryCard } from '@/components/agent/chat/ConversationSummaryCard';

export const ConversationSummaryCardWrapper: React.FC<{
  conversationId?: string | null | undefined;
}> = memo(({ conversationId }) => {
  const currentConversation = useConversationsStore((s) => s.currentConversation);
  const generateConversationSummary = useConversationsStore((s) => s.generateConversationSummary);

  if (!conversationId || !currentConversation || currentConversation.id !== conversationId) {
    return null;
  }

  return (
    <ConversationSummaryCard
      summary={currentConversation.summary ?? null}
      conversationId={conversationId}
      onRegenerate={generateConversationSummary}
    />
  );
});
ConversationSummaryCardWrapper.displayName = 'ConversationSummaryCardWrapper';
