/**
 * memstack-agent-ui - useAgentChat Hook
 *
 * Main hook for agent chat, similar to Vercel AI SDK's useChat.
 * Manages WebSocket connection and message submission.
 *
 * @packageDocumentation
 */

import { useContext, useCallback, useEffect, useState } from 'react';

import type {
  WebSocketClient,
  WebSocketClientOptions,
  WebSocketStatus,
} from '@memstack-agent-ui/sdk';
import type { UserMessageEvent } from '@memstack-agent-ui/core';

/**
 * useAgentChat options
 */
export interface UseAgentChatOptions {
  /** WebSocket server URL */
  wsUrl: string;

  /** Optional authentication token */
  token?: string;

  /** Optional conversation ID to connect to */
  conversationId?: string;

  /** Heartbeat interval in milliseconds (default: 30000) */
  heartbeatInterval?: number;

  /** Maximum reconnect attempts (default: 5) */
  maxReconnectAttempts?: number;

  /** Callback when connection status changes */
  onStatusChange?: (status: WebSocketStatus) => void;

  /** Callback when connection error occurs */
  onError?: (error: Error) => void;

  /** Callback when agent completes execution */
  onComplete?: (data: unknown) => void;

  /** Callback when agent produces an error */
  onAgentError?: (data: unknown) => void;

  /** Callback when user message is acknowledged */
  onMessageAcknowledged?: (data: unknown) => void;
}

/**
 * useAgentChat return value
 */
export interface UseAgentChatReturn {
  /** Submit a message to the agent */
  submit: (content: string, fileId?: string[]) => void;

  /** Whether agent is currently running */
  isRunning: boolean;

  /** Current WebSocket connection status */
  status: WebSocketStatus;

  /** Current error if any */
  error: Error | null;

  /** WebSocket client instance (for advanced use) */
  client: WebSocketClient | null;
}

/**
 * useAgentChat hook
 *
 * Manages WebSocket connection and message submission.
 * Automatically handles connection lifecycle, reconnection, and event routing.
 *
 * @param options - Hook options
 * @returns Hook return value
 *
 * @example
 * ```typescript
 * function Chat() {
 *   const { submit, isRunning, status } = useAgentChat({
 *     wsUrl: 'ws://localhost:8000/agent/ws',
 *     conversationId: 'conv-123',
 *   });
 *
 *   return (
 *     <div>
 *       <input onSend={submit} disabled={isRunning} />
 *       <StatusBar status={status} />
 *     </div>
 *   );
 * }
 * ```
 */
export function useAgentChat(
  options: UseAgentChatOptions
): UseAgentChatReturn {
  const {
    wsUrl,
    token,
    conversationId,
    heartbeatInterval,
    maxReconnectAttempts,
    onStatusChange,
    onError,
    onComplete,
    onAgentError,
    onMessageAcknowledged,
  } = options;

  // State
  const [client, setClient] = useState<WebSocketClient | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [error, setError] = useState<Error | null>(null);

  // Create WebSocket client on mount
  useEffect(() => {
    // Dynamic import to avoid SSR issues
    const initClient = async () => {
      const { WebSocketClient } = await import('@memstack-agent-ui/sdk');

      const wsOptions: WebSocketClientOptions = {
        url: wsUrl,
        token,
        conversationId,
        heartbeatInterval,
        maxReconnectAttempts,
        onStatusChange: (newStatus) => {
          setStatus(newStatus);
          onStatusChange?.(newStatus);
        },
        onError: (err) => {
          setError(err);
          setIsRunning(false);
          onError?.(err);
        },
      };

      const wsClient = new WebSocketClient(wsOptions);
      setClient(wsClient);

      // Connect to WebSocket
      await wsClient.connect();

      // Subscribe to agent events
      wsClient.onAny((event) => {
        switch (event.type) {
          case 'complete':
            setIsRunning(false);
            onComplete?.(event.data);
            break;
          case 'error':
            setIsRunning(false);
            onAgentError?.(event.data);
            break;
          case 'user_message':
            setIsRunning(false);
            onMessageAcknowledged?.(event.data);
            break;
        }
      });
    };

    initClient().catch((err) => {
      console.error('[useAgentChat] Failed to initialize client:', err);
      setError(err);
    });

    // Cleanup on unmount
    return () => {
      client?.disconnect();
      setClient(null);
      setIsRunning(false);
    };
  }, [wsUrl, token]);

  // Submit message function
  const submit = useCallback(
    (content: string, fileId?: string[]) => {
      if (!client || !client.isConnected()) {
        console.warn('[useAgentChat] Cannot submit: client not connected');
        return;
      }

      // Create user message event
      const userMessage: UserMessageEvent = {
        id: `msg-${Date.now()}-${Math.random()}`,
        type: 'user_message',
        conversation_id: conversationId || '',
        timestamp: Date.now(),
        data: {
          content,
          fileMetadata: fileId ? [{ id: fileId[0] } as any] : undefined,
        },
      };

      // Send via WebSocket
      const sent = client.send({
        type: 'chat',
        conversation_id: conversationId,
        message: content,
        file_ids: fileId,
      });

      if (sent) {
        setIsRunning(true);
        setError(null);
      }
    },
    [client, conversationId]
  );

  return {
    submit,
    isRunning,
    status,
    error,
    client,
  };
}
