import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { DesktopApiClient } from '../api/client';
import type { AgentWsEvent, DesktopRuntimeConfig } from '../types';

type AgentSocketState = {
  connected: boolean;
  error: string | null;
  events: AgentWsEvent[];
  subscribeConversation: (conversationId: string) => boolean;
  sendAgentMessage: (message: AgentRunMessage) => boolean;
};

type AgentRunMessage = {
  conversationId: string;
  projectId: string;
  message: string;
  messageId?: string;
};

export function useAgentSocket(config: DesktopRuntimeConfig, enabled: boolean): AgentSocketState {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentWsEvent[]>([]);
  const socketRef = useRef<WebSocket | null>(null);

  const client = useMemo(() => new DesktopApiClient(config), [config]);

  const sendSocketMessage = useCallback((payload: Record<string, unknown>) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(payload));
    return true;
  }, []);

  const subscribeConversation = useCallback(
    (conversationId: string) =>
      sendSocketMessage({
        type: 'subscribe',
        conversation_id: conversationId,
      }),
    [sendSocketMessage],
  );

  const sendAgentMessage = useCallback((message: AgentRunMessage) => {
    return sendSocketMessage({
        type: 'send_message',
        conversation_id: message.conversationId,
        project_id: message.projectId,
        message: message.message,
        message_id: message.messageId,
    });
  }, [sendSocketMessage]);

  useEffect(() => {
    if (!enabled || !config.apiKey.trim()) {
      setConnected(false);
      setError(null);
      return;
    }

    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(client.agentWsUrl(`desktop-${Date.now()}`));
      socketRef.current = socket;
    } catch (caught) {
      setError(String(caught));
      return;
    }

    socket.onopen = () => {
      setConnected(true);
      setError(null);
      if (config.projectId.trim()) {
        socket?.send(
          JSON.stringify({
            type: 'subscribe_status',
            project_id: config.projectId,
          }),
        );
        socket?.send(
          JSON.stringify({
            type: 'subscribe_lifecycle_state',
            project_id: config.projectId,
          }),
        );
      }
      if (config.workspaceId.trim()) {
        socket?.send(
          JSON.stringify({
            type: 'subscribe_workspace',
            project_id: config.projectId,
            workspace_id: config.workspaceId,
            tenant_id: config.tenantId || undefined,
          }),
        );
      }
      if (config.projectId.trim()) {
        socket?.send(JSON.stringify({ type: 'subscribe_sandbox', project_id: config.projectId }));
      }
    };

    socket.onerror = () => {
      setError('Agent WebSocket error');
    };

    socket.onclose = () => {
      setConnected(false);
    };

    socket.onmessage = (message) => {
      const event = parseEvent(message.data);
      setEvents((current) => [event, ...current].slice(0, 80));
    };

    return () => {
      socket?.close();
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
    };
  }, [client, config.apiKey, config.projectId, config.workspaceId, enabled]);

  return { connected, error, events, subscribeConversation, sendAgentMessage };
}

function parseEvent(data: unknown): AgentWsEvent {
  if (typeof data !== 'string') return { type: 'binary', payload: data };
  try {
    const parsed = JSON.parse(data);
    if (parsed && typeof parsed === 'object') return parsed as AgentWsEvent;
  } catch {
    return { type: 'text', payload: data };
  }
  return { type: 'text', payload: data };
}
