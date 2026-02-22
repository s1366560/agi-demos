import { afterEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import type { AgentStreamHandler } from '@/types/agent';

describe('agentService subagent session event routing', () => {
  const route = (eventType: string, data: Record<string, unknown>, handler: AgentStreamHandler) => {
    (agentService as any).routeToHandler(eventType, data, handler);
  };

  it('routes subagent_announce_retry to onSubAgentStarted', () => {
    const onSubAgentStarted = vi.fn();
    const handler: AgentStreamHandler = { onSubAgentStarted };

    route(
      'subagent_announce_retry',
      {
        conversation_id: 'conv-1',
        run_id: 'run-1',
        subagent_name: 'researcher',
        attempt: 2,
        error: 'temporary failure',
        next_delay_ms: 100,
      },
      handler
    );

    expect(onSubAgentStarted).toHaveBeenCalledTimes(1);
    const routed = onSubAgentStarted.mock.calls[0][0];
    expect(routed.type).toBe('subagent_started');
    expect(routed.data.subagent_id).toBe('run-1');
    expect(routed.data.task).toContain('Retry 2');
  });

  it('routes subagent_announce_giveup to onSubAgentFailed', () => {
    const onSubAgentFailed = vi.fn();
    const handler: AgentStreamHandler = { onSubAgentFailed };

    route(
      'subagent_announce_giveup',
      {
        conversation_id: 'conv-1',
        run_id: 'run-2',
        subagent_name: 'coder',
        attempts: 3,
        error: 'permanent failure',
      },
      handler
    );

    expect(onSubAgentFailed).toHaveBeenCalledTimes(1);
    const routed = onSubAgentFailed.mock.calls[0][0];
    expect(routed.type).toBe('subagent_failed');
    expect(routed.data.subagent_id).toBe('run-2');
    expect(routed.data.error).toContain('Give up after 3 attempts');
  });
});

describe('agentService project-scoped subagent lifecycle routing', () => {
  const handleMessage = (message: Record<string, unknown>) => {
    (agentService as any).handleMessage(message);
  };

  const handlers = () => (agentService as any).handlers as Map<string, AgentStreamHandler>;

  afterEach(() => {
    handlers().clear();
  });

  it('routes subagent_lifecycle spawned payload to onSubAgentStarted by data.conversation_id', () => {
    const onSubAgentStarted = vi.fn();
    handlers().set('conv-1', { onSubAgentStarted });

    handleMessage({
      type: 'subagent_lifecycle',
      project_id: 'proj-1',
      data: {
        type: 'subagent_spawned',
        conversation_id: 'conv-1',
        run_id: 'run-10',
        subagent_name: 'researcher',
      },
    });

    expect(onSubAgentStarted).toHaveBeenCalledTimes(1);
    const routed = onSubAgentStarted.mock.calls[0][0];
    expect(routed.type).toBe('subagent_started');
    expect(routed.data.subagent_id).toBe('run-10');
    expect(routed.data.task).toBe('Session spawned');
  });

  it('routes subagent_lifecycle spawning payload to onSubAgentStarted', () => {
    const onSubAgentStarted = vi.fn();
    handlers().set('conv-3', { onSubAgentStarted });

    handleMessage({
      type: 'subagent_lifecycle',
      data: {
        type: 'subagent_spawning',
        conversation_id: 'conv-3',
        run_id: 'run-30',
        subagent_name: 'planner',
      },
    });

    expect(onSubAgentStarted).toHaveBeenCalledTimes(1);
    const routed = onSubAgentStarted.mock.calls[0][0];
    expect(routed.type).toBe('subagent_started');
    expect(routed.data.subagent_id).toBe('run-30');
    expect(routed.data.task).toBe('Spawning detached session');
  });

  it('routes subagent_lifecycle ended payload with non-completed status to onSubAgentFailed', () => {
    const onSubAgentFailed = vi.fn();
    handlers().set('conv-2', { onSubAgentFailed });

    handleMessage({
      type: 'subagent_lifecycle',
      data: {
        type: 'subagent_ended',
        conversation_id: 'conv-2',
        run_id: 'run-20',
        subagent_name: 'coder',
        status: 'timed_out',
      },
    });

    expect(onSubAgentFailed).toHaveBeenCalledTimes(1);
    const routed = onSubAgentFailed.mock.calls[0][0];
    expect(routed.type).toBe('subagent_failed');
    expect(routed.data.subagent_id).toBe('run-20');
    expect(routed.data.error).toContain('timed_out');
  });
});
