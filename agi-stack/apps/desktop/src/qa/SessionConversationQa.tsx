import '@radix-ui/themes/styles.css';
import React, { useEffect, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem, ConversationTimelineState } from '../types';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __sessionConversationQaRoot: Root | undefined;
}

// Visual QA fixture for the agent conversation timeline: day dividers, a
// reasoning row, paired tool calls (complete / running / failed), SubAgent,
// multi-Agent, orchestration, and graph lifecycle rows, markdown with a
// highlighted code block, a streaming assistant reply, and the live working
// indicator. Item timestamps are relative to load time so the day dividers are
// deterministic ("yesterday" then "today").

const nowMs = Date.now();
const HOUR = 3_600_000;

function item(partial: Partial<AgentTimelineItem> & { id: string; type: string }): AgentTimelineItem {
  return {
    eventTimeUs: nowMs * 1000,
    eventCounter: 0,
    timestamp: nowMs,
    ...partial,
  } as AgentTimelineItem;
}

const longTestReport = JSON.stringify(
  {
    suite: 'pipeline_race_regression',
    status: 'failed',
    duration_ms: 12_431,
    totals: { tests: 18, passed: 17, failed: 1, skipped: 0 },
    failures: [
      {
        name: 'race_regression::concurrent_fixture_disposal',
        message: 'fixture disposed while job 42 was still running',
        location: 'tests/race_regression.rs:87',
      },
    ],
    environment: {
      os: 'macos',
      arch: 'aarch64',
      rust: '1.81.0',
      workers: 8,
      seed: 918_273,
    },
  },
  null,
  2,
);

const conversationItems: AgentTimelineItem[] = [
  item({
    id: 'user-1',
    type: 'user_message',
    role: 'user',
    content:
      'Please reproduce the flaky pipeline test, isolate the race without changing the public API, and leave verification evidence in this session.',
    eventTimeUs: (nowMs - 26 * HOUR) * 1000,
    eventCounter: 1,
    timestamp: nowMs - 26 * HOUR,
  }),
  item({
    id: 'thought-1',
    type: 'thought',
    content:
      'The runner shares a module-level fixture across jobs. I will inspect `src/pipeline/runner.py` first, then reproduce the race in an isolated worktree before touching the public API.',
    eventTimeUs: (nowMs - 25.8 * HOUR) * 1000,
    eventCounter: 2,
    timestamp: nowMs - 25.8 * HOUR,
  }),
  item({
    id: 'act-1',
    type: 'act',
    toolName: 'read_file',
    toolInput: { path: 'src/pipeline/runner.py', offset: 0, limit: 120 },
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 25.7 * HOUR) * 1000,
    eventCounter: 3,
    timestamp: nowMs - 25.7 * HOUR,
  }),
  item({
    id: 'observe-1',
    type: 'observe',
    toolName: 'read_file',
    toolOutput:
      'async def run_job(job: PipelineJob) -> Result:\n    # shared across jobs — race source\n    async with shared_fixture() as runner:\n        await runner.execute(job)\n        return runner.result',
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 25.7 * HOUR + 420) * 1000,
    eventCounter: 4,
    timestamp: nowMs - 25.7 * HOUR + 420,
  }),
  item({
    id: 'act-2',
    type: 'act',
    toolName: 'run_tests',
    toolInput: { command: 'pytest tests/pipeline -k race --count 50' },
    display: { kind: 'check' },
    eventTimeUs: (nowMs - 25.6 * HOUR) * 1000,
    eventCounter: 5,
    timestamp: nowMs - 25.6 * HOUR,
  }),
  item({
    id: 'observe-2',
    type: 'observe',
    toolName: 'run_tests',
    toolOutput: longTestReport,
    display: { kind: 'check' },
    eventTimeUs: (nowMs - 25.6 * HOUR + 12_431) * 1000,
    eventCounter: 6,
    timestamp: nowMs - 25.6 * HOUR + 12_431,
  }),
  item({
    id: 'act-edit-1',
    type: 'act',
    toolName: 'apply_patch',
    toolInput: { path: 'src/pipeline/runner.py' },
    display: { kind: 'edit', title: 'runner.py', summary: 'Scope fixture to job ID' },
    eventTimeUs: (nowMs - 25.5 * HOUR) * 1000,
    eventCounter: 7,
    timestamp: nowMs - 25.5 * HOUR,
  }),
  item({
    id: 'observe-edit-1',
    type: 'observe',
    toolName: 'apply_patch',
    toolOutput: { files_changed: 2, additions: 28, deletions: 9 },
    display: { kind: 'edit', title: 'runner.py', summary: 'Fixture scoped to job ID' },
    fileMetadata: { diffStat: { filesChanged: 2, additions: 28, deletions: 9 } },
    eventTimeUs: (nowMs - 25.5 * HOUR + 680) * 1000,
    eventCounter: 8,
    timestamp: nowMs - 25.5 * HOUR + 680,
  }),
  item({
    id: 'agent-1',
    type: 'assistant_message',
    role: 'assistant',
    content:
      '已定位竞态：共享可变状态让上一个任务的 runner 保持存活。修复方案：\n\n- 将 fixture 作用域收窄到 `job_id`\n- 增加并发回归覆盖\n\n```ts\nexport async function withIsolatedFixture<T>(\n  jobId: string,\n  run: (fixture: Fixture) => Promise<T>,\n): Promise<T> {\n  const fixture = await createFixture({ scope: jobId });\n  try {\n    return await run(fixture);\n  } finally {\n    await fixture.dispose();\n  }\n}\n```\n\n验证证据已同步到右侧变更面板。',
    metadata: {
      executionSummary: {
        step_count: 6,
        artifact_count: 2,
        call_count: 4,
        total_cost: 0.01842,
        total_cost_formatted: '$0.018420',
        total_tokens: { total: 12480 },
        tasks: { total: 3, completed: 3, remaining: 0 },
      },
    },
    eventTimeUs: (nowMs - 25.4 * HOUR) * 1000,
    eventCounter: 9,
    timestamp: nowMs - 25.4 * HOUR,
  }),
  item({
    id: 'user-2',
    type: 'user_message',
    role: 'user',
    content: '很好 — 把竞态回归也加到 CI。',
    eventTimeUs: (nowMs - 2 * HOUR) * 1000,
    eventCounter: 10,
    timestamp: nowMs - 2 * HOUR,
  }),
  item({
    id: 'subagent-started-1',
    type: 'subagent_started',
    payload: {
      subagent_name: 'Regression reviewer',
      task: 'Verify the concurrent disposal fix',
    },
    eventTimeUs: (nowMs - 1.99 * HOUR) * 1000,
    eventCounter: 11,
    timestamp: nowMs - 1.99 * HOUR,
  }),
  item({
    id: 'graph-run-started-1',
    type: 'graph_run_started',
    payload: { graph_name: 'Release validation', pattern: 'supervisor' },
    eventTimeUs: (nowMs - 1.98 * HOUR) * 1000,
    eventCounter: 12,
    timestamp: nowMs - 1.98 * HOUR,
  }),
  item({
    id: 'graph-handoff-1',
    type: 'graph_handoff',
    payload: {
      from_label: 'Planner',
      to_label: 'Reviewer',
      context_summary: 'Patch ready for verification',
    },
    eventTimeUs: (nowMs - 1.97 * HOUR) * 1000,
    eventCounter: 13,
    timestamp: nowMs - 1.97 * HOUR,
  }),
  item({
    id: 'graph-node-failed-1',
    type: 'graph_node_failed',
    payload: {
      node_label: 'Run regression tests',
      error_message: '1 test failed after 12.4s',
    },
    eventTimeUs: (nowMs - 1.96 * HOUR) * 1000,
    eventCounter: 14,
    timestamp: nowMs - 1.96 * HOUR,
  }),
  item({
    id: 'subagent-completed-1',
    type: 'subagent_completed',
    payload: {
      subagent_name: 'Patch reviewer',
      summary: 'Public API remains unchanged',
      success: true,
    },
    eventTimeUs: (nowMs - 1.95 * HOUR) * 1000,
    eventCounter: 15,
    timestamp: nowMs - 1.95 * HOUR,
  }),
  item({
    id: 'agent-spawned-1',
    type: 'agent_spawned',
    payload: {
      agent_name: 'Researcher',
      task_summary: 'Collect release evidence',
    },
    eventTimeUs: (nowMs - 1.945 * HOUR) * 1000,
    eventCounter: 16,
    timestamp: nowMs - 1.945 * HOUR,
  }),
  item({
    id: 'agent-message-sent-1',
    type: 'agent_message_sent',
    payload: {
      from_agent_name: 'Planner',
      to_agent_name: 'Reviewer',
      message_preview: 'Please verify the patch',
    },
    eventTimeUs: (nowMs - 1.94 * HOUR) * 1000,
    eventCounter: 17,
    timestamp: nowMs - 1.94 * HOUR,
  }),
  item({
    id: 'agent-message-received-1',
    type: 'agent_message_received',
    payload: {
      agent_name: 'Planner',
      from_agent_name: 'Reviewer',
      message_preview: 'Patch verified successfully',
    },
    eventTimeUs: (nowMs - 1.935 * HOUR) * 1000,
    eventCounter: 18,
    timestamp: nowMs - 1.935 * HOUR,
  }),
  item({
    id: 'agent-completed-1',
    type: 'agent_completed',
    payload: {
      agent_name: 'Verifier',
      result: 'Release gate failed',
      success: false,
    },
    eventTimeUs: (nowMs - 1.93 * HOUR) * 1000,
    eventCounter: 19,
    timestamp: nowMs - 1.93 * HOUR,
  }),
  item({
    id: 'agent-stopped-1',
    type: 'agent_stopped',
    payload: {
      agent_name: 'Researcher',
      reason: 'Superseded by a newer run',
    },
    eventTimeUs: (nowMs - 1.925 * HOUR) * 1000,
    eventCounter: 20,
    timestamp: nowMs - 1.925 * HOUR,
  }),
  item({
    id: 'parallel-started-1',
    type: 'parallel_started',
    payload: {
      task_count: 3,
      subtasks: [
        { subagent_name: 'Researcher', task: 'Collect evidence' },
        { subagent_name: 'Reviewer', task: 'Review evidence' },
        { subagent_name: 'Verifier', task: 'Verify the gate' },
      ],
    },
    eventTimeUs: (nowMs - 1.922 * HOUR) * 1000,
    eventCounter: 21,
    timestamp: nowMs - 1.922 * HOUR,
  }),
  item({
    id: 'chain-started-1',
    type: 'chain_started',
    payload: {
      total_steps: 3,
      step_names: ['Plan', 'Review', 'Verify'],
    },
    eventTimeUs: (nowMs - 1.919 * HOUR) * 1000,
    eventCounter: 22,
    timestamp: nowMs - 1.919 * HOUR,
  }),
  item({
    id: 'chain-step-started-1',
    type: 'chain_step_started',
    payload: {
      step_index: 0,
      step_name: 'Plan',
      task_preview: 'Prepare the release validation plan',
    },
    eventTimeUs: (nowMs - 1.916 * HOUR) * 1000,
    eventCounter: 23,
    timestamp: nowMs - 1.916 * HOUR,
  }),
  item({
    id: 'chain-step-completed-1',
    type: 'chain_step_completed',
    payload: {
      step_index: 0,
      step_name: 'Plan',
      summary: 'Validation plan prepared',
      success: true,
    },
    eventTimeUs: (nowMs - 1.913 * HOUR) * 1000,
    eventCounter: 24,
    timestamp: nowMs - 1.913 * HOUR,
  }),
  item({
    id: 'background-launched-1',
    type: 'background_launched',
    payload: {
      subagent_name: 'Auditor',
      task_description: 'Audit release evidence asynchronously',
    },
    eventTimeUs: (nowMs - 1.91 * HOUR) * 1000,
    eventCounter: 25,
    timestamp: nowMs - 1.91 * HOUR,
  }),
  item({
    id: 'chain-completed-1',
    type: 'chain_completed',
    payload: {
      steps_completed: 3,
      total_steps: 3,
      final_summary: 'Release chain complete',
      success: true,
    },
    eventTimeUs: (nowMs - 1.907 * HOUR) * 1000,
    eventCounter: 26,
    timestamp: nowMs - 1.907 * HOUR,
  }),
  item({
    id: 'parallel-completed-1',
    type: 'parallel_completed',
    payload: {
      total_tasks: 3,
      succeeded: 2,
      failed: 1,
      failed_agents: ['Reviewer'],
      results: [
        { subagent_name: 'Researcher', summary: 'Evidence collected', success: true },
        { subagent_name: 'Reviewer', summary: 'Review failed', success: false },
        { subagent_name: 'Verifier', summary: 'Gate verified', success: true },
      ],
    },
    eventTimeUs: (nowMs - 1.904 * HOUR) * 1000,
    eventCounter: 27,
    timestamp: nowMs - 1.904 * HOUR,
  }),
  item({
    id: 'execution-path-decided-1',
    type: 'execution_path_decided',
    payload: {
      path: 'react_loop',
      confidence: 0.92,
      reason: 'Complex task requires tools',
      target: 'workspace-agent',
    },
    eventTimeUs: (nowMs - 1.903 * HOUR) * 1000,
    eventCounter: 28,
    timestamp: nowMs - 1.903 * HOUR,
  }),
  item({
    id: 'selection-trace-1',
    type: 'selection_trace',
    payload: {
      domain_lane: 'code',
      initial_count: 12,
      final_count: 4,
      removed_total: 8,
      tool_budget: 4,
      budget_exceeded_stages: ['semantic_ranker_stage'],
    },
    eventTimeUs: (nowMs - 1.9025 * HOUR) * 1000,
    eventCounter: 29,
    timestamp: nowMs - 1.9025 * HOUR,
  }),
  item({
    id: 'policy-filtered-1',
    type: 'policy_filtered',
    payload: {
      domain_lane: 'code',
      removed_total: 3,
      stage_count: 2,
      budget_exceeded_stages: ['semantic_ranker_stage'],
    },
    eventTimeUs: (nowMs - 1.902 * HOUR) * 1000,
    eventCounter: 30,
    timestamp: nowMs - 1.902 * HOUR,
  }),
  item({
    id: 'tool-policy-denied-1',
    type: 'tool_policy_denied',
    payload: {
      agent_id: 'agent-main',
      tool_name: 'shell_command',
      policy_layer: 'workspace',
      denial_reason: 'Requires approval',
    },
    eventTimeUs: (nowMs - 1.9015 * HOUR) * 1000,
    eventCounter: 31,
    timestamp: nowMs - 1.9015 * HOUR,
  }),
  item({
    id: 'toolset-changed-1',
    type: 'toolset_changed',
    payload: {
      source: 'plugin_manager',
      plugin_name: 'github',
      action: 'install',
      refresh_status: 'success',
      refreshed_tool_count: 3,
    },
    eventTimeUs: (nowMs - 1.901 * HOUR) * 1000,
    eventCounter: 32,
    timestamp: nowMs - 1.901 * HOUR,
  }),
  item({
    id: 'skill-matched-1',
    type: 'skill_matched',
    payload: {
      skill_id: 'skill-release-guard',
      skill_name: 'Release guard',
      tools: ['read_file', 'shell_command'],
      match_score: 1,
      execution_mode: 'forced',
    },
    eventTimeUs: (nowMs - 1.9009 * HOUR) * 1000,
    eventCounter: 33,
    timestamp: nowMs - 1.9009 * HOUR,
  }),
  item({
    id: 'skill-execution-start-1',
    type: 'skill_execution_start',
    payload: {
      skill_id: 'skill-release-guard',
      skill_name: 'Release guard',
      query: 'Run release checks',
      total_steps: 2,
    },
    eventTimeUs: (nowMs - 1.9008 * HOUR) * 1000,
    eventCounter: 34,
    timestamp: nowMs - 1.9008 * HOUR,
  }),
  item({
    id: 'skill-tool-start-1',
    type: 'skill_tool_start',
    payload: {
      skill_id: 'skill-release-guard',
      skill_name: 'Release guard',
      tool_name: 'shell_command',
      tool_input: { command: 'pnpm test' },
      step_index: 1,
      total_steps: 2,
      status: 'running',
    },
    eventTimeUs: (nowMs - 1.9007 * HOUR) * 1000,
    eventCounter: 35,
    timestamp: nowMs - 1.9007 * HOUR,
  }),
  item({
    id: 'skill-tool-result-1',
    type: 'skill_tool_result',
    payload: {
      skill_id: 'skill-release-guard',
      skill_name: 'Release guard',
      tool_name: 'shell_command',
      result: 'All release checks passed',
      duration_ms: 812,
      step_index: 1,
      total_steps: 2,
      status: 'completed',
    },
    eventTimeUs: (nowMs - 1.9006 * HOUR) * 1000,
    eventCounter: 36,
    timestamp: nowMs - 1.9006 * HOUR,
  }),
  item({
    id: 'skill-execution-complete-1',
    type: 'skill_execution_complete',
    payload: {
      skill_id: 'skill-release-guard',
      skill_name: 'Release guard',
      success: true,
      summary: 'Release checks passed',
      tool_results: [
        { tool_name: 'read_file', status: 'completed' },
        { tool_name: 'shell_command', status: 'completed' },
      ],
      execution_time_ms: 1_240,
    },
    eventTimeUs: (nowMs - 1.9005 * HOUR) * 1000,
    eventCounter: 37,
    timestamp: nowMs - 1.9005 * HOUR,
  }),
  item({
    id: 'skill-fallback-1',
    type: 'skill_fallback',
    payload: {
      skill_name: 'Dependency auditor',
      reason: 'execution_error',
      error: 'Skill runtime unavailable; continuing with agent',
    },
    eventTimeUs: (nowMs - 1.9004 * HOUR) * 1000,
    eventCounter: 38,
    timestamp: nowMs - 1.9004 * HOUR,
  }),
  item({
    id: 'model-switch-requested-1',
    type: 'model_switch_requested',
    payload: {
      model: 'gpt-4.1',
      provider_type: 'openai',
      provider_name: 'OpenAI production',
      scope: 'next_turn',
      reason: 'Need deeper reasoning',
    },
    eventTimeUs: (nowMs - 1.9003 * HOUR) * 1000,
    eventCounter: 39,
    timestamp: nowMs - 1.9003 * HOUR,
  }),
  item({
    id: 'model-override-rejected-1',
    type: 'model_override_rejected',
    payload: {
      model: 'claude-sonnet-4',
      reason: 'Cross-provider switch not allowed',
      current_model: 'gpt-4.1',
      current_provider: 'openai',
    },
    eventTimeUs: (nowMs - 1.9002 * HOUR) * 1000,
    eventCounter: 40,
    timestamp: nowMs - 1.9002 * HOUR,
  }),
  item({
    id: 'context-status-1',
    type: 'context_status',
    payload: {
      current_tokens: 7_200,
      token_budget: 16_000,
      occupancy_pct: 45,
      compression_level: 'none',
      from_cache: false,
      messages_in_summary: 0,
    },
    eventTimeUs: (nowMs - 1.9001 * HOUR) * 1000,
    eventCounter: 41,
    timestamp: nowMs - 1.9001 * HOUR,
  }),
  item({
    id: 'context-compressed-1',
    type: 'context_compressed',
    payload: {
      was_compressed: true,
      compression_strategy: 'summarize',
      compression_level: 'moderate',
      original_message_count: 18,
      final_message_count: 10,
      estimated_tokens: 8_600,
      token_budget: 16_000,
      budget_utilization_pct: 53.8,
      summarized_message_count: 8,
      tokens_saved: 3_400,
      compression_ratio: 0.56,
      pruned_tool_outputs: 2,
      duration_ms: 38,
    },
    eventTimeUs: (nowMs - 1.9 * HOUR) * 1000,
    eventCounter: 42,
    timestamp: nowMs - 1.9 * HOUR,
  }),
  item({
    id: 'mcp-app-registered-1',
    type: 'mcp_app_registered',
    payload: {
      app_id: 'github-issue-board',
      server_name: 'github',
      tool_name: 'create_issue_board',
      source: 'agent_developed',
      resource_uri: 'ui://github/issue-board',
      title: 'Issue board',
    },
    eventTimeUs: (nowMs - 1.8999 * HOUR) * 1000,
    eventCounter: 43,
    timestamp: nowMs - 1.8999 * HOUR,
  }),
  item({
    id: 'mcp-app-result-1',
    type: 'mcp_app_result',
    payload: {
      app_id: 'github-issue-board',
      server_name: 'github',
      tool_name: 'create_issue_board',
      tool_input: { repository: 'memstack/agi-demos' },
      resource_uri: 'ui://github/issue-board',
      ui_metadata: { title: 'Issue board' },
      structured_content: { open: 12, closed: 34 },
    },
    eventTimeUs: (nowMs - 1.8998 * HOUR) * 1000,
    eventCounter: 44,
    timestamp: nowMs - 1.8998 * HOUR,
  }),
  item({
    id: 'memory-recalled-1',
    type: 'memory_recalled',
    payload: {
      memories: [
        { id: 'memory-1', category: 'semantic', title: 'Pipeline fixture isolation' },
        { id: 'memory-2', category: 'preference', title: 'Require regression evidence' },
        { id: 'memory-3', category: 'procedural', title: 'Verify in an isolated worktree' },
      ],
      count: 3,
      search_ms: 24,
    },
    eventTimeUs: (nowMs - 1.8997 * HOUR) * 1000,
    eventCounter: 45,
    timestamp: nowMs - 1.8997 * HOUR,
  }),
  item({
    id: 'memory-captured-1',
    type: 'memory_captured',
    payload: {
      captured_count: 2,
      categories: ['semantic', 'preference'],
    },
    eventTimeUs: (nowMs - 1.8996 * HOUR) * 1000,
    eventCounter: 46,
    timestamp: nowMs - 1.8996 * HOUR,
  }),
  item({
    id: 'task-start-1',
    type: 'task_start',
    payload: {
      task_id: 'release-task-2',
      content: 'Verify the release evidence',
      order_index: 1,
      total_tasks: 4,
    },
    eventTimeUs: (nowMs - 1.8995 * HOUR) * 1000,
    eventCounter: 47,
    timestamp: nowMs - 1.8995 * HOUR,
  }),
  item({
    id: 'task-complete-1',
    type: 'task_complete',
    payload: {
      task_id: 'release-task-3',
      status: 'failed',
      order_index: 2,
      total_tasks: 4,
    },
    eventTimeUs: (nowMs - 1.8994 * HOUR) * 1000,
    eventCounter: 48,
    timestamp: nowMs - 1.8994 * HOUR,
  }),
  item({
    id: 'artifact-created-1',
    type: 'artifact_created',
    artifactId: 'artifact-release-notes',
    filename: 'release-notes.md',
    payload: {
      artifact_id: 'artifact-release-notes',
      filename: 'release-notes.md',
      source_tool: 'export_artifact',
    },
    eventTimeUs: (nowMs - 1.8993 * HOUR) * 1000,
    eventCounter: 49,
    timestamp: nowMs - 1.8993 * HOUR,
  }),
  item({
    id: 'artifact-ready-1',
    type: 'artifact_ready',
    artifactId: 'artifact-verification-report',
    filename: 'verification-report.pdf',
    payload: {
      artifact_id: 'artifact-verification-report',
      filename: 'verification-report.pdf',
      source_tool: 'publish_report',
      url: 'https://artifacts.example/verification-report.pdf',
    },
    eventTimeUs: (nowMs - 1.8992 * HOUR) * 1000,
    eventCounter: 50,
    timestamp: nowMs - 1.8992 * HOUR,
  }),
  item({
    id: 'artifact-error-1',
    type: 'artifact_error',
    artifactId: 'artifact-broken-archive',
    filename: 'broken-archive.tar.gz',
    error: 'Upload checksum mismatch',
    payload: {
      artifact_id: 'artifact-broken-archive',
      filename: 'broken-archive.tar.gz',
      error: 'Upload checksum mismatch',
    },
    eventTimeUs: (nowMs - 1.8991 * HOUR) * 1000,
    eventCounter: 51,
    timestamp: nowMs - 1.8991 * HOUR,
  }),
  item({
    id: 'artifacts-batch-1',
    type: 'artifacts_batch',
    payload: {
      source_tool: 'export_release',
      artifacts: [
        { id: 'artifact-manifest', filename: 'manifest.json' },
        { id: 'artifact-checksums', filename: 'checksums.txt' },
      ],
    },
    eventTimeUs: (nowMs - 1.899 * HOUR) * 1000,
    eventCounter: 52,
    timestamp: nowMs - 1.899 * HOUR,
  }),
  item({
    id: 'act-3',
    type: 'act',
    toolName: 'shell_command',
    toolInput: { command: 'cargo test -p pipeline --test race_regression' },
    display: { kind: 'command' },
    eventTimeUs: (nowMs - 1.9 * HOUR) * 1000,
    eventCounter: 11,
    timestamp: nowMs - 1.9 * HOUR,
  }),
  item({
    id: 'observe-3',
    type: 'observe',
    toolName: 'shell_command',
    isError: true,
    display: { kind: 'command' },
    toolOutput:
      'error[E0432]: unresolved import `pipeline::shared_fixture`\n  --> tests/race_regression.rs:3:5\n\nnote: the fixture module was made private by the scoping fix',
    eventTimeUs: (nowMs - 1.9 * HOUR + 3_800) * 1000,
    eventCounter: 12,
    timestamp: nowMs - 1.9 * HOUR + 3_800,
  }),
  item({
    id: 'stream-1',
    type: 'assistant_message',
    role: 'assistant',
    message_id: 'msg-stream-1',
    content: '已修复导入并重新运行回归，目前 **17 项测试**通过，还有 1 项在重试验证。正在整理最终报告…',
    metadata: { streaming: true },
    eventTimeUs: (nowMs - 40_000) * 1000,
    eventCounter: 13,
    timestamp: nowMs - 40_000,
  }),
];

const workingIndicatorItems: AgentTimelineItem[] = [
  item({
    id: 'w-user-1',
    type: 'user_message',
    role: 'user',
    content: '把竞态回归加入 CI 之后，顺手更新流水线徽章状态。',
    eventTimeUs: (nowMs - 30_000) * 1000,
    eventCounter: 1,
    timestamp: nowMs - 30_000,
  }),
  item({
    id: 'w-act-1',
    type: 'act',
    toolName: 'read_file',
    toolInput: { path: '.github/workflows/pipeline.yml' },
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 20_000) * 1000,
    eventCounter: 2,
    timestamp: nowMs - 20_000,
  }),
  item({
    id: 'w-observe-1',
    type: 'observe',
    toolName: 'read_file',
    toolOutput: 'name: pipeline\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest',
    display: { kind: 'read' },
    eventTimeUs: (nowMs - 19_000) * 1000,
    eventCounter: 3,
    timestamp: nowMs - 19_000,
  }),
];

function timelineState(items: AgentTimelineItem[]): ConversationTimelineState {
  return {
    conversationId: 'conversation-qa',
    items,
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: null,
    lastCursor: null,
  };
}

function TimelineFixture({
  state,
  presence,
}: {
  state: ConversationTimelineState;
  presence: 'live' | 'recorded';
}) {
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  return (
    <AgentTimeline
      state={state}
      expandedItems={expandedItems}
      onToggleItem={(toggleItem) =>
        setExpandedItems((current) => ({
          ...current,
          [toggleItem.id]: !current[toggleItem.id],
        }))
      }
      onLoadEarlier={() => {}}
      onShowEarlier={() => {}}
      earlierRenderAllowance={0}
      onRetry={() => {}}
      onRespondToHitl={() => Promise.resolve()}
      respondableHitlRequestIds={[]}
      activityPresence={presence}
    />
  );
}

function SessionConversationQa() {
  useEffect(() => {
    // Open the interactive layers (groups, pairs, reasoning) so the capture
    // shows the expanded states without a scripted browser session.
    const timer = window.setTimeout(() => {
      document
        .querySelectorAll<HTMLElement>('.timeline-tool-group > summary')
        .forEach((element) => element.click());
      document
        .querySelectorAll<HTMLElement>('.tool-call .timeline-row-toggle')
        .forEach((element) => element.click());
      document
        .querySelectorAll<HTMLElement>('.message.timeline-row.thought .timeline-row-toggle')
        .forEach((element) => element.click());
    }, 350);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="session-workspace-thread" style={{ minHeight: '100%' }}>
      <section
        className="pane-shell chat-shell session-chat-narrative"
        style={{ maxWidth: 860, margin: '0 auto' }}
      >
        <div className="message-scroll">
          <div className="message-stack">
            <TimelineFixture state={timelineState(conversationItems)} presence="live" />
            <div style={{ height: 48 }} aria-hidden="true" />
            <TimelineFixture state={timelineState(workingIndicatorItems)} presence="live" />
          </div>
        </div>
      </section>
    </div>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__sessionConversationQaRoot) {
    globalThis.__sessionConversationQaRoot = createRoot(container);
  }
  globalThis.__sessionConversationQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
          <SessionConversationQa />
        </Theme>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
