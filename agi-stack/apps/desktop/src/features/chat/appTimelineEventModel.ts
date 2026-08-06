import {
  protocolClientMessageId,
  protocolStreamMessageId,
} from './agentEventIdentityModel';
import type { AgentTaskSignalStatus } from './agentTaskSignalModel';
import {
  applyArtifactCanvasStreamEvent,
  emptyArtifactCanvasState,
} from './artifactCanvasEventModel';
import {
  eventScopedStreamMessageId,
  mergeAgentSendAcknowledgement,
  mergeArtifactStreamItem,
  mergeAssistantCompletionEvent,
  mergeAssistantTextStreamChunk,
  mergeConversationTimelineItems,
  mergeCostUpdateEvent,
  mergeThoughtStreamChunk,
  mergeToolStreamItem,
  shouldSkipLiveTimelineEvent,
} from './chatTimelineModel';
import { readConversationTitleStreamEvent } from './conversationTitleEventModel';
import { applyHitlResponseStreamEvent } from './hitlResponseEventModel';
import type {
  AgentInputFileMetadata,
  AgentTimelineItem,
  ConversationTimelineState,
} from '../../types';
import {
  numberField,
  objectField,
  readStringField,
  readTextField,
} from '../../utils/format';

export function agentTaskUpdateFromSocketEvent(event: unknown): null | {
  conversationId: string;
  messageId?: string;
  executionMessageId?: string;
  status: AgentTaskSignalStatus;
  detail: string;
  eventType: string;
} {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const conversationId = readStringField(payload, 'conversation_id');
  if (!conversationId) return null;

  const type =
    readStringField(payload, 'type') ??
    readStringField(payload, 'event_type') ??
    'event';
  const action = readStringField(payload, 'action');
  const eventType = action ? `${type}:${action}` : type;
  const messageId = socketMessageId(payload);

  if (type === 'ack' && action === 'send_message') {
    return {
      conversationId,
      messageId,
      executionMessageId:
        readStringField(payload, 'execution_message_id') ??
        readStringField(payload, 'executionMessageId'),
      status: 'acknowledged',
      detail: 'Agent acknowledged the task over WebSocket.',
      eventType,
    };
  }

  if (type === 'user_message' || type === 'message') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent conversation received the task message.',
      eventType,
    };
  }

  if (
    type === 'act' ||
    type === 'observe' ||
    type.startsWith('text_') ||
    type.startsWith('thought_')
  ) {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent is streaming updates for this task.',
      eventType,
    };
  }

  if (type === 'assistant_message') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent response was added to the conversation.',
      eventType,
    };
  }

  if (type === 'complete') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent run completed.',
      eventType,
    };
  }

  if (
    type.toLowerCase().includes('error') ||
    action?.toLowerCase().includes('error')
  ) {
    const errorDetail = socketErrorDetail(payload);
    return {
      conversationId,
      messageId,
      status: 'failed',
      detail: errorDetail
        ? `Agent reported an error for this task: ${errorDetail}`
        : 'Agent reported an error for this task.',
      eventType,
    };
  }

  return null;
}

export function socketErrorDetail(
  payload: Record<string, unknown>,
): string | undefined {
  const direct =
    readStringField(payload, 'detail') ??
    readStringField(payload, 'message') ??
    readStringField(payload, 'error') ??
    readStringField(payload, 'reason');
  if (direct) return direct;

  for (const key of [
    'payload',
    'data',
    'error',
    'detail',
    'message',
    'reason',
  ]) {
    const nested = payload[key];
    if (nested && typeof nested === 'object') {
      const nestedDetail = socketErrorDetail(nested as Record<string, unknown>);
      if (nestedDetail) return nestedDetail;
    }
  }

  return undefined;
}

export function socketMessageId(
  payload: Record<string, unknown>,
): string | undefined {
  return protocolClientMessageId(payload);
}

export function mergeTimelineItems(
  existing: AgentTimelineItem[],
  incoming: AgentTimelineItem[],
): AgentTimelineItem[] {
  return mergeConversationTimelineItems(existing, incoming);
}

export function timelineCursorFromFirst(
  items: AgentTimelineItem[],
): ConversationTimelineState['firstCursor'] {
  const first = items[0];
  if (!first) return null;
  return { timeUs: first.eventTimeUs, counter: first.eventCounter };
}

export function timelineCursorFromLast(
  items: AgentTimelineItem[],
): ConversationTimelineState['lastCursor'] {
  const last = items[items.length - 1];
  if (!last) return null;
  return { timeUs: last.eventTimeUs, counter: last.eventCounter };
}

export function optimisticUserTimelineItem(
  messageId: string,
  content: string,
  forcedSkillName?: string,
  fileMetadata?: readonly AgentInputFileMetadata[],
): AgentTimelineItem {
  const nowMs = Date.now();
  return {
    id: `optimistic-user-${messageId}`,
    type: 'user_message',
    eventTimeUs: nowMs * 1000,
    eventCounter: 0,
    timestamp: nowMs,
    message_id: messageId,
    role: 'user',
    content,
    metadata: {
      optimistic: true,
      ...(forcedSkillName?.trim()
        ? { forcedSkillName: forcedSkillName.trim() }
        : {}),
      ...(fileMetadata?.length ? { fileMetadata: [...fileMetadata] } : {}),
    },
  };
}

export function timelineItemFromSocketEvent(
  event: unknown,
): AgentTimelineItem | null {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const type =
    readStringField(payload, 'type') ?? readStringField(payload, 'event_type');
  if (
    !type ||
    shouldSkipLiveTimelineEvent(type, readStringField(payload, 'action'))
  )
    return null;
  const data =
    objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
  const nowMs = Date.now();
  const eventTimeUs =
    numberField(payload, 'time_us') ??
    numberField(payload, 'event_time_us') ??
    numberField(payload, 'eventTimeUs') ??
    nowMs * 1000;
  const eventCounter =
    numberField(payload, 'counter') ??
    numberField(payload, 'event_counter') ??
    numberField(payload, 'eventCounter') ??
    0;
  const messageId =
    socketMessageId(payload) ??
    readStringField(data, 'message_id') ??
    readStringField(data, 'messageId');
  const executionMessageId =
    readStringField(data, 'execution_message_id') ??
    readStringField(data, 'executionMessageId') ??
    readStringField(payload, 'execution_message_id') ??
    readStringField(payload, 'executionMessageId');
  const item: AgentTimelineItem = {
    id: `${type}-${eventTimeUs}-${eventCounter}`,
    type,
    eventTimeUs,
    eventCounter,
    timestamp: Math.floor(eventTimeUs / 1000),
    message_id: messageId ?? null,
    payload: data,
  };

  if (type === 'user_message' || type === 'assistant_message') {
    item.role = type === 'user_message' ? 'user' : 'assistant';
    if (executionMessageId ?? messageId) {
      item.executionMessageId = executionMessageId ?? messageId;
    }
    item.content =
      readStringField(data, 'content') ??
      readStringField(data, 'answer') ??
      readStringField(payload, 'message') ??
      '';
  } else if (type === 'thought') {
    item.content =
      readStringField(data, 'thought') ??
      readStringField(data, 'content') ??
      '';
  } else if (type === 'act' || type === 'act_delta') {
    item.type = 'act';
    item.toolName =
      readStringField(data, 'tool_name') ??
      readStringField(data, 'toolName') ??
      '';
    item.toolInput =
      data.tool_input ?? data.toolInput ?? data.accumulated_arguments ?? {};
  } else if (type === 'observe') {
    item.toolName =
      readStringField(data, 'tool_name') ??
      readStringField(data, 'toolName') ??
      '';
    item.toolInput = data.tool_input ?? data.toolInput;
    item.toolOutput =
      data.observation ?? data.tool_output ?? data.toolOutput ?? '';
    item.error = readStringField(data, 'error');
    item.isError = Boolean(data.is_error ?? data.isError ?? item.error);
  } else if (type === 'error') {
    item.content = socketErrorDetail(payload) ?? 'Agent run failed.';
    item.error = item.content;
    item.isError = true;
  }

  const display = objectField(data, 'display');
  if (display) item.display = display as AgentTimelineItem['display'];
  const fileMetadata =
    objectField(data, 'fileMetadata') ?? objectField(data, 'file_metadata');
  if (fileMetadata)
    item.fileMetadata = fileMetadata as AgentTimelineItem['fileMetadata'];
  const metadata = objectField(data, 'metadata');
  if (metadata) item.metadata = metadata;

  return item;
}

export function mergeLiveTimelineEvent(
  existing: AgentTimelineItem[],
  event: unknown,
): AgentTimelineItem[] {
  if (!event || typeof event !== 'object') return existing;
  const payload = event as Record<string, unknown>;
  const type =
    readStringField(payload, 'type') ?? readStringField(payload, 'event_type');
  if (type === 'ack' && readStringField(payload, 'action') === 'send_message') {
    const clientMessageId = socketMessageId(payload);
    const executionMessageId =
      readStringField(payload, 'execution_message_id') ??
      readStringField(payload, 'executionMessageId');
    return clientMessageId && executionMessageId
      ? mergeAgentSendAcknowledgement(
          existing,
          clientMessageId,
          executionMessageId,
        )
      : existing;
  }
  if (type === 'cost_update') {
    const data =
      objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
    return mergeCostUpdateEvent(existing, data);
  }
  if (type === 'text_start' || type === 'text_delta' || type === 'text_end') {
    return mergeStreamingTextEvent(existing, payload, type);
  }
  if (type === 'assistant_message') {
    const item = timelineItemFromSocketEvent(event);
    if (!item) return existing;
    const data =
      objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
    const messageId =
      item.message_id ??
      eventScopedStreamMessageId(
        readStringField(payload, 'conversation_id') ?? 'agent',
        type,
        item.eventTimeUs,
        item.eventCounter,
      );
    return mergeAssistantCompletionEvent(existing, {
      messageId,
      content: item.content ?? '',
      eventTimeUs: item.eventTimeUs,
      eventCounter: item.eventCounter,
      payload: data,
      metadata: item.metadata ?? undefined,
      artifacts: Array.isArray(data.artifacts) ? data.artifacts : undefined,
    });
  }
  if (type === 'complete') {
    const data =
      objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
    const nowMs = Date.now();
    const eventTimeUs =
      numberField(payload, 'time_us') ??
      numberField(payload, 'event_time_us') ??
      numberField(payload, 'eventTimeUs') ??
      nowMs * 1000;
    const eventCounter =
      numberField(payload, 'counter') ??
      numberField(payload, 'event_counter') ??
      numberField(payload, 'eventCounter') ??
      0;
    const executionSummary =
      objectField(data, 'execution_summary') ??
      objectField(data, 'executionSummary');
    const traceUrl =
      readStringField(data, 'trace_url') ?? readStringField(data, 'traceUrl');
    const artifacts = Array.isArray(data.artifacts)
      ? data.artifacts
      : undefined;
    const metadata = {
      ...(traceUrl ? { traceUrl } : {}),
      ...(executionSummary ? { executionSummary } : {}),
      ...(artifacts?.length ? { artifacts } : {}),
    };
    const explicitMessageId = streamingMessageId(payload);
    const messageId =
      explicitMessageId ??
      eventScopedStreamMessageId(
        readStringField(payload, 'conversation_id') ?? 'agent',
        type,
        eventTimeUs,
        eventCounter,
      );
    return mergeAssistantCompletionEvent(existing, {
      messageId,
      content: readTextField(data, 'content') ?? '',
      eventTimeUs,
      eventCounter,
      turnScopedFallback: !explicitMessageId,
      payload: data,
      metadata,
      artifacts,
    });
  }
  if (
    type === 'thought_start' ||
    type === 'thought_delta' ||
    type === 'thought'
  ) {
    const data =
      objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
    const nowMs = Date.now();
    const eventTimeUs =
      numberField(payload, 'time_us') ??
      numberField(payload, 'event_time_us') ??
      numberField(payload, 'eventTimeUs') ??
      nowMs * 1000;
    const eventCounter =
      numberField(payload, 'counter') ??
      numberField(payload, 'event_counter') ??
      numberField(payload, 'eventCounter') ??
      0;
    const content =
      readTextField(data, type === 'thought_delta' ? 'delta' : 'thought') ??
      readTextField(data, 'content') ??
      '';
    const explicitMessageId = streamingMessageId(payload);
    if (!explicitMessageId && type !== 'thought') return existing;
    const messageId =
      explicitMessageId ??
      eventScopedStreamMessageId(
        readStringField(payload, 'conversation_id') ?? 'agent',
        type,
        eventTimeUs,
        eventCounter,
      );
    return mergeThoughtStreamChunk(existing, {
      kind:
        type === 'thought_start'
          ? 'start'
          : type === 'thought_delta'
            ? 'delta'
            : 'complete',
      messageId,
      content,
      eventTimeUs,
      eventCounter,
      payload: data,
    });
  }
  const titleEvent = readConversationTitleStreamEvent(event);
  if (titleEvent.handled) return existing;
  const artifactCanvasResult = applyArtifactCanvasStreamEvent(emptyArtifactCanvasState(), event);
  if (artifactCanvasResult.handled && type !== 'canvas_updated')
    return existing;
  const hitlResponse = applyHitlResponseStreamEvent(existing, event);
  if (hitlResponse.handled) return hitlResponse.items;
  const timeline = existing;
  const item = timelineItemFromSocketEvent(event);
  if (
    item &&
    [
      'artifact_created',
      'artifact_ready',
      'artifact_error',
      'artifacts_batch',
    ].includes(item.type)
  ) {
    return mergeArtifactStreamItem(timeline, item);
  }
  if (item && (type === 'act_delta' || type === 'act' || type === 'observe')) {
    return mergeToolStreamItem(
      timeline,
      item,
      type === 'act_delta' ? 'delta' : type,
    );
  }
  return item ? mergeTimelineItems(timeline, [item]) : timeline;
}

export function mergeStreamingTextEvent(
  existing: AgentTimelineItem[],
  payload: Record<string, unknown>,
  type: 'text_start' | 'text_delta' | 'text_end',
): AgentTimelineItem[] {
  const data =
    objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
  const nowMs = Date.now();
  const eventTimeUs =
    numberField(payload, 'time_us') ??
    numberField(payload, 'event_time_us') ??
    numberField(payload, 'eventTimeUs') ??
    nowMs * 1000;
  const eventCounter =
    numberField(payload, 'counter') ??
    numberField(payload, 'event_counter') ??
    numberField(payload, 'eventCounter') ??
    0;
  const explicitMessageId = streamingMessageId(payload);
  if (!explicitMessageId && type !== 'text_end') return existing;
  const messageId =
    explicitMessageId ??
    eventScopedStreamMessageId(
      readStringField(payload, 'conversation_id') ?? 'agent',
      type,
      eventTimeUs,
      eventCounter,
    );
  const content =
    (type === 'text_end'
      ? (readTextField(data, 'full_text') ?? readTextField(data, 'fullText'))
      : readTextField(data, 'delta')) ??
    readTextField(data, 'text') ??
    readTextField(data, 'content') ??
    '';
  return mergeAssistantTextStreamChunk(existing, {
    kind:
      type === 'text_start'
        ? 'start'
        : type === 'text_delta'
          ? 'delta'
          : 'complete',
    messageId,
    content,
    eventTimeUs,
    eventCounter,
    payload: data,
  });
}

export function streamingMessageId(
  payload: Record<string, unknown>,
): string | undefined {
  return protocolStreamMessageId(payload);
}
