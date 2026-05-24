import { afterEach, describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';
import { routeToHandler } from '@/services/agent/messageRouter';

import type { AgentStreamHandler } from '@/types/agent';

describe('agentService subagent session event routing', () => {
  const route = (eventType: string, data: Record<string, unknown>, handler: AgentStreamHandler) => {
    routeToHandler(eventType, data, handler);
  };

  it('routes subagent_announce_retry to its dedicated handler', () => {
    const onSubAgentAnnounceRetry = vi.fn();
    const handler: AgentStreamHandler = { onSubAgentAnnounceRetry };

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

    expect(onSubAgentAnnounceRetry).toHaveBeenCalledTimes(1);
    const routed = onSubAgentAnnounceRetry.mock.calls[0][0];
    expect(routed.type).toBe('subagent_announce_retry');
    expect(routed.data.run_id).toBe('run-1');
    expect(routed.data.attempt).toBe(2);
  });

  it('routes subagent_announce_giveup to its dedicated handler', () => {
    const onSubAgentAnnounceGiveup = vi.fn();
    const handler: AgentStreamHandler = { onSubAgentAnnounceGiveup };

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

    expect(onSubAgentAnnounceGiveup).toHaveBeenCalledTimes(1);
    const routed = onSubAgentAnnounceGiveup.mock.calls[0][0];
    expect(routed.type).toBe('subagent_announce_giveup');
    expect(routed.data.run_id).toBe('run-2');
    expect(routed.data.attempts).toBe(3);
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

  it('routes subagent_lifecycle spawned payload to onSubAgentSessionSpawned by data.conversation_id', () => {
    const onSubAgentSessionSpawned = vi.fn();
    handlers().set('conv-1', { onSubAgentSessionSpawned });

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

    expect(onSubAgentSessionSpawned).toHaveBeenCalledTimes(1);
    const routed = onSubAgentSessionSpawned.mock.calls[0][0];
    expect(routed.type).toBe('subagent_session_spawned');
    expect(routed.data.run_id).toBe('run-10');
  });

  it('routes subagent_lifecycle spawning payload to onSubAgentRunStarted', () => {
    const onSubAgentRunStarted = vi.fn();
    handlers().set('conv-3', { onSubAgentRunStarted });

    handleMessage({
      type: 'subagent_lifecycle',
      data: {
        type: 'subagent_spawning',
        conversation_id: 'conv-3',
        run_id: 'run-30',
        subagent_name: 'planner',
      },
    });

    expect(onSubAgentRunStarted).toHaveBeenCalledTimes(1);
    const routed = onSubAgentRunStarted.mock.calls[0][0];
    expect(routed.type).toBe('subagent_run_started');
    expect(routed.data.run_id).toBe('run-30');
    expect(routed.data.task).toBe('Spawning detached session');
  });

  it('routes subagent_lifecycle ended payload with non-completed status to onSubAgentRunFailed', () => {
    const onSubAgentRunFailed = vi.fn();
    handlers().set('conv-2', { onSubAgentRunFailed });

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

    expect(onSubAgentRunFailed).toHaveBeenCalledTimes(1);
    const routed = onSubAgentRunFailed.mock.calls[0][0];
    expect(routed.type).toBe('subagent_run_failed');
    expect(routed.data.run_id).toBe('run-20');
    expect(routed.data.error).toContain('timed_out');
  });
});
