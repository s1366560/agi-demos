import { describe, expect, it } from 'vitest';

import {
  hasBubble,
  latestPosition,
  transcriptRows,
  type Thought,
} from '../../../../plugins/business/agent/ui/signed/transcriptRows';
import type { InteractionEvent } from '../../../../plugins/business/agent/ui/signed/useInteractions';
import type { Message } from '../../../../plugins/business/agent/ui/signed/useChat';

const at = (time: number, counter = 0) => ({ eventTimeUs: time, eventCounter: counter });
const message = (id: string, role: Message['role'], position?: object): Message => ({
  id,
  role,
  content: id,
  ...position,
});
const thought = (id: string, position?: object, after?: [number, number]): Thought => ({
  id,
  content: id,
  ...position,
  ...(after ? { after } : {}),
});
const act = (id: string, position: object, extra: object = {}): InteractionEvent => ({
  id,
  type: 'act',
  execution_id: `exec-${id}`,
  call_id: `call-${id}`,
  toolName: 'bash',
  toolInput: { command: 'pwd' },
  ...position,
  ...extra,
});
const observe = (id: string, actId: string, position: object): InteractionEvent => ({
  id,
  type: 'observe',
  execution_id: `exec-${actId}`,
  call_id: `call-${actId}`,
  toolName: 'bash',
  toolOutput: '/workspace',
  isError: false,
  ...position,
});
const asked = (id: string, position: object, answered: boolean): InteractionEvent => ({
  id,
  type: 'permission_asked',
  requestId: `perm-${id}`,
  toolName: 'bash',
  riskLevel: 'medium',
  description: 'Run bash',
  answered,
  ...(answered ? { granted: true } : {}),
  ...position,
});

const kinds = (rows: { kind: string; id: string }[]) => rows.map((row) => `${row.kind}:${row.id}`);

describe('signed chat transcript rows', () => {
  it('orders a turn as it happened: reasoning, tool steps, messages and answered permissions', () => {
    const rows = transcriptRows(
      [
        message('u1', 'user_message', at(10)),
        message('m1', 'assistant_message', at(60)),
        message('m2', 'assistant_message', at(200)),
      ],
      [thought('t1', at(20))],
      [
        act('a1', at(30, 0), { timestamp: 30, execution: { status: 'success', duration: 50 } }),
        asked('p1', at(70), true),
        observe('o1', 'a1', at(80, 0)),
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'thought:t1',
      'steps:steps:exec-a1',
      'message:m1',
      'event:p1',
      'message:m2',
    ]);
    const steps = rows[2];
    expect(steps.kind).toBe('steps');
    if (steps.kind !== 'steps') return;
    // The result arrives after the message in the timeline and still completes its step.
    expect(steps.steps).toEqual([
      expect.objectContaining({
        id: 'exec-a1',
        toolName: 'bash',
        status: 'success',
        input: { command: 'pwd' },
        output: '/workspace',
      }),
    ]);
  });

  it('keeps a tool call without a result running', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10))],
      [],
      [act('a1', at(30), { timestamp: 30 })]
    );

    const steps = rows[1];
    expect(steps.kind).toBe('steps');
    if (steps.kind !== 'steps') return;
    expect(steps.steps[0]).toMatchObject({ id: 'exec-a1', status: 'running', output: undefined });
  });

  it('leaves a request that is still waiting to the panel and still ends the steps before it', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        act('a1', at(20), { timestamp: 20 }),
        observe('o1', 'a1', at(25)),
        asked('waiting', at(30), false),
        act('a2', at(40), { timestamp: 40 }),
        observe('o2', 'a2', at(45)),
        { id: 'c1', type: 'canvas_updated', block_id: 'b', ...at(50) },
        { id: 'z1', type: 'act', toolName: 'late' },
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'steps:steps:exec-a1',
      'steps:steps:exec-a2',
      'message:m1',
    ]);
  });

  it('hides permissions that were allowed automatically and keeps the answered ones', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        { ...asked('automatic', at(20), true), autoApproved: true },
        asked('decided', at(30), true),
        { ...asked('denied', at(40), true), granted: false },
        asked('waiting', at(50), false),
      ]
    );

    expect(kinds(rows)).toEqual(['message:u1', 'event:decided', 'event:denied', 'message:m1']);
  });

  it('keeps the tool steps of a turn together across an automatically allowed permission', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        act('a1', at(20), { timestamp: 20 }),
        observe('o1', 'a1', at(25)),
        { ...asked('automatic', at(30), true), autoApproved: true },
        act('a2', at(40), { timestamp: 40 }),
        observe('o2', 'a2', at(45)),
      ]
    );

    expect(kinds(rows)).toEqual(['message:u1', 'steps:steps:exec-a1', 'message:m1']);
    const steps = rows[1];
    expect(steps.kind === 'steps' && steps.steps.map((step) => step.id)).toEqual([
      'exec-a1',
      'exec-a2',
    ]);
  });

  it('ends a group of tool steps at an event that is not drawn', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        act('a1', at(20), { timestamp: 20 }),
        observe('o1', 'a1', at(25)),
        act('a2', at(30), { timestamp: 30 }),
        observe('o2', 'a2', at(35)),
        { id: 'k1', type: 'task_updated', ...at(36) },
        act('a3', at(40), { timestamp: 40 }),
        observe('o3', 'a3', at(45)),
        // Events that only update the conversation state do not end a group.
        { id: 's1', type: 'selection_trace', ...at(46) },
        act('a4', at(50), { timestamp: 50 }),
        observe('o4', 'a4', at(55)),
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'steps:steps:exec-a1',
      'steps:steps:exec-a3',
      'message:m1',
    ]);
    const last = rows[2];
    expect(last.kind === 'steps' && last.steps.map((step) => step.id)).toEqual([
      'exec-a3',
      'exec-a4',
    ]);
  });

  it('shows a request with the answer that was recorded as its own event', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        {
          id: 'p1',
          type: 'permission_asked',
          requestId: 'perm-1',
          toolName: 'bash',
          description: 'Run bash',
          ...at(20),
        },
        { id: 'r1', type: 'permission_replied', requestId: 'perm-1', granted: true, ...at(30) },
        { id: 'p2', type: 'permission_asked', requestId: 'perm-2', toolName: 'bash', ...at(40) },
        {
          id: 'r2',
          type: 'permission_replied',
          requestId: 'perm-2',
          granted: true,
          autoApproved: true,
          ...at(50),
        },
        { id: 'p3', type: 'permission_asked', requestId: 'perm-3', toolName: 'bash', ...at(60) },
        { id: 'r3', type: 'permission_replied', requestId: 'perm-3', granted: false, ...at(70) },
      ]
    );

    expect(kinds(rows)).toEqual(['message:u1', 'event:p1', 'event:p3', 'message:m1']);
    const allowed = rows[1];
    const denied = rows[2];
    // The card reads the answer, and the answer itself is not a second card.
    expect(allowed.kind === 'event' && allowed.event).toMatchObject({
      id: 'p1',
      type: 'permission_asked',
      requestId: 'perm-1',
      answered: true,
      granted: true,
    });
    expect(denied.kind === 'event' && denied.event).toMatchObject({
      id: 'p3',
      answered: true,
      granted: false,
    });
  });

  it('shows an error and the answered requests of a turn where they happened', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        act('a1', at(20), { timestamp: 20 }),
        observe('o1', 'a1', at(25)),
        {
          id: 'e1',
          type: 'error',
          message: 'model override has no provider route',
          code: 'route',
          ...at(30),
        },
        {
          id: 'd1',
          type: 'decision_asked',
          requestId: 'decision-1',
          question: 'Which?',
          options: [],
          answered: true,
          decision: 'Full report',
          ...at(40),
        },
        {
          id: 'v1',
          type: 'env_var_requested',
          requestId: 'env-1',
          toolName: 'bash',
          fields: [],
          answered: true,
          providedVariables: ['TOKEN'],
          ...at(50),
        },
        act('a2', at(60), { timestamp: 60 }),
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'steps:steps:exec-a1',
      'event:e1',
      'event:d1',
      'event:v1',
      'steps:steps:exec-a2',
      'message:m1',
    ]);
  });

  it('shows recalled and captured memory where they happened', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        {
          id: 'mr1',
          type: 'memory_recalled',
          count: 1,
          searchMs: 1350,
          memories: [
            {
              content: 'Earlier report',
              score: 0.82,
              source: 'memory_index',
              category: 'decision',
            },
          ],
          ...at(20),
        },
        act('a1', at(40), { timestamp: 40 }),
        observe('o1', 'a1', at(45)),
        { id: 'mc1', type: 'memory_captured', capturedCount: 2, categories: ['entity'], ...at(50) },
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'memory:mr1',
      'steps:steps:exec-a1',
      'memory:mc1',
      'message:m1',
    ]);
  });

  it('places a tool call that has no execution id', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        { id: 'a1', type: 'act', toolName: 'bash', timestamp: 20, ...at(20) },
        {
          id: 'o1',
          type: 'observe',
          toolName: 'bash',
          toolOutput: 'x',
          isError: false,
          timestamp: 25,
          ...at(25),
        },
      ]
    );

    expect(kinds(rows)).toEqual(['message:u1', 'steps:steps:a1', 'message:m1']);
    const steps = rows[1];
    expect(steps.kind === 'steps' && steps.steps[0]).toMatchObject({ id: 'a1', status: 'success' });
  });

  // The argument of a call can be recorded as a draft before its execution.
  const draft = (call: string, position: object): InteractionEvent => ({
    id: `act_delta-${call}`,
    type: 'act',
    execution_id: call,
    call_id: call,
    message_id: 'message-1',
    toolName: 'bash',
    toolInput: { command: 'pwd' },
    metadata: { sourceEventType: 'act_delta' },
    ...position,
  });

  it('shows one step for a call whose argument draft was read on an earlier page', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [
        act('a1', at(40, 0), { timestamp: 40, call_id: 'call-1', message_id: 'message-1' }),
        observe('o1', 'a1', at(45)),
        draft('call-1', { timestamp: 35, ...at(35) }),
      ]
    );

    expect(kinds(rows)).toEqual(['message:u1', 'steps:steps:exec-a1', 'message:m1']);
    const steps = rows[1];
    expect(steps.kind === 'steps' && steps.steps.map((step) => step.id)).toEqual(['exec-a1']);
  });

  it('keeps the draft of a call whose execution is not read yet as a running step', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [],
      [draft('call-9', { timestamp: 35, ...at(35) })]
    );

    expect(kinds(rows)).toEqual(['message:u1', 'steps:steps:call-9', 'message:m1']);
    const steps = rows[1];
    expect(steps.kind === 'steps' && steps.steps[0]).toMatchObject({
      id: 'call-9',
      status: 'running',
    });
  });

  it('counts a message that both commands report once and still ends a group at one without text', () => {
    const rows = transcriptRows(
      [message('u1', 'user_message', at(10)), message('m1', 'assistant_message', at(90))],
      [thought('t1', at(95))],
      [
        { id: 'u1', type: 'user_message', ...at(10) },
        { id: 'm1', type: 'assistant_message', ...at(90) },
        { id: 't1', type: 'thought', ...at(95) },
        act('a1', at(20), { timestamp: 20 }),
        observe('o1', 'a1', at(25)),
        { id: 'x1', type: 'assistant_message', ...at(60) },
        act('a2', at(70), { timestamp: 70 }),
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'steps:steps:exec-a1',
      'steps:steps:exec-a2',
      'message:m1',
      'thought:t1',
    ]);
  });

  it('starts the turn of a message that is still being sent after the loaded history', () => {
    const rows = transcriptRows(
      [
        message('u1', 'user_message', at(10)),
        message('m1', 'assistant_message', at(100)),
        message('sending', 'user_message'),
        message('streaming', 'assistant_message'),
      ],
      [thought('live')],
      [
        act('old', at(20), { timestamp: 20 }),
        observe('old-o', 'old', at(30)),
        act('new', at(300), { timestamp: 300 }),
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'steps:steps:exec-old',
      'message:m1',
      'message:sending',
      'thought:live',
      'steps:steps:exec-new',
      'message:streaming',
    ]);
  });

  it('keeps a history without positions in its original order', () => {
    const rows = transcriptRows(
      [
        message('u1', 'user_message'),
        message('a1', 'assistant_message'),
        message('u2', 'user_message'),
        message('streaming', 'assistant_message'),
      ],
      [thought('live')],
      []
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'message:a1',
      'message:u2',
      'thought:live',
      'message:streaming',
    ]);
  });

  it('starts a first turn with the message being sent, before its reasoning and its steps', () => {
    const rows = transcriptRows(
      [message('sending', 'user_message'), message('streaming', 'assistant_message')],
      [thought('live')],
      [act('a1', at(300), { timestamp: 300 }), asked('p1', at(310), false)]
    );

    expect(kinds(rows)).toEqual([
      'message:sending',
      'thought:live',
      'steps:steps:exec-a1',
      'message:streaming',
    ]);
  });

  it('places reasoning that arrives while the page streams after the steps read before it', () => {
    const rows = transcriptRows(
      [
        message('u1', 'user_message', at(10)),
        message('m1', 'assistant_message', at(100)),
        message('sending', 'user_message'),
        message('streaming', 'assistant_message'),
      ],
      [thought('t1', undefined, [100, 0]), thought('t2', undefined, [310, 0])],
      [
        act('a1', at(300), { timestamp: 300 }),
        observe('o1', 'a1', at(310)),
        // The request ends the group of steps before it.
        asked('p1', at(320), false),
        act('a2', at(330), { timestamp: 330 }),
        observe('o2', 'a2', at(340)),
      ]
    );

    expect(kinds(rows)).toEqual([
      'message:u1',
      'message:m1',
      'message:sending',
      'thought:t1',
      'steps:steps:exec-a1',
      'thought:t2',
      'steps:steps:exec-a2',
      'message:streaming',
    ]);
  });

  it('reads the last position of the events, to place streaming reasoning after it', () => {
    expect(latestPosition([])).toBeUndefined();
    expect(
      latestPosition([
        { id: 'a', type: 'act', eventTimeUs: 5, eventCounter: 1 },
        { id: 'b', type: 'observe', eventTimeUs: 7, eventCounter: 0 },
        { id: 'c', type: 'task_updated' },
      ])
    ).toEqual([7, 0]);
  });

  it('draws an answer without text only while its turn still runs or when it has a usage summary', () => {
    const empty = message('a', 'assistant_message', { content: '' });
    expect(hasBubble(empty, true)).toBe(true);
    expect(hasBubble(empty, false)).toBe(false);
    expect(hasBubble(message('a', 'assistant_message'), false)).toBe(true);
    expect(hasBubble({ ...empty, summary: { summary: { stepCount: 3 } } as never }, false)).toBe(
      true
    );
  });
});
