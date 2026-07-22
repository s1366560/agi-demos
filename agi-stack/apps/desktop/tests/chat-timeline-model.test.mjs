import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { agentLifecyclePresentation } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/agentLifecyclePresentationModel.js',
);
const {
  assistantExecutionSummary,
  detectPayloadLanguage,
  formatToolCallDuration,
  latestAgentSuggestions,
  mergeArtifactStreamItem,
  mergeAssistantTextStreamChunk,
  mergeAssistantCompletionEvent,
  mergeCostUpdateEvent,
  mergeThoughtStreamChunk,
  mergeToolStreamItem,
  pairToolCallItems,
  toolActivityRows,
  shouldShowAgentWorkingIndicator,
  timelineWorkingStartedAtUs,
  timelineItemsForDisplay,
  timelineDayKey,
  timelineDayLabel,
  toolCallDiffStat,
  toolCallPairDurationMs,
  toolCallPairStatus,
  toolCallPresentationKind,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/chatTimelineModel.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('assistant text stream preserves whitespace tokens and settles to authoritative full text', () => {
  let items = mergeAssistantTextStreamChunk([], {
    kind: 'start',
    messageId: 'message-text-1',
    content: '',
    eventTimeUs: 1_000_000,
    eventCounter: 1,
  });
  for (const [index, content] of ['Hello', ' ', 'world', '\n\n', 'draft'].entries()) {
    items = mergeAssistantTextStreamChunk(items, {
      kind: 'delta',
      messageId: 'message-text-1',
      content,
      eventTimeUs: 1_100_000 + index * 100_000,
      eventCounter: index + 2,
    });
  }

  assert.equal(items.length, 1);
  assert.equal(items[0].content, 'Hello world\n\ndraft');
  assert.equal(items[0].metadata.streaming, true);

  items = mergeAssistantTextStreamChunk(items, {
    kind: 'complete',
    messageId: 'message-text-1',
    content: 'Hello world\n\nFinal answer.',
    eventTimeUs: 2_000_000,
    eventCounter: 7,
  });
  assert.equal(items.length, 1);
  assert.equal(items[0].content, 'Hello world\n\nFinal answer.');
  assert.equal(items[0].metadata.streaming, false);
});

test('text end can recover the full response when every delta was missed', () => {
  const items = mergeAssistantTextStreamChunk([], {
    kind: 'complete',
    messageId: 'message-text-replay',
    content: 'Recovered from text_end.full_text',
    eventTimeUs: 3_000_000,
    eventCounter: 1,
  });

  assert.equal(items.length, 1);
  assert.equal(items[0].content, 'Recovered from text_end.full_text');
  assert.equal(items[0].message_id, 'message-text-replay');
  assert.equal(items[0].metadata.streaming, false);
});

test('complete merges content and execution metadata into the latest assistant turn', () => {
  const existing = [
    {
      id: 'user-1',
      type: 'user_message',
      role: 'user',
      content: 'Run it',
      eventTimeUs: 1_000_000,
      eventCounter: 1,
    },
    {
      id: 'streaming-assistant-stream-conversation-1',
      type: 'assistant_message',
      role: 'assistant',
      message_id: 'stream-conversation-1',
      content: 'Draft',
      metadata: { streaming: false },
      eventTimeUs: 2_000_000,
      eventCounter: 2,
    },
  ];
  const items = mergeAssistantCompletionEvent(existing, {
    messageId: 'server-final-message-id',
    content: 'Authoritative final answer',
    eventTimeUs: 3_000_000,
    eventCounter: 3,
    metadata: {
      traceUrl: 'https://trace.example/run',
      executionSummary: { step_count: 4, call_count: 2, total_tokens: { total: 3200 } },
    },
    artifacts: [{ artifact_id: 'artifact-1' }],
  });

  assert.equal(items.length, 2);
  assert.equal(items[1].id, 'streaming-assistant-stream-conversation-1');
  assert.equal(items[1].content, 'Authoritative final answer');
  assert.equal(items[1].metadata.streaming, false);
  assert.equal(items[1].metadata.traceUrl, 'https://trace.example/run');
  assert.deepEqual(items[1].artifacts, [{ artifact_id: 'artifact-1' }]);
  assert.deepEqual(assistantExecutionSummary(items[1]), {
    stepCount: 4,
    artifactCount: 0,
    callCount: 2,
    totalCost: 0,
    totalCostFormatted: '$0.000000',
    totalTokens: 3200,
    tasks: null,
  });
});

test('complete can create a final assistant response when text streaming was absent', () => {
  const items = mergeAssistantCompletionEvent([], {
    messageId: 'message-complete-only',
    content: 'Completed without text events',
    eventTimeUs: 4_000_000,
    eventCounter: 1,
  });

  assert.equal(items.length, 1);
  assert.equal(items[0].role, 'assistant');
  assert.equal(items[0].content, 'Completed without text events');
  assert.equal(items[0].metadata.streaming, false);
});

test('live Agent complete events preserve final content and execution summary metadata', () => {
  assert.match(appSource, /type === 'complete'[\s\S]*?mergeAssistantCompletionEvent\(/);
  assert.match(appSource, /objectField\(data, 'execution_summary'\)/);
  assert.match(appSource, /readTextField\(data, 'content'\)/);
});

test('cost updates merge into the current Agent reply without losing execution summary fields', () => {
  const existing = [
    {
      id: 'user-cost-1',
      type: 'user_message',
      role: 'user',
      content: 'Run the verification',
      eventTimeUs: 1_000_000,
      eventCounter: 1,
    },
    {
      id: 'assistant-cost-1',
      type: 'assistant_message',
      role: 'assistant',
      content: 'Verification complete',
      eventTimeUs: 2_000_000,
      eventCounter: 2,
      metadata: {
        streaming: false,
        executionSummary: { step_count: 4, artifact_count: 1 },
      },
    },
  ];

  const merged = mergeCostUpdateEvent(existing, {
    cost_usd: 0.0042,
    total_tokens: 900,
    input_tokens: 700,
    output_tokens: 200,
    model: 'gpt-5.5',
  });

  assert.notEqual(merged, existing);
  assert.equal(merged.length, 2);
  assert.deepEqual(assistantExecutionSummary(merged[1]), {
    stepCount: 4,
    artifactCount: 1,
    callCount: 0,
    totalCost: 0.0042,
    totalCostFormatted: '$0.004200',
    totalTokens: 900,
    tasks: null,
  });
  assert.deepEqual(merged[1].metadata.costTracking, {
    inputTokens: 700,
    outputTokens: 200,
    totalTokens: 900,
    costUsd: 0.0042,
    model: 'gpt-5.5',
  });
});

test('cost updates accept domain token maps, prefer cumulative totals, and avoid phantom rows', () => {
  const existing = [
    {
      id: 'assistant-cost-2',
      type: 'assistant_message',
      role: 'assistant',
      content: 'Done',
      eventTimeUs: 3_000_000,
      eventCounter: 3,
    },
  ];
  const merged = mergeCostUpdateEvent(existing, {
    cost: 0.001,
    cumulative_cost_usd: 0.006,
    tokens: { input: 800, output: 200, total: 1_000 },
    cumulative_tokens: 1_600,
  });

  assert.equal(assistantExecutionSummary(merged[0]).totalCost, 0.006);
  assert.equal(assistantExecutionSummary(merged[0]).totalTokens, 1_600);
  assert.equal(mergeCostUpdateEvent([], { cost: 0.001, tokens: { total: 100 } }).length, 0);
  assert.match(appSource, /type === 'cost_update'[\s\S]*?mergeCostUpdateEvent\(/);
});

test('LLM retry events expose an explicit waiting lifecycle instead of a raw generic event', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'retry-1',
      type: 'retry',
      eventTimeUs: 4_000_000,
      eventCounter: 4,
      payload: {
        attempt: 2,
        delay_ms: 1_500,
        message: 'Provider rate limit',
      },
    }),
    {
      family: 'retry',
      state: 'waiting',
      subject: '2',
      detail: 'Provider rate limit',
      isError: false,
    },
  );
});

test('subagent lifecycle events expose readable subjects, details, and protocol states', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'subagent-started-1',
      type: 'subagent_started',
      eventTimeUs: 1_000_000,
      eventCounter: 1,
      payload: {
        subagent_name: 'Regression reviewer',
        task: 'Verify the concurrent disposal fix',
      },
    }),
    {
      family: 'subagent',
      state: 'running',
      subject: 'Regression reviewer',
      detail: 'Verify the concurrent disposal fix',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'subagent-failed-1',
      type: 'subagent_failed',
      eventTimeUs: 2_000_000,
      eventCounter: 2,
      payload: {
        subagent_name: 'CI verifier',
        error: 'Runner image is missing the fixture module',
      },
    }),
    {
      family: 'subagent',
      state: 'failed',
      subject: 'CI verifier',
      detail: 'Runner image is missing the fixture module',
      isError: true,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'tools-updated-1',
      type: 'tools_updated',
      eventTimeUs: 23_500_000,
      eventCounter: 4,
      payload: {
        project_id: 'project-release',
        server_name: 'release-tools',
        tool_names: ['mcp__release__verify', 'mcp__release__publish'],
        requires_refresh: true,
      },
    }),
    {
      family: 'toolset',
      state: 'ready',
      subject: 'release-tools',
      detail: '',
      isError: false,
      progress: { unit: 'tools', total: 2 },
    },
  );
});

test('graph lifecycle events render run, node, and handoff semantics without raw JSON', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'graph-completed-1',
      type: 'graph_run_completed',
      eventTimeUs: 3_000_000,
      eventCounter: 1,
      payload: { graph_name: 'Release validation', total_steps: 6 },
    }),
    {
      family: 'graphRun',
      state: 'complete',
      subject: 'Release validation',
      detail: '',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'graph-node-failed-1',
      type: 'graph_node_failed',
      eventTimeUs: 4_000_000,
      eventCounter: 2,
      payload: {
        node_label: 'Run regression tests',
        error_message: '1 test failed after 12.4s',
      },
    }),
    {
      family: 'graphNode',
      state: 'failed',
      subject: 'Run regression tests',
      detail: '1 test failed after 12.4s',
      isError: true,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'graph-handoff-1',
      type: 'graph_handoff',
      eventTimeUs: 5_000_000,
      eventCounter: 3,
      payload: {
        from_label: 'Planner',
        to_label: 'Reviewer',
        context_summary: 'Patch ready for verification',
      },
    }),
    {
      family: 'graphHandoff',
      state: 'running',
      subject: 'Planner → Reviewer',
      detail: 'Patch ready for verification',
      isError: false,
    },
  );
});

test('agent collaboration lifecycle exposes readable work, completion, and stop states', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-spawned-1',
      type: 'agent_spawned',
      eventTimeUs: 6_000_000,
      eventCounter: 1,
      payload: {
        agent_name: 'Researcher',
        task_summary: 'Collect release evidence',
      },
    }),
    {
      family: 'agent',
      state: 'running',
      subject: 'Researcher',
      detail: 'Collect release evidence',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-completed-1',
      type: 'agent_completed',
      eventTimeUs: 7_000_000,
      eventCounter: 2,
      payload: {
        agent_name: 'Verifier',
        result: 'Release gate failed',
        success: false,
      },
    }),
    {
      family: 'agent',
      state: 'failed',
      subject: 'Verifier',
      detail: 'Release gate failed',
      isError: true,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-stopped-1',
      type: 'agent_stopped',
      eventTimeUs: 8_000_000,
      eventCounter: 3,
      payload: { agent_name: 'Researcher', reason: 'Superseded by a newer run' },
    }),
    {
      family: 'agent',
      state: 'stopped',
      subject: 'Researcher',
      detail: 'Superseded by a newer run',
      isError: false,
    },
  );
});

test('agent messages expose sender to recipient direction for live and history shapes', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-message-sent-1',
      type: 'agent_message_sent',
      eventTimeUs: 9_000_000,
      eventCounter: 1,
      payload: {
        from_agent_name: 'Planner',
        to_agent_name: 'Reviewer',
        message_preview: 'Please verify the patch',
      },
    }),
    {
      family: 'agentMessage',
      state: 'sent',
      subject: 'Planner → Reviewer',
      detail: 'Please verify the patch',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-message-received-1',
      type: 'agent_message_received',
      eventTimeUs: 10_000_000,
      eventCounter: 2,
      agentName: 'Planner',
      fromAgentName: 'Reviewer',
      messagePreview: 'Patch verified successfully',
    }),
    {
      family: 'agentMessage',
      state: 'received',
      subject: 'Reviewer → Planner',
      detail: 'Patch verified successfully',
      isError: false,
    },
  );
});

test('parallel orchestration exposes task progress, participants, and structured failure', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'parallel-started-1',
      type: 'parallel_started',
      eventTimeUs: 11_000_000,
      eventCounter: 1,
      payload: {
        task_count: 2,
        subtasks: [
          { subagent_name: 'Researcher', task: 'Collect release evidence' },
          { subagent_name: 'Reviewer', task: 'Review the release gate' },
        ],
      },
    }),
    {
      family: 'parallel',
      state: 'running',
      subject: 'Researcher, Reviewer',
      detail: '',
      isError: false,
      progress: { unit: 'tasks', total: 2 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'parallel-completed-1',
      type: 'parallel_completed',
      eventTimeUs: 12_000_000,
      eventCounter: 2,
      results: [
        { subagentName: 'Researcher', summary: 'Evidence collected', success: true },
        { subagentName: 'Reviewer', summary: 'Release gate failed', success: false },
      ],
    }),
    {
      family: 'parallel',
      state: 'failed',
      subject: 'Researcher, Reviewer',
      detail: 'Reviewer',
      isError: true,
      progress: { unit: 'tasks', current: 2, total: 2 },
    },
  );
});

test('chain orchestration preserves step names, previews, summaries, and progress', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'chain-started-1',
      type: 'chain_started',
      eventTimeUs: 13_000_000,
      eventCounter: 1,
      payload: {
        total_steps: 3,
        step_names: ['Plan', 'Review', 'Verify'],
      },
    }),
    {
      family: 'chain',
      state: 'running',
      subject: 'Plan → Review → Verify',
      detail: '',
      isError: false,
      progress: { unit: 'steps', total: 3 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'chain-step-started-1',
      type: 'chain_step_started',
      eventTimeUs: 14_000_000,
      eventCounter: 2,
      stepIndex: 1,
      stepName: 'Review',
      taskPreview: 'Review the release evidence',
    }),
    {
      family: 'chainStep',
      state: 'running',
      subject: 'Review',
      detail: 'Review the release evidence',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'chain-step-completed-1',
      type: 'chain_step_completed',
      eventTimeUs: 15_000_000,
      eventCounter: 3,
      payload: {
        step_index: 1,
        step_name: 'Review',
        summary: 'Evidence passed review',
        success: true,
      },
    }),
    {
      family: 'chainStep',
      state: 'complete',
      subject: 'Review',
      detail: 'Evidence passed review',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'chain-completed-1',
      type: 'chain_completed',
      eventTimeUs: 16_000_000,
      eventCounter: 4,
      payload: {
        steps_completed: 3,
        total_steps: 3,
        final_summary: 'Release ready',
        success: true,
      },
    }),
    {
      family: 'chain',
      state: 'complete',
      subject: '',
      detail: 'Release ready',
      isError: false,
      progress: { unit: 'steps', current: 3, total: 3 },
    },
  );
});

test('background launch exposes the assigned SubAgent and task for both protocol shapes', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'background-launched-1',
      type: 'background_launched',
      eventTimeUs: 17_000_000,
      eventCounter: 1,
      payload: {
        subagent_name: 'Auditor',
        task_description: 'Audit the release evidence asynchronously',
      },
    }),
    {
      family: 'background',
      state: 'running',
      subject: 'Auditor',
      detail: 'Audit the release evidence asynchronously',
      isError: false,
    },
  );
});

test('execution governance events expose routing, selection, and policy semantics', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'execution-path-decided-1',
      type: 'execution_path_decided',
      eventTimeUs: 18_000_000,
      eventCounter: 1,
      payload: {
        path: 'react_loop',
        confidence: 0.92,
        reason: 'Complex task requires tools',
        target: 'workspace-agent',
      },
    }),
    {
      family: 'routing',
      state: 'complete',
      subject: 'react_loop → workspace-agent',
      detail: 'Complex task requires tools',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'selection-trace-1',
      type: 'selection_trace',
      eventTimeUs: 19_000_000,
      eventCounter: 2,
      domainLane: 'code',
      initialCount: 12,
      finalCount: 4,
      removedTotal: 8,
      budgetExceededStages: ['semantic_ranker_stage'],
    }),
    {
      family: 'selection',
      state: 'complete',
      subject: 'code',
      detail: 'semantic_ranker_stage',
      isError: false,
      progress: { unit: 'tools', current: 4, total: 12 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'policy-filtered-1',
      type: 'policy_filtered',
      eventTimeUs: 20_000_000,
      eventCounter: 3,
      payload: {
        domain_lane: 'code',
        removed_total: 3,
        stage_count: 2,
        budget_exceeded_stages: ['semantic_ranker_stage'],
      },
    }),
    {
      family: 'policy',
      state: 'attention',
      subject: 'code',
      detail: 'semantic_ranker_stage',
      isError: false,
      progress: { unit: 'filteredTools', total: 3 },
    },
  );
});

test('tool policy denial and toolset refresh expose blocked and failure states', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'tool-policy-denied-1',
      type: 'tool_policy_denied',
      eventTimeUs: 21_000_000,
      eventCounter: 1,
      payload: {
        agent_id: 'agent-main',
        tool_name: 'shell_command',
        policy_layer: 'workspace',
        denial_reason: 'Requires approval',
      },
    }),
    {
      family: 'policy',
      state: 'blocked',
      subject: 'shell_command',
      detail: 'Requires approval',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'toolset-changed-1',
      type: 'toolset_changed',
      eventTimeUs: 22_000_000,
      eventCounter: 2,
      payload: {
        source: 'plugin_manager',
        plugin_name: 'github',
        action: 'install',
        refresh_status: 'success',
        refreshed_tool_count: 3,
      },
    }),
    {
      family: 'toolset',
      state: 'complete',
      subject: 'github',
      detail: 'install',
      isError: false,
      progress: { unit: 'tools', total: 3 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'toolset-changed-failed-1',
      type: 'toolset_changed',
      eventTimeUs: 23_000_000,
      eventCounter: 3,
      source: 'register_mcp_server',
      serverName: 'release-tools',
      refreshStatus: 'failed',
    }),
    {
      family: 'toolset',
      state: 'failed',
      subject: 'release-tools',
      detail: 'register_mcp_server',
      isError: true,
    },
  );
});

test('skill matching and execution expose the selected skill and structured progress', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'skill-matched-1',
      type: 'skill_matched',
      eventTimeUs: 24_000_000,
      eventCounter: 1,
      payload: {
        skill_id: 'skill-release-guard',
        skill_name: 'Release guard',
        tools: ['read_file', 'shell_command'],
        match_score: 1,
        execution_mode: 'forced',
      },
    }),
    {
      family: 'skill',
      state: 'complete',
      subject: 'Release guard',
      detail: 'forced',
      isError: false,
      progress: { unit: 'tools', total: 2 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'skill-execution-start-1',
      type: 'skill_execution_start',
      eventTimeUs: 25_000_000,
      eventCounter: 2,
      skillName: 'Release guard',
      query: 'Run release checks',
      totalSteps: 3,
    }),
    {
      family: 'skill',
      state: 'running',
      subject: 'Release guard',
      detail: 'Run release checks',
      isError: false,
      progress: { unit: 'steps', total: 3 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'skill-tool-start-1',
      type: 'skill_tool_start',
      eventTimeUs: 26_000_000,
      eventCounter: 3,
      payload: {
        skill_name: 'Release guard',
        tool_name: 'shell_command',
        step_index: 1,
        total_steps: 3,
        status: 'running',
      },
    }),
    {
      family: 'skill',
      state: 'running',
      subject: 'Release guard → shell_command',
      detail: '',
      isError: false,
      progress: { unit: 'steps', current: 1, total: 3 },
    },
  );
});

test('skill results, completion, and fallback expose outcome semantics', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'skill-tool-result-1',
      type: 'skill_tool_result',
      eventTimeUs: 27_000_000,
      eventCounter: 1,
      payload: {
        skill_name: 'Release guard',
        tool_name: 'shell_command',
        error: 'Release verification failed',
        duration_ms: 812,
        step_index: 2,
        total_steps: 3,
        status: 'error',
      },
    }),
    {
      family: 'skill',
      state: 'failed',
      subject: 'Release guard → shell_command',
      detail: 'Release verification failed',
      isError: true,
      progress: { unit: 'steps', current: 2, total: 3 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'skill-execution-complete-1',
      type: 'skill_execution_complete',
      eventTimeUs: 28_000_000,
      eventCounter: 2,
      payload: {
        skill_name: 'Release guard',
        success: true,
        summary: 'Release checks passed',
        tool_results: [
          { tool_name: 'read_file', status: 'completed' },
          { tool_name: 'shell_command', status: 'completed' },
        ],
        execution_time_ms: 1_240,
      },
    }),
    {
      family: 'skill',
      state: 'complete',
      subject: 'Release guard',
      detail: 'Release checks passed',
      isError: false,
      progress: { unit: 'tools', total: 2 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'skill-fallback-1',
      type: 'skill_fallback',
      eventTimeUs: 29_000_000,
      eventCounter: 3,
      skillName: 'Release guard',
      reason: 'execution_failed',
      error: 'Continuing with the general agent',
    }),
    {
      family: 'skill',
      state: 'attention',
      subject: 'Release guard',
      detail: 'Continuing with the general agent',
      isError: false,
    },
  );
});

test('model switch events distinguish scheduled changes from rejected overrides', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'model-switch-requested-1',
      type: 'model_switch_requested',
      eventTimeUs: 30_000_000,
      eventCounter: 1,
      payload: {
        model: 'gpt-4.1',
        provider_type: 'openai',
        provider_name: 'OpenAI production',
        scope: 'next_turn',
        reason: 'Need deeper reasoning',
      },
    }),
    {
      family: 'model',
      state: 'scheduled',
      subject: 'gpt-4.1',
      detail: 'Need deeper reasoning',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'model-override-rejected-1',
      type: 'model_override_rejected',
      eventTimeUs: 31_000_000,
      eventCounter: 2,
      model: 'claude-sonnet-4',
      reason: 'Cross-provider switch not allowed',
      currentModel: 'gpt-4.1',
      currentProvider: 'openai',
    }),
    {
      family: 'model',
      state: 'blocked',
      subject: 'claude-sonnet-4',
      detail: 'Cross-provider switch not allowed',
      isError: false,
    },
  );
});

test('context events expose token occupancy and compression results', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'context-status-1',
      type: 'context_status',
      eventTimeUs: 32_000_000,
      eventCounter: 1,
      payload: {
        current_tokens: 7_200,
        token_budget: 16_000,
        occupancy_pct: 45,
        compression_level: 'none',
      },
    }),
    {
      family: 'context',
      state: 'complete',
      subject: 'none',
      detail: '',
      isError: false,
      progress: { unit: 'tokens', current: 7_200, total: 16_000 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'context-compressed-1',
      type: 'context_compressed',
      eventTimeUs: 33_000_000,
      eventCounter: 2,
      compressionStrategy: 'summarize',
      compressionLevel: 'moderate',
      originalMessageCount: 18,
      finalMessageCount: 10,
      tokensSaved: 3_400,
    }),
    {
      family: 'context',
      state: 'complete',
      subject: 'summarize',
      detail: 'moderate',
      isError: false,
      progress: { unit: 'messages', current: 10, total: 18 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'context-compacted-1',
      type: 'context_compacted',
      eventTimeUs: 33_500_000,
      eventCounter: 3,
      payload: {
        conversation_id: 'conversation-release',
        before_tokens: 12_000,
        after_tokens: 4_500,
      },
    }),
    {
      family: 'context',
      state: 'complete',
      subject: 'conversation-release',
      detail: '',
      isError: false,
      progress: { unit: 'tokens', current: 4_500, total: 12_000 },
    },
  );
});

test('session fork and merge events expose the child lifecycle direction and strategy', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'session-forked-1',
      type: 'session_forked',
      eventTimeUs: 33_600_000,
      eventCounter: 1,
      payload: {
        parent_conversation_id: 'conversation-parent',
        child_conversation_id: 'conversation-child',
      },
    }),
    {
      family: 'sessionLifecycle',
      state: 'complete',
      subject: 'conversation-parent → conversation-child',
      detail: '',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'session-merged-1',
      type: 'session_merged',
      eventTimeUs: 33_700_000,
      eventCounter: 2,
      payload: {
        parent_conversation_id: 'conversation-parent',
        child_conversation_id: 'conversation-child',
        merge_strategy: 'result_only',
      },
    }),
    {
      family: 'sessionLifecycle',
      state: 'complete',
      subject: 'conversation-child → conversation-parent',
      detail: 'result_only',
      isError: false,
    },
  );
});

test('conversation participant events expose roster membership and exit context', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'participant-joined-1',
      type: 'conversation_participant_joined',
      eventTimeUs: 33_800_000,
      eventCounter: 1,
      payload: {
        conversation_id: 'conversation-release',
        agent_id: 'agent-reviewer',
        actor_id: 'agent-coordinator',
        role: 'participant',
      },
    }),
    {
      family: 'participant',
      state: 'ready',
      subject: 'agent-reviewer',
      detail: 'participant',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'participant-left-1',
      type: 'conversation_participant_left',
      eventTimeUs: 33_900_000,
      eventCounter: 2,
      payload: {
        conversation_id: 'conversation-release',
        agent_id: 'agent-reviewer',
        actor_id: 'agent-coordinator',
        reason: 'review completed',
      },
    }),
    {
      family: 'participant',
      state: 'stopped',
      subject: 'agent-reviewer',
      detail: 'review completed',
      isError: false,
    },
  );
});

test('structured agent task events expose assignment, refusal, and declared progress', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-task-assigned-1',
      type: 'agent_task_assigned',
      eventTimeUs: 34_000_000,
      eventCounter: 1,
      payload: {
        conversation_id: 'conversation-release',
        actor_agent_id: 'agent-coordinator',
        target_agent_id: 'agent-reviewer',
        task_id: 'task-release-review',
        task_title: 'Review the release evidence',
        rationale: 'Independent verification is required.',
      },
    }),
    {
      family: 'agentTask',
      state: 'scheduled',
      subject: 'agent-coordinator → agent-reviewer',
      detail: 'Review the release evidence',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-task-refused-1',
      type: 'agent_task_refused',
      eventTimeUs: 34_100_000,
      eventCounter: 2,
      payload: {
        conversation_id: 'conversation-release',
        actor_agent_id: 'agent-reviewer',
        task_id: 'task-release-review',
        reason: 'Missing deployment credentials',
        suggested_reassignment: 'agent-operator',
      },
    }),
    {
      family: 'agentTask',
      state: 'blocked',
      subject: 'agent-reviewer',
      detail: 'Missing deployment credentials · agent-operator',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-progress-declared-1',
      type: 'agent_progress_declared',
      eventTimeUs: 34_200_000,
      eventCounter: 3,
      payload: {
        conversation_id: 'conversation-release',
        actor_agent_id: 'agent-reviewer',
        task_id: 'task-release-review',
        status: 'needs_review',
        summary: 'Ready for coordinator review',
        percent_complete: 75,
      },
    }),
    {
      family: 'agentTask',
      state: 'attention',
      subject: 'task-release-review',
      detail: 'Ready for coordinator review',
      isError: false,
      progress: { unit: 'percent', current: 75, total: 100 },
    },
  );
});

test('agent governance events expose human input, escalation, and conflict evidence', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-human-input-1',
      type: 'agent_human_input_requested',
      eventTimeUs: 34_300_000,
      eventCounter: 1,
      payload: {
        conversation_id: 'conversation-release',
        actor_agent_id: 'agent-reviewer',
        question: 'Approve the production rollout?',
        urgency: 'blocking',
        category: 'permission',
        rationale: 'Deployment changes production state.',
      },
    }),
    {
      family: 'agentGovernance',
      state: 'blocked',
      subject: 'agent-reviewer',
      detail: 'Approve the production rollout? · blocking · permission',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-escalated-1',
      type: 'agent_escalated',
      eventTimeUs: 34_400_000,
      eventCounter: 2,
      payload: {
        conversation_id: 'conversation-release',
        actor_agent_id: 'agent-reviewer',
        escalated_to: 'human',
        reason: 'Release approval required',
        severity: 'high',
      },
    }),
    {
      family: 'agentGovernance',
      state: 'attention',
      subject: 'agent-reviewer → human',
      detail: 'Release approval required · high',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-conflict-1',
      type: 'agent_conflict_marked',
      eventTimeUs: 34_500_000,
      eventCounter: 3,
      payload: {
        conversation_id: 'conversation-release',
        actor_agent_id: 'agent-reviewer',
        conflict_with: 'artifact-release-notes',
        summary: 'Release evidence mismatch',
        evidence: 'Checksum differs from the verified build.',
      },
    }),
    {
      family: 'agentGovernance',
      state: 'attention',
      subject: 'agent-reviewer ↔ artifact-release-notes',
      detail: 'Release evidence mismatch · Checksum differs from the verified build.',
      isError: false,
    },
  );
});

test('MCP App events expose the registered app and interactive tool result', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'mcp-app-registered-1',
      type: 'mcp_app_registered',
      eventTimeUs: 34_000_000,
      eventCounter: 1,
      payload: {
        app_id: 'github-issue-board',
        server_name: 'github',
        tool_name: 'create_issue_board',
        source: 'agent_developed',
        resource_uri: 'ui://github/issue-board',
        title: 'Issue board',
      },
    }),
    {
      family: 'mcpApp',
      state: 'ready',
      subject: 'Issue board',
      detail: 'github · create_issue_board · agent_developed',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'mcp-app-result-1',
      type: 'mcp_app_result',
      eventTimeUs: 35_000_000,
      eventCounter: 2,
      payload: {
        app_id: 'github-issue-board',
        server_name: 'github',
        tool_name: 'create_issue_board',
        resource_uri: 'ui://github/issue-board',
        ui_metadata: { title: 'Issue board' },
        structured_content: { open: 12, closed: 34 },
      },
    }),
    {
      family: 'mcpApp',
      state: 'complete',
      subject: 'Issue board',
      detail: 'github · create_issue_board',
      isError: false,
    },
  );
});

test('memory events expose authoritative recall and capture counts', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'memory-recalled-1',
      type: 'memory_recalled',
      eventTimeUs: 36_000_000,
      eventCounter: 1,
      payload: {
        memories: [
          { id: 'memory-1', category: 'semantic' },
          { id: 'memory-2', category: 'preference' },
          { id: 'memory-3', category: 'procedural' },
        ],
        count: 3,
        search_ms: 24,
      },
    }),
    {
      family: 'memory',
      state: 'complete',
      subject: '',
      detail: '',
      isError: false,
      progress: { unit: 'memories', total: 3 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'memory-captured-1',
      type: 'memory_captured',
      eventTimeUs: 37_000_000,
      eventCounter: 2,
      capturedCount: 2,
      categories: ['semantic', 'preference'],
    }),
    {
      family: 'memory',
      state: 'complete',
      subject: 'semantic, preference',
      detail: '',
      isError: false,
      progress: { unit: 'memories', total: 2 },
    },
  );
});

test('task timeline markers expose content, progress, and terminal status', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'task-start-1',
      type: 'task_start',
      eventTimeUs: 38_000_000,
      eventCounter: 1,
      payload: {
        task_id: 'task-2',
        content: 'Verify the release evidence',
        order_index: 1,
        total_tasks: 4,
      },
    }),
    {
      family: 'task',
      state: 'running',
      subject: 'Verify the release evidence',
      detail: '',
      isError: false,
      progress: { unit: 'tasks', current: 2, total: 4 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'task-complete-1',
      type: 'task_complete',
      eventTimeUs: 39_000_000,
      eventCounter: 2,
      taskId: 'task-2',
      status: 'completed',
      orderIndex: 1,
      totalTasks: 4,
    }),
    {
      family: 'task',
      state: 'complete',
      subject: 'task-2',
      detail: 'completed',
      isError: false,
      progress: { unit: 'tasks', current: 2, total: 4 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'task-complete-failed-1',
      type: 'task_complete',
      eventTimeUs: 40_000_000,
      eventCounter: 3,
      payload: {
        task_id: 'task-3',
        status: 'failed',
        order_index: 2,
        total_tasks: 4,
      },
    }),
    {
      family: 'task',
      state: 'failed',
      subject: 'task-3',
      detail: 'failed',
      isError: true,
      progress: { unit: 'tasks', current: 3, total: 4 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'task-complete-cancelled-1',
      type: 'task_complete',
      eventTimeUs: 41_000_000,
      eventCounter: 4,
      taskId: 'task-4',
      status: 'cancelled',
      orderIndex: 3,
      totalTasks: 4,
    }),
    {
      family: 'task',
      state: 'attention',
      subject: 'task-4',
      detail: 'cancelled',
      isError: false,
      progress: { unit: 'tasks', current: 4, total: 4 },
    },
  );
});

test('artifact timeline events expose lifecycle state, source, and batch progress', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'artifact-created-1',
      type: 'artifact_created',
      eventTimeUs: 42_000_000,
      eventCounter: 1,
      payload: {
        artifact_id: 'artifact-1',
        filename: 'release-notes.md',
        source_tool: 'export_artifact',
      },
    }),
    {
      family: 'artifact',
      state: 'running',
      subject: 'release-notes.md',
      detail: 'export_artifact',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'artifact-created-ready-1',
      type: 'artifact_created',
      eventTimeUs: 43_000_000,
      eventCounter: 2,
      artifactId: 'artifact-2',
      filename: 'verification.pdf',
      sourceTool: 'publish_report',
      url: 'https://artifacts.example/verification.pdf',
    }),
    {
      family: 'artifact',
      state: 'ready',
      subject: 'verification.pdf',
      detail: 'publish_report',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'artifact-ready-1',
      type: 'artifact_ready',
      eventTimeUs: 44_000_000,
      eventCounter: 3,
      payload: {
        artifact_id: 'artifact-3',
        filename: 'release.zip',
        source_tool: 'package_release',
        url: 'https://artifacts.example/release.zip',
      },
    }),
    {
      family: 'artifact',
      state: 'ready',
      subject: 'release.zip',
      detail: 'package_release',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'artifact-error-1',
      type: 'artifact_error',
      eventTimeUs: 45_000_000,
      eventCounter: 4,
      payload: {
        artifact_id: 'artifact-4',
        filename: 'broken.tar.gz',
        error: 'Upload checksum mismatch',
      },
    }),
    {
      family: 'artifact',
      state: 'failed',
      subject: 'broken.tar.gz',
      detail: 'Upload checksum mismatch',
      isError: true,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'artifacts-batch-1',
      type: 'artifacts_batch',
      eventTimeUs: 46_000_000,
      eventCounter: 5,
      payload: {
        source_tool: 'export_release',
        artifacts: [
          { id: 'artifact-5', filename: 'manifest.json' },
          { id: 'artifact-6', filename: 'checksums.txt' },
        ],
      },
    }),
    {
      family: 'artifact',
      state: 'complete',
      subject: 'export_release',
      detail: '',
      isError: false,
      progress: { unit: 'artifacts', total: 2 },
    },
  );
});

test('runtime infrastructure events expose sandbox, desktop, and terminal state', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'sandbox-created-1',
      type: 'sandbox_created',
      eventTimeUs: 60_000_000,
      eventCounter: 1,
      payload: {
        sandbox_id: 'sandbox-release-1',
        status: 'running',
        endpoint: 'wss://sandbox.example/ws',
      },
    }),
    {
      family: 'sandbox',
      state: 'ready',
      subject: 'sandbox-release-1',
      detail: 'wss://sandbox.example/ws',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'sandbox-status-error-1',
      type: 'sandbox_status',
      eventTimeUs: 61_000_000,
      eventCounter: 2,
      payload: {
        sandbox_id: 'sandbox-release-1',
        status: 'error',
        error_message: 'Runtime health probe failed',
      },
    }),
    {
      family: 'sandbox',
      state: 'failed',
      subject: 'sandbox-release-1',
      detail: 'Runtime health probe failed',
      isError: true,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'desktop-started-1',
      type: 'desktop_started',
      eventTimeUs: 62_000_000,
      eventCounter: 3,
      payload: {
        sandbox_id: 'sandbox-release-1',
        resolution: '1280x720',
        display: ':1',
      },
    }),
    {
      family: 'desktop',
      state: 'ready',
      subject: 'sandbox-release-1',
      detail: '1280x720 · :1',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'terminal-status-1',
      type: 'terminal_status',
      eventTimeUs: 63_000_000,
      eventCounter: 4,
      payload: {
        sandbox_id: 'sandbox-release-1',
        session_id: 'terminal-release-1',
        running: false,
      },
    }),
    {
      family: 'terminal',
      state: 'stopped',
      subject: 'terminal-release-1',
      detail: 'sandbox-release-1',
      isError: false,
    },
  );
});

test('HTTP preview service events expose service identity, preview URL, and status', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'http-service-started-1',
      type: 'http_service_started',
      eventTimeUs: 64_000_000,
      eventCounter: 1,
      payload: {
        sandbox_id: 'sandbox-release-1',
        service_id: 'service-preview-1',
        service_name: 'Vite preview',
        source_type: 'sandbox_internal',
        service_url: 'http://172.17.0.2:5173',
        proxy_url: '/api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
        auto_open: true,
      },
    }),
    {
      family: 'httpService',
      state: 'ready',
      subject: 'Vite preview',
      detail:
        'service-preview-1 · /api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'http-service-updated-1',
      type: 'http_service_updated',
      eventTimeUs: 65_000_000,
      eventCounter: 2,
      payload: {
        sandbox_id: 'sandbox-release-1',
        service_id: 'service-preview-1',
        service_name: 'Vite preview',
        source_type: 'sandbox_internal',
        service_url: 'http://172.17.0.2:4173',
        proxy_url: '/api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
        status: 'running',
      },
    }),
    {
      family: 'httpService',
      state: 'ready',
      subject: 'Vite preview',
      detail:
        'service-preview-1 · /api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'http-service-stopped-1',
      type: 'http_service_stopped',
      eventTimeUs: 66_000_000,
      eventCounter: 3,
      payload: {
        sandbox_id: 'sandbox-release-1',
        service_id: 'service-preview-1',
        service_name: 'Vite preview',
        status: 'stopped',
      },
    }),
    {
      family: 'httpService',
      state: 'stopped',
      subject: 'Vite preview',
      detail: 'service-preview-1',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'http-service-error-1',
      type: 'http_service_error',
      eventTimeUs: 67_000_000,
      eventCounter: 4,
      payload: {
        sandbox_id: 'sandbox-release-1',
        service_id: 'service-preview-1',
        service_name: 'Vite preview',
        status: 'error',
        error_message: 'Preview port is not reachable',
      },
    }),
    {
      family: 'httpService',
      state: 'failed',
      subject: 'Vite preview',
      detail: 'Preview port is not reachable',
      isError: true,
    },
  );
});

test('doom-loop safeguard events expose repeated tool calls and intervention state', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'doom-loop-detected-1',
      type: 'doom_loop_detected',
      eventTimeUs: 68_000_000,
      eventCounter: 1,
      payload: {
        request_id: 'request-doom-loop-1',
        tool_name: 'terminal',
        call_count: 4,
        last_calls: [],
      },
    }),
    {
      family: 'doomLoop',
      state: 'failed',
      subject: 'terminal',
      detail: '',
      isError: true,
      progress: { unit: 'calls', total: 4 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'doom-loop-intervened-1',
      type: 'doom_loop_intervened',
      eventTimeUs: 69_000_000,
      eventCounter: 2,
      payload: {
        request_id: 'request-doom-loop-1',
        action: 'resume_with_guardrails',
      },
    }),
    {
      family: 'doomLoop',
      state: 'complete',
      subject: 'resume_with_guardrails',
      detail: '',
      isError: false,
    },
  );

  assert.equal(
    agentLifecyclePresentation({
      id: 'doom-loop-detected-python-1',
      type: 'doom_loop_detected',
      eventTimeUs: 70_000_000,
      eventCounter: 3,
      payload: {
        tool: 'desktop',
        input: { action: 'click' },
      },
    })?.subject,
    'desktop',
  );
});

test('conversation terminal events expose completion and gate-specific stop states', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-goal-completed-1',
      type: 'agent_goal_completed',
      eventTimeUs: 71_000_000,
      eventCounter: 1,
      payload: {
        conversation_id: 'conversation-1',
        actor_agent_id: 'coordinator',
        summary: 'All requested checks passed',
        artifacts: ['report-1', 'patch-1'],
      },
    }),
    {
      family: 'conversation',
      state: 'complete',
      subject: 'All requested checks passed',
      detail: 'coordinator',
      isError: false,
      progress: { unit: 'artifacts', total: 2 },
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-conversation-budget-finished-1',
      type: 'agent_conversation_finished',
      eventTimeUs: 72_000_000,
      eventCounter: 2,
      payload: {
        conversation_id: 'conversation-1',
        reason: 'budget_turns',
        actor: 'system',
        rationale: 'Turn budget reached',
      },
    }),
    {
      family: 'conversation',
      state: 'attention',
      subject: 'budget_turns',
      detail: 'Turn budget reached',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-conversation-safety-finished-1',
      type: 'agent_conversation_finished',
      eventTimeUs: 73_000_000,
      eventCounter: 3,
      payload: {
        conversation_id: 'conversation-1',
        reason: 'safety_doom_loop',
        actor: 'supervisor',
        rationale: 'Repeated tool calls remained unsafe',
      },
    }),
    {
      family: 'conversation',
      state: 'failed',
      subject: 'safety_doom_loop',
      detail: 'Repeated tool calls remained unsafe',
      isError: true,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-conversation-cancelled-1',
      type: 'agent_conversation_finished',
      eventTimeUs: 74_000_000,
      eventCounter: 4,
      payload: {
        conversation_id: 'conversation-1',
        reason: 'user_cancel',
        actor: 'user',
        rationale: 'Stopped from the session header',
      },
    }),
    {
      family: 'conversation',
      state: 'stopped',
      subject: 'user_cancel',
      detail: 'Stopped from the session header',
      isError: false,
    },
  );
});

test('Agent definition mutation events expose the changed definition and operation state', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-definition-created-1',
      type: 'agent_definition_created',
      eventTimeUs: 75_000_000,
      eventCounter: 1,
      payload: { agent_id: 'agent-release', agent_name: 'release_guardian' },
    }),
    {
      family: 'agentDefinition',
      state: 'complete',
      subject: 'release_guardian',
      detail: 'agent-release',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-definition-updated-1',
      type: 'agent_definition_updated',
      eventTimeUs: 76_000_000,
      eventCounter: 2,
      payload: { agent_id: 'agent-release', agent_name: 'release_guardian' },
    }),
    {
      family: 'agentDefinition',
      state: 'complete',
      subject: 'release_guardian',
      detail: 'agent-release',
      isError: false,
    },
  );

  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'agent-definition-deleted-1',
      type: 'agent_definition_deleted',
      eventTimeUs: 77_000_000,
      eventCounter: 3,
      payload: { agent_id: 'agent-release', agent_name: 'release_guardian' },
    }),
    {
      family: 'agentDefinition',
      state: 'stopped',
      subject: 'release_guardian',
      detail: 'agent-release',
      isError: false,
    },
  );
});

test('plan reflection events expose assessment and adjustment attention without raw JSON', () => {
  assert.deepEqual(
    agentLifecyclePresentation({
      id: 'plan-reflection-complete-1',
      type: 'reflection_complete',
      eventTimeUs: 78_000_000,
      eventCounter: 1,
      payload: {
        plan_id: 'release-plan',
        assessment: 'needs_adjustment',
        reasoning: 'Reorder the verification and rollout steps',
        has_adjustments: true,
        adjustment_count: 2,
      },
    }),
    {
      family: 'planReflection',
      state: 'attention',
      subject: 'release-plan',
      detail: 'needs_adjustment · Reorder the verification and rollout steps',
      isError: false,
    },
  );
});

test('artifact ready and error stream events settle the original created row', () => {
  const created = {
    id: 'artifact-created-1',
    type: 'artifact_created',
    eventTimeUs: 47_000_000,
    eventCounter: 1,
    payload: {
      artifact_id: 'artifact-1',
      filename: 'release-notes.md',
      source_tool: 'export_artifact',
    },
  };
  const createdItems = mergeArtifactStreamItem([], created);
  assert.equal(createdItems.length, 1);
  assert.equal(createdItems[0].artifactId, 'artifact-1');
  assert.equal(createdItems[0].filename, 'release-notes.md');

  const readyItems = mergeArtifactStreamItem(createdItems, {
    id: 'artifact-ready-1',
    type: 'artifact_ready',
    eventTimeUs: 48_000_000,
    eventCounter: 2,
    payload: {
      artifact_id: 'artifact-1',
      filename: 'release-notes.md',
      url: 'https://artifacts.example/release-notes.md',
      preview_url: 'https://artifacts.example/release-notes.preview',
    },
  });
  assert.equal(readyItems.length, 1);
  assert.equal(readyItems[0].id, 'artifact-created-1');
  assert.equal(readyItems[0].type, 'artifact_created');
  assert.equal(
    readyItems[0].payload.url,
    'https://artifacts.example/release-notes.md',
  );

  const errorItems = mergeArtifactStreamItem(createdItems, {
    id: 'artifact-error-1',
    type: 'artifact_error',
    eventTimeUs: 49_000_000,
    eventCounter: 3,
    payload: {
      artifact_id: 'artifact-1',
      filename: 'release-notes.md',
      error: 'Upload checksum mismatch',
    },
  });
  assert.equal(errorItems.length, 1);
  assert.equal(errorItems[0].id, 'artifact-created-1');
  assert.equal(errorItems[0].type, 'artifact_created');
  assert.equal(errorItems[0].error, 'Upload checksum mismatch');
  assert.equal(errorItems[0].isError, true);

  const orphanReady = mergeArtifactStreamItem([], {
    id: 'artifact-ready-orphan-1',
    type: 'artifact_ready',
    eventTimeUs: 50_000_000,
    eventCounter: 4,
    payload: {
      artifact_id: 'artifact-orphan',
      filename: 'recovered.zip',
      url: 'https://artifacts.example/recovered.zip',
    },
  });
  assert.equal(orphanReady.length, 1);
  assert.equal(orphanReady[0].type, 'artifact_ready');
  assert.equal(orphanReady[0].filename, 'recovered.zip');
});

test('UI-state events stay out of the visible conversation timeline', () => {
  const items = [
    {
      id: 'user-message-1',
      type: 'user_message',
      role: 'user',
      content: 'Prepare the release.',
      eventTimeUs: 51_000_000,
      eventCounter: 1,
    },
    {
      id: 'assistant-message-1',
      type: 'assistant_message',
      role: 'assistant',
      content: 'The release is ready for review.',
      eventTimeUs: 52_000_000,
      eventCounter: 2,
    },
    {
      id: 'suggestions-1',
      type: 'suggestions',
      payload: {
        suggestions: [
          'Open the verification report',
          '',
          'Run the compatibility matrix',
          42,
        ],
      },
      eventTimeUs: 53_000_000,
      eventCounter: 3,
    },
    {
      id: 'context-status-1',
      type: 'context_status',
      payload: { current_tokens: 1200, token_budget: 8000 },
      eventTimeUs: 54_000_000,
      eventCounter: 4,
    },
    {
      id: 'canvas-replay-1',
      type: 'canvas_updated',
      payload: {
        action: 'created',
        block_id: 'release-approval',
        block: { id: 'release-approval', content: '{"beginRendering":{}}' },
      },
      eventTimeUs: 54_500_000,
      eventCounter: 5,
    },
    {
      id: 'pattern-match-1',
      type: 'pattern_match',
      payload: { pattern_name: 'internal-pattern-sentinel' },
      eventTimeUs: 54_510_000,
      eventCounter: 6,
    },
    {
      id: 'context-summary-generated-1',
      type: 'context_summary_generated',
      payload: { summary_id: 'internal-summary-sentinel' },
      eventTimeUs: 54_520_000,
      eventCounter: 7,
    },
    {
      id: 'compact-needed-1',
      type: 'compact_needed',
      payload: { reason: 'internal-compact-sentinel' },
      eventTimeUs: 54_530_000,
      eventCounter: 8,
    },
    {
      id: 'screenshot-update-1',
      type: 'screenshot_update',
      payload: {
        sandbox_id: 'sandbox-release',
        image_url: 'data:image/png;base64,internal-screenshot-sentinel',
      },
      eventTimeUs: 54_540_000,
      eventCounter: 9,
    },
    ...[
      'plan_mode_enter',
      'plan_mode_exit',
      'plan_created',
      'plan_updated',
      'plan_suggested',
      'plan_exploration_started',
      'plan_exploration_completed',
      'plan_draft_created',
      'plan_approved',
      'plan_rejected',
      'plan_cancelled',
      'workplan_created',
      'workplan_step_started',
      'workplan_step_completed',
      'workplan_step_failed',
      'workplan_completed',
      'workplan_failed',
      'plan_execution_start',
      'plan_execution_complete',
      'plan_mode_changed',
      'plan_status_changed',
      'plan_step_ready',
      'plan_step_complete',
      'plan_step_skipped',
      'plan_snapshot_created',
      'plan_rollback',
      'adjustment_applied',
    ].map((type, index) => ({
      id: `plan-ui-state-${index}`,
      type,
      payload: { plan_id: 'release-plan' },
      eventTimeUs: 54_600_000 + index,
      eventCounter: 6 + index,
    })),
    {
      id: 'reflection-complete-1',
      type: 'reflection_complete',
      payload: { plan_id: 'release-plan', assessment: 'continue' },
      eventTimeUs: 54_700_000,
      eventCounter: 40,
    },
    {
      id: 'task-list-updated-1',
      type: 'task_list_updated',
      payload: { tasks: [{ id: 'release-task', content: 'task-list-sentinel' }] },
      eventTimeUs: 54_800_000,
      eventCounter: 41,
    },
    {
      id: 'task-updated-1',
      type: 'task_updated',
      payload: { task: { id: 'release-task', content: 'task-update-sentinel' } },
      eventTimeUs: 54_900_000,
      eventCounter: 42,
    },
    {
      id: 'task-start-1',
      type: 'task_start',
      payload: { task_id: 'release-task', content: 'Verify the release' },
      eventTimeUs: 55_000_000,
      eventCounter: 43,
    },
    {
      id: 'task-complete-1',
      type: 'task_complete',
      payload: { task_id: 'release-task', success: true },
      eventTimeUs: 55_100_000,
      eventCounter: 44,
    },
  ];

  assert.deepEqual(latestAgentSuggestions(items), [
    'Open the verification report',
    'Run the compatibility matrix',
  ]);
  assert.deepEqual(
    timelineItemsForDisplay(items).map((item) => item.id),
    [
      'user-message-1',
      'assistant-message-1',
      'context-status-1',
      'reflection-complete-1',
      'task-start-1',
      'task-complete-1',
    ],
  );

  assert.deepEqual(
    latestAgentSuggestions([
      ...items,
      {
        id: 'user-message-2',
        type: 'user_message',
        role: 'user',
        content: 'Run the compatibility matrix',
        eventTimeUs: 55_000_000,
        eventCounter: 5,
      },
    ]),
    [],
  );

  assert.deepEqual(
    latestAgentSuggestions([
      ...items,
      {
        id: 'suggestions-cleared',
        type: 'suggestions',
        suggestions: [],
        eventTimeUs: 55_000_000,
        eventCounter: 5,
      },
    ]),
    [],
  );

  assert.deepEqual(
    latestAgentSuggestions([
      {
        id: 'suggestions-history-1',
        type: 'suggestions',
        suggestions: ['Inspect the generated patch'],
        eventTimeUs: 56_000_000,
        eventCounter: 6,
      },
    ]),
    ['Inspect the generated patch'],
  );
});

test('channel inbound message events become conversation rows and other generic messages stay hidden', () => {
  const inboundUser = {
    id: 'message-event-user',
    type: 'message',
    payload: {
      id: 'channel-user-1',
      role: 'user',
      content: 'Hello from Feishu',
      metadata: { source: 'channel_inbound', channel: 'feishu' },
    },
    eventTimeUs: 56_000_000,
    eventCounter: 1,
  };
  const inboundAssistant = {
    id: 'message-event-assistant',
    type: 'message',
    payload: {
      id: 'channel-assistant-1',
      role: 'assistant',
      content: 'Reply mirrored to the channel',
      metadata: { source: 'channel_inbound', channel: 'feishu' },
    },
    eventTimeUs: 57_000_000,
    eventCounter: 2,
  };
  const nonChannel = {
    id: 'message-event-internal',
    type: 'message',
    payload: {
      id: 'internal-1',
      role: 'user',
      content: 'internal-message-sentinel',
      metadata: { source: 'agent_runtime' },
    },
    eventTimeUs: 58_000_000,
    eventCounter: 3,
  };
  const malformed = {
    id: 'message-event-malformed',
    type: 'message',
    payload: {
      id: 'malformed-1',
      role: 'system',
      content: 'malformed-message-sentinel',
      metadata: { source: 'channel_inbound' },
    },
    eventTimeUs: 59_000_000,
    eventCounter: 4,
  };

  assert.deepEqual(timelineItemsForDisplay([inboundUser, inboundAssistant, nonChannel, malformed]), [
    {
      ...inboundUser,
      id: 'channel-user-1',
      type: 'user_message',
      role: 'user',
      content: 'Hello from Feishu',
      message_id: 'channel-user-1',
      metadata: { source: 'channel_inbound', channel: 'feishu' },
    },
    {
      ...inboundAssistant,
      id: 'channel-assistant-1',
      type: 'assistant_message',
      role: 'assistant',
      content: 'Reply mirrored to the channel',
      message_id: 'channel-assistant-1',
      metadata: { source: 'channel_inbound', channel: 'feishu' },
    },
  ]);
  assert.equal(inboundUser.type, 'message');
});

test('streaming thought chunks merge into one readable timeline item and then settle', () => {
  let items = mergeThoughtStreamChunk([], {
    kind: 'start',
    messageId: 'message-1',
    content: '',
    eventTimeUs: 1_000_000,
    eventCounter: 1,
    payload: { thought_level: 'reasoning' },
  });
  items = mergeThoughtStreamChunk(items, {
    kind: 'delta',
    messageId: 'message-1',
    content: 'Inspect ',
    eventTimeUs: 1_100_000,
    eventCounter: 2,
    payload: { delta: 'Inspect ' },
  });
  items = mergeThoughtStreamChunk(items, {
    kind: 'delta',
    messageId: 'message-1',
    content: 'the tests.',
    eventTimeUs: 1_200_000,
    eventCounter: 3,
    payload: { delta: 'the tests.' },
  });

  assert.equal(items.length, 1);
  assert.equal(items[0].type, 'thought');
  assert.equal(items[0].content, 'Inspect the tests.');
  assert.equal(items[0].metadata.streaming, true);

  items = mergeThoughtStreamChunk(items, {
    kind: 'complete',
    messageId: 'message-1',
    content: 'Inspect the tests before editing.',
    eventTimeUs: 1_300_000,
    eventCounter: 4,
    payload: { thought: 'Inspect the tests before editing.' },
  });
  assert.equal(items.length, 1);
  assert.equal(items[0].content, 'Inspect the tests before editing.');
  assert.equal(items[0].metadata.streaming, false);
});

test('a second thought stream under the same Agent message remains a separate step', () => {
  const completed = mergeThoughtStreamChunk([], {
    kind: 'complete',
    messageId: 'message-1',
    content: 'First thought',
    eventTimeUs: 1_000_000,
    eventCounter: 1,
  });
  const withNext = mergeThoughtStreamChunk(completed, {
    kind: 'start',
    messageId: 'message-1',
    content: '',
    eventTimeUs: 2_000_000,
    eventCounter: 2,
  });

  assert.equal(withNext.length, 2);
  assert.equal(withNext[0].content, 'First thought');
  assert.equal(withNext[1].metadata.streaming, true);
});

test('live Agent events route thought start, delta, and completion through the stream merger', () => {
  assert.match(
    appSource,
    /type === 'thought_start'[\s\S]*?type === 'thought_delta'[\s\S]*?type === 'thought'/,
  );
  assert.match(appSource, /mergeThoughtStreamChunk\(existing/);
  assert.match(appSource, /type\.startsWith\('thought_'\)/);
});

test('live Agent text events preserve raw delta whitespace and read text_end full_text', () => {
  assert.match(appSource, /mergeAssistantTextStreamChunk\(existing/);
  assert.match(appSource, /readTextField\(data, 'full_text'\)/);
  assert.match(appSource, /readTextField\(data, 'delta'\)/);
});

test('act items pair with the observe that answers them, preserving order', () => {
  const pairs = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'read_file', eventTimeUs: 1_000_000 },
    { id: 'observe-1', type: 'observe', toolName: 'read_file', eventTimeUs: 1_400_000 },
    { id: 'act-2', type: 'act', toolName: 'run_tests', eventTimeUs: 2_000_000 },
    { id: 'observe-2', type: 'observe', toolName: 'run_tests', eventTimeUs: 3_000_000 },
  ]);

  assert.equal(pairs.length, 2);
  assert.equal(pairs[0].call.id, 'act-1');
  assert.equal(pairs[0].result?.id, 'observe-1');
  assert.equal(pairs[1].call.id, 'act-2');
  assert.equal(pairs[1].result?.id, 'observe-2');
});

test('streamed tool arguments merge into one stable call and settle on observe', () => {
  let items = mergeToolStreamItem(
    [],
    {
      id: 'delta-1',
      type: 'act',
      toolName: 'read_file',
      toolInput: '',
      payload: { call_id: 'call-1', accumulated_arguments: '' },
      message_id: 'message-1',
      eventTimeUs: 1_000_000,
      eventCounter: 1,
    },
    'delta',
  );
  items = mergeToolStreamItem(
    items,
    {
      id: 'delta-2',
      type: 'act',
      toolName: 'read_file',
      toolInput: '{"path":"README.md"',
      payload: { call_id: 'call-1', accumulated_arguments: '{"path":"README.md"' },
      message_id: 'message-1',
      eventTimeUs: 1_100_000,
      eventCounter: 2,
    },
    'delta',
  );
  items = mergeToolStreamItem(
    items,
    {
      id: 'act-1',
      type: 'act',
      toolName: 'read_file',
      toolInput: { path: 'README.md' },
      payload: { call_id: 'call-1', tool_execution_id: 'exec-1' },
      message_id: 'message-1',
      eventTimeUs: 1_200_000,
      eventCounter: 3,
    },
    'act',
  );

  assert.equal(items.length, 1);
  assert.equal(items[0].id, 'delta-1');
  assert.deepEqual(items[0].toolInput, { path: 'README.md' });
  assert.equal(items[0].metadata.streaming, true);

  items = mergeToolStreamItem(
    items,
    {
      id: 'observe-1',
      type: 'observe',
      toolName: 'read_file',
      toolOutput: 'contents',
      payload: { call_id: 'call-1', tool_execution_id: 'exec-1' },
      message_id: 'message-1',
      eventTimeUs: 1_800_000,
      eventCounter: 4,
    },
    'observe',
  );
  assert.equal(items.length, 2);
  assert.equal(items[0].metadata.streaming, false);
  assert.equal(pairToolCallItems(items)[0].result?.id, 'observe-1');
});

test('parallel tool observations pair by call identity instead of arrival order', () => {
  const pairs = pairToolCallItems([
    {
      id: 'act-1',
      type: 'act',
      toolName: 'read_file',
      payload: { call_id: 'call-1', tool_execution_id: 'exec-1' },
      eventTimeUs: 1,
    },
    {
      id: 'act-2',
      type: 'act',
      toolName: 'read_file',
      payload: { call_id: 'call-2', tool_execution_id: 'exec-2' },
      eventTimeUs: 2,
    },
    {
      id: 'observe-2',
      type: 'observe',
      toolName: 'read_file',
      payload: { call_id: 'call-2', tool_execution_id: 'exec-2' },
      eventTimeUs: 3,
    },
    {
      id: 'observe-1',
      type: 'observe',
      toolName: 'read_file',
      payload: { call_id: 'call-1', tool_execution_id: 'exec-1' },
      eventTimeUs: 4,
    },
  ]);

  assert.equal(pairs.length, 2);
  assert.equal(pairs[0].result?.id, 'observe-1');
  assert.equal(pairs[1].result?.id, 'observe-2');
});

test('live Agent tool events route deltas, calls, and observations through the stream merger', () => {
  assert.match(appSource, /type === 'act_delta'[\s\S]*?type === 'act'[\s\S]*?type === 'observe'/);
  assert.match(appSource, /mergeToolStreamItem\(/);
});

test('tool activity rows preserve structured thinking ahead of paired tool calls', () => {
  const rows = toolActivityRows([
    { id: 'thought-1', type: 'thought', content: 'Inspect the shared fixture.' },
    { id: 'act-1', type: 'act', toolName: 'read_file' },
    { id: 'observe-1', type: 'observe', toolName: 'read_file' },
  ]);

  assert.equal(rows.length, 2);
  assert.equal(rows[0].kind, 'thought');
  assert.equal(rows[0].item.id, 'thought-1');
  assert.equal(rows[1].kind, 'tool_call');
  assert.equal(rows[1].pair.call.id, 'act-1');
  assert.equal(rows[1].pair.result.id, 'observe-1');
});

test('a trailing act without its observe renders as a running call', () => {
  const pairs = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'read_file', eventTimeUs: 1 },
    { id: 'observe-1', type: 'observe', toolName: 'read_file', eventTimeUs: 2 },
    { id: 'act-2', type: 'act', toolName: 'write_file', eventTimeUs: 3 },
  ]);

  assert.equal(pairs.length, 2);
  assert.equal(toolCallPairStatus(pairs[0]), 'complete');
  assert.equal(toolCallPairStatus(pairs[1]), 'running');
  assert.equal(toolCallPairDurationMs(pairs[1]), null);
});

test('an orphaned observe still renders as a completed call on its own', () => {
  const pairs = pairToolCallItems([
    { id: 'observe-1', type: 'observe', toolName: 'read_file', eventTimeUs: 5 },
  ]);

  assert.equal(pairs.length, 1);
  assert.equal(pairs[0].result, null);
  assert.equal(toolCallPairStatus(pairs[0]), 'complete');
});

test('failed observations surface as failed pairs with a duration', () => {
  const failed = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'run_tests', eventTimeUs: 1_000_000 },
    { id: 'observe-1', type: 'observe', toolName: 'run_tests', isError: true, eventTimeUs: 2_000_000 },
  ]);
  const withDelta = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'run_tests', eventTimeUs: 1_000_000 },
    { id: 'observe-1', type: 'observe', toolName: 'run_tests', eventTimeUs: 2_500_000 },
  ]);

  assert.equal(toolCallPairStatus(failed[0]), 'failed');
  assert.equal(toolCallPairDurationMs(withDelta[0]), 1500);
});

test('tool call durations format for quick scanning', () => {
  assert.equal(formatToolCallDuration(420), '420ms');
  assert.equal(formatToolCallDuration(1800), '1.8s');
  assert.equal(formatToolCallDuration(12_000), '12s');
  assert.equal(formatToolCallDuration(72_000), '1m 12s');
  assert.equal(formatToolCallDuration(-5), '');
});

test('structured tool presentation metadata drives worklog anatomy', () => {
  const pair = pairToolCallItems([
    {
      id: 'act-edit',
      type: 'act',
      toolName: 'patch',
      display: { kind: 'edit' },
      eventTimeUs: 1_000_000,
    },
    {
      id: 'observe-edit',
      type: 'observe',
      toolName: 'patch',
      display: { kind: 'edit' },
      fileMetadata: { diffStat: { filesChanged: 2, additions: 18, deletions: 4 } },
      eventTimeUs: 1_500_000,
    },
  ])[0];

  assert.equal(toolCallPresentationKind(pair), 'edit');
  assert.deepEqual(toolCallDiffStat(pair), { filesChanged: 2, additions: 18, deletions: 4 });
});

test('unknown presentation metadata stays generic instead of text-classified', () => {
  const pair = pairToolCallItems([
    {
      id: 'act-unknown',
      type: 'act',
      toolName: 'custom_tool',
      toolInput: { description: 'edit and run a command' },
      eventTimeUs: 1,
    },
  ])[0];

  assert.equal(toolCallPresentationKind(pair), 'tool');
  assert.equal(toolCallDiffStat(pair), null);
});

test('working duration starts from the latest authoritative running boundary', () => {
  const items = [
    { id: 'user-1', type: 'user_message', role: 'user', eventTimeUs: 1_000_000 },
    { id: 'run-1', type: 'run_status', payload: { status: 'running' }, eventTimeUs: 2_000_000 },
    { id: 'tool-1', type: 'act', eventTimeUs: 3_000_000 },
  ];

  assert.equal(timelineWorkingStartedAtUs(items), 2_000_000);
  assert.equal(timelineWorkingStartedAtUs(items.slice(0, 1)), 1_000_000);
  assert.equal(timelineWorkingStartedAtUs([]), null);
});

test('day dividers bucket items by local calendar day', () => {
  const now = new Date(2026, 6, 20, 15, 0, 0).getTime();
  const todayUs = new Date(2026, 6, 20, 9, 0, 0).getTime() * 1000;
  const yesterdayUs = new Date(2026, 6, 19, 23, 0, 0).getTime() * 1000;
  const olderUs = new Date(2026, 6, 10, 12, 0, 0).getTime() * 1000;

  assert.equal(timelineDayKey(todayUs), timelineDayKey(now * 1000));
  assert.notEqual(timelineDayKey(yesterdayUs), timelineDayKey(todayUs));
  assert.deepEqual(timelineDayLabel(todayUs, now), { kind: 'today' });
  assert.deepEqual(timelineDayLabel(yesterdayUs, now), { kind: 'yesterday' });
  const older = timelineDayLabel(olderUs, now);
  assert.equal(older.kind, 'date');
  assert.ok(older.date.length > 0);
});

test('working indicator only shows while live, blocked neither by stream nor HITL', () => {
  const userTail = [{ id: 'u1', type: 'user_message', role: 'user', eventTimeUs: 1 }];
  const streamingTail = [
    {
      id: 'a1',
      type: 'assistant_message',
      role: 'assistant',
      metadata: { streaming: true },
      eventTimeUs: 2,
    },
  ];
  const answerTail = [{ id: 'a2', type: 'assistant_message', role: 'assistant', eventTimeUs: 3 }];
  const observeTail = [{ id: 'o1', type: 'observe', toolName: 'read_file', eventTimeUs: 4 }];
  const terminatedTail = [
    ...observeTail,
    {
      id: 'conversation-finished-1',
      type: 'agent_conversation_finished',
      eventTimeUs: 5,
      payload: { reason: 'budget_turns' },
    },
  ];

  assert.equal(
    shouldShowAgentWorkingIndicator({ items: userTail, presence: 'live', awaitingHitl: false }),
    true,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: observeTail, presence: 'live', awaitingHitl: false }),
    true,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: streamingTail, presence: 'live', awaitingHitl: false }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: answerTail, presence: 'live', awaitingHitl: false }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({
      items: terminatedTail,
      presence: 'live',
      awaitingHitl: false,
    }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: userTail, presence: 'recorded', awaitingHitl: false }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: userTail, presence: 'live', awaitingHitl: true }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: [], presence: 'live', awaitingHitl: false }),
    false,
  );
});

test('payload detection pretty-prints JSON and keeps plain text untouched', () => {
  assert.deepEqual(detectPayloadLanguage('hello world'), {
    code: 'hello world',
    language: 'text',
  });
  assert.deepEqual(detectPayloadLanguage('{"a":1}'), { code: '{\n  "a": 1\n}', language: 'json' });
  assert.deepEqual(detectPayloadLanguage({ a: 1 }), { code: '{\n  "a": 1\n}', language: 'json' });
  assert.deepEqual(detectPayloadLanguage('{not json'), { code: '{not json', language: 'text' });
  assert.deepEqual(detectPayloadLanguage('$ cargo test\nok'), {
    code: '$ cargo test\nok',
    language: 'text',
  });
});
