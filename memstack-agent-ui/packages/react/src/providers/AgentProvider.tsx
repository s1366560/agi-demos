/**
 * memstack-agent-ui - Agent Provider
 *
 * Context provider for agent chat functionality.
 * Wraps application with WebSocket client and state management.
 *
 * @packageDocumentation
 */

import { createElement, Context, ReactNode, useContext, useMemo } from 'react';

import type {
  WebSocketClientOptions,
  WebSocketStatus,
} from '@memstack-agent-ui/sdk';

/**
 * Agent context value
 */
export interface AgentContextValue {
  /** WebSocket server URL */
  wsUrl: string;

  /** Optional authentication token */
  token?: string;

  /** WebSocket connection status */
  status: WebSocketStatus;

  /** Submit a message to the agent */
  submit: (content: string, fileId?: string[]) => void;

  /** Whether agent is currently running */
  isRunning: boolean;

  /** Current error if any */
  error: Error | null;
}

/**
 * Agent context
 */
const AgentContext = Context<AgentContextValue | null>(null);

/**
 * Agent provider props
 */
export interface AgentProviderProps {
  /** WebSocket server URL */
  wsUrl: string;

  /** Optional authentication token */
  token?: string;

  /** Optional conversation ID */
  conversationId?: string;

  /** WebSocket client options */
  wsClientOptions?: Partial<Omit<WebSocketClientOptions, 'url' | 'token' | 'conversationId'>>;

  /** Child components */
  children: ReactNode;
}

/**
 * AgentProvider component
 *
 * Provides agent chat context to child components.
 *
 * @example
 * ```typescript
 * function App() {
 *   return (
 *     <AgentProvider wsUrl="ws://localhost:8000/agent/ws">
 *       <ChatInterface />
 *     </AgentProvider>
 *   );
 * }
 *
 * function ChatInterface() {
 *   const { submit, isRunning, status } = useAgentContext();
 *   return <input onSend={submit} disabled={isRunning} />;
 * }
 * ```
 */
export function AgentProvider(props: AgentProviderProps): JSX.Element {
  const { wsUrl, token, conversationId, wsClientOptions, children } = props;

  // For now, provide a minimal context
  // Full implementation would integrate with useAgentChat hook
  const contextValue = useMemo<AgentContextValue>(
    () => ({
      wsUrl,
      token,
      status: 'disconnected',
      submit: () => {
        console.warn('[AgentProvider] submit called but not implemented');
      },
      isRunning: false,
      error: null,
    }),
    [wsUrl, token]
  );

  return createElement(
    AgentContext.Provider,
    { value: contextValue },
    children as any
  );
}

/**
 * useAgentContext hook
 *
 * Access agent context from parent AgentProvider.
 *
 * @returns Agent context value
 * @throws Error if used outside of AgentProvider
 *
 * @example
 * ```typescript
 * function ChatInterface() {
 *   const { submit, isRunning } = useAgentContext();
 *   return <input onSend={submit} disabled={isRunning} />;
 * }
 * ```
 */
export function useAgentContext(): AgentContextValue {
  const context = useContext(AgentContext);
  if (!context) {
    throw new Error('useAgentContext must be used within AgentProvider');
  }
  return context;
}
