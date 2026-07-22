import '@radix-ui/themes/styles.css';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CodeIcon,
  CubeIcon,
  GearIcon,
  GridIcon,
  HomeIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { ChatPanel } from '../features/chat/ChatPanel';
import type { ComposerCatalogClient } from '../features/chat/ComposerPlusMenu';
import { DesktopMCPAppCanvas } from '../features/chat/DesktopMCPAppCanvas';
import { LiveArtifactCanvas } from '../features/chat/LiveArtifactCanvas';
import {
  applyArtifactCanvasStreamEvent,
  emptyArtifactCanvasState,
  selectArtifactCanvasTab,
} from '../features/chat/artifactCanvasEventModel';
import {
  applyConversationTitleUpdate,
  readConversationTitleStreamEvent,
} from '../features/chat/conversationTitleEventModel';
import { applyHitlResponseStreamEvent } from '../features/chat/hitlResponseEventModel';
import { applyWorkspaceLifecycleStreamEvent } from '../features/chat/workspaceLifecycleEventModel';
import { applyWorkspaceMessageStreamEvent } from '../features/chat/workspaceMessageEventModel';
import { applyWorkspaceRosterStreamEvent } from '../features/chat/workspaceRosterEventModel';
import { applyWorkspaceTaskStreamEvent } from '../features/chat/workspaceTaskEventModel';
import {
  applyMCPAppCanvasStreamEvent,
  closeMCPAppCanvasTab,
  emptyMCPAppCanvasState,
  selectMCPAppCanvasTab,
} from '../features/chat/mcpAppCanvasEventModel';
import { SessionChangesCanvas } from '../features/session/SessionChangesCanvas';
import { SessionAgentsCanvas } from '../features/session/SessionAgentsCanvas';
import { SessionContextWindowCanvas } from '../features/session/SessionContextWindowCanvas';
import { SessionExecutionGraphCanvas } from '../features/session/SessionExecutionGraphCanvas';
import { SessionExecutionInsightsCanvas } from '../features/session/SessionExecutionInsightsCanvas';
import { SessionRuntimeInfrastructureCanvas } from '../features/session/SessionRuntimeInfrastructureCanvas';
import { buildSessionAgentTree } from '../features/session/sessionAgentTreeModel';
import { buildSessionContextWindow } from '../features/session/sessionContextWindowModel';
import { buildSessionExecutionGraph } from '../features/session/sessionExecutionGraphModel';
import { buildSessionExecutionInsights } from '../features/session/sessionExecutionInsightsModel';
import { buildSessionRuntimeInfrastructure } from '../features/session/sessionRuntimeInfrastructureModel';
import { toggleRunInputReference } from '../features/session/sessionChangesModel';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  AgentTimelineItem,
  ChangeSnapshot,
  CodeRangeReference,
  ConversationTimelineState,
  DesktopRunInput,
  RuntimeDataset,
  RunInputDelivery,
  WorkspaceMessage,
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
  WorkspaceTask,
} from '../types';
import '../styles.css';
import './sessionSteeringQa.css';

declare global {
  var __sessionSteeringQaRoot: Root | undefined;
}

const qaApi: ComposerCatalogClient = {
  listWorkspaceAgents: async () => [],
  listManagedAgents: async () => [],
  listManagedSkills: async () => [],
  listManagedPlugins: async () => [],
  uploadSandboxFile: async (file) => {
    await new Promise((resolve) => window.setTimeout(resolve, 180));
    return {
      filename: file.name,
      sandbox_path: `/workspace/input/${file.name}`,
      mime_type: file.type || 'application/octet-stream',
      size_bytes: file.size,
    };
  },
};

const snapshot: ChangeSnapshot = {
  id: 'change-snapshot-72e3a5b9',
  run_id: 'run-desktop-session-42',
  conversation_id: 'conversation-desktop-session',
  run_revision: 7,
  environment_id: 'environment-worktree-42',
  repository_root: '/workspace/memstack',
  workspace_path: '/workspace/.agistack-worktrees/desktop-session-42',
  branch: 'agistack/desktop-session-42',
  base_revision: '8f19c6e',
  head_revision: '8f19c6e',
  status: 'ready',
  additions: 8,
  deletions: 3,
  files_changed: 2,
  truncated: false,
  captured_at: '2026-07-13T12:30:00Z',
  files: [
    {
      path: 'src/session/steering.ts',
      status: 'modified',
      additions: 6,
      deletions: 3,
      binary: false,
      untracked: false,
      patch_digest: '0ac29be318f42861',
      hunks: [
        {
          header: '@@ -41,7 +41,10 @@ export function deliverInput',
          old_start: 41,
          new_start: 41,
          lines: [
            { kind: 'context', old_line: 41, new_line: 41, text: '  const run = authority.run;' },
            { kind: 'deletion', old_line: 42, new_line: null, text: '  return send(message);' },
            { kind: 'addition', old_line: null, new_line: 42, text: '  const input = bindToRevision(message, run.revision);' },
            { kind: 'addition', old_line: null, new_line: 43, text: '  await ledger.persist(input);' },
            { kind: 'addition', old_line: null, new_line: 44, text: '  return run.control.deliver(input);' },
            { kind: 'context', old_line: 43, new_line: 45, text: '}' },
          ],
        },
      ],
    },
    {
      path: 'src/session/changes.ts',
      status: 'added',
      additions: 2,
      deletions: 0,
      binary: false,
      untracked: true,
      patch_digest: 'af62d78a822cf890',
      hunks: [
        {
          header: '@@ -0,0 +1,2 @@',
          old_start: 0,
          new_start: 1,
          lines: [
            { kind: 'addition', old_line: null, new_line: 1, text: "export const scope = 'run';" },
            { kind: 'addition', old_line: null, new_line: 2, text: 'export const revision = 7;' },
          ],
        },
      ],
    },
  ],
};

const queuedInput: DesktopRunInput = {
  id: 'run-input-next-1',
  conversation_id: 'conversation-desktop-session',
  run_id: 'run-desktop-session-42',
  expected_run_revision: 7,
  message_id: 'message-next-1',
  idempotency_key: 'queue-next-1',
  delivery: 'queue_next',
  status: 'ready',
  sequence: 1,
  queue_position: 1,
  content: 'Run the compatibility matrix and prepare a migration plan.',
  references: [],
  created_at: '2026-07-13T10:10:00Z',
  updated_at: '2026-07-13T10:18:00Z',
};

const qaModelOptions = [
  { value: 'gpt-5.5', modelId: 'gpt-5.5', providerLabel: 'OpenAI production' },
  { value: 'gpt-5.5-mini', modelId: 'gpt-5.5-mini', providerLabel: 'OpenAI production' },
  { value: 'glm-5.2', modelId: 'glm-5.2', providerLabel: 'OpenAI-compatible' },
];

const messages: WorkspaceMessage[] = [
  {
    id: 'message-1',
    sender_type: 'user',
    content: 'Implement the authoritative steering path and keep revision conflicts explicit.',
    created_at: '2026-07-13T12:20:00Z',
  },
  {
    id: 'message-2',
    sender_type: 'agent',
    content: 'The run is active in an isolated worktree. I am applying the reviewed plan.',
    created_at: '2026-07-13T12:21:00Z',
  },
];

const workspaceMessageCreatedEvent = {
  type: 'workspace_message_created',
  data: {
    message: {
      id: 'message-live-workspace',
      workspace_id: 'workspace-desktop',
      sender_id: 'agent-release',
      sender_type: 'agent',
      content: 'Cloud workspace message arrived without a manual refresh.',
      mentions: [],
      created_at: '2026-07-22T09:00:00Z',
    },
  },
};

const workspaceTaskEvents = [
  {
    type: 'workspace_task_created',
    data: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-live-release',
      title: 'Verify live cloud task updates',
    },
  },
  {
    type: 'workspace_task_status_changed',
    data: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-live-release',
      new_status: 'in_progress',
    },
  },
];

const workspaceRosterEvents = [
  {
    type: 'workspace_member_joined',
    data: { workspace_id: 'workspace-desktop', member: {
      id: 'member-live', workspace_id: 'workspace-desktop', user_id: 'user-live', role: 'owner',
    } },
  },
  {
    type: 'workspace_agent_bound',
    data: { workspace_id: 'workspace-desktop', agent: {
      id: 'binding-live', workspace_id: 'workspace-desktop', agent_id: 'agent-live',
      display_name: 'Cloud release agent', is_active: true,
    } },
  },
];

const workspaceLifecycleDataset: RuntimeDataset = {
  workspaces: [
    {
      id: 'workspace-desktop', tenant_id: 'tenant-desktop', project_id: 'project-desktop',
      name: 'Workspace Alpha', created_by: 'user-live', is_archived: false,
      created_at: '2026-07-22T08:00:00Z',
    },
    {
      id: 'workspace-beta', tenant_id: 'tenant-desktop', project_id: 'project-desktop',
      name: 'Workspace Beta', created_by: 'user-live', is_archived: false,
      created_at: '2026-07-22T08:01:00Z',
    },
  ],
  workspacesByProject: {
    'project-desktop': [
      {
        id: 'workspace-desktop', tenant_id: 'tenant-desktop', project_id: 'project-desktop',
        name: 'Workspace Alpha', created_by: 'user-live', is_archived: false,
        created_at: '2026-07-22T08:00:00Z',
      },
      {
        id: 'workspace-beta', tenant_id: 'tenant-desktop', project_id: 'project-desktop',
        name: 'Workspace Beta', created_by: 'user-live', is_archived: false,
        created_at: '2026-07-22T08:01:00Z',
      },
    ],
  },
  conversationsByWorkspace: { 'workspace-desktop': [], 'workspace-beta': [] },
  nodeState: {
    projects: { 'project-desktop': { loading: false, error: null } },
    workspaces: {
      'workspace-desktop': { loading: false, error: null },
      'workspace-beta': { loading: false, error: null },
    },
  },
  messages: [],
  tasks: [],
  plan: null,
  workspaceMembers: { status: 'ready', items: [], error: null },
  workspaceAgents: { status: 'ready', items: [], error: null },
  sandbox: null,
  myWork: [],
  myWorkError: null,
};

const workspaceLifecycleEvents = [
  {
    type: 'workspace_updated',
    data: {
      workspace_id: 'workspace-desktop',
      workspace: {
        ...workspaceLifecycleDataset.workspaces[0],
        name: 'Workspace Renamed',
      },
    },
  },
  {
    type: 'workspace_deleted',
    data: { workspace_id: 'workspace-desktop' },
  },
];

const timelineState: ConversationTimelineState = {
  conversationId: 'conversation-desktop-session',
  items: [
    {
      id: 'message-user-goal',
      type: 'user_message',
      eventTimeUs: 1_784_282_041_000_000,
      eventCounter: 1,
      role: 'user',
      content:
        'Please reproduce the flaky pipeline test, isolate the race, and leave verification evidence.',
    },
    {
      id: 'message-agent-result',
      type: 'assistant_message',
      eventTimeUs: 1_784_282_042_000_000,
      eventCounter: 2,
      role: 'assistant',
      content:
        'I scoped fixture ownership to the job ID and added concurrent regression coverage.',
    },
    {
      id: 'verification-progress',
      type: 'task_updated',
      eventTimeUs: 1_784_282_043_000_000,
      eventCounter: 3,
      content: '18 tests passed · 50 race runs passed · static checks',
      display: {
        title: 'Verifying the isolated fix',
        summary: '18 tests passed · 50 race runs passed · static checks',
        checkpoint: 'Patch applied',
        evidence: '18 tests · 50 race runs',
      },
    },
  ],
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

const earlierTimelineItem: ConversationTimelineState['items'][number] = {
  id: 'message-earlier-context',
  type: 'assistant_message',
  eventTimeUs: 1_784_282_022_000_000,
  eventCounter: 0,
  role: 'assistant',
  content: 'I am checking the pipeline fixture ownership before reproducing the race.',
};

const anchorTimelineItems: ConversationTimelineState['items'] = [
  ...Array.from({ length: 18 }, (_, index) => ({
    id: `message-recorded-checkpoint-${index + 1}`,
    type: 'assistant_message',
    eventTimeUs: 1_784_282_023_000_000 + index * 1_000_000,
    eventCounter: index,
    role: 'assistant',
    content: `Recorded checkpoint ${index + 1}: pipeline ownership remained isolated.`,
  })),
  ...timelineState.items,
];

const concurrentTailItem: ConversationTimelineState['items'][number] = {
  id: 'message-concurrent-live-tail',
  type: 'assistant_message',
  eventTimeUs: 1_784_282_044_000_000,
  eventCounter: 4,
  role: 'assistant',
  content: 'A concurrent live update arrived while earlier history was loading.',
};

const suggestionTimelineItem: ConversationTimelineState['items'][number] = {
  id: 'agent-follow-up-suggestions',
  type: 'suggestions',
  eventTimeUs: 1_784_282_045_000_000,
  eventCounter: 5,
  payload: {
    suggestions: [
      'Open the verification report',
      'Run the compatibility matrix',
      'Prepare the migration checklist',
    ],
  },
};

const llmRuntimeTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'llm-runtime-assistant',
    type: 'assistant_message',
    eventTimeUs: 1_784_282_046_000_000,
    eventCounter: 6,
    role: 'assistant',
    content: 'The release verification completed after the provider recovered.',
    metadata: {
      executionSummary: {
        stepCount: 4,
        totalCost: 0.006,
        totalCostFormatted: '$0.006000',
        totalTokens: { total: 1_600 },
      },
      costTracking: {
        inputTokens: 1_200,
        outputTokens: 400,
        totalTokens: 1_600,
        costUsd: 0.006,
        model: 'gpt-5.5',
      },
    },
  },
  {
    id: 'llm-runtime-retry',
    type: 'retry',
    eventTimeUs: 1_784_282_047_000_000,
    eventCounter: 7,
    payload: {
      attempt: 2,
      delay_ms: 1_500,
      message: 'Provider rate limit',
    },
  },
];

const modelOverrideTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'model-switch-next-turn',
    type: 'model_switch_requested',
    eventTimeUs: 1_784_282_048_000_000,
    eventCounter: 8,
    payload: {
      model: 'gpt-5.5-mini',
      provider_type: 'openai',
      provider_name: 'OpenAI production',
      scope: 'next_turn',
      reason: 'Use the faster model for the next verification turn',
    },
  },
];

const subagentTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'subagent-review-routed',
    type: 'subagent_routed',
    eventTimeUs: 1_784_282_044_000_000,
    eventCounter: 4,
    payload: {
      subagent_id: 'regression-reviewer',
      subagent_name: 'Regression reviewer',
      confidence: 0.94,
      reason: 'Matched repository validation and lifecycle review capabilities',
    },
  },
  {
    id: 'subagent-review-started',
    type: 'subagent_started',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: {
      subagent_id: 'regression-reviewer',
      subagent_name: 'Regression reviewer',
      task: 'Verify concurrent session ownership and regression evidence.',
    },
  },
  {
    id: 'subagent-review-progress',
    type: 'subagent_session_update',
    eventTimeUs: 1_784_282_046_000_000,
    eventCounter: 6,
    payload: {
      subagent_id: 'regression-reviewer',
      subagent_name: 'Regression reviewer',
      progress: 70,
      status_message: 'Running the focused regression suite',
      tokens_used: 840,
      tool_calls_count: 4,
    },
  },
  {
    id: 'subagent-review-completed',
    type: 'subagent_completed',
    eventTimeUs: 1_784_282_047_000_000,
    eventCounter: 7,
    payload: {
      subagent_id: 'regression-reviewer',
      subagent_name: 'Regression reviewer',
      summary: 'Ownership is isolated and all focused regression checks pass.',
      tokens_used: 1240,
      execution_time_ms: 3450,
      success: true,
    },
  },
  {
    id: 'subagent-review-announce-sent',
    type: 'subagent_announce_sent',
    eventTimeUs: 1_784_282_048_000_000,
    eventCounter: 8,
    payload: {
      agent_id: 'regression-reviewer',
      session_id: 'session-regression-reviewer',
      parent_agent_id: 'main-agent',
      result_preview: 'Focused regression checks pass.',
    },
  },
  {
    id: 'subagent-review-announce-received',
    type: 'subagent_announce_received',
    eventTimeUs: 1_784_282_049_000_000,
    eventCounter: 9,
    payload: {
      agent_id: 'main-agent',
      session_id: 'session-regression-reviewer',
      from_agent_id: 'regression-reviewer',
      from_agent_name: 'Regression reviewer',
      result_preview: 'Focused regression checks pass with complete evidence.',
    },
  },
  {
    id: 'subagent-loop-delegation',
    type: 'subagent_delegation',
    eventTimeUs: 1_784_282_050_000_000,
    eventCounter: 10,
    payload: {
      conversation_id: 'conversation-desktop-session',
      from_agent_id: null,
      to_subagent_id: 'loop-investigator',
      to_subagent_name: 'Loop investigator',
      trigger_type: 'semantic',
      task_description: 'Inspect repeated terminal invocations.',
    },
  },
  {
    id: 'subagent-loop-started',
    type: 'subagent_started',
    eventTimeUs: 1_784_282_051_000_000,
    eventCounter: 11,
    payload: {
      subagent_id: 'loop-investigator',
      subagent_name: 'Loop investigator',
      task: 'Inspect repeated terminal invocations.',
    },
  },
  {
    id: 'subagent-loop-detected',
    type: 'subagent_doom_loop',
    eventTimeUs: 1_784_282_052_000_000,
    eventCounter: 12,
    payload: {
      subagent_id: 'loop-investigator',
      subagent_name: 'Loop investigator',
      reason: 'Repeated terminal invocation detected.',
      threshold: 3,
    },
  },
];

const multiAgentCanvasTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-coordinator-spawned',
    type: 'agent_spawned',
    eventTimeUs: 1_784_282_044_000_000,
    eventCounter: 4,
    payload: {
      agent_id: 'agent-coordinator',
      agent_name: 'Release coordinator',
      child_session_id: 'conversation-agent-coordinator',
      task_summary: 'Coordinate release evidence and independent verification.',
    },
  },
  {
    id: 'agent-reviewer-spawned',
    type: 'agent_spawned',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: {
      agent_id: 'agent-reviewer',
      agent_name: 'Evidence reviewer',
      parent_agent_id: 'agent-coordinator',
      child_session_id: 'conversation-agent-reviewer',
      task_summary: 'Review test evidence and artifact provenance.',
    },
  },
  {
    id: 'agent-investigator-spawned',
    type: 'agent_spawned',
    eventTimeUs: 1_784_282_046_000_000,
    eventCounter: 6,
    payload: {
      agent_id: 'agent-investigator',
      agent_name: 'Race investigator',
      parent_agent_id: 'agent-coordinator',
      child_session_id: 'conversation-agent-investigator',
      task_summary: 'Reproduce the concurrent fixture race 50 times.',
    },
  },
  {
    id: 'agent-coordinator-message',
    type: 'agent_message_sent',
    eventTimeUs: 1_784_282_047_000_000,
    eventCounter: 7,
    payload: {
      from_agent_id: 'agent-coordinator',
      from_agent_name: 'Release coordinator',
      to_agent_id: 'agent-reviewer',
      to_agent_name: 'Evidence reviewer',
      message_preview: 'Verify the report against the raw test output.',
    },
  },
  {
    id: 'agent-reviewer-completed',
    type: 'agent_completed',
    eventTimeUs: 1_784_282_048_000_000,
    eventCounter: 8,
    payload: {
      agent_id: 'agent-reviewer',
      session_id: 'conversation-agent-reviewer',
      success: true,
      result: 'All 18 checks have authoritative evidence.',
      artifacts: ['release-verification.md'],
    },
  },
];

const executionGraphCanvasTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'graph-release-started',
    type: 'graph_run_started',
    eventTimeUs: 1_784_282_050_000_000,
    eventCounter: 9,
    payload: {
      graph_run_id: 'graph-run-release',
      graph_id: 'graph-release',
      graph_name: 'Release verification',
      pattern: 'supervisor',
      entry_node_ids: ['graph-plan'],
    },
  },
  {
    id: 'graph-plan-started',
    type: 'graph_node_started',
    eventTimeUs: 1_784_282_051_000_000,
    eventCounter: 10,
    payload: {
      graph_run_id: 'graph-run-release',
      node_id: 'graph-plan',
      node_label: 'Plan release checks',
      agent_definition_id: 'release-planner',
      agent_session_id: 'conversation-graph-plan',
    },
  },
  {
    id: 'graph-plan-review-handoff',
    type: 'graph_handoff',
    eventTimeUs: 1_784_282_052_000_000,
    eventCounter: 11,
    payload: {
      graph_run_id: 'graph-run-release',
      from_node_id: 'graph-plan',
      to_node_id: 'graph-review',
      from_label: 'Plan release checks',
      to_label: 'Review evidence',
      context_summary: 'Release plan ready for independent evidence review.',
    },
  },
  {
    id: 'graph-plan-completed',
    type: 'graph_node_completed',
    eventTimeUs: 1_784_282_053_000_000,
    eventCounter: 12,
    payload: {
      graph_run_id: 'graph-run-release',
      node_id: 'graph-plan',
      node_label: 'Plan release checks',
      output_keys: ['release-plan.md'],
      duration_seconds: 2.4,
    },
  },
  {
    id: 'graph-review-started',
    type: 'graph_node_started',
    eventTimeUs: 1_784_282_054_000_000,
    eventCounter: 13,
    payload: {
      graph_run_id: 'graph-run-release',
      node_id: 'graph-review',
      node_label: 'Review evidence',
      agent_definition_id: 'evidence-reviewer',
      agent_session_id: 'conversation-graph-review',
    },
  },
  {
    id: 'graph-review-publish-handoff',
    type: 'graph_handoff',
    eventTimeUs: 1_784_282_055_000_000,
    eventCounter: 14,
    payload: {
      graph_run_id: 'graph-run-release',
      from_node_id: 'graph-review',
      to_node_id: 'graph-publish',
      from_label: 'Review evidence',
      to_label: 'Publish release',
      context_summary: 'All release gates have authoritative evidence.',
    },
  },
  {
    id: 'graph-review-completed',
    type: 'graph_node_completed',
    eventTimeUs: 1_784_282_056_000_000,
    eventCounter: 15,
    payload: {
      graph_run_id: 'graph-run-release',
      node_id: 'graph-review',
      node_label: 'Review evidence',
      output_keys: ['verification-report.md', 'test-results.json'],
      duration_seconds: 4.8,
    },
  },
  {
    id: 'graph-publish-started',
    type: 'graph_node_started',
    eventTimeUs: 1_784_282_057_000_000,
    eventCounter: 16,
    payload: {
      graph_run_id: 'graph-run-release',
      node_id: 'graph-publish',
      node_label: 'Publish release',
      agent_definition_id: 'release-publisher',
      agent_session_id: 'conversation-graph-publish',
    },
  },
];

const executionInsightsCanvasTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'insights-release-route',
    type: 'execution_path_decided',
    eventTimeUs: 1_784_282_058_000_000,
    eventCounter: 17,
    payload: {
      route_id: 'route-release-verification',
      trace_id: 'trace-release-verification',
      path: 'react_loop',
      confidence: 0.94,
      reason: 'Release verification requires governed tools and independent evidence.',
      target: 'workspace-agent',
      metadata: { domain_lane: 'code' },
    },
  },
  {
    id: 'insights-release-selection',
    type: 'selection_trace',
    eventTimeUs: 1_784_282_059_000_000,
    eventCounter: 18,
    payload: {
      route_id: 'route-release-verification',
      trace_id: 'trace-release-verification',
      domain_lane: 'code',
      initial_count: 12,
      final_count: 4,
      removed_total: 8,
      tool_budget: 4,
      budget_exceeded_stages: ['semantic_ranker'],
      stages: [
        {
          stage: 'capability_filter',
          before_count: 12,
          after_count: 7,
          removed_count: 5,
          duration_ms: 2.4,
          explain: { reason: 'Workspace capability boundary' },
        },
        {
          stage: 'semantic_ranker',
          before_count: 7,
          after_count: 4,
          removed_count: 3,
          duration_ms: 5.8,
        },
      ],
    },
  },
  {
    id: 'insights-release-policy',
    type: 'policy_filtered',
    eventTimeUs: 1_784_282_060_000_000,
    eventCounter: 19,
    payload: {
      route_id: 'route-release-verification',
      trace_id: 'trace-release-verification',
      domain_lane: 'code',
      removed_total: 3,
      stage_count: 2,
      tool_budget: 4,
      budget_exceeded_stages: ['semantic_ranker'],
    },
  },
  {
    id: 'insights-release-toolset',
    type: 'toolset_changed',
    eventTimeUs: 1_784_282_061_000_000,
    eventCounter: 20,
    payload: {
      trace_id: 'trace-release-verification',
      source: 'plugin_manager',
      action: 'install',
      plugin_name: 'github',
      refresh_status: 'success',
      refreshed_tool_count: 3,
      mutation_fingerprint: 'sha256:release-verification',
    },
  },
];

const contextWindowCanvasTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'context-release-status-before',
    type: 'context_status',
    eventTimeUs: 1_784_282_062_000_000,
    eventCounter: 21,
    payload: {
      current_tokens: 72_000,
      token_budget: 128_000,
      occupancy_pct: 56.25,
      compression_level: 'none',
      token_distribution: {
        system: 8_000,
        user: 12_000,
        assistant: 22_000,
        tool: 24_000,
        summary: 6_000,
      },
      compression_history_summary: {},
      from_cache: false,
      messages_in_summary: 0,
    },
  },
  {
    id: 'context-release-compressed',
    type: 'context_compressed',
    eventTimeUs: 1_784_282_063_000_000,
    eventCounter: 22,
    payload: {
      was_compressed: true,
      compression_strategy: 'summarize',
      compression_level: 'l2_summarize',
      original_message_count: 42,
      final_message_count: 26,
      estimated_tokens: 54_000,
      token_budget: 128_000,
      budget_utilization_pct: 42.2,
      summarized_message_count: 16,
      tokens_saved: 18_000,
      compression_ratio: 0.75,
      pruned_tool_outputs: 4,
      duration_ms: 46,
      token_distribution: {
        system: 8_000,
        user: 8_000,
        assistant: 16_000,
        tool: 12_000,
        summary: 10_000,
      },
      compression_history_summary: {
        total_compressions: 2,
        total_tokens_saved: 28_000,
        average_compression_ratio: 0.64,
        average_savings_pct: 36,
        recent_records: [
          {
            timestamp: '2026-07-22T08:02:00Z',
            level: 'l1_prune',
            tokens_before: 68_000,
            tokens_after: 58_000,
            tokens_saved: 10_000,
            compression_ratio: 0.85,
            savings_pct: 14.7,
            messages_before: 36,
            messages_after: 31,
            duration_ms: 18,
          },
          {
            timestamp: '2026-07-22T08:10:00Z',
            level: 'l2_summarize',
            tokens_before: 72_000,
            tokens_after: 54_000,
            tokens_saved: 18_000,
            compression_ratio: 0.75,
            savings_pct: 25,
            messages_before: 42,
            messages_after: 26,
            duration_ms: 46,
          },
        ],
      },
    },
  },
  {
    id: 'context-release-status-after',
    type: 'context_status',
    eventTimeUs: 1_784_282_064_000_000,
    eventCounter: 23,
    payload: {
      current_tokens: 61_000,
      token_budget: 128_000,
      occupancy_pct: 47.7,
      compression_level: 'l2_summarize',
      token_distribution: {},
      compression_history_summary: {},
      from_cache: true,
      messages_in_summary: 16,
    },
  },
];

const skillTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'skill-release-match',
    type: 'skill_matched',
    eventTimeUs: 1_784_282_044_000_000,
    eventCounter: 4,
    payload: {
      skill_id: 'release-guard',
      skill_name: 'Release guard',
      tools: ['read_file', 'shell_command'],
      match_score: 0.96,
      execution_mode: 'direct',
    },
  },
  {
    id: 'skill-release-start',
    type: 'skill_execution_start',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: {
      skill_id: 'release-guard',
      skill_name: 'Release guard',
      query: 'Run release checks and preserve the evidence.',
      total_steps: 2,
    },
  },
  {
    id: 'skill-release-tool-start',
    type: 'skill_tool_start',
    eventTimeUs: 1_784_282_046_000_000,
    eventCounter: 6,
    payload: {
      skill_id: 'release-guard',
      skill_name: 'Release guard',
      tool_name: 'shell_command',
      tool_input: { command: 'pnpm test' },
      step_index: 1,
      total_steps: 2,
      status: 'running',
    },
  },
  {
    id: 'skill-release-tool-result',
    type: 'skill_tool_result',
    eventTimeUs: 1_784_282_047_000_000,
    eventCounter: 7,
    payload: {
      skill_id: 'release-guard',
      skill_name: 'Release guard',
      tool_name: 'shell_command',
      result: 'All release checks passed',
      duration_ms: 812,
      step_index: 1,
      total_steps: 2,
      status: 'completed',
    },
  },
  {
    id: 'skill-release-complete',
    type: 'skill_execution_complete',
    eventTimeUs: 1_784_282_048_000_000,
    eventCounter: 8,
    payload: {
      skill_id: 'release-guard',
      skill_name: 'Release guard',
      success: true,
      summary: 'Release checks passed with complete evidence.',
      tool_results: [
        { tool_name: 'read_file', status: 'completed' },
        { tool_name: 'shell_command', status: 'completed' },
      ],
      execution_time_ms: 1240,
    },
  },
  {
    id: 'skill-audit-match',
    type: 'skill_matched',
    eventTimeUs: 1_784_282_049_000_000,
    eventCounter: 9,
    payload: {
      skill_id: 'dependency-auditor',
      skill_name: 'Dependency auditor',
      tools: ['dependency_scan'],
      match_score: 0.87,
      execution_mode: 'prompt',
    },
  },
  {
    id: 'skill-audit-fallback',
    type: 'skill_fallback',
    eventTimeUs: 1_784_282_050_000_000,
    eventCounter: 10,
    payload: {
      skill_id: 'dependency-auditor',
      skill_name: 'Dependency auditor',
      reason: 'runtime_unavailable',
      error: 'The managed scanner is temporarily unavailable.',
    },
  },
  {
    id: 'skill-research-match',
    type: 'skill_matched',
    eventTimeUs: 1_784_282_051_000_000,
    eventCounter: 11,
    payload: {
      skill_id: 'source-research',
      skill_name: 'Source research',
      tools: ['search', 'read_page', 'summarize'],
      match_score: 0.91,
      execution_mode: 'forced',
    },
  },
  {
    id: 'skill-research-start',
    type: 'skill_execution_start',
    eventTimeUs: 1_784_282_052_000_000,
    eventCounter: 12,
    payload: {
      skill_id: 'source-research',
      skill_name: 'Source research',
      query: 'Confirm the release behavior against primary sources.',
      total_steps: 3,
    },
  },
  {
    id: 'skill-research-tool-start',
    type: 'skill_tool_start',
    eventTimeUs: 1_784_282_053_000_000,
    eventCounter: 13,
    payload: {
      skill_id: 'source-research',
      skill_name: 'Source research',
      tool_name: 'search',
      tool_input: { query: 'release behavior primary source' },
      step_index: 0,
      total_steps: 3,
      status: 'running',
    },
  },
];

const memoryTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'memory-release-context',
    type: 'memory_recalled',
    eventTimeUs: 1_784_282_044_000_000,
    eventCounter: 4,
    payload: {
      count: 3,
      search_ms: 24,
      memories: [
        {
          id: 'memory-native-runner',
          content:
            'Launch the native Desktop client from the repository root with make -C agi-stack run-desktop so Tauri runtime, signing, and application-vault persistence match the supported development path.',
          score: 0.96,
          source: 'repository',
          category: 'procedural',
        },
        {
          id: 'memory-release-evidence',
          content:
            'Release reviews should include the focused regression result, the full suite result, production build output, and a rendered interaction check with console evidence. Keep each evidence item traceable to the exact client state that was exercised.',
          score: 0.91,
          source: 'project',
          category: 'preference',
        },
        {
          id: 'memory-event-rendering',
          content:
            'Agent protocol events should render as structured first-class cards rather than exposing raw payload JSON.',
          score: 0.86,
          source: 'project',
          category: 'semantic',
        },
      ],
    },
  },
  {
    id: 'memory-release-captured',
    type: 'memory_captured',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: {
      captured_count: 2,
      categories: ['procedural', 'preference'],
    },
  },
];

const runtimeInfrastructureTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'sandbox-runtime-created',
    type: 'sandbox_created',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: {
      sandbox_id: 'sandbox-release-1',
      status: 'running',
      endpoint: 'wss://sandbox.example/ws',
    },
  },
  {
    id: 'sandbox-desktop-started',
    type: 'desktop_started',
    eventTimeUs: 1_784_282_046_000_000,
    eventCounter: 6,
    payload: {
      sandbox_id: 'sandbox-release-1',
      resolution: '1280x720',
      display: ':1',
    },
  },
  {
    id: 'sandbox-terminal-started',
    type: 'terminal_started',
    eventTimeUs: 1_784_282_047_000_000,
    eventCounter: 7,
    payload: {
      sandbox_id: 'sandbox-release-1',
      session_id: 'terminal-release-1',
      url: 'wss://sandbox.example/terminal',
    },
  },
  {
    id: 'sandbox-terminal-stopped',
    type: 'terminal_status',
    eventTimeUs: 1_784_282_048_000_000,
    eventCounter: 8,
    payload: {
      sandbox_id: 'sandbox-release-1',
      session_id: 'terminal-release-1',
      running: false,
    },
  },
  {
    id: 'sandbox-runtime-error',
    type: 'sandbox_status',
    eventTimeUs: 1_784_282_049_000_000,
    eventCounter: 9,
    payload: {
      sandbox_id: 'sandbox-release-1',
      status: 'error',
      error_message: 'Runtime health probe failed',
    },
  },
];

const httpServiceTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'http-service-preview-started',
    type: 'http_service_started',
    eventTimeUs: 1_784_282_050_000_000,
    eventCounter: 10,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      source_type: 'sandbox_internal',
      service_url: 'http://172.17.0.2:5173',
      proxy_url: '/api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
      auto_open: true,
    },
  },
  {
    id: 'http-service-preview-updated',
    type: 'http_service_updated',
    eventTimeUs: 1_784_282_051_000_000,
    eventCounter: 11,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      source_type: 'sandbox_internal',
      service_url: 'http://172.17.0.2:4173',
      proxy_url: '/api/v1/projects/project-1/sandbox/http-services/service-preview-1/proxy/',
      status: 'running',
    },
  },
  {
    id: 'http-service-preview-stopped',
    type: 'http_service_stopped',
    eventTimeUs: 1_784_282_052_000_000,
    eventCounter: 12,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      status: 'stopped',
    },
  },
  {
    id: 'http-service-preview-error',
    type: 'http_service_error',
    eventTimeUs: 1_784_282_053_000_000,
    eventCounter: 13,
    payload: {
      sandbox_id: 'sandbox-release-1',
      service_id: 'service-preview-1',
      service_name: 'Vite preview',
      status: 'error',
      error_message: 'Preview port is not reachable',
    },
  },
];

const doomLoopTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'doom-loop-detected-terminal',
    type: 'doom_loop_detected',
    eventTimeUs: 1_784_282_054_000_000,
    eventCounter: 14,
    payload: {
      request_id: 'request-doom-loop-1',
      tool_name: 'terminal',
      call_count: 4,
      last_calls: [],
    },
  },
  {
    id: 'doom-loop-intervened-terminal',
    type: 'doom_loop_intervened',
    eventTimeUs: 1_784_282_055_000_000,
    eventCounter: 15,
    payload: {
      request_id: 'request-doom-loop-1',
      action: 'resume_with_guardrails',
    },
  },
];

const conversationTerminalTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-goal-completed-release',
    type: 'agent_goal_completed',
    eventTimeUs: 1_784_282_056_000_000,
    eventCounter: 16,
    payload: {
      conversation_id: 'conversation-release-1',
      actor_agent_id: 'coordinator',
      summary: 'Release verification completed with all requested checks passing',
      artifacts: ['release-report', 'verification-log'],
    },
  },
  {
    id: 'agent-conversation-finished-budget',
    type: 'agent_conversation_finished',
    eventTimeUs: 1_784_282_057_000_000,
    eventCounter: 17,
    payload: {
      conversation_id: 'conversation-budget-1',
      reason: 'budget_turns',
      actor: 'system',
      rationale: 'Turn budget reached before the remaining optional checks',
    },
  },
  {
    id: 'agent-conversation-finished-safety',
    type: 'agent_conversation_finished',
    eventTimeUs: 1_784_282_058_000_000,
    eventCounter: 18,
    payload: {
      conversation_id: 'conversation-safety-1',
      reason: 'safety_doom_loop',
      actor: 'supervisor',
      rationale: 'Repeated terminal calls remained unsafe after intervention',
    },
  },
];

const agentDefinitionTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-definition-created-release',
    type: 'agent_definition_created',
    eventTimeUs: 1_784_282_059_000_000,
    eventCounter: 19,
    payload: { agent_id: 'agent-release', agent_name: 'release_guardian' },
  },
  {
    id: 'agent-definition-updated-release',
    type: 'agent_definition_updated',
    eventTimeUs: 1_784_282_060_000_000,
    eventCounter: 20,
    payload: { agent_id: 'agent-release', agent_name: 'release_guardian' },
  },
  {
    id: 'agent-definition-deleted-release',
    type: 'agent_definition_deleted',
    eventTimeUs: 1_784_282_061_000_000,
    eventCounter: 21,
    payload: { agent_id: 'agent-release', agent_name: 'release_guardian' },
  },
];

const hitlResponseTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'clarification-cache-strategy',
    type: 'clarification_asked',
    eventTimeUs: 1_784_282_062_000_000,
    eventCounter: 22,
    requestId: 'clarification-cache-strategy',
    question: 'Which cache should protect the shared session state?',
    options: ['Redis', 'In-memory'],
  },
  {
    id: 'decision-release-window',
    type: 'decision_asked',
    eventTimeUs: 1_784_282_063_000_000,
    eventCounter: 23,
    requestId: 'decision-release-window',
    question: 'Should the verified patch ship in this release window?',
    options: ['Ship', 'Hold'],
  },
  {
    id: 'env-deployment-token',
    type: 'env_var_requested',
    eventTimeUs: 1_784_282_064_000_000,
    eventCounter: 24,
    requestId: 'env-deployment-token',
    question: 'Provide the deployment credential.',
    fields: [{ name: 'DEPLOY_TOKEN', label: 'Deployment token', required: true }],
  },
  {
    id: 'permission-release-command',
    type: 'permission_asked',
    eventTimeUs: 1_784_282_065_000_000,
    eventCounter: 25,
    requestId: 'permission-release-command',
    question: 'Allow the release verification command?',
    action: 'execute',
    resource: 'terminal',
    riskLevel: 'medium',
  },
  {
    id: 'a2ui-approve-release',
    type: 'a2ui_action_asked',
    eventTimeUs: 1_784_282_066_000_000,
    eventCounter: 26,
    requestId: 'a2ui-approve-release',
    question: 'Choose the release action.',
  },
];

const hitlResponseEvents = [
  {
    type: 'clarification_answered',
    data: { request_id: 'clarification-cache-strategy', answer: 'Redis' },
  },
  {
    type: 'decision_answered',
    data: { request_id: 'decision-release-window', decision: 'Ship' },
  },
  {
    type: 'env_var_provided',
    data: { request_id: 'env-deployment-token', saved_variables: ['DEPLOY_TOKEN'] },
  },
  {
    type: 'permission_replied',
    data: { request_id: 'permission-release-command', granted: true },
  },
  {
    type: 'a2ui_action_answered',
    data: { request_id: 'a2ui-approve-release', action_name: 'approve_release' },
  },
];

const elicitationTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'elicitation-pending-release-channel',
    type: 'elicitation_asked',
    eventTimeUs: 1_784_282_062_500_000,
    eventCounter: 27,
    payload: {
      request_id: 'elicitation-pending-release-channel',
      server_id: 'release-tools',
      server_name: 'Release MCP',
      message: 'Choose the release channel',
      requested_schema: {
        type: 'object',
        properties: { channel: { type: 'string' } },
      },
    },
  },
  {
    id: 'elicitation-release-region',
    type: 'elicitation_asked',
    eventTimeUs: 1_784_282_063_500_000,
    eventCounter: 28,
    payload: {
      request_id: 'elicitation-release-region',
      server_id: 'release-tools',
      server_name: 'Release MCP',
      message: 'Choose the release region',
      requested_schema: {
        type: 'object',
        properties: {
          region: { type: 'string' },
          api_token: { type: 'string' },
        },
      },
    },
  },
];

const elicitationResponseEvent = {
  type: 'elicitation_answered',
  data: {
    request_id: 'elicitation-release-region',
    response: { region: 'eu-west', api_token: 'qa-secret-must-never-render' },
  },
};

const a2uiCanvasComponents = [
  JSON.stringify({ beginRendering: { surfaceId: 'release-surface', root: 'release-root' } }),
  JSON.stringify({
    surfaceUpdate: {
      surfaceId: 'release-surface',
      components: [
        {
          id: 'release-root',
          component: { Column: { children: { explicitList: ['approve-button'] } } },
        },
        {
          id: 'approve-button',
          component: {
            Button: { child: 'approve-label', action: { name: 'approve_release' } },
          },
        },
        {
          id: 'approve-label',
          component: { Text: { text: { literalString: 'Approve verified release' } } },
        },
      ],
    },
  }),
].join('\n');

const a2uiCanvasTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'a2ui-release-canvas',
    type: 'canvas_updated',
    eventTimeUs: 1_784_282_062_000_000,
    eventCounter: 22,
    payload: {
      action: 'created',
      block_id: 'release-approval',
      block: {
        id: 'release-approval',
        block_type: 'a2ui_surface',
        title: 'Release approval',
        content: a2uiCanvasComponents,
      },
    },
  },
  {
    id: 'a2ui-release-action',
    type: 'a2ui_action_asked',
    eventTimeUs: 1_784_282_063_000_000,
    eventCounter: 23,
    requestId: 'a2ui-release-action',
    question: 'Approve the verified release?',
    payload: {
      request_id: 'a2ui-release-action',
      block_id: 'release-approval',
      allowed_actions: [
        { source_component_id: 'approve-button', action_name: 'approve_release' },
      ],
    },
  },
];

const a2uiCanvasDeletedTimelineItems: ConversationTimelineState['items'] = [
  a2uiCanvasTimelineItems[0]!,
  {
    id: 'a2ui-release-canvas-deleted',
    type: 'canvas_updated',
    eventTimeUs: 1_784_282_062_500_000,
    eventCounter: 24,
    payload: {
      action: 'deleted',
      block_id: 'release-approval',
      block: null,
    },
  },
  a2uiCanvasTimelineItems[1]!,
];

const a2uiCanvasIncrementalTimelineItems: ConversationTimelineState['items'] = [
  a2uiCanvasTimelineItems[0]!,
  {
    id: 'a2ui-release-canvas-updated',
    type: 'canvas_updated',
    eventTimeUs: 1_784_282_062_500_000,
    eventCounter: 24,
    payload: {
      action: 'updated',
      block_id: 'release-approval',
      block: {
        id: 'release-approval',
        block_type: 'a2ui_surface',
        title: 'Updated release approval',
        content: JSON.stringify({
          surfaceUpdate: {
            surfaceId: 'release-surface',
            components: [
              {
                id: 'approve-label',
                component: {
                  Text: { text: { literalString: 'Ship verified release' } },
                },
              },
            ],
          },
        }),
      },
    },
  },
  a2uiCanvasTimelineItems[1]!,
];

const planUiStateTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'plan-ui-state-enter',
    type: 'plan_mode_enter',
    eventTimeUs: 1_784_282_064_000_000,
    eventCounter: 25,
    payload: { plan_id: 'release-plan', reason: 'enter-plan-sentinel' },
  },
  {
    id: 'plan-ui-state-workplan-step',
    type: 'workplan_step_started',
    eventTimeUs: 1_784_282_064_500_000,
    eventCounter: 26,
    payload: { plan_id: 'release-plan', task: 'workplan-sentinel' },
  },
  {
    id: 'plan-ui-state-mode-changed',
    type: 'plan_mode_changed',
    eventTimeUs: 1_784_282_065_000_000,
    eventCounter: 27,
    payload: { conversation_id: 'conversation-desktop-session', mode: 'plan' },
  },
  {
    id: 'plan-reflection-complete',
    type: 'reflection_complete',
    eventTimeUs: 1_784_282_065_500_000,
    eventCounter: 28,
    payload: {
      plan_id: 'release-plan',
      assessment: 'continue',
      reasoning: 'Reflection kept visible',
      has_adjustments: false,
      adjustment_count: 0,
    },
  },
];

const taskUiStateTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'task-ui-state-list-updated',
    type: 'task_list_updated',
    eventTimeUs: 1_784_282_066_000_000,
    eventCounter: 29,
    payload: {
      tasks: [{ id: 'release-task', content: 'task-list-sentinel', status: 'pending' }],
    },
  },
  {
    id: 'task-ui-state-updated',
    type: 'task_updated',
    eventTimeUs: 1_784_282_066_500_000,
    eventCounter: 30,
    payload: {
      task: { id: 'release-task', content: 'task-update-sentinel', status: 'running' },
    },
  },
  {
    id: 'task-execution-started',
    type: 'task_start',
    eventTimeUs: 1_784_282_067_000_000,
    eventCounter: 31,
    payload: {
      task_id: 'release-task',
      content: 'Verify the release candidate',
      order_index: 0,
      total_tasks: 2,
    },
  },
  {
    id: 'task-execution-completed',
    type: 'task_complete',
    eventTimeUs: 1_784_282_067_500_000,
    eventCounter: 32,
    payload: {
      task_id: 'release-task',
      status: 'completed',
      order_index: 1,
      total_tasks: 2,
    },
  },
];

const internalUiStateTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'internal-pattern-match',
    type: 'pattern_match',
    eventTimeUs: 1_784_282_068_000_000,
    eventCounter: 33,
    payload: { pattern_name: 'internal-pattern-sentinel' },
  },
  {
    id: 'internal-context-summary',
    type: 'context_summary_generated',
    eventTimeUs: 1_784_282_068_500_000,
    eventCounter: 34,
    payload: { summary_id: 'internal-summary-sentinel' },
  },
  {
    id: 'internal-compact-needed',
    type: 'compact_needed',
    eventTimeUs: 1_784_282_069_000_000,
    eventCounter: 35,
    payload: { reason: 'internal-compact-sentinel' },
  },
  {
    id: 'internal-screenshot-update',
    type: 'screenshot_update',
    eventTimeUs: 1_784_282_069_500_000,
    eventCounter: 36,
    payload: {
      sandbox_id: 'sandbox-release',
      image_url: 'data:image/png;base64,internal-screenshot-sentinel',
    },
  },
  {
    id: 'visible-context-compressed',
    type: 'context_compressed',
    eventTimeUs: 1_784_282_070_000_000,
    eventCounter: 37,
    payload: {
      compression_strategy: 'context-visible-sentinel',
      compression_level: 'moderate',
      original_message_count: 12,
      final_message_count: 4,
    },
  },
];

const channelInboundMessageTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'channel-message-event',
    type: 'message',
    eventTimeUs: 1_784_282_071_000_000,
    eventCounter: 38,
    payload: {
      id: 'channel-message-feishu',
      role: 'user',
      content: 'Hello from Feishu',
      metadata: {
        source: 'channel_inbound',
        channel: 'feishu',
        chat_id: 'release-chat',
      },
    },
  },
  {
    id: 'internal-message-event',
    type: 'message',
    eventTimeUs: 1_784_282_071_500_000,
    eventCounter: 39,
    payload: {
      id: 'internal-message',
      role: 'user',
      content: 'internal-message-sentinel',
      metadata: { source: 'agent_runtime' },
    },
  },
  {
    id: 'malformed-channel-message-event',
    type: 'message',
    eventTimeUs: 1_784_282_072_000_000,
    eventCounter: 40,
    payload: {
      id: 'malformed-channel-message',
      role: 'system',
      content: 'malformed-message-sentinel',
      metadata: { source: 'channel_inbound' },
    },
  },
];

const toolsUpdatedTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'tools-updated-release-server',
    type: 'tools_updated',
    eventTimeUs: 1_784_282_073_000_000,
    eventCounter: 41,
    payload: {
      project_id: 'project-release',
      server_name: 'release-tools',
      tool_names: ['mcp__release__verify', 'mcp__release__publish'],
      requires_refresh: true,
    },
  },
];

const contextCompactedTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'context-compacted-release',
    type: 'context_compacted',
    eventTimeUs: 1_784_282_074_000_000,
    eventCounter: 42,
    payload: {
      conversation_id: 'conversation-release',
      before_tokens: 12_000,
      after_tokens: 4_500,
    },
  },
];

const sessionLifecycleTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'session-forked-release',
    type: 'session_forked',
    eventTimeUs: 1_784_282_075_000_000,
    eventCounter: 43,
    payload: {
      parent_conversation_id: 'conversation-parent',
      child_conversation_id: 'conversation-child',
    },
  },
  {
    id: 'session-merged-release',
    type: 'session_merged',
    eventTimeUs: 1_784_282_075_500_000,
    eventCounter: 44,
    payload: {
      parent_conversation_id: 'conversation-parent',
      child_conversation_id: 'conversation-child',
      merge_strategy: 'result_only',
    },
  },
];

const participantTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'participant-joined-release',
    type: 'conversation_participant_joined',
    eventTimeUs: 1_784_282_076_000_000,
    eventCounter: 45,
    payload: {
      conversation_id: 'conversation-desktop-session',
      agent_id: 'agent-reviewer',
      actor_id: 'agent-coordinator',
      role: 'participant',
    },
  },
  {
    id: 'participant-left-release',
    type: 'conversation_participant_left',
    eventTimeUs: 1_784_282_076_500_000,
    eventCounter: 46,
    payload: {
      conversation_id: 'conversation-desktop-session',
      agent_id: 'agent-reviewer',
      actor_id: 'agent-coordinator',
      reason: 'review completed',
    },
  },
];

const agentTaskTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-task-assigned-release',
    type: 'agent_task_assigned',
    eventTimeUs: 1_784_282_077_000_000,
    eventCounter: 47,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-coordinator',
      target_agent_id: 'agent-reviewer',
      task_id: 'task-release-review',
      task_title: 'Review the release evidence',
      rationale: 'Independent verification is required.',
    },
  },
  {
    id: 'agent-task-refused-release',
    type: 'agent_task_refused',
    eventTimeUs: 1_784_282_077_500_000,
    eventCounter: 48,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-reviewer',
      task_id: 'task-release-review',
      reason: 'Missing deployment credentials',
      suggested_reassignment: 'agent-operator',
    },
  },
  {
    id: 'agent-progress-declared-release',
    type: 'agent_progress_declared',
    eventTimeUs: 1_784_282_078_000_000,
    eventCounter: 49,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-reviewer',
      task_id: 'task-release-review',
      status: 'needs_review',
      summary: 'Ready for coordinator review',
      percent_complete: 75,
    },
  },
];

const agentGovernanceTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-human-input-release',
    type: 'agent_human_input_requested',
    eventTimeUs: 1_784_282_078_500_000,
    eventCounter: 50,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-reviewer',
      question: 'Approve the production rollout?',
      urgency: 'blocking',
      category: 'permission',
      rationale: 'Deployment changes production state.',
    },
  },
  {
    id: 'agent-escalated-release',
    type: 'agent_escalated',
    eventTimeUs: 1_784_282_079_000_000,
    eventCounter: 51,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-reviewer',
      escalated_to: 'human',
      reason: 'Release approval required',
      severity: 'high',
    },
  },
  {
    id: 'agent-conflict-release',
    type: 'agent_conflict_marked',
    eventTimeUs: 1_784_282_079_500_000,
    eventCounter: 52,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-reviewer',
      conflict_with: 'artifact-release-notes',
      summary: 'Release evidence mismatch',
      evidence: 'Checksum differs from the verified build.',
    },
  },
];

const agentAuditTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'agent-supervisor-verdict-release',
    type: 'agent_supervisor_verdict',
    eventTimeUs: 1_784_282_080_000_000,
    eventCounter: 53,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-supervisor',
      status: 'goal_drift',
      rationale: 'Implementation diverged from the release objective.',
      recommended_actions: ['restate goal', 'reassign review'],
      trigger: 'tick',
    },
  },
  {
    id: 'agent-decision-logged-release',
    type: 'agent_decision_logged',
    eventTimeUs: 1_784_282_080_500_000,
    eventCounter: 54,
    payload: {
      conversation_id: 'conversation-desktop-session',
      actor_agent_id: 'agent-reviewer',
      tool_name: 'mark_conflict',
      output_summary: 'Conflict recorded',
      rationale: 'Evidence mismatch requires adjudication.',
      latency_ms: 18,
    },
  },
];

const workspaceOrchestrationTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'workspace-goal-materialized-release',
    type: 'workspace_goal_materialized',
    eventTimeUs: 1_784_282_081_000_000,
    eventCounter: 55,
    payload: {
      workspace_id: 'workspace-desktop',
      goal_id: 'goal-release',
      goal_description: 'Validate and publish the release.',
    },
  },
  {
    id: 'workspace-decomposition-release',
    type: 'workspace_decomposition_complete',
    eventTimeUs: 1_784_282_081_500_000,
    eventCounter: 56,
    payload: {
      workspace_id: 'workspace-desktop',
      goal_id: 'goal-release',
      subtask_ids: ['task-security-review', 'task-docs', 'task-publish'],
      subtask_count: 3,
    },
  },
  {
    id: 'workspace-worker-dispatched-release',
    type: 'workspace_worker_dispatched',
    eventTimeUs: 1_784_282_082_000_000,
    eventCounter: 57,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      worker_agent_id: 'agent-security',
      attempt_id: 'attempt-1',
    },
  },
  {
    id: 'workspace-worker-report-release',
    type: 'workspace_worker_report_submitted',
    eventTimeUs: 1_784_282_082_500_000,
    eventCounter: 58,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      attempt_id: 'attempt-1',
      worker_agent_id: 'agent-security',
      status: 'completed',
    },
  },
  {
    id: 'workspace-adjudication-release',
    type: 'workspace_adjudication_complete',
    eventTimeUs: 1_784_282_083_000_000,
    eventCounter: 59,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      attempt_id: 'attempt-1',
      verdict: 'accepted',
      next_task_id: 'task-docs',
    },
  },
  {
    id: 'workspace-goal-completed-release',
    type: 'workspace_goal_completed',
    eventTimeUs: 1_784_282_083_500_000,
    eventCounter: 60,
    payload: {
      workspace_id: 'workspace-desktop',
      goal_id: 'goal-release',
      final_status: 'completed',
      completed_subtask_count: 3,
      total_subtask_count: 3,
    },
  },
];

const taskRecoveryTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'task-session-updated-release',
    type: 'task_execution_session_updated',
    eventTimeUs: 1_784_282_084_000_000,
    eventCounter: 61,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      health: 'degraded',
      session_status: 'initialization_failed',
      attempt_id: 'attempt-1',
      recommended_recovery_action: 'new_attempt',
    },
  },
  {
    id: 'task-incident-opened-release',
    type: 'task_execution_incident_opened',
    eventTimeUs: 1_784_282_084_500_000,
    eventCounter: 62,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      conversation_id: 'conversation-desktop-session',
      attempt_id: 'attempt-1',
      incident: {
        type: 'no_assistant_response',
        severity: 'error',
        summary: 'Conversation produced no assistant output.',
      },
    },
  },
  {
    id: 'task-recovery-started-release',
    type: 'task_recovery_action_started',
    eventTimeUs: 1_784_282_085_000_000,
    eventCounter: 63,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      action: 'new_attempt',
      status: 'queued',
      message: 'Fresh worker attempt queued.',
      attempt_id: 'attempt-1',
    },
  },
  {
    id: 'task-recovery-completed-release',
    type: 'task_recovery_action_completed',
    eventTimeUs: 1_784_282_085_500_000,
    eventCounter: 64,
    payload: {
      workspace_id: 'workspace-desktop',
      task_id: 'task-security-review',
      action: 'new_attempt',
      status: 'queued',
      message: 'Fresh worker attempt queued.',
      attempt_id: 'attempt-1',
    },
  },
];

const toolProgressTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'tool-progress-release-upload',
    type: 'progress',
    eventTimeUs: 1_784_282_086_000_000,
    eventCounter: 65,
    payload: {
      tool_name: 'release_uploader',
      progress_token: 'upload-release-bundle',
      progress: 42,
      total: 100,
      message: 'Uploading release bundle',
    },
  },
];

const titleGeneratedEvent = {
  type: 'title_generated',
  data: {
    conversation_id: 'conversation-desktop-session',
    title: 'Verify cloud session startup',
    generated_at: '2026-07-22T08:00:00Z',
  },
};

const artifactCanvasOpenEvents = [
  {
    type: 'artifact_open',
    data: {
      artifact_id: 'artifact-release-notes',
      title: 'release-notes.md',
      content: '# Cloud session release notes\n\nPreparing the verified rollout summary…',
      content_type: 'markdown',
      language: 'markdown',
    },
  },
  {
    type: 'artifact_open',
    data: {
      artifact_id: 'artifact-checklist',
      title: 'deployment-checklist.txt',
      content: '[x] Authenticated workspace\n[x] Model selected\n[ ] Final rollout verification',
      content_type: 'code',
      language: 'text',
    },
  },
];

const mcpAppResultEvent = {
  type: 'mcp_app_result',
  data: {
    app_id: 'release-verification-dashboard',
    tool_name: 'show_release_verification',
    server_name: 'release-tools',
    resource_uri: 'ui://release/verification-dashboard',
    resource_html: `<!doctype html>
      <html lang="en">
        <head>
          <meta charset="utf-8" />
          <style>
            body {
              margin: 0; padding: 24px; color: #172033;
              background: #f7f9fc; font: 14px system-ui;
            }
            main {
              padding: 22px; border: 1px solid #d8deea;
              border-radius: 12px; background: white;
            }
            h1 { margin: 0 0 8px; font-size: 22px; }
            p { color: #59657a; }
            dl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0; }
            dl div { padding: 14px; border-radius: 8px; background: #edf7f2; }
            dt { color: #667085; font-size: 12px; }
            dd { margin: 4px 0 0; color: #067647; font-size: 20px; font-weight: 700; }
            button {
              padding: 9px 13px; border: 0; border-radius: 7px;
              color: white; background: #6d45d8; cursor: pointer;
            }
            button + button { margin-left: 8px; }
            #details[hidden] { display: none; }
          </style>
        </head>
        <body>
          <main>
            <h1>Release verification dashboard</h1>
            <p>Interactive result returned by the release-tools plugin.</p>
            <dl>
              <div><dt>Checks</dt><dd>18/18</dd></div>
              <div><dt>Race runs</dt><dd>50</dd></div>
              <div><dt>Failures</dt><dd>0</dd></div>
            </dl>
            <button type="button" id="toggle">Show verified items</button>
            <button type="button" id="approve">Approve through host</button>
            <button type="button" id="message">Send follow-up to Agent</button>
            <p id="details" hidden>
              Authentication, model routing, session startup, and event rendering verified.
            </p>
            <p id="host-status" role="status">Connecting to Desktop host…</p>
          </main>
          <script>
            var nextRequestId = 1;
            var pendingRequests = {};
            var hostStatus = document.getElementById('host-status');
            function hostRequest(method, params) {
              return new Promise(function (resolve, reject) {
                var id = nextRequestId++;
                pendingRequests[id] = { resolve: resolve, reject: reject };
                window.parent.postMessage({ jsonrpc: '2.0', id: id, method: method, params: params }, '*');
              });
            }
            window.addEventListener('message', function (event) {
              var message = event.data;
              if (!message || message.jsonrpc !== '2.0' || message.id === undefined) return;
              var pending = pendingRequests[message.id];
              if (!pending) return;
              delete pendingRequests[message.id];
              if (message.error) pending.reject(new Error(message.error.message || 'Host request failed'));
              else pending.resolve(message.result);
            });
            hostRequest('ui/initialize', {
              appInfo: { name: 'release-verification-qa', version: '1.0.0' },
              appCapabilities: {},
              protocolVersion: '2026-01-26'
            }).then(function () {
              window.parent.postMessage({
                jsonrpc: '2.0', method: 'ui/notifications/initialized', params: {}
              }, '*');
              hostStatus.textContent = 'Connected to Desktop host';
            }).catch(function (error) {
              hostStatus.textContent = error.message;
            });
            document.getElementById('toggle').addEventListener('click', function () {
              var details = document.getElementById('details');
              details.hidden = !details.hidden;
              this.textContent = details.hidden ? 'Show verified items' : 'Hide verified items';
            });
            document.getElementById('approve').addEventListener('click', function () {
              hostStatus.textContent = 'Calling release tool…';
              hostRequest('tools/call', {
                name: 'approve_release', arguments: { release: '2026.07' }
              }).then(function (result) {
                hostStatus.textContent = result.isError ? 'Host tool call failed' : 'Host tool call approved';
              }).catch(function (error) {
                hostStatus.textContent = error.message;
              });
            });
            document.getElementById('message').addEventListener('click', function () {
              hostStatus.textContent = 'Sending follow-up…';
              hostRequest('ui/message', {
                role: 'user', content: [{ type: 'text', text: 'Summarize the release verification' }]
              }).then(function () {
                hostStatus.textContent = 'Follow-up accepted by Desktop host';
              }).catch(function (error) {
                hostStatus.textContent = error.message;
              });
            });
          </script>
        </body>
      </html>`,
    tool_input: { release: '2026.07' },
    tool_result: { content: [{ type: 'text', text: 'Verification complete' }] },
    structured_content: { checks: 18, race_runs: 50, failures: 0 },
    ui_metadata: { title: 'Release verification' },
    project_id: 'project-desktop',
  },
};

const mcpAppTimelineItems: ConversationTimelineState['items'] = [
  {
    id: 'mcp-app-release-registered',
    type: 'mcp_app_registered',
    eventTimeUs: 1_784_282_044_000_000,
    eventCounter: 4,
    payload: {
      app_id: 'release-verification-dashboard',
      server_name: 'release-tools',
      tool_name: 'show_release_verification',
      source: 'agent_developed',
      resource_uri: 'ui://release/verification-dashboard',
      title: 'Release verification',
    },
  },
  {
    id: 'mcp-app-release-result',
    type: 'mcp_app_result',
    eventTimeUs: 1_784_282_045_000_000,
    eventCounter: 5,
    payload: mcpAppResultEvent.data,
  },
];

const qaConversation: AgentConversation = {
  id: 'conversation-desktop-session',
  project_id: 'project-desktop',
  tenant_id: 'tenant-desktop',
  user_id: 'user-desktop',
  title: 'New Conversation',
  status: 'active',
  message_count: 2,
  created_at: '2026-07-22T07:59:00Z',
  workspace_id: 'workspace-desktop',
};

function SessionSteeringQa() {
  const searchParams = new URLSearchParams(window.location.search);
  const historyMode = searchParams.get('history');
  const suggestionsMode = searchParams.get('suggestions') === '1';
  const skillEventsMode = searchParams.get('skill-events') === '1';
  const subagentEventsMode = searchParams.get('subagent-events') === '1';
  const multiAgentCanvasMode = searchParams.get('multi-agent-canvas') === '1';
  const executionGraphCanvasMode = searchParams.get('execution-graph-canvas') === '1';
  const executionInsightsCanvasMode = searchParams.get('execution-insights-canvas') === '1';
  const contextWindowCanvasMode = searchParams.get('context-window-canvas') === '1';
  const runtimeInfrastructureCanvasMode =
    searchParams.get('runtime-infrastructure-canvas') === '1';
  const memoryEventsMode = searchParams.get('memory-events') === '1';
  const modelOverrideEventsMode = searchParams.get('model-override-events') === '1';
  const llmRuntimeEventsMode = searchParams.get('llm-runtime-events') === '1';
  const runtimeEventsMode = searchParams.get('runtime-events') === '1';
  const httpServiceEventsMode = searchParams.get('http-service-events') === '1';
  const doomLoopEventsMode = searchParams.get('doom-loop-events') === '1';
  const terminalEventsMode = searchParams.get('terminal-events') === '1';
  const agentDefinitionEventsMode = searchParams.get('agent-definition-events') === '1';
  const hitlResponseEventsMode = searchParams.get('hitl-response-events') === '1';
  const elicitationEventsMode = searchParams.get('elicitation-events') === '1';
  const a2uiCanvasEventsMode = searchParams.get('a2ui-canvas-events') === '1';
  const a2uiCanvasDeletedEventsMode = searchParams.get('a2ui-canvas-deleted') === '1';
  const a2uiCanvasIncrementalEventsMode =
    searchParams.get('a2ui-canvas-incremental') === '1';
  const planUiStateEventsMode = searchParams.get('plan-ui-state-events') === '1';
  const taskUiStateEventsMode = searchParams.get('task-ui-state-events') === '1';
  const internalUiStateEventsMode = searchParams.get('internal-ui-state-events') === '1';
  const channelInboundMessageMode = searchParams.get('channel-inbound-message') === '1';
  const toolsUpdatedEventMode = searchParams.get('tools-updated-event') === '1';
  const contextCompactedEventMode = searchParams.get('context-compacted-event') === '1';
  const sessionLifecycleEventsMode = searchParams.get('session-lifecycle-events') === '1';
  const participantEventsMode = searchParams.get('participant-events') === '1';
  const agentTaskEventsMode = searchParams.get('agent-task-events') === '1';
  const agentGovernanceEventsMode = searchParams.get('agent-governance-events') === '1';
  const agentAuditEventsMode = searchParams.get('agent-audit-events') === '1';
  const workspaceOrchestrationEventsMode =
    searchParams.get('workspace-orchestration-events') === '1';
  const taskRecoveryEventsMode = searchParams.get('task-recovery-events') === '1';
  const toolProgressEventMode = searchParams.get('tool-progress-event') === '1';
  const workspaceMessageEventMode = searchParams.get('workspace-message-event') === '1';
  const workspaceTaskEventMode = searchParams.get('workspace-task-event') === '1';
  const workspaceRosterEventMode = searchParams.get('workspace-roster-event') === '1';
  const workspaceLifecycleEventMode = searchParams.get('workspace-lifecycle-event') === '1';
  const titleEventsMode = searchParams.get('title-events') === '1';
  const artifactCanvasEventsMode = searchParams.get('artifact-canvas-events') === '1';
  const mcpAppEventsMode = searchParams.get('mcp-app-events') === '1';
  const [delivery, setDelivery] = useState<RunInputDelivery>('steer_now');
  const [references, setReferences] = useState<CodeRangeReference[]>([]);
  const [runInputs, setRunInputs] = useState<DesktopRunInput[]>([queuedInput]);
  const [model, setModel] = useState(
    modelOverrideEventsMode ? 'gpt-5.5-mini' : 'gpt-5.5',
  );
  const [qaMessages, setQaMessages] = useState(messages);
  const [qaTasks, setQaTasks] = useState<WorkspaceTask[]>([]);
  const [qaMembers, setQaMembers] = useState<WorkspaceAuthorityCollection<WorkspaceMemberSummary>>({
    status: 'ready', items: [], error: null,
  });
  const [qaAgents, setQaAgents] = useState<WorkspaceAuthorityCollection<WorkspaceAgentBinding>>({
    status: 'ready', items: [], error: null,
  });
  const [qaWorkspaceLifecycleSummary, setQaWorkspaceLifecycleSummary] = useState('pending');
  const [switchingModel, setSwitchingModel] = useState(false);
  const [artifactCanvas, setArtifactCanvas] = useState(() =>
    artifactCanvasEventsMode
      ? artifactCanvasOpenEvents.reduce(
          (state, event) => applyArtifactCanvasStreamEvent(state, event).state,
          emptyArtifactCanvasState(),
        )
      : emptyArtifactCanvasState(),
  );
  const [mcpAppCanvas, setMCPAppCanvas] = useState(() =>
    mcpAppEventsMode
      ? applyMCPAppCanvasStreamEvent(emptyMCPAppCanvasState(), mcpAppResultEvent).state
      : emptyMCPAppCanvasState(),
  );
  const openQaMCPAppResult = useCallback((item: AgentTimelineItem) => {
    setMCPAppCanvas((current) => applyMCPAppCanvasStreamEvent(current, item).state);
  }, []);
  const [mcpAppHostMessage, setMCPAppHostMessage] = useState('');
  const [a2uiCanvasResponse, setA2UICanvasResponse] = useState('');
  const [openedAgentSession, setOpenedAgentSession] = useState('');
  const sessionAgentTree = useMemo(
    () => buildSessionAgentTree(multiAgentCanvasMode ? multiAgentCanvasTimelineItems : []),
    [multiAgentCanvasMode],
  );
  const sessionExecutionGraph = useMemo(
    () =>
      buildSessionExecutionGraph(
        executionGraphCanvasMode ? executionGraphCanvasTimelineItems : [],
      ),
    [executionGraphCanvasMode],
  );
  const sessionExecutionInsights = useMemo(
    () =>
      buildSessionExecutionInsights(
        executionInsightsCanvasMode ? executionInsightsCanvasTimelineItems : [],
      ),
    [executionInsightsCanvasMode],
  );
  const sessionContextWindow = useMemo(
    () =>
      buildSessionContextWindow(
        contextWindowCanvasMode ? contextWindowCanvasTimelineItems : [],
      ),
    [contextWindowCanvasMode],
  );
  const sessionRuntimeInfrastructure = useMemo(
    () =>
      buildSessionRuntimeInfrastructure(
        runtimeInfrastructureCanvasMode
          ? [...runtimeInfrastructureTimelineItems, ...httpServiceTimelineItems]
          : [],
      ),
    [runtimeInfrastructureCanvasMode],
  );
  const mcpAppHostApi = useMemo(
    () => ({
      callMCPAppTool: async (_appId: string, toolName: string) => ({
        content: [{ type: 'text', text: `${toolName} accepted` }],
        is_error: false,
      }),
      readMCPAppResource: async (_projectId: string, uri: string) => ({
        contents: [{ uri, mimeType: 'text/plain', text: 'QA resource' }],
      }),
      listMCPAppResources: async () => ({ resources: [] }),
    }),
    [],
  );
  const [qaConversations, setQaConversations] = useState<AgentConversation[]>(() => [
    titleEventsMode ? qaConversation : { ...qaConversation, title: 'Session interaction redesign' },
  ]);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [timeline, setTimeline] = useState<ConversationTimelineState>(() => {
    const items =
      historyMode === 'anchor'
        ? anchorTimelineItems
        : suggestionsMode
          ? [...timelineState.items, suggestionTimelineItem]
          : skillEventsMode
            ? [...timelineState.items, ...skillTimelineItems]
            : multiAgentCanvasMode
              ? [...timelineState.items, ...multiAgentCanvasTimelineItems]
              : executionGraphCanvasMode
                ? [...timelineState.items, ...executionGraphCanvasTimelineItems]
              : executionInsightsCanvasMode
                ? [...timelineState.items, ...executionInsightsCanvasTimelineItems]
              : contextWindowCanvasMode
                ? [...timelineState.items, ...contextWindowCanvasTimelineItems]
              : runtimeInfrastructureCanvasMode
                ? [
                    ...timelineState.items,
                    ...runtimeInfrastructureTimelineItems,
                    ...httpServiceTimelineItems,
                  ]
            : mcpAppEventsMode
              ? [...timelineState.items, ...mcpAppTimelineItems]
              : subagentEventsMode
                ? [...timelineState.items, ...subagentTimelineItems]
                : memoryEventsMode
                  ? [...timelineState.items, ...memoryTimelineItems]
              : modelOverrideEventsMode
                ? [...timelineState.items, ...modelOverrideTimelineItems]
            : llmRuntimeEventsMode
            ? [...timelineState.items, ...llmRuntimeTimelineItems]
            : runtimeEventsMode
              ? [...timelineState.items, ...runtimeInfrastructureTimelineItems]
              : httpServiceEventsMode
                ? [...timelineState.items, ...httpServiceTimelineItems]
                : doomLoopEventsMode
                  ? [...timelineState.items, ...doomLoopTimelineItems]
                  : terminalEventsMode
                    ? [...timelineState.items, ...conversationTerminalTimelineItems]
                    : agentDefinitionEventsMode
                      ? [...timelineState.items, ...agentDefinitionTimelineItems]
                      : hitlResponseEventsMode
                        ? [...timelineState.items, ...hitlResponseTimelineItems]
                        : elicitationEventsMode
                          ? [...timelineState.items, ...elicitationTimelineItems]
                          : a2uiCanvasDeletedEventsMode
                          ? [...timelineState.items, ...a2uiCanvasDeletedTimelineItems]
                          : a2uiCanvasIncrementalEventsMode
                            ? [...timelineState.items, ...a2uiCanvasIncrementalTimelineItems]
                            : planUiStateEventsMode
                              ? [...timelineState.items, ...planUiStateTimelineItems]
                              : taskUiStateEventsMode
                                ? [...timelineState.items, ...taskUiStateTimelineItems]
                                : internalUiStateEventsMode
                                  ? [...timelineState.items, ...internalUiStateTimelineItems]
                                  : channelInboundMessageMode
                                    ? [...timelineState.items, ...channelInboundMessageTimelineItems]
                                    : toolsUpdatedEventMode
                                      ? [...timelineState.items, ...toolsUpdatedTimelineItems]
                                      : contextCompactedEventMode
                                        ? [...timelineState.items, ...contextCompactedTimelineItems]
                                        : sessionLifecycleEventsMode
                                          ? [...timelineState.items, ...sessionLifecycleTimelineItems]
                                          : participantEventsMode
                                            ? [...timelineState.items, ...participantTimelineItems]
                                            : agentTaskEventsMode
                                              ? [...timelineState.items, ...agentTaskTimelineItems]
                                              : agentGovernanceEventsMode
                                                ? [
                                                    ...timelineState.items,
                                                    ...agentGovernanceTimelineItems,
                                                  ]
                                                : agentAuditEventsMode
                                                  ? [
                                                      ...timelineState.items,
                                                      ...agentAuditTimelineItems,
                                                    ]
                                                  : workspaceOrchestrationEventsMode
                                                    ? [
                                                        ...timelineState.items,
                                                        ...workspaceOrchestrationTimelineItems,
                                                      ]
                                                    : taskRecoveryEventsMode
                                                      ? [
                                                          ...timelineState.items,
                                                          ...taskRecoveryTimelineItems,
                                                        ]
                                                      : toolProgressEventMode
                                                        ? [
                                                            ...timelineState.items,
                                                            ...toolProgressTimelineItems,
                                                          ]
                          : a2uiCanvasEventsMode
                            ? [...timelineState.items, ...a2uiCanvasTimelineItems]
                            : timelineState.items;
    return {
      ...timelineState,
      items,
      hasMore:
        historyMode === 'pagination' || historyMode === 'error' || historyMode === 'anchor',
      firstCursor: {
        timeUs: items[0]?.eventTimeUs ?? 0,
        counter: items[0]?.eventCounter ?? 0,
      },
      lastCursor: {
        timeUs: items[items.length - 1]?.eventTimeUs ?? 0,
        counter: items[items.length - 1]?.eventCounter ?? 0,
      },
    };
  });

  useEffect(() => {
    if (!workspaceRosterEventMode) return;
    const timer = window.setTimeout(() => {
      let members = qaMembers;
      let agents = qaAgents;
      for (const event of workspaceRosterEvents) {
        ({ members, agents } = applyWorkspaceRosterStreamEvent(
          members, agents, event, 'workspace-desktop',
        ));
      }
      setQaMembers(members);
      setQaAgents(agents);
    }, 600);
    return () => window.clearTimeout(timer);
  }, [workspaceRosterEventMode]);

  useEffect(() => {
    if (!workspaceLifecycleEventMode) return;
    const timer = window.setTimeout(() => {
      let current = workspaceLifecycleDataset;
      let nextWorkspaceId = 'workspace-desktop';
      for (const event of workspaceLifecycleEvents) {
        const result = applyWorkspaceLifecycleStreamEvent(current, event, {
          tenantId: 'tenant-desktop',
          projectId: 'project-desktop',
          workspaceId: 'workspace-desktop',
        });
        current = result.dataset;
        nextWorkspaceId = result.nextWorkspaceId;
      }
      const nextWorkspace = current.workspaces.find(({ id }) => id === nextWorkspaceId);
      setQaWorkspaceLifecycleSummary(
        `Workspaces ${current.workspaces.length} · Next ${nextWorkspace?.name ?? 'none'} · ` +
          `Cleared ${current.workspaceMembers.status === 'unavailable' ? 'yes' : 'no'}`,
      );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [workspaceLifecycleEventMode]);

  useEffect(() => {
    if (!workspaceTaskEventMode) return;
    const timer = window.setTimeout(() => {
      setQaTasks((current) =>
        workspaceTaskEvents.reduce(
          (tasks, event) =>
            applyWorkspaceTaskStreamEvent(tasks, event, 'workspace-desktop').tasks,
          current,
        ),
      );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [workspaceTaskEventMode]);

  useEffect(() => {
    if (!workspaceMessageEventMode) return;
    const timer = window.setTimeout(() => {
      setQaMessages((current) =>
        applyWorkspaceMessageStreamEvent(
          current,
          workspaceMessageCreatedEvent,
          'workspace-desktop',
        ).messages,
      );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [workspaceMessageEventMode]);

  useEffect(() => {
    if (!hitlResponseEventsMode) return;
    const timer = window.setTimeout(() => {
      setTimeline((current) => ({
        ...current,
        items: hitlResponseEvents.reduce(
          (items, event) => applyHitlResponseStreamEvent(items, event).items,
          current.items,
        ),
      }));
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [hitlResponseEventsMode]);

  useEffect(() => {
    if (!elicitationEventsMode) return;
    const timer = window.setTimeout(() => {
      setTimeline((current) => ({
        ...current,
        items: applyHitlResponseStreamEvent(
          current.items,
          elicitationResponseEvent,
        ).items,
      }));
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [elicitationEventsMode]);

  useEffect(() => {
    if (!titleEventsMode) return;
    const timer = window.setTimeout(() => {
      const titleEvent = readConversationTitleStreamEvent(titleGeneratedEvent);
      const update = titleEvent.update;
      if (!update) return;
      setQaConversations((current) =>
        applyConversationTitleUpdate(
          null,
          { 'workspace-desktop': current },
          update,
        ).conversationsByWorkspace['workspace-desktop'] ?? current,
      );
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [titleEventsMode]);

  useEffect(() => {
    if (!artifactCanvasEventsMode) return;
    const timer = window.setTimeout(() => {
      setArtifactCanvas((current) =>
        applyArtifactCanvasStreamEvent(current, {
          type: 'artifact_update',
          data: {
            artifact_id: 'artifact-release-notes',
            content: '\n\nCloud session release notes verified for Desktop Canvas.',
            append: true,
          },
        }).state,
      );
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [artifactCanvasEventsMode]);

  const qaConversationTitle = qaConversations[0]?.title ?? 'Conversation';

  const loadEarlierHistory = () => {
    setTimeline((current) => ({ ...current, loadingEarlier: true, error: null }));
    if (historyMode === 'anchor') {
      window.setTimeout(() => {
        setTimeline((current) => ({
          ...current,
          items: current.items.some((item) => item.id === concurrentTailItem.id)
            ? current.items
            : [...current.items, concurrentTailItem],
        }));
      }, 1000);
    }
    window.setTimeout(() => {
      if (historyMode === 'error' && historyAttempt === 0) {
        setHistoryAttempt(1);
        setTimeline((current) => ({
          ...current,
          loadingEarlier: false,
          error: 'Earlier history could not be loaded. Retry without losing this page.',
          hasMore: false,
        }));
        return;
      }
      setTimeline((current) => ({
        ...current,
        items: current.items.some((item) => item.id === earlierTimelineItem.id)
          ? current.items
          : [earlierTimelineItem, ...current.items],
        loadingEarlier: false,
        error: null,
        hasMore: false,
        firstCursor: {
          timeUs: earlierTimelineItem.eventTimeUs ?? 0,
          counter: earlierTimelineItem.eventCounter ?? 0,
        },
      }));
    }, historyMode === 'anchor' ? 2000 : 180);
  };

  const sendQaMessage = (content: string) => {
    if (!suggestionsMode) return;
    setTimeline((current) => {
      const eventTimeUs = (current.items[current.items.length - 1]?.eventTimeUs ?? 0) + 1_000_000;
      const eventCounter = (current.items[current.items.length - 1]?.eventCounter ?? 0) + 1;
      const nextItem: ConversationTimelineState['items'][number] = {
        id: `suggestion-user-message-${eventCounter}`,
        type: 'user_message',
        eventTimeUs,
        eventCounter,
        role: 'user',
        content,
      };
      return {
        ...current,
        items: [...current.items, nextItem],
        lastCursor: { timeUs: eventTimeUs, counter: eventCounter },
      };
    });
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="session-steering-qa-shell">
        <aside className="session-steering-qa-rail">
          <div className="session-steering-qa-brand"><CubeIcon /><strong>MemStack</strong></div>
          <button type="button"><PlusIcon /> New task</button>
          <nav>
            <button type="button"><HomeIcon /> Home</button>
            <button type="button"><GridIcon /> My work</button>
          </nav>
          <section>
            <span>WORKSPACE</span>
            <button type="button"><CubeIcon /> Desktop Client</button>
            <button type="button" className="selected">
              <ChatBubbleIcon /> {qaConversationTitle}
            </button>
          </section>
          <button type="button"><GearIcon /> Settings</button>
        </aside>
        <main>
          <header className="session-steering-qa-titlebar">
            <div>
              <CodeIcon />
              <span>
                <strong>{qaConversationTitle}</strong>
                <small>Code · Build · Running</small>
              </span>
            </div>
            <dl>
              <div><dt>Environment</dt><dd>Worktree</dd></div>
              <div><dt>Branch</dt><dd>agistack/desktop-session-42</dd></div>
              <div><dt>Run</dt><dd>run-desk · r7</dd></div>
            </dl>
          </header>
          <div className="session-steering-qa-content">
            <ChatPanel
              api={qaApi}
              conversations={qaConversations}
              selectedConversationId={
                workspaceMessageEventMode ? null : 'conversation-desktop-session'
              }
              messages={qaMessages}
              timelineState={workspaceMessageEventMode ? null : timeline}
              agentTaskSignals={[]}
              workflowCounts={{ changes: 2, plan: 'ready' }}
              sessionTitle={qaConversationTitle}
              scopeLabel="Current run narrative"
              composerVariant="session"
              composerResetKey="qa-session-steering"
              initialInput={
                suggestionsMode ? '' : 'Keep the public API stable and add the missing revision test.'
              }
              activityPresence={
                suggestionsMode ||
                skillEventsMode ||
                multiAgentCanvasMode ||
                executionGraphCanvasMode ||
                executionInsightsCanvasMode ||
                contextWindowCanvasMode ||
                subagentEventsMode ||
                memoryEventsMode ||
                modelOverrideEventsMode ||
                llmRuntimeEventsMode ||
                runtimeEventsMode ||
                httpServiceEventsMode ||
                doomLoopEventsMode ||
                hitlResponseEventsMode ||
                elicitationEventsMode ||
                a2uiCanvasEventsMode ||
                a2uiCanvasDeletedEventsMode ||
                a2uiCanvasIncrementalEventsMode ||
                planUiStateEventsMode ||
                taskUiStateEventsMode ||
                internalUiStateEventsMode ||
                channelInboundMessageMode ||
                toolsUpdatedEventMode ||
                contextCompactedEventMode ||
                sessionLifecycleEventsMode ||
                participantEventsMode ||
                agentTaskEventsMode ||
                agentGovernanceEventsMode ||
                agentAuditEventsMode ||
                workspaceOrchestrationEventsMode ||
                taskRecoveryEventsMode ||
                workspaceMessageEventMode ||
                workspaceTaskEventMode ||
                workspaceRosterEventMode ||
                workspaceLifecycleEventMode ||
                artifactCanvasEventsMode ||
                mcpAppEventsMode ||
                titleEventsMode
                  ? 'recorded'
                  : 'live'
              }
              activityStructuredEvidence={null}
              sending={false}
              disabledReason={null}
              activeWorkflowTarget="changes"
              modelLabel={model}
              modelOptions={qaModelOptions}
              selectedModelValue={model}
              modelSwitching={switchingModel}
              runtimeTargetLabel="Local Rust Core"
              runtimeTargetOptions={['Local Rust Core']}
              runInputDelivery={delivery}
              runInputDeliveryOptions={['steer_now', 'queue_next']}
              runInputs={runInputs}
              runInputsLoading={false}
              runInputsError={null}
              promotingRunInputId={null}
              runInputAuthorityRunId="run-desktop-session-42"
              respondableHitlRequestIds={
                a2uiCanvasEventsMode ||
                a2uiCanvasDeletedEventsMode ||
                a2uiCanvasIncrementalEventsMode
                  ? ['a2ui-release-action']
                  : []
              }
              references={references}
              onRunInputDeliveryChange={setDelivery}
              onPromoteRunInput={(input) =>
                setRunInputs((current) =>
                  current.map((candidate) =>
                    candidate.id === input.id
                      ? { ...candidate, status: 'promoted_to_plan' }
                      : candidate,
                  ),
                )
              }
              onRemoveReference={(reference) =>
                setReferences((current) => toggleRunInputReference(current, reference))
              }
              onSend={sendQaMessage}
              onRefresh={() => undefined}
              onLoadEarlier={loadEarlierHistory}
              onRespondToHitl={async (submission) => {
                if (!a2uiCanvasEventsMode && !a2uiCanvasIncrementalEventsMode) return;
                setA2UICanvasResponse(
                  `${submission.responseData.action_name}:${submission.responseData.source_component_id}`,
                );
              }}
              onWorkflowSelect={() => undefined}
              onModelChange={async (value) => {
                setSwitchingModel(true);
                await new Promise((resolve) => window.setTimeout(resolve, 180));
                setModel(value);
                setSwitchingModel(false);
              }}
              onModelReset={
                modelOverrideEventsMode
                  ? async () => {
                      setSwitchingModel(true);
                      await new Promise((resolve) => window.setTimeout(resolve, 180));
                      setModel('gpt-5.5');
                      setSwitchingModel(false);
                    }
                  : undefined
              }
              onRuntimeTargetChange={() => undefined}
              onOpenMCPAppResult={openQaMCPAppResult}
              onOpenCommands={() => undefined}
            />
            {a2uiCanvasResponse ? (
              <p data-testid="a2ui-canvas-response">{a2uiCanvasResponse}</p>
            ) : null}
            {workspaceTaskEventMode && qaTasks[0] ? (
              <p data-testid="workspace-task-stream">
                {qaTasks[0].title} · {qaTasks[0].status}
              </p>
            ) : null}
            {workspaceRosterEventMode ? (
              <p data-testid="workspace-roster-stream">
                Members {qaMembers.items.length} · Agents {qaAgents.items.length} ·{' '}
                {qaMembers.items[0]?.role ?? 'pending'}
              </p>
            ) : null}
            {workspaceLifecycleEventMode ? (
              <p data-testid="workspace-lifecycle-stream">{qaWorkspaceLifecycleSummary}</p>
            ) : null}
            {runtimeInfrastructureCanvasMode ? (
              <SessionRuntimeInfrastructureCanvas model={sessionRuntimeInfrastructure} />
            ) : contextWindowCanvasMode ? (
              <SessionContextWindowCanvas model={sessionContextWindow} />
            ) : executionInsightsCanvasMode ? (
              <SessionExecutionInsightsCanvas model={sessionExecutionInsights} />
            ) : executionGraphCanvasMode ? (
              <>
                <SessionExecutionGraphCanvas
                  model={sessionExecutionGraph}
                  onOpenSession={setOpenedAgentSession}
                />
                {openedAgentSession ? (
                  <p data-testid="opened-agent-session">{openedAgentSession}</p>
                ) : null}
              </>
            ) : multiAgentCanvasMode ? (
              <>
                <SessionAgentsCanvas
                  model={sessionAgentTree}
                  onOpenSession={setOpenedAgentSession}
                />
                {openedAgentSession ? (
                  <p data-testid="opened-agent-session">{openedAgentSession}</p>
                ) : null}
              </>
            ) : mcpAppEventsMode ? (
              <>
                <DesktopMCPAppCanvas
                  state={mcpAppCanvas}
                  api={mcpAppHostApi}
                  projectId="project-desktop"
                  sandboxProxyUrl="http://127.0.0.1:8000/static/sandbox_proxy.html"
                  onSendMessage={(message) => setMCPAppHostMessage(message)}
                  onSelect={(tabId) =>
                    setMCPAppCanvas((current) => selectMCPAppCanvasTab(current, tabId))
                  }
                  onClose={(tabId) =>
                    setMCPAppCanvas((current) => closeMCPAppCanvasTab(current, tabId))
                  }
                />
                {mcpAppHostMessage ? (
                  <p data-testid="mcp-app-host-message">{mcpAppHostMessage}</p>
                ) : null}
              </>
            ) : artifactCanvasEventsMode ? (
              <LiveArtifactCanvas
                state={artifactCanvas}
                onSelect={(artifactId) =>
                  setArtifactCanvas((current) => selectArtifactCanvasTab(current, artifactId))
                }
              />
            ) : (
              <SessionChangesCanvas
                snapshot={snapshot}
                loading={false}
                error={null}
                references={references}
                onRefresh={() => undefined}
                onToggleReference={(reference) =>
                  setReferences((current) => toggleRunInputReference(current, reference))
                }
              />
            )}
          </div>
        </main>
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');
const qaRoot = globalThis.__sessionSteeringQaRoot ?? createRoot(root);
globalThis.__sessionSteeringQaRoot = qaRoot;
qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <SessionSteeringQa />
    </I18nProvider>
  </React.StrictMode>,
);
