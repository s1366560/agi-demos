import type { AgentWsEvent } from '../../types';

export type AgentStopErrorCode =
  | 'socket_unavailable'
  | 'STOP_SESSION_FAILED'
  | 'SESSION_NOT_RUNNING';

export type AgentStopRequestState = {
  conversationId: string | null;
  status: 'idle' | 'stopping' | 'stopped' | 'error';
  errorCode: AgentStopErrorCode | null;
};

export const EMPTY_AGENT_STOP_REQUEST: AgentStopRequestState = {
  conversationId: null,
  status: 'idle',
  errorCode: null,
};

const STOP_ERROR_CODES = new Set<AgentStopErrorCode>([
  'STOP_SESSION_FAILED',
  'SESSION_NOT_RUNNING',
]);

export function beginAgentStopRequest(
  conversationId: string,
  sent: boolean,
): AgentStopRequestState {
  const normalizedConversationId = conversationId.trim();
  if (!normalizedConversationId) return EMPTY_AGENT_STOP_REQUEST;
  return {
    conversationId: normalizedConversationId,
    status: sent ? 'stopping' : 'error',
    errorCode: sent ? null : 'socket_unavailable',
  };
}

export function applyAgentStopEvent(
  state: AgentStopRequestState,
  event: AgentWsEvent,
): AgentStopRequestState {
  if (state.status !== 'stopping' || !state.conversationId) return state;
  if (structuredString(event, ['conversation_id', 'conversationId']) !== state.conversationId) {
    return state;
  }

  const eventType = structuredString(event, ['type', 'event_type']) ?? '';
  if (eventType === 'ack' && event.action === 'stop_session') {
    return settledAgentStopRequest(state.conversationId);
  }
  if (eventType === 'cancelled' && structuredBoolean(event, ['cancelled']) === true) {
    return settledAgentStopRequest(state.conversationId);
  }
  if (eventType !== 'error') return state;

  const errorCode = structuredString(event, ['code']);
  if (!errorCode || !STOP_ERROR_CODES.has(errorCode as AgentStopErrorCode)) return state;
  return {
    conversationId: state.conversationId,
    status: 'error',
    errorCode: errorCode as AgentStopErrorCode,
  };
}

export function reconcileAgentStopScope(
  state: AgentStopRequestState,
  conversationId: string | null | undefined,
): AgentStopRequestState {
  const normalizedConversationId = conversationId?.trim() ?? '';
  return state.conversationId === normalizedConversationId
    ? state
    : EMPTY_AGENT_STOP_REQUEST;
}

export function agentStopRequestSettlesStreaming(
  state: AgentStopRequestState,
  conversationId: string,
): boolean {
  return state.status === 'stopped' && state.conversationId === conversationId.trim();
}

function settledAgentStopRequest(conversationId: string): AgentStopRequestState {
  return {
    conversationId,
    status: 'stopped',
    errorCode: null,
  };
}

function structuredString(
  event: Record<string, unknown>,
  keys: readonly string[],
): string | null {
  for (const key of keys) {
    const value = event[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  for (const nestedKey of ['data', 'payload']) {
    const nested = event[nestedKey];
    if (nested && typeof nested === 'object') {
      const value = structuredString(nested as Record<string, unknown>, keys);
      if (value) return value;
    }
  }
  return null;
}

function structuredBoolean(
  event: Record<string, unknown>,
  keys: readonly string[],
): boolean | null {
  for (const key of keys) {
    const value = event[key];
    if (typeof value === 'boolean') return value;
  }
  for (const nestedKey of ['data', 'payload']) {
    const nested = event[nestedKey];
    if (nested && typeof nested === 'object') {
      const value = structuredBoolean(nested as Record<string, unknown>, keys);
      if (value !== null) return value;
    }
  }
  return null;
}
