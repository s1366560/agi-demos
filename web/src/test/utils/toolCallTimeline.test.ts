import { describe, expect, it } from 'vitest';

import { coalesceToolCallDrafts } from '../../utils/toolCallTimeline';

import type { ActEvent, TimelineEvent } from '../../types/agent';

const act = (id: string, fields: Partial<ActEvent> = {}): ActEvent => ({
  id,
  type: 'act',
  toolName: 'Read',
  toolInput: { path: 'calc.py' },
  eventTimeUs: 1000,
  eventCounter: 0,
  timestamp: 1,
  ...fields,
});

describe('coalesceToolCallDrafts', () => {
  it('replaces a replayed argument draft with its execution using the model call identity', () => {
    const draft = act('draft', {
      call_id: 'call-1',
      execution_id: 'call-1',
      metadata: { sourceEventType: 'act_delta', status: 'preparing' },
    });
    const execution = act('execution', { call_id: 'call-1', execution_id: 'execution-1' });

    expect(coalesceToolCallDrafts([draft, execution])).toEqual([execution]);
    expect(coalesceToolCallDrafts([execution, draft])).toEqual([execution]);
  });

  it('keeps the latest draft while retaining independent calls with identical tools and arguments', () => {
    const draft = act('draft', {
      call_id: 'call-1',
      metadata: { sourceEventType: 'act_delta' },
    });
    const latest = { ...draft, id: 'latest', toolInput: { path: 'calc.py', offset: 10 } };
    const independent = act('independent', { call_id: 'call-2', execution_id: 'execution-2' });

    expect(coalesceToolCallDrafts([draft, latest, independent])).toEqual([latest, independent]);
  });

  it('does not merge distinct execution IDs or calls in separate messages', () => {
    const first = act('first', { call_id: 'call-1', execution_id: 'execution-1' });
    const second = act('second', { call_id: 'call-1', execution_id: 'execution-2' });
    const draft = act('draft', {
      call_id: 'call-1',
      message_id: 'message-2',
      metadata: { sourceEventType: 'act_delta' },
    });

    expect(coalesceToolCallDrafts([first, second, draft])).toEqual([first, second, draft]);
  });

  it('uses user-turn boundaries when historical events have no message ID', () => {
    const first = act('first', { call_id: 'call-1', execution_id: 'execution-1' });
    const boundary = {
      id: 'user-2',
      type: 'user_message',
      role: 'user',
      content: 'Read again',
      eventTimeUs: 2000,
      eventCounter: 0,
      timestamp: 2,
    } satisfies TimelineEvent;
    const draft = act('draft', {
      call_id: 'call-1',
      metadata: { sourceEventType: 'act_delta' },
    });

    expect(coalesceToolCallDrafts([first, boundary, draft])).toEqual([first, boundary, draft]);
  });

  it('retains unidentifiable drafts rather than guessing from a tool name', () => {
    const draft = act('draft', { metadata: { sourceEventType: 'act_delta' } });
    const execution = act('execution', { execution_id: 'execution-1' });
    expect(coalesceToolCallDrafts([draft, execution])).toEqual([draft, execution]);
  });

  it('retains a draft with a distinct explicit execution ID even when the call ID matches', () => {
    const draft = act('draft', {
      call_id: 'call-1',
      execution_id: 'execution-retry',
      metadata: { sourceEventType: 'act_delta' },
    });
    const execution = act('execution', { call_id: 'call-1', execution_id: 'execution-1' });
    expect(coalesceToolCallDrafts([draft, execution])).toEqual([draft, execution]);
  });
});
