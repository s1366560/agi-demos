import { describe, expect, it } from 'vitest';

import { foldableTurns, foldTurns } from '../../../../plugins/business/agent/ui/signed/foldTurns';
import {
  hasBubble,
  timelineCount,
  type Thought,
  type TranscriptRow,
} from '../../../../plugins/business/agent/ui/signed/transcriptRows';
import type { InteractionEvent } from '../../../../plugins/business/agent/ui/signed/useInteractions';
import type { Message } from '../../../../plugins/business/agent/ui/signed/useChat';

const message = (id: string, role: Message['role']): TranscriptRow => ({
  kind: 'message',
  id,
  message: { id, role, content: id },
});
const thought = (id: string): TranscriptRow => ({ kind: 'thought', id, content: id });
const steps = (id: string): TranscriptRow => ({ kind: 'steps', id, steps: [] });

const rows: TranscriptRow[] = [
  steps('before-the-first-message'),
  message('u1', 'user_message'),
  thought('t1'),
  steps('s1'),
  message('a1', 'assistant_message'),
  message('u2', 'user_message'),
  steps('s2'),
  message('a2', 'assistant_message'),
  message('u3', 'user_message'),
];
const shown = (entries: ReturnType<typeof foldTurns>) =>
  entries.map((entry) => (entry.kind === 'row' ? entry.row.id : `folded(${entry.hiddenCount})`));

describe('folding the turns of the signed transcript', () => {
  it('leaves every row in place while no turn is folded', () => {
    expect(shown(foldTurns(rows, new Set()))).toEqual([
      'before-the-first-message',
      'u1',
      't1',
      's1',
      'a1',
      'u2',
      's2',
      'a2',
      'u3',
    ]);
  });

  it('folds what answers a user message up to the next one, and keeps the message', () => {
    const entries = foldTurns(rows, new Set(['u2']));

    expect(shown(entries)).toEqual([
      'before-the-first-message',
      'u1',
      't1',
      's1',
      'a1',
      'u2',
      'folded(2)',
      'u3',
    ]);
    expect(entries[6]).toEqual({ kind: 'folded', turnId: 'u2', hiddenCount: 2 });
  });

  it('lists the turns that have something to fold, by the message that opens them', () => {
    // Rows before the first message and a message without an answer are not a turn.
    expect([...foldableTurns(rows)]).toEqual([
      ['u1', 3],
      ['u2', 2],
    ]);
    expect(foldableTurns([]).size).toBe(0);
  });

  it('counts the rows of the transcript the way the original does', () => {
    const at = (eventTimeUs: number) => ({ eventTimeUs, eventCounter: 0 });
    const messages: Message[] = [
      { id: 'u1', role: 'user_message', content: 'hi', ...at(1) },
      { id: 'm1', role: 'assistant_message', content: 'done', ...at(9) },
    ];
    const events: InteractionEvent[] = [
      { id: 'a1', type: 'act', execution_id: 'e1', toolName: 'bash', ...at(2) },
      {
        id: 'p1',
        type: 'permission_asked',
        requestId: 'p',
        answered: true,
        granted: true,
        ...at(3),
      },
      // The answer to a request and a draft of a call are merged into what they belong to.
      { id: 'r1', type: 'permission_replied', requestId: 'p', granted: true, ...at(4) },
      {
        id: 'd1',
        type: 'act',
        execution_id: 'c1',
        call_id: 'c1',
        message_id: 'm',
        metadata: { sourceEventType: 'act_delta' },
        ...at(5),
      },
      {
        id: 'a2',
        type: 'act',
        execution_id: 'e2',
        call_id: 'c1',
        message_id: 'm',
        toolName: 'list',
        ...at(6),
      },
      { id: 'o1', type: 'observe', execution_id: 'e1', toolName: 'bash', ...at(7) },
      // Events that only update the conversation state still count.
      { id: 'k1', type: 'task_updated', ...at(8) },
    ];
    const thoughts: Thought[] = [{ id: 't1', content: 'reason', ...at(2) }];

    // u1, m1, t1, a1, p1, a2, o1 and k1: the reply and the draft are merged away.
    expect(timelineCount(messages, thoughts, events)).toBe(8);
    // Without the interactions capability, the text rows are what is known.
    expect(timelineCount(messages, thoughts, [])).toBe(3);
  });
});
