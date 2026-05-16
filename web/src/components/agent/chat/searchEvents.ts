export const OPEN_AGENT_CHAT_SEARCH_EVENT = 'memstack:agent-open-chat-search';

export function requestOpenAgentChatSearch(): void {
  window.dispatchEvent(new CustomEvent(OPEN_AGENT_CHAT_SEARCH_EVENT));
}

export function subscribeToAgentChatSearchRequests(onOpen: () => void): () => void {
  window.addEventListener(OPEN_AGENT_CHAT_SEARCH_EVENT, onOpen);
  return () => {
    window.removeEventListener(OPEN_AGENT_CHAT_SEARCH_EVENT, onOpen);
  };
}
