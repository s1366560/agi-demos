import type { AgentTimelineItem, DesktopRun, RunControlOutcome, RuntimeMode } from '../../types';
import type { AgentTaskSignal } from './agentTaskSignalModel';
import type { AgentStopReceipt, AgentStopTarget } from './agentStopResponseModel';

export function composerStopMessageId(
  conversationId: string,
  items: readonly AgentTimelineItem[],
  signals: readonly AgentTaskSignal[],
): string | undefined {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.role === 'user' || item.type === 'user_message') {
      const messageId = item.executionMessageId?.trim() || item.message_id?.trim();
      if (messageId) return messageId;
      break;
    }
  }
  const candidates = signals.filter((signal) => signal.conversationId === conversationId &&
    signal.status === 'acknowledged' && signal.eventType !== 'complete' && signal.messageId?.trim());
  return candidates.length === 1 ? candidates[0].messageId?.trim() : undefined;
}

export function composerStopTarget(input: {
  mode: RuntimeMode;
  scopeKey: string;
  conversationId: string;
  run: DesktopRun | null;
  messageId?: string;
}): AgentStopTarget | undefined {
  const conversationId = input.conversationId.trim();
  if (!conversationId) return undefined;
  const base = { scopeKey: input.scopeKey, conversationId };
  if (input.mode === 'cloud') {
    return { ...base, kind: 'cloud', messageId: input.messageId };
  }
  if (input.run?.conversation_id === conversationId && input.run.status === 'running' &&
      input.run.id.trim() && Number.isSafeInteger(input.run.revision) && input.run.revision >= 0) {
    return { ...base, kind: 'local_run', runId: input.run.id, revision: input.run.revision,
      messageId: input.run.message_id };
  }
  const messageId = input.messageId?.trim();
  if (messageId && (!input.run || input.run.message_id !== messageId)) {
    return { ...base, kind: 'local_turn', messageId };
  }
  return undefined;
}

/** A target is captured by the rendered control; rejection never looks up a newer run. */
export async function dispatchComposerStop(
  target: AgentStopTarget,
  operations: {
    cancelRun: (runId: string, revision: number) => Promise<RunControlOutcome>;
    stopSession: (conversationId: string, target?: { messageId: string }) => boolean;
    onRunOutcome?: (outcome: RunControlOutcome) => void;
  },
): Promise<AgentStopReceipt> {
  const { kind, conversationId, runId, revision, messageId } = target;
  if (kind !== 'local_run') {
    if (kind === 'local_turn' && !messageId?.trim()) {
      return { status: 'rejected', errorCode: 'SESSION_NOT_RUNNING' };
    }
    const sent = kind === 'cloud'
      ? operations.stopSession(conversationId)
      : operations.stopSession(conversationId, { messageId: messageId! });
    return sent ? { status: 'cancel_requested' }
      : { status: 'rejected', errorCode: 'socket_unavailable' };
  }
  if (!runId?.trim() || revision === undefined || !Number.isSafeInteger(revision) || revision < 0) {
    return { status: 'rejected', errorCode: 'SESSION_NOT_RUNNING' };
  }
  try {
    const outcome = await operations.cancelRun(runId, revision);
    if (!outcome.accepted || outcome.run.id !== runId ||
        outcome.run.conversation_id !== conversationId) {
      return { status: 'rejected', errorCode: 'STOP_SESSION_FAILED' };
    }
    operations.onRunOutcome?.(outcome);
    if (outcome.run.status === 'cancelled') return { status: 'cancelled' };
    return outcome.status === 'cancel_requested'
      ? { status: 'cancel_requested' }
      : { status: 'rejected', errorCode: 'SESSION_NOT_RUNNING' };
  } catch {
    return { status: 'rejected', errorCode: 'STOP_SESSION_FAILED' };
  }
}
