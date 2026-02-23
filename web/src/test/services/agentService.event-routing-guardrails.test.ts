import { describe, expect, it, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import type { AgentStreamHandler } from '@/types/agent';

describe('agentService event routing guardrails', () => {
  const route = (eventType: string, data: Record<string, unknown>, handler: AgentStreamHandler) => {
    (agentService as any).routeToHandler(eventType, data, handler);
  };

  it('routes task synchronization events to task handlers', () => {
    const onTaskListUpdated = vi.fn();
    const onTaskUpdated = vi.fn();
    const onTaskStart = vi.fn();
    const onTaskComplete = vi.fn();

    const handler: AgentStreamHandler = {
      onTaskListUpdated,
      onTaskUpdated,
      onTaskStart,
      onTaskComplete,
    };

    route('task_list_updated', { conversation_id: 'conv-1', tasks: [] }, handler);
    route(
      'task_updated',
      { conversation_id: 'conv-1', task_id: 'task-1', status: 'in_progress' },
      handler
    );
    route('task_start', { conversation_id: 'conv-1', task_id: 'task-1' }, handler);
    route('task_complete', { conversation_id: 'conv-1', task_id: 'task-1' }, handler);

    expect(onTaskListUpdated).toHaveBeenCalledTimes(1);
    expect(onTaskUpdated).toHaveBeenCalledTimes(1);
    expect(onTaskStart).toHaveBeenCalledTimes(1);
    expect(onTaskComplete).toHaveBeenCalledTimes(1);
  });

  it('routes execution diagnostics events to dedicated handlers', () => {
    const onExecutionPathDecided = vi.fn();
    const onSelectionTrace = vi.fn();
    const onPolicyFiltered = vi.fn();
    const handler: AgentStreamHandler = {
      onExecutionPathDecided,
      onSelectionTrace,
      onPolicyFiltered,
    };

    route(
      'execution_path_decided',
      { path: 'react_loop', confidence: 0.6, reason: 'default path' },
      handler
    );
    route(
      'selection_trace',
      { initial_count: 18, final_count: 9, removed_total: 9, stages: [] },
      handler
    );
    route('policy_filtered', { removed_total: 9, stage_count: 4 }, handler);

    expect(onExecutionPathDecided).toHaveBeenCalledTimes(1);
    expect(onSelectionTrace).toHaveBeenCalledTimes(1);
    expect(onPolicyFiltered).toHaveBeenCalledTimes(1);
  });

  it('routes MCP and memory events to dedicated handlers', () => {
    const onMCPAppRegistered = vi.fn();
    const onMCPAppResult = vi.fn();
    const onMemoryRecalled = vi.fn();
    const onMemoryCaptured = vi.fn();

    const handler: AgentStreamHandler = {
      onMCPAppRegistered,
      onMCPAppResult,
      onMemoryRecalled,
      onMemoryCaptured,
    };

    route('mcp_app_registered', { app_id: 'mcp-app-1' }, handler);
    route('mcp_app_result', { app_id: 'mcp-app-1', output: 'ok' }, handler);
    route('memory_recalled', { memory_count: 1 }, handler);
    route('memory_captured', { memory_id: 'mem-1' }, handler);

    expect(onMCPAppRegistered).toHaveBeenCalledTimes(1);
    expect(onMCPAppResult).toHaveBeenCalledTimes(1);
    expect(onMemoryRecalled).toHaveBeenCalledTimes(1);
    expect(onMemoryCaptured).toHaveBeenCalledTimes(1);
  });

  it('ignores unknown event types without throwing', () => {
    const handler: AgentStreamHandler = {};
    expect(() => route('unknown_event_type', {}, handler)).not.toThrow();
  });
});
