import { describe, expect, it } from 'vitest';

import { groupTimelineEvents } from '../../../../components/agent/message/groupTimelineEvents';

import type { TimelineEvent } from '../../../../types/agent';

describe('groupTimelineEvents SubAgent grouping', () => {
  it('keeps terminal aliases for one SubAgent execution in one card', () => {
    const timeline = [
      {
        id: 'started-1',
        type: 'subagent_started',
        timestamp: 1,
        eventTimeUs: 1_000,
        eventCounter: 0,
        subagentId: '',
        subagentName: 'e2e-autonomous-worker-20260424-090132',
        task: '执行一个简单的 no-op 测试任务，确认委托机制正常工作',
      },
      {
        id: 'started-2',
        type: 'subagent_started',
        timestamp: 2,
        eventTimeUs: 2_000,
        eventCounter: 0,
        subagentId: 'run-1',
        subagentName: 'E2E Autonomous Worker 20260424-090132',
        task: '执行一个简单的 no-op 测试任务，确认委托机制正常工作',
      },
      {
        id: 'run-completed-1',
        type: 'subagent_run_completed',
        timestamp: 19_700,
        eventTimeUs: 19_700_000,
        eventCounter: 0,
        subagentId: 'run-1',
        subagentName: 'e2e-autonomous-worker-20260424-090132',
        task: '执行一个简单的 no-op 测试任务，确认委托机制正常工作',
        status: 'completed',
        summary: 'No-op 测试任务已完成。',
        executionTimeMs: 19_700,
        tokensUsed: 32,
      },
      {
        id: 'completed-1',
        type: 'subagent_completed',
        timestamp: 19_800,
        eventTimeUs: 19_800_000,
        eventCounter: 0,
        subagentId: '',
        subagentName: 'e2e-autonomous-worker-20260424-090132',
        summary: 'No-op 测试任务已完成。',
        tokensUsed: 32,
        executionTimeMs: 19_800,
        success: true,
      },
    ] satisfies TimelineEvent[];

    const grouped = groupTimelineEvents(timeline);

    expect(grouped).toHaveLength(1);
    expect(grouped[0]?.kind).toBe('subagent');
    if (grouped[0]?.kind !== 'subagent') return;
    expect(grouped[0].group.subagentId).toBe('run-1');
    expect(grouped[0].group.subagentName).toBe('e2e-autonomous-worker-20260424-090132');
    expect(grouped[0].group.status).toBe('success');
    expect(grouped[0].group.events).toHaveLength(4);
  });

  it('does not merge adjacent SubAgent executions with different identities', () => {
    const timeline = [
      {
        id: 'started-a',
        type: 'subagent_started',
        timestamp: 1,
        eventTimeUs: 1_000,
        eventCounter: 0,
        subagentId: 'run-a',
        subagentName: 'worker-a',
        task: 'Task A',
      },
      {
        id: 'completed-a',
        type: 'subagent_completed',
        timestamp: 2,
        eventTimeUs: 2_000,
        eventCounter: 0,
        subagentId: 'run-a',
        subagentName: 'worker-a',
        summary: 'A done',
        tokensUsed: 1,
        executionTimeMs: 1,
        success: true,
      },
      {
        id: 'started-b',
        type: 'subagent_started',
        timestamp: 3,
        eventTimeUs: 3_000,
        eventCounter: 0,
        subagentId: 'run-b',
        subagentName: 'worker-b',
        task: 'Task B',
      },
    ] satisfies TimelineEvent[];

    const grouped = groupTimelineEvents(timeline);

    expect(grouped).toHaveLength(2);
    expect(grouped[0]?.kind).toBe('subagent');
    expect(grouped[1]?.kind).toBe('subagent');
  });
});
