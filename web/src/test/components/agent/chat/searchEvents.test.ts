import { describe, expect, it, vi } from 'vitest';

import {
  OPEN_AGENT_CHAT_SEARCH_EVENT,
  requestOpenAgentChatSearch,
  subscribeToAgentChatSearchRequests,
} from '@/components/agent/chat/searchEvents';

describe('agent chat search events', () => {
  it('notifies subscribers when the header requests chat search', () => {
    const onOpen = vi.fn();
    const unsubscribe = subscribeToAgentChatSearchRequests(onOpen);

    requestOpenAgentChatSearch();

    expect(onOpen).toHaveBeenCalledTimes(1);

    unsubscribe();
    requestOpenAgentChatSearch();

    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('uses the stable event name consumed by AgentChatContent', () => {
    expect(OPEN_AGENT_CHAT_SEARCH_EVENT).toBe('memstack:agent-open-chat-search');
  });
});
