/**
 * memstack-agent-ui - React Package
 *
 * React hooks and providers for agent UI components.
 *
 * @packageDocumentation
 */

// Hooks
export type {
  UseAgentChatOptions,
  UseAgentChatReturn,
} from './hooks/useAgentChat';

export type {
  UseConversationOptions,
  UseConversationReturn,
} from './hooks/useConversation';

export type {
  UseStreamingOptions,
  UseStreamingReturn,
} from './hooks/useStreaming';

export { useAgentChat } from './hooks/useAgentChat';
export { useConversation } from './hooks/useConversation';
export { useStreaming } from './hooks/useStreaming';

// Provider
export type {
  AgentProviderProps,
  AgentContextValue,
} from './providers/AgentProvider';

export { AgentProvider, useAgentContext } from './providers/AgentProvider';
