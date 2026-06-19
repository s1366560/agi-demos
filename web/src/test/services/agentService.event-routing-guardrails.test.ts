import { afterEach, describe, expect, it, vi } from 'vitest';

import { routeToHandler } from '@/services/agent/messageRouter';

import type { AgentStreamHandler } from '@/types/agent';

describe('agentService event routing guardrails', () => {
  const route = (eventType: string, data: unknown, handler: AgentStreamHandler) => {
    routeToHandler(eventType as any, data, handler);
  };

  afterEach(() => {
    localStorage.removeItem('memstack:debugLogs');
    vi.restoreAllMocks();
  });

  it('routes task synchronization events to task handlers', () => {
    const onTaskListUpdated = vi.fn();
    const onTaskUpdated = vi.fn();
    const onTaskStart = vi.fn();
    const onTaskComplete = vi.fn();
    const onModelSwitchRequested = vi.fn();

    const handler: AgentStreamHandler = {
      onTaskListUpdated,
      onTaskUpdated,
      onTaskStart,
      onTaskComplete,
      onModelSwitchRequested,
    };

    route('task_list_updated', { conversation_id: 'conv-1', tasks: [] }, handler);
    route(
      'task_updated',
      { conversation_id: 'conv-1', task_id: 'task-1', status: 'in_progress' },
      handler
    );
    route('task_start', { conversation_id: 'conv-1', task_id: 'task-1' }, handler);
    route('task_complete', { conversation_id: 'conv-1', task_id: 'task-1' }, handler);
    route('model_switch_requested', { conversation_id: 'conv-1', model: 'gpt-4o-mini' }, handler);

    expect(onTaskListUpdated).toHaveBeenCalledTimes(1);
    expect(onTaskUpdated).toHaveBeenCalledTimes(1);
    expect(onTaskStart).toHaveBeenCalledTimes(1);
    expect(onTaskComplete).toHaveBeenCalledTimes(1);
    expect(onModelSwitchRequested).toHaveBeenCalledTimes(1);
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

  it('routes multi-agent message events to dedicated handlers', () => {
    const onAgentMessageSent = vi.fn();
    const onAgentMessageReceived = vi.fn();
    const handler: AgentStreamHandler = {
      onAgentMessageSent,
      onAgentMessageReceived,
    };

    route('agent_message_sent', { from_agent_id: 'a', to_agent_id: 'b' }, handler);
    route('agent_message_received', { agent_id: 'b', from_agent_id: 'a' }, handler);

    expect(onAgentMessageSent).toHaveBeenCalledTimes(1);
    expect(onAgentMessageReceived).toHaveBeenCalledTimes(1);
  });

  it('ignores unknown event types without throwing', () => {
    const handler: AgentStreamHandler = {};
    expect(() => route('unknown_event_type', {}, handler)).not.toThrow();
  });

  it('isolates handler exceptions from malformed stream events', () => {
    const onError = vi.fn(() => {
      throw new Error('bad handler');
    });
    const handler: AgentStreamHandler = { onError };

    expect(() => route('error', undefined, handler)).not.toThrow();
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('routes thought_start to the thought start handler', () => {
    const onThoughtStart = vi.fn();
    const handler: AgentStreamHandler = { onThoughtStart };

    route('thought_start', { thought_level: 'reasoning' }, handler);

    expect(onThoughtStart).toHaveBeenCalledTimes(1);
    expect(onThoughtStart).toHaveBeenCalledWith({
      type: 'thought_start',
      data: { thought_level: 'reasoning' },
    });
  });

  it('does not debug-log high-frequency streaming deltas even when debug logs are enabled', () => {
    localStorage.setItem('memstack:debugLogs', 'true');
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const handler: AgentStreamHandler = {
      onTextDelta: vi.fn(),
      onThoughtDelta: vi.fn(),
      onActDelta: vi.fn(),
    };

    route('text_delta', { text: 'token' }, handler);
    route('thought_delta', { text: 'thinking' }, handler);
    route('act_delta', { text: 'running' }, handler);

    expect(handler.onTextDelta).toHaveBeenCalledTimes(1);
    expect(handler.onThoughtDelta).toHaveBeenCalledTimes(1);
    expect(handler.onActDelta).toHaveBeenCalledTimes(1);
    expect(logSpy).not.toHaveBeenCalledWith(
      '[DEBUG]',
      '[AgentWS] routeToHandler:',
      expect.anything()
    );
  });
});
