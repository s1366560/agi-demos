import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  bindTimelineBufferDeps,
  clearAllTimelineBuffers,
  flushTimelineBufferSync,
  queueTimelineEvent,
} from '../../../stores/agent/deltaBuffers';
import { createDefaultConversationState } from '../../../types/conversationState';

import type { AgentEvent } from '../../../types/agent';

afterEach(() => clearAllTimelineBuffers());

describe('timeline commit buffer', () => {
  it('upgrades a replayed draft and ignores the repeated stream frame without losing a separate call', () => {
    let state = createDefaultConversationState();
    state.timeline = [
      {
        id: 'draft',
        type: 'act',
        toolName: 'Read',
        toolInput: {},
        eventTimeUs: 1000,
        eventCounter: 0,
        timestamp: 1,
        call_id: 'call-1',
        message_id: 'message-1',
        execution_id: 'call-1',
        metadata: { sourceEventType: 'act_delta' },
      },
    ];
    const update = vi.fn((_id, patch) => {
      state = { ...state, ...patch };
    });
    bindTimelineBufferDeps('conversation-1', {
      getConversationState: () => state,
      updateConversationState: update,
    });
    const execution = {
      type: 'act',
      data: {
        tool_name: 'Read',
        tool_input: { path: 'calc.py' },
        call_id: 'call-1',
        message_id: 'message-1',
        tool_execution_id: 'execution-1',
        event_time_us: 2000,
        event_counter: 0,
      },
    } satisfies AgentEvent<unknown>;
    queueTimelineEvent('conversation-1', execution);
    queueTimelineEvent('conversation-1', execution);
    queueTimelineEvent('conversation-1', {
      ...execution,
      data: {
        ...execution.data,
        call_id: 'call-2',
        tool_execution_id: 'execution-2',
        event_time_us: 3000,
      },
    });
    flushTimelineBufferSync('conversation-1');

    expect(state.timeline).toHaveLength(2);
    expect(state.timeline).toMatchObject([
      { type: 'act', call_id: 'call-1', execution_id: 'execution-1' },
      { type: 'act', call_id: 'call-2', execution_id: 'execution-2' },
    ]);
    expect(update).toHaveBeenCalledTimes(1);
  });
});
