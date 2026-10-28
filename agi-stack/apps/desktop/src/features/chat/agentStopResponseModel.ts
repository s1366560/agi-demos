import type { AgentWsEvent } from '../../types';

export type AgentStopErrorCode =
  | 'socket_unavailable'
  | 'STOP_SESSION_FAILED'
  | 'SESSION_NOT_RUNNING';

export type AgentStopTarget = Readonly<{
  kind: 'local_run' | 'local_turn' | 'cloud';
  scopeKey: string;
  conversationId: string;
  runId?: string;
  revision?: number;
  messageId?: string;
}>;

export type AgentStopReceipt =
  | { status: 'cancel_requested' }
  | { status: 'cancelled' }
  | { status: 'rejected'; errorCode: AgentStopErrorCode };

export type AgentStopRequestState = {
  conversationId: string | null;
  status: 'idle' | 'stopping' | 'stopped' | 'error';
  errorCode: AgentStopErrorCode | null;
  target?: AgentStopTarget;
  requestId?: number;
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
  target?: AgentStopTarget,
  requestId?: number,
): AgentStopRequestState {
  const normalizedConversationId = conversationId.trim();
  if (!normalizedConversationId) return EMPTY_AGENT_STOP_REQUEST;
  return {
    conversationId: normalizedConversationId,
    status: sent ? 'stopping' : 'error',
    errorCode: sent ? null : 'socket_unavailable',
    ...(target ? { target } : {}),
    ...(requestId === undefined ? {} : { requestId }),
  };
}

export function agentStopTargetKey(target: AgentStopTarget | undefined): string {
  return target ? JSON.stringify([
    target.scopeKey, target.kind, target.conversationId, target.runId,
    target.revision, target.messageId,
  ]) : '';
}

export function applyAgentStopReceipt(
  state: AgentStopRequestState,
  requestId: number,
  target: AgentStopTarget | undefined,
  receipt: AgentStopReceipt,
): AgentStopRequestState {
  if (state.status !== 'stopping' || state.requestId !== requestId ||
      agentStopTargetKey(state.target) !== agentStopTargetKey(target)) return state;
  if (receipt.status === 'cancel_requested') return state;
  return receipt.status === 'cancelled'
    ? { ...state, status: 'stopped', errorCode: null }
    : { ...state, status: 'error', errorCode: receipt.errorCode };
}

export function applyAgentStopEvent(
  state: AgentStopRequestState,
  event: AgentWsEvent,
): AgentStopRequestState {
  if (state.status !== 'stopping' || !state.conversationId) return state;
  if (structuredString(event, ['conversation_id', 'conversationId']) !== state.conversationId) {
    return state;
  }
  if (state.target?.kind === 'local_run' &&
      structuredString(event, ['run_id', 'execution_id']) !== state.target.runId) return state;
  if (state.target?.kind === 'local_turn' &&
      structuredString(event, ['message_id', 'messageId']) !== state.target.messageId) return state;

  const eventType = structuredString(event, ['type', 'event_type']) ?? '';
  if (eventType === 'ack' && event.action === 'stop_session') {
    if (state.target?.kind !== 'cloud' && state.target &&
        structuredString(event, ['status']) !== 'cancelled') return state;
    return { ...state, status: 'stopped', errorCode: null };
  }
  if (eventType === 'cancelled' || eventType === 'run_status') {
    // The runtime emits {type: "cancelled", data: {run_id, status:
    // "cancelled"}}; the boolean flag form is a legacy alias.
    if (
      structuredString(event, ['status']) === 'cancelled' ||
      structuredBoolean(event, ['cancelled']) === true
    ) {
      return { ...state, status: 'stopped', errorCode: null };
    }
    return state;
  }
  if (eventType !== 'error') return state;

  const errorCode = structuredString(event, ['code']);
  if (!errorCode || !STOP_ERROR_CODES.has(errorCode as AgentStopErrorCode)) return state;
  return {
    ...state,
    status: 'error',
    errorCode: errorCode as AgentStopErrorCode,
  };
}

export function reconcileAgentStopScope(
  state: AgentStopRequestState,
  conversationId: string | null | undefined,
  target?: AgentStopTarget,
): AgentStopRequestState {
  const normalizedConversationId = conversationId?.trim() ?? '';
  return state.conversationId === normalizedConversationId &&
    agentStopTargetKey(state.target) === agentStopTargetKey(target)
    ? state
    : EMPTY_AGENT_STOP_REQUEST;
}

export function agentStopRequestSettlesStreaming(
  state: AgentStopRequestState,
  conversationId: string,
): boolean {
  return state.status === 'stopped' && state.conversationId === conversationId.trim();
}

export type AgentStopButtonInput = {
  socketConnected: boolean;
  status: AgentStopRequestState['status'];
};

/**
 * The stop control is disabled while a stop is in flight, and while the live
 * socket is disconnected (a click could only fail with `socket_unavailable`).
 * The click-time error feedback stays as a belt-and-suspenders fallback.
 */
export function agentStopResponseButtonDisabled(input: AgentStopButtonInput): boolean {
  return input.status === 'stopping' || !input.socketConnected;
}

export function agentStopResponseButtonLabelKey(input: AgentStopButtonInput): string {
  return input.status === 'stopping'
    ? 'session.stoppingResponse'
    : 'session.stopResponse';
}

export function agentStopResponseButtonTitleKey(input: AgentStopButtonInput): string {
  if (input.status === 'stopping') return 'session.stoppingResponse';
  return input.socketConnected
    ? 'session.stopResponse'
    : 'session.stopResponseDisconnectedHint';
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
