import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { desktopApiCredential, DesktopApiClient } from '../api/client';
import type {
  AgentInputFileMetadata,
  AgentWsEvent,
  DesktopRuntimeConfig,
  HitlResponseSubmission,
} from '../types';

const HEARTBEAT_INTERVAL_MS = 20_000;
const WATCHDOG_INTERVAL_MS = 10_000;
const STALE_CONNECTION_MS = 60_000;
const MAX_SOCKET_EVENTS = 200;
const MAX_EVENT_KEYS = 400;
const MAX_PENDING_AGENT_MESSAGES = 100;

type AgentEventCursor = {
  conversationId: string;
  timeUs: number;
  counter: number;
};

export type AgentSocketContextState = {
  conversationCursors: Map<string, AgentEventCursor>;
  subscribedConversations: Set<string>;
  workspaceEventId: string | null;
  seenEventKeys: Set<string>;
};

type AgentSocketState = {
  connected: boolean;
  error: string | null;
  events: AgentWsEvent[];
  sendAgentMessage: (message: AgentRunMessage) => boolean;
  respondToHitl: (submission: HitlResponseSubmission) => boolean;
};

export type AgentSocketConversationTransition = {
  unsubscribeConversationIds: string[];
  subscribeConversationId: string | null;
};

export type AgentRunMessage = {
  conversationId: string;
  projectId: string;
  message: string;
  messageId?: string;
  agentId?: string;
  forcedSkillName?: string;
  mentions?: string[];
  fileMetadata?: AgentInputFileMetadata[];
  appModelContext?: Record<string, unknown>;
};

export type AgentRunSocketMessage = {
  type: 'send_message';
  conversation_id: string;
  project_id: string;
  message: string;
  message_id: string;
  agent_id?: string;
  forced_skill_name?: string;
  mentions?: string[];
  file_metadata?: AgentInputFileMetadata[];
  app_model_context?: Record<string, unknown>;
};

export type PendingAgentMessageQueue = Map<string, AgentRunSocketMessage>;

let pendingAgentMessageSequence = 0;

export function createPendingAgentMessageQueue(): PendingAgentMessageQueue {
  return new Map();
}

export function canQueuePendingAgentRunMessage(
  mode: DesktopRuntimeConfig['mode'],
  enabled: boolean,
  credential: string,
): boolean {
  return mode === 'cloud' && enabled && Boolean(credential.trim());
}

export function pendingAgentRunQueueScopeKey(
  config: DesktopRuntimeConfig,
  contextRevision: number | null,
): string {
  return [
    config.apiBaseUrl.trim(),
    config.apiKey.trim(),
    config.localApiToken.trim(),
    config.mode,
    config.tenantId.trim(),
    config.projectId.trim(),
    contextRevision ?? '',
  ].join('\u0000');
}

export function enqueuePendingAgentRunMessage(
  queue: PendingAgentMessageQueue,
  message: AgentRunMessage,
): boolean {
  const payload = agentRunSocketMessage(message);
  if (!payload) return false;
  return enqueuePendingAgentSocketMessage(queue, payload);
}

function agentRunSocketMessage(message: AgentRunMessage): AgentRunSocketMessage | null {
  const conversationId = message.conversationId.trim();
  const projectId = message.projectId.trim();
  const content = message.message.trim();
  if (!conversationId || !projectId || !content) return null;
  const messageId =
    message.messageId?.trim() ||
    `desktop-agent-${Date.now()}-${(pendingAgentMessageSequence += 1)}`;
  const agentId = message.agentId?.trim();
  const forcedSkillName = message.forcedSkillName?.trim();
  const mentions = message.mentions?.map((mention) => mention.trim()).filter(Boolean);
  return {
    type: 'send_message',
    conversation_id: conversationId,
    project_id: projectId,
    message: content,
    message_id: messageId,
    ...(agentId ? { agent_id: agentId } : {}),
    ...(forcedSkillName ? { forced_skill_name: forcedSkillName } : {}),
    ...(mentions?.length ? { mentions: [...new Set(mentions)] } : {}),
    ...(message.fileMetadata?.length
      ? { file_metadata: message.fileMetadata.map((file) => ({ ...file })) }
      : {}),
    ...(message.appModelContext && Object.keys(message.appModelContext).length
      ? { app_model_context: message.appModelContext }
      : {}),
  };
}

function enqueuePendingAgentSocketMessage(
  queue: PendingAgentMessageQueue,
  payload: AgentRunSocketMessage,
): boolean {
  const key = `${payload.conversation_id}\u0000${payload.message_id}`;
  if (!queue.has(key) && queue.size >= MAX_PENDING_AGENT_MESSAGES) return false;
  queue.set(key, payload);
  return true;
}

export function flushPendingAgentRunMessages(
  queue: PendingAgentMessageQueue,
  send: (message: AgentRunSocketMessage) => boolean,
): number {
  let sent = 0;
  for (const [key, message] of queue) {
    if (!send(message)) break;
    queue.delete(key);
    sent += 1;
  }
  return sent;
}

export function useAgentSocket(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  contextRevision: number | null,
  activeConversationId: string | null,
): AgentSocketState {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentWsEvent[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const contextStateRef = useRef(createAgentSocketContextState());
  const pendingAgentMessagesRef = useRef(createPendingAgentMessageQueue());
  const pendingEventsRef = useRef<AgentWsEvent[]>([]);
  const eventsFlushCancelRef = useRef<(() => void) | null>(null);
  const pendingAgentQueueScopeKey = pendingAgentRunQueueScopeKey(config, contextRevision);

  const client = useMemo(
    () => new DesktopApiClient(config),
    [config.apiBaseUrl, config.apiKey, config.localApiToken, config.mode],
  );
  const credential = desktopApiCredential(config);

  const sendSocketMessage = useCallback((payload: Record<string, unknown>) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    try {
      socket.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }, []);

  const subscribeConversation = useCallback(
    (conversationId: string) => {
      const normalizedConversationId = conversationId.trim();
      if (!normalizedConversationId) return false;
      contextStateRef.current.subscribedConversations.add(normalizedConversationId);
      const cursor = contextStateRef.current.conversationCursors.get(
        normalizedConversationId,
      );
      return sendSocketMessage({
        type: 'subscribe',
        conversation_id: normalizedConversationId,
        ...(cursor
          ? { from_time_us: cursor.timeUs, from_counter: cursor.counter + 1 }
          : {}),
      });
    },
    [sendSocketMessage],
  );

  const sendAgentMessage = useCallback(
    (message: AgentRunMessage) => {
      const conversationId = message.conversationId.trim();
      if (!conversationId) return false;
      contextStateRef.current.subscribedConversations.add(conversationId);
      const payload = agentRunSocketMessage(message);
      if (!payload) return false;
      if (sendSocketMessage(payload)) return true;
      if (!canQueuePendingAgentRunMessage(config.mode, enabled, credential)) return false;
      return enqueuePendingAgentSocketMessage(pendingAgentMessagesRef.current, payload);
    },
    [config.mode, credential, enabled, sendSocketMessage],
  );

  useEffect(
    () => () => {
      pendingAgentMessagesRef.current.clear();
    },
    [pendingAgentQueueScopeKey],
  );

  useEffect(() => {
    resetAgentSocketContextState(contextStateRef.current);
    setEvents([]);
  }, [
    config.apiBaseUrl,
    config.apiKey,
    config.localApiToken,
    config.mode,
    config.projectId,
    config.tenantId,
    config.workspaceId,
    contextRevision,
  ]);

  useEffect(() => {
    const transition = transitionAgentSocketConversationSelection(
      contextStateRef.current,
      activeConversationId,
    );
    transition.unsubscribeConversationIds.forEach((conversationId) => {
      sendSocketMessage({ type: 'unsubscribe', conversation_id: conversationId });
    });
    if (transition.subscribeConversationId) {
      subscribeConversation(transition.subscribeConversationId);
    }
  }, [
    activeConversationId,
    config.apiBaseUrl,
    config.apiKey,
    config.localApiToken,
    config.mode,
    config.projectId,
    config.tenantId,
    config.workspaceId,
    contextRevision,
    sendSocketMessage,
    subscribeConversation,
  ]);

  const respondToHitl = useCallback(
    (submission: HitlResponseSubmission) =>
      sendSocketMessage(buildHitlSocketMessage(submission)),
    [sendSocketMessage],
  );

  const flushPendingEvents = useCallback(() => {
    eventsFlushCancelRef.current = null;
    const pending = pendingEventsRef.current;
    if (!pending.length) return;
    pendingEventsRef.current = [];
    setEvents((current) =>
      [...pending.reverse(), ...current].slice(0, MAX_SOCKET_EVENTS),
    );
  }, []);

  const scheduleEventsFlush = useCallback(() => {
    if (eventsFlushCancelRef.current) return;
    if (typeof requestAnimationFrame === 'function') {
      const frame = requestAnimationFrame(flushPendingEvents);
      eventsFlushCancelRef.current = () => cancelAnimationFrame(frame);
    } else {
      const timer = setTimeout(flushPendingEvents, 16);
      eventsFlushCancelRef.current = () => clearTimeout(timer);
    }
  }, [flushPendingEvents]);

  useEffect(() => {
    const credential = desktopApiCredential(config);
    if (!enabled || !credential) {
      setConnected(false);
      setError(null);
      return;
    }

    let disposed = false;
    let reconnectAttempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let watchdogTimer: ReturnType<typeof setInterval> | null = null;
    let lastMessageAt = Date.now();

    const stopConnectionTimers = () => {
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (watchdogTimer) clearInterval(watchdogTimer);
      heartbeatTimer = null;
      watchdogTimer = null;
    };

    const sendSubscriptions = (socket: WebSocket) => {
      if (config.mode === 'cloud' && config.projectId.trim()) {
        socket.send(
          JSON.stringify({
            type: 'subscribe_status',
            project_id: config.projectId,
          }),
        );
        socket.send(
          JSON.stringify({
            type: 'subscribe_lifecycle_state',
            project_id: config.projectId,
            tenant_id: config.tenantId || undefined,
          }),
        );
        socket.send(
          JSON.stringify({
            type: 'subscribe_sandbox',
            project_id: config.projectId,
            tenant_id: config.tenantId || undefined,
          }),
        );
      }
      if (config.mode === 'cloud' && config.workspaceId.trim()) {
        socket.send(
          JSON.stringify({
            type: 'subscribe_workspace',
            project_id: config.projectId,
            workspace_id: config.workspaceId,
            tenant_id: config.tenantId || undefined,
            last_event_id: contextStateRef.current.workspaceEventId || undefined,
          }),
        );
      }
      conversationSubscriptionMessages(contextStateRef.current).forEach((message) => {
        socket.send(JSON.stringify(message));
      });
    };

    const scheduleReconnect = (connect: () => void) => {
      if (disposed || reconnectTimer) return;
      const delay = reconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (disposed) return;
      let socket: WebSocket;
      try {
        socket = new WebSocket(
          client.agentWsUrl(`desktop-${Date.now()}`),
          client.agentWsProtocols(),
        );
        socketRef.current = socket;
      } catch (caught) {
        setError(String(caught));
        scheduleReconnect(connect);
        return;
      }

      socket.onopen = () => {
        if (disposed || socketRef.current !== socket) return;
        reconnectAttempt = 0;
        lastMessageAt = Date.now();
        setConnected(true);
        setError(null);
        sendSubscriptions(socket);
        flushPendingAgentRunMessages(pendingAgentMessagesRef.current, (payload) => {
          if (socket.readyState !== WebSocket.OPEN) return false;
          try {
            socket.send(JSON.stringify(payload));
            return true;
          } catch {
            return false;
          }
        });
        stopConnectionTimers();
        if (config.mode === 'cloud') {
          heartbeatTimer = setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'heartbeat' }));
            }
          }, HEARTBEAT_INTERVAL_MS);
          watchdogTimer = setInterval(() => {
            if (Date.now() - lastMessageAt > STALE_CONNECTION_MS) {
              socket.close(4000, 'Agent WebSocket heartbeat timeout');
            }
          }, WATCHDOG_INTERVAL_MS);
        }
      };

      socket.onerror = () => {
        if (!disposed) setError('Agent WebSocket error');
      };

      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        stopConnectionTimers();
        setConnected(false);
        if (!disposed) scheduleReconnect(connect);
      };

      socket.onmessage = (message) => {
        if (disposed || socketRef.current !== socket) return;
        lastMessageAt = Date.now();
        const event = parseEvent(message.data);
        const type =
          stringField(event, 'type') ?? stringField(event, 'event_type');
        if (type === 'heartbeat' || type === 'pong') return;

        const cursor = eventCursor(event);
        if (cursor) {
          const previous = contextStateRef.current.conversationCursors.get(
            cursor.conversationId,
          );
          if (
            !previous ||
            cursor.timeUs > previous.timeUs ||
            (cursor.timeUs === previous.timeUs &&
              cursor.counter > previous.counter)
          ) {
            contextStateRef.current.conversationCursors.set(cursor.conversationId, cursor);
          }
        }
        const workspaceId = stringField(event, 'workspace_id');
        const eventId = stringField(event, 'event_id');
        if (workspaceId && eventId) contextStateRef.current.workspaceEventId = eventId;

        const key = socketEventKey(event);
        if (key && contextStateRef.current.seenEventKeys.has(key)) return;
        if (key) {
          contextStateRef.current.seenEventKeys.add(key);
          if (contextStateRef.current.seenEventKeys.size > MAX_EVENT_KEYS) {
            const oldestKey = contextStateRef.current.seenEventKeys.values().next().value;
            if (typeof oldestKey === 'string')
              contextStateRef.current.seenEventKeys.delete(oldestKey);
          }
        }
        pendingEventsRef.current.push(event);
        scheduleEventsFlush();
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      stopConnectionTimers();
      eventsFlushCancelRef.current?.();
      eventsFlushCancelRef.current = null;
      pendingEventsRef.current = [];
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [
    client,
    config.apiKey,
    config.localApiToken,
    config.mode,
    config.projectId,
    config.tenantId,
    config.workspaceId,
    contextRevision,
    enabled,
    scheduleEventsFlush,
  ]);

  return {
    connected,
    error,
    events,
    sendAgentMessage,
    respondToHitl,
  };
}

export function createAgentSocketContextState(): AgentSocketContextState {
  return {
    conversationCursors: new Map(),
    subscribedConversations: new Set(),
    workspaceEventId: null,
    seenEventKeys: new Set(),
  };
}

export function resetAgentSocketContextState(state: AgentSocketContextState): void {
  state.conversationCursors.clear();
  state.subscribedConversations.clear();
  state.workspaceEventId = null;
  state.seenEventKeys.clear();
}

export function transitionAgentSocketConversationSelection(
  state: AgentSocketContextState,
  conversationId: string | null,
): AgentSocketConversationTransition {
  const normalizedConversationId = conversationId?.trim() || null;
  const unsubscribeConversationIds = [...state.subscribedConversations].filter(
    (currentConversationId) => currentConversationId !== normalizedConversationId,
  );
  state.subscribedConversations.clear();
  if (normalizedConversationId) {
    state.subscribedConversations.add(normalizedConversationId);
  }
  return {
    unsubscribeConversationIds,
    subscribeConversationId: normalizedConversationId,
  };
}

export function conversationSubscriptionMessages(
  state: AgentSocketContextState,
): Record<string, unknown>[] {
  return [...state.subscribedConversations].map((conversationId) => {
    const cursor = state.conversationCursors.get(conversationId);
    return {
      type: 'subscribe',
      conversation_id: conversationId,
      ...(cursor
        ? {
            from_time_us: cursor.timeUs,
            from_counter: cursor.counter + 1,
          }
        : {}),
    };
  });
}

export function buildHitlSocketMessage(
  submission: HitlResponseSubmission,
): Record<string, unknown> {
  const { requestId, hitlType, responseData } = submission;
  switch (hitlType) {
    case 'clarification':
      return {
        type: 'clarification_respond',
        request_id: requestId,
        answer: responseData.answer,
      };
    case 'decision':
      return {
        type: 'decision_respond',
        request_id: requestId,
        decision: responseData.decision,
      };
    case 'env_var':
      return {
        type: 'env_var_respond',
        request_id: requestId,
        ...(responseData.values ? { values: responseData.values } : {}),
        ...(responseData.cancelled === true ? { cancelled: true } : {}),
        ...(responseData.timeout === true ? { timeout: true } : {}),
      };
    case 'permission': {
      const granted =
        typeof responseData.granted === 'boolean'
          ? responseData.granted
          : responseData.action === 'allow' ||
            responseData.action === 'allow_always';
      return {
        type: 'permission_respond',
        request_id: requestId,
        granted,
      };
    }
    case 'a2ui_action':
      return {
        type: 'a2ui_action_respond',
        request_id: requestId,
        action_name: responseData.action_name,
        source_component_id: responseData.source_component_id,
        context: responseData.context ?? {},
      };
  }
}

export function reconnectDelay(attempt: number): number {
  return Math.min(500 * 2 ** Math.max(0, attempt), 15_000);
}

export function eventCursor(event: AgentWsEvent): AgentEventCursor | null {
  const conversationId = stringField(event, 'conversation_id');
  const timeUs =
    numberField(event, 'event_time_us') ??
    numberField(event, 'time_us') ??
    numberField(event, 'eventTimeUs');
  const counter =
    numberField(event, 'event_counter') ??
    numberField(event, 'counter') ??
    numberField(event, 'eventCounter');
  if (!conversationId || timeUs === null || counter === null) return null;
  return { conversationId, timeUs, counter };
}

export function socketEventKey(event: AgentWsEvent): string | null {
  const eventId = stringField(event, 'event_id') ?? stringField(event, 'seq');
  if (eventId) return `event:${eventId}`;
  const cursor = eventCursor(event);
  if (!cursor) return null;
  return `cursor:${cursor.conversationId}:${cursor.timeUs}:${cursor.counter}`;
}

export function socketEventsSince<T>(events: readonly T[], previousHead: T | null): T[] {
  if (!events.length) return [];
  const boundaryIndex = previousHead === null ? -1 : events.indexOf(previousHead);
  const fresh = events.slice(0, boundaryIndex < 0 ? events.length : boundaryIndex);
  return fresh.reverse();
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

function stringField(
  value: Record<string, unknown>,
  key: string,
): string | null {
  const field = value[key];
  return typeof field === 'string' && field ? field : null;
}

function numberField(
  value: Record<string, unknown>,
  key: string,
): number | null {
  const field = value[key];
  return typeof field === 'number' && Number.isFinite(field) ? field : null;
}
