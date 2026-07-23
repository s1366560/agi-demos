export type AgentTaskSignalStatus = 'saving' | 'queued' | 'acknowledged' | 'failed';

export type AgentTaskSignal = {
  id: string;
  content: string;
  status: AgentTaskSignalStatus;
  detail: string;
  createdAt: string;
  conversationId?: string;
  messageId?: string;
  eventType?: string;
};

export type AgentTaskSignalUpdate = {
  conversationId: string;
  messageId?: string;
  executionMessageId?: string;
  status: AgentTaskSignalStatus;
  detail: string;
  eventType: string;
};

/**
 * Reconcile transport state only through an explicit client or execution ID.
 * Falling back to the latest signal can apply a concurrent turn's completion
 * or failure to the wrong task.
 */
export function reconcileAgentTaskSignals(
  current: AgentTaskSignal[],
  update: AgentTaskSignalUpdate,
): AgentTaskSignal[] {
  if (!update.messageId) return current;
  const targetIndex = current.findIndex(
    (signal) =>
      signal.conversationId === update.conversationId &&
      signal.status !== 'failed' &&
      signal.messageId === update.messageId,
  );
  if (targetIndex < 0) return current;
  if (update.eventType === 'complete') {
    return current.filter((_, index) => index !== targetIndex);
  }
  return current.map((signal, index) =>
    index === targetIndex
      ? {
          ...signal,
          messageId: update.executionMessageId ?? update.messageId,
          status: update.status,
          detail: update.detail,
          eventType: update.eventType,
        }
      : signal,
  );
}
