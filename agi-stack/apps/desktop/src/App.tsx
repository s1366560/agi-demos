import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import {
  Badge,
  Box,
  Button,
  Flex,
  Heading,
  IconButton,
  Text,
  Theme,
  Tooltip,
} from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ArrowUpIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  ClockIcon,
  CodeIcon,
  CommitIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ColumnsIcon,
  Cross2Icon,
  DashboardIcon,
  DotsHorizontalIcon,
  DesktopIcon,
  EnterFullScreenIcon,
  ExitFullScreenIcon,
  FileTextIcon,
  FrameIcon,
  GearIcon,
  GridIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  ReaderIcon,
  RocketIcon,
  ExclamationTriangleIcon,
  StopIcon,
  ViewVerticalIcon,
} from '@radix-ui/react-icons';

import { desktopApiCredential, DesktopApiClient } from './api/client';
import {
  ingestLocalMemory,
  searchLocalMemory,
  semanticSearchLocalMemory,
} from './api/localMemory';
import { AuthPanel } from './features/auth/AuthPanel';
import { BoardPanel } from './features/board/BoardPanel';
import {
  ChatPanel,
  type AgentTaskSignal,
  type AgentTaskSignalStatus,
  type ChatWorkflowTarget,
} from './features/chat/ChatPanel';
import { ComposerControls } from './features/chat/ComposerControls';
import { markA2UIActionAnswered } from './features/chat/a2uiAction';
import { RuntimeConfigPanel } from './features/runtime/RuntimeConfigPanel';
import { StatusPanel } from './features/status/StatusPanel';
import { WorkspaceDock } from './features/workspace/WorkspaceDock';
import { useAgentSocket } from './hooks/useAgentSocket';
import { useTerminalProxy } from './hooks/useTerminalProxy';
import type {
  AgentConversation,
  AgentTimelineItem,
  AuthState,
  BoardMode,
  ConnectionState,
  ConversationTimelineState,
  DesktopRuntimeConfig,
  DesktopServiceResponse,
  HitlResponseSubmission,
  LocalRuntimeStatus,
  LocalMemoryResult,
  PlanSnapshot,
  ProjectSummary,
  ProjectSandbox,
  RuntimeNodeLoadState,
  RuntimeDataset,
  StatusTab,
  TerminalServiceResponse,
  WorkbenchSection,
  WorkspaceSummary,
  WorkspaceTask,
} from './types';
import { DEFAULT_CONFIG, mergeLocalRuntimeStatus } from './types';

const emptyDataset: RuntimeDataset = {
  workspaces: [],
  workspacesByProject: {},
  conversationsByWorkspace: {},
  nodeState: { projects: {}, workspaces: {} },
  messages: [],
  tasks: [],
  plan: null,
  sandbox: null,
};

const emptyAuthState: AuthState = {
  status: 'signed_out',
  user: null,
  tenants: [],
  projects: [],
  mustChangePassword: false,
  error: null,
};

const emptyConversationTimeline: ConversationTimelineState = {
  conversationId: null,
  items: [],
  loading: false,
  loadingEarlier: false,
  error: null,
  hasMore: false,
  firstCursor: null,
  lastCursor: null,
};

const DEFAULT_WORKSPACE_NAME = 'Desktop workspace';

const formatDesktopWorkspaceName = () => {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  return `${DEFAULT_WORKSPACE_NAME} ${date} ${time}`;
};

const resolveNewWorkspaceName = (draft: string) => {
  const trimmed = draft.trim();
  return !trimmed || trimmed === DEFAULT_WORKSPACE_NAME ? formatDesktopWorkspaceName() : trimmed;
};

type CommandPaletteItem = {
  id: string;
  label: string;
  description: string;
  icon: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  onSelect: () => void;
};

type WorkflowTarget =
  | 'changes'
  | 'pull'
  | 'plan'
  | 'board'
  | 'background'
  | 'artifacts'
  | 'runtime';
type SessionGroupMode = 'recent' | 'project';
type RunControlState = 'planning' | 'running' | 'paused' | 'stopped';
type RunDotTone = RunControlState | 'completed' | 'failed' | 'idle';
const runControlLabels: Record<RunControlState, string> = {
  planning: 'Planning',
  running: 'Running',
  paused: 'Paused',
  stopped: 'Stopped',
};
const RUN_CONTROL_UNAVAILABLE =
  'Run pause, resume, and stop are unavailable until every configured backend provides the same control contract.';
const REVIEW_ACTION_UNAVAILABLE =
  'Workspace packet review is read-only. Respond to an explicit Agent HITL request in Chat.';
const runControlStates = new Set<RunControlState>(['planning', 'running', 'paused', 'stopped']);
function isRunControlState(value: string): value is RunControlState {
  return runControlStates.has(value as RunControlState);
}

function runToneFromStatus(status: string): RunDotTone {
  const normalized = status.trim().toLowerCase();
  if (isRunControlState(normalized)) return normalized;
  if (normalized === 'completed' || normalized === 'complete' || normalized === 'done') {
    return 'completed';
  }
  if (normalized === 'failed' || normalized === 'error') return 'failed';
  if (normalized === 'active') return 'running';
  return 'idle';
}

function runLabelFromStatus(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (isRunControlState(normalized)) return runControlLabels[normalized];
  if (normalized === 'active') return 'Running';
  if (normalized === 'completed' || normalized === 'complete' || normalized === 'done') {
    return 'Completed';
  }
  if (normalized === 'failed' || normalized === 'error') return 'Failed';
  return status;
}

function runStatusLabel(state: RunControlState | undefined, fallback: string): string {
  return state ? runControlLabels[state] : runLabelFromStatus(fallback);
}

type RuntimeTarget = 'local' | 'staging';
const runtimeTargetLabels: Record<RuntimeTarget, string> = {
  local: 'Local Rust Core',
  staging: 'Staging Runtime',
};
const titlebarRuntimeTargetLabels: Record<RuntimeTarget, string> = {
  local: 'Local Rust Core',
  staging: 'Remote staging',
};
const runtimeTargetComposerOptions = Object.values(runtimeTargetLabels);
type RuntimeHealthState = 'healthy' | 'starting' | 'waiting' | 'offline' | 'error';
const runtimeHealthLabels: Record<RuntimeHealthState, string> = {
  healthy: 'Healthy',
  starting: 'Starting',
  waiting: 'Waiting',
  offline: 'Offline',
  error: 'Error',
};
const runtimeHealthBadgeColors: Record<RuntimeHealthState, 'gray' | 'blue' | 'green' | 'red'> = {
  healthy: 'green',
  starting: 'blue',
  waiting: 'gray',
  offline: 'gray',
  error: 'red',
};
type QuickLinkItem = {
  id: string;
  section: WorkbenchSection;
  target?: WorkflowTarget;
  label: string;
  icon: ReactNode;
};
type SidebarRunItem = {
  id: string;
  label: string;
  status: string;
  meta: string;
  time: string;
  sortTime: number;
  projectId: string;
  workspaceId?: string;
  conversation?: AgentConversation;
};
type SessionScopeKind = 'project' | 'worktree' | 'branch';
type ComposerReferenceKind = 'files' | 'issues';
type MobileTitlebarMenuItem = {
  id: string;
  label: string;
  icon: ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};
type ReviewTab =
  | 'changes'
  | 'pull'
  | 'plan'
  | 'background'
  | 'artifacts'
  | 'terminal';
type WorkspaceEventKind = 'Tools' | 'Reasoning' | 'Messages' | 'System' | 'Errors';
type WorkspaceEventRecord = {
  id: string;
  kind: WorkspaceEventKind;
  eventType: string;
  source: string;
  status: string;
  detail: string;
  time: string;
  latency: string;
  sortTime: number;
  raw: unknown;
  searchableText: string;
};
const workspaceEventFilterItems: Array<WorkspaceEventKind | 'All'> = [
  'All',
  'Tools',
  'Reasoning',
  'Messages',
  'System',
  'Errors',
];
type WorkspaceArtifactKind = 'Files' | 'Patches' | 'Reports' | 'Logs' | 'Events';
type WorkspaceArtifactSort = 'recent' | 'largest' | 'name';
type WorkspaceArtifactView = 'list' | 'grid';
type WorkspaceArtifact = {
  id: string;
  name: string;
  path: string;
  kind: WorkspaceArtifactKind;
  source: string;
  status: string;
  time: string;
  sortTime: number;
  size: string;
  diff: string;
  preview: string;
  raw: unknown;
  searchableText: string;
};
const workspaceArtifactKindLabels: Record<WorkspaceArtifactKind, string> = {
  Files: 'File',
  Patches: 'Patch',
  Reports: 'Report',
  Logs: 'Log',
  Events: 'Event',
};
type ReviewDecisionStatus = 'pending' | 'approved' | 'changes';
type ReviewDecisionRecordStatus = Exclude<ReviewDecisionStatus, 'pending'> | 'snoozed';
type ReviewDecisionArtifact = {
  id: string;
  name: string;
  path: string;
  meta: string;
  diff: string;
};
type ReviewDecisionSummary = {
  title: string;
  summary: string;
  reasoning: string;
  risk: 'Low' | 'Medium' | 'High';
  changeValue: string;
  filesChanged: number;
  artifacts: ReviewDecisionArtifact[];
  checks: Array<{ label: string; value: string }>;
  canAct: boolean;
};
type ReviewDecisionRecord = {
  id: string;
  status: ReviewDecisionRecordStatus;
  label: string;
  detail: string;
  time: string;
};
type ReviewPullRequestCheckStatus = 'passed' | 'pending' | 'failed';
type ReviewPullRequestSummary = {
  title: string;
  summary: string;
  status: string;
  branch: string;
  base: string;
  risk: ReviewDecisionSummary['risk'];
  diff: string;
  filesChanged: number;
  canAct: boolean;
  checks: Array<{ label: string; value: string; status: ReviewPullRequestCheckStatus }>;
  files: ReviewDecisionArtifact[];
  activity: Array<{ id: string; time: string; label: string; detail: string; status: string }>;
};

type AgentConversationSession = {
  scopeKey: string;
  conversation: AgentConversation;
};

type AgentTaskSignalPatch = Partial<Omit<AgentTaskSignal, 'id'>> & {
  id: string;
};

function detectTauriShell(): boolean {
  if (typeof window === 'undefined') return false;
  return Boolean(
    window.__TAURI__?.core?.invoke ||
      window.__TAURI_INTERNALS__ ||
      document.documentElement.hasAttribute('data-tauri-window'),
  );
}

function localRuntimeTauriConfig(config: DesktopRuntimeConfig) {
  return {
    provider: config.llmProvider || 'mock',
    base_url: config.llmBaseUrl,
    model: config.llmModel,
    api_key: config.llmApiKey,
    workspace_root: config.workspaceRoot,
  };
}

const composerReferenceOptions: Record<
  ComposerReferenceKind,
  Array<{ id: string; label: string; description: string; icon: ReactNode }>
> = {
  files: [
    {
      id: 'readme',
      label: 'README.md',
      description: 'Project quick start and desktop run notes.',
      icon: <FileTextIcon />,
    },
    {
      id: 'desktop-app',
      label: 'apps/desktop/src/App.tsx',
      description: 'Desktop shell, command palette, and signed-out composer.',
      icon: <CodeIcon />,
    },
    {
      id: 'styles',
      label: 'apps/desktop/src/styles.css',
      description: 'Copilot-like layout, popovers, and responsive polish.',
      icon: <MixerHorizontalIcon />,
    },
  ],
  issues: [
    {
      id: 'login',
      label: '#desktop-login',
      description: 'Sign-in flow, account scope, and session readiness.',
      icon: <ChatBubbleIcon />,
    },
    {
      id: 'sandbox',
      label: '#sandbox-terminal',
      description: 'Workspace shell, desktop view, and sandbox health.',
      icon: <DesktopIcon />,
    },
    {
      id: 'figma',
      label: '#figma-design',
      description: 'Design capture and componentized desktop screen work.',
      icon: <FrameIcon />,
    },
  ],
};

const sessionScopeOptions: Record<SessionScopeKind, string[]> = {
  project: ['No project', 'Connect project', 'Manual API key'],
  worktree: ['New worktree', 'Current worktree', 'Review worktree'],
  branch: ['Default branch', 'Current branch', 'Review branch'],
};

function sessionScopeOptionId(kind: SessionScopeKind, option: string): string {
  const normalized = option.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `session-scope-option-${kind}-${normalized}`;
}

function mobileMenuOptionId(id: string): string {
  const normalized = id.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `mobile-section-option-${normalized}`;
}

function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

function agentConversationScopeKey(config: DesktopRuntimeConfig): string {
  return agentConversationScopeKeyFor(config.projectId, config.workspaceId);
}

function agentConversationScopeKeyFor(projectId: string, workspaceId: string): string {
  return `${projectId.trim()}::${workspaceId.trim()}`;
}

function agentTaskUpdateFromSocketEvent(
  event: unknown,
): null | {
  conversationId: string;
  messageId?: string;
  status: AgentTaskSignalStatus;
  detail: string;
  eventType: string;
} {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const conversationId = readStringField(payload, 'conversation_id');
  if (!conversationId) return null;

  const type = readStringField(payload, 'type') ?? readStringField(payload, 'event_type') ?? 'event';
  const action = readStringField(payload, 'action');
  const eventType = action ? `${type}:${action}` : type;
  const messageId = socketMessageId(payload);

  if (type === 'ack' && action === 'send_message') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent acknowledged the task over WebSocket.',
      eventType,
    };
  }

  if (type === 'user_message' || type === 'message') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent conversation received the task message.',
      eventType,
    };
  }

  if (type === 'act' || type === 'observe' || type.startsWith('text_')) {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent is streaming updates for this task.',
      eventType,
    };
  }

  if (type === 'assistant_message') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent response was added to the conversation.',
      eventType,
    };
  }

  if (type === 'complete') {
    return {
      conversationId,
      messageId,
      status: 'acknowledged',
      detail: 'Agent run completed.',
      eventType,
    };
  }

  if (type.toLowerCase().includes('error') || action?.toLowerCase().includes('error')) {
    const errorDetail = socketErrorDetail(payload);
    return {
      conversationId,
      messageId,
      status: 'failed',
      detail: errorDetail
        ? `Agent reported an error for this task: ${errorDetail}`
        : 'Agent reported an error for this task.',
      eventType,
    };
  }

  return null;
}

function socketErrorDetail(payload: Record<string, unknown>): string | undefined {
  const direct =
    readStringField(payload, 'detail') ??
    readStringField(payload, 'message') ??
    readStringField(payload, 'error') ??
    readStringField(payload, 'reason');
  if (direct) return direct;

  for (const key of ['payload', 'data', 'error', 'detail', 'message', 'reason']) {
    const nested = payload[key];
    if (nested && typeof nested === 'object') {
      const nestedDetail = socketErrorDetail(nested as Record<string, unknown>);
      if (nestedDetail) return nestedDetail;
    }
  }

  return undefined;
}

function socketMessageId(payload: Record<string, unknown>): string | undefined {
  const direct = readStringField(payload, 'message_id') ?? readStringField(payload, 'messageId');
  if (direct) return direct;

  for (const key of ['message', 'payload', 'data']) {
    const nested = payload[key];
    if (nested && typeof nested === 'object') {
      const nestedId = socketMessageId(nested as Record<string, unknown>);
      if (nestedId) return nestedId;
    }
  }

  return undefined;
}

function readStringField(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function mergeTimelineItems(
  existing: AgentTimelineItem[],
  incoming: AgentTimelineItem[],
): AgentTimelineItem[] {
  const merged = [...existing];
  for (const item of incoming) {
    const duplicateIndex = merged.findIndex((current) => timelineItemsMatch(current, item));
    if (duplicateIndex >= 0) {
      merged[duplicateIndex] = { ...merged[duplicateIndex], ...item };
    } else {
      merged.push(item);
    }
  }
  return merged.sort((a, b) => {
    if (a.eventTimeUs !== b.eventTimeUs) return a.eventTimeUs - b.eventTimeUs;
    return a.eventCounter - b.eventCounter;
  });
}

function timelineItemsMatch(current: AgentTimelineItem, incoming: AgentTimelineItem): boolean {
  if (current.id === incoming.id) return true;
  if (!current.message_id || current.message_id !== incoming.message_id) return false;
  if (current.type === incoming.type) {
    return (
      current.type === 'user_message' ||
      current.type === 'assistant_message' ||
      Boolean(current.metadata?.optimistic) ||
      Boolean(current.metadata?.streaming)
    );
  }
  return (
    current.role === 'assistant' &&
    incoming.role === 'assistant' &&
    (current.type === 'assistant_message' || incoming.type === 'assistant_message')
  );
}

function timelineCursorFromFirst(items: AgentTimelineItem[]): ConversationTimelineState['firstCursor'] {
  const first = items[0];
  if (!first) return null;
  return { timeUs: first.eventTimeUs, counter: first.eventCounter };
}

function timelineCursorFromLast(items: AgentTimelineItem[]): ConversationTimelineState['lastCursor'] {
  const last = items[items.length - 1];
  if (!last) return null;
  return { timeUs: last.eventTimeUs, counter: last.eventCounter };
}

function optimisticUserTimelineItem(messageId: string, content: string): AgentTimelineItem {
  const nowMs = Date.now();
  return {
    id: `optimistic-user-${messageId}`,
    type: 'user_message',
    eventTimeUs: nowMs * 1000,
    eventCounter: 0,
    timestamp: nowMs,
    message_id: messageId,
    role: 'user',
    content,
    metadata: { optimistic: true },
  };
}

function localRunArtifactTimelineItems(runId: string, nowMs: number): AgentTimelineItem[] {
  const eventTimeUs = nowMs * 1000;
  return [
    {
      id: `${runId}:artifact:retry-patch`,
      type: 'artifact_ready',
      eventTimeUs: eventTimeUs - 500,
      eventCounter: 1,
      timestamp: nowMs - 500,
      artifactId: `${runId}:0002-retry-backoff.patch`,
      filename: '0002-retry-backoff.patch',
      content:
        '+ for attempt in 0..max_retries {\n- client.send(req).await?\n+ jitter.sleep(attempt).await',
      payload: {
        path: 'patches/0002-retry-backoff.patch',
        bytesWritten: 2_150,
      },
      fileMetadata: {
        operation: 'patch',
        diffStat: { filesChanged: 2, additions: 45, deletions: 12 },
      },
      display: {
        title: '0002-retry-backoff.patch',
        summary: 'Retry backoff patch ready for local review.',
      },
      metadata: { localFixture: true, runId },
    },
    {
      id: `${runId}:artifact:changed-files`,
      type: 'observe',
      eventTimeUs: eventTimeUs - 1_000,
      eventCounter: 2,
      timestamp: nowMs - 1_000,
      toolName: 'filesystem.write',
      toolOutput: 'Modified 2 files',
      fileMetadata: {
        operation: 'edit',
        diffStat: { filesChanged: 2, additions: 45, deletions: 12 },
        paths: [
          {
            relativePath: 'src/engine/runner.rs',
            bytesWritten: 8_900,
            changed: true,
            diff: '+38 / -8',
            preview: 'pub async fn run(&self) -> Result<()> {\n  let mut attempt: u32 = 0;',
          },
          {
            relativePath: 'tests/integration/test_retry.rs',
            bytesWritten: 3_280,
            changed: true,
            diff: '+7 / -4',
            preview: '#[tokio::test]\nasync fn test_retry_succeeds() {',
          },
        ],
      },
      display: {
        title: 'Changed files',
        summary: 'Runner retry implementation and integration coverage updated.',
      },
      metadata: { localFixture: true, runId },
    },
    {
      id: `${runId}:artifact:run-report`,
      type: 'artifact_ready',
      eventTimeUs: eventTimeUs - 3_000,
      eventCounter: 3,
      timestamp: nowMs - 3_000,
      artifactId: `${runId}:reports/run-42.md`,
      filename: 'run-report.md',
      content: '## Summary\nAll checks passed. 2 files changed.',
      payload: {
        path: 'reports/run-42.md',
        bytesWritten: 12_700,
      },
      fileMetadata: {
        operation: 'report',
      },
      display: {
        title: 'run-report.md',
        summary: 'All checks passed. 2 files changed.',
      },
      metadata: { localFixture: true, runId },
    },
  ];
}

function localRunWorkspaceEvents(input: {
  runId: string;
  runNumber: number;
  nowMs: number;
  projectId?: string;
  workspaceId?: string;
}): Record<string, unknown>[] {
  const { runId, runNumber, nowMs, projectId, workspaceId } = input;
  const base = {
    run_id: runId,
    project_id: projectId,
    workspace_id: workspaceId,
  };
  return [
    {
      ...base,
      type: 'observe',
      source: 'executor.apply_patch',
      status: 'Success',
      detail: 'Modified 2 files',
      latency_ms: 412,
      timestamp: nowMs - 600,
    },
    {
      ...base,
      type: 'reasoning',
      source: 'Executor',
      detail: 'Patch applied cleanly. Next: run unit tests to validate...',
      timestamp: nowMs - 1_200,
    },
    {
      ...base,
      type: 'observe',
      source: 'filesystem.write',
      status: 'Success',
      detail: 'src/engine/runner.rs',
      latency_ms: 98,
      timestamp: nowMs - 1_800,
    },
    {
      ...base,
      type: 'reasoning',
      source: 'Executor',
      detail: 'Implement retry with exponential backoff for transient...',
      timestamp: nowMs - 2_400,
    },
    {
      ...base,
      type: 'observe',
      source: 'git.diff',
      status: 'Success',
      detail: '2 files',
      latency_ms: 77,
      timestamp: nowMs - 3_000,
    },
    {
      ...base,
      type: 'message',
      source: 'Planner',
      detail: 'Consider edge cases for cancellation and timeouts.',
      timestamp: nowMs - 3_600,
    },
    {
      ...base,
      type: 'message',
      source: 'System',
      message: `New run #${runNumber} queued with local runtime.`,
      timestamp: nowMs,
    },
  ];
}

function localRunBoardTasks(input: {
  runId: string;
  runNumber: number;
  nowMs: number;
  projectId?: string;
  workspaceId?: string;
}): WorkspaceTask[] {
  const { runId, runNumber, nowMs, projectId, workspaceId } = input;
  const timestamp = (offsetMs: number) => new Date(nowMs - offsetMs).toISOString();
  const baseMetadata = {
    localFixture: true,
    runId,
    runNumber,
    projectId,
  };
  const taskSpecs = [
    {
      id: 'planner-plan',
      owner: 'Planner',
      agentState: 'Active',
      title: 'Plan',
      summary: 'Define the retry-backoff implementation path for this run.',
      status: 'done',
      progress: 100,
      left: 13,
      width: 11,
      offset: 7_800,
    },
    {
      id: 'planner-decompose',
      owner: 'Planner',
      agentState: 'Active',
      title: 'Decompose',
      summary: 'Split implementation, tests, artifact review, and follow-up work.',
      status: 'done',
      progress: 100,
      left: 29,
      width: 13,
      offset: 7_200,
    },
    {
      id: 'planner-assign',
      owner: 'Planner',
      agentState: 'Active',
      title: 'Assign',
      summary: 'Route implementation to Executor and validation to Verifier.',
      status: 'planning',
      progress: 38,
      left: 45,
      width: 11,
      offset: 6_400,
    },
    {
      id: 'planner-replan',
      owner: 'Planner',
      agentState: 'Active',
      title: 'Replan',
      summary: 'Adjust the plan after test and review feedback.',
      status: 'planning',
      progress: 24,
      left: 62,
      width: 13,
      offset: 5_700,
    },
    {
      id: 'research-search-docs',
      owner: 'Researcher',
      agentState: 'Active',
      title: 'Search docs',
      summary: 'Confirm retry and cancellation expectations from local context.',
      status: 'done',
      progress: 100,
      left: 21,
      width: 13,
      offset: 6_900,
    },
    {
      id: 'research-collect-context',
      owner: 'Researcher',
      agentState: 'Active',
      title: 'Collect context',
      summary: 'Gather changed-file context for runner and integration tests.',
      status: 'running',
      progress: 52,
      left: 40,
      width: 16,
      offset: 5_100,
    },
    {
      id: 'research-synthesize',
      owner: 'Researcher',
      agentState: 'Active',
      title: 'Synthesize',
      summary: 'Summarize risk, edge cases, and validation evidence for review.',
      status: 'planning',
      progress: 26,
      left: 67,
      width: 16,
      offset: 3_900,
    },
    {
      id: 'executor-checkout-repo',
      owner: 'Executor',
      agentState: 'Working',
      title: 'Checkout repo',
      summary: 'Prepare the local workspace before editing the retry path.',
      status: 'done',
      progress: 100,
      left: 19,
      width: 11,
      offset: 6_100,
    },
    {
      id: 'executor-apply-patch',
      owner: 'Executor',
      agentState: 'Working',
      title: 'Apply patch',
      summary: 'QA seed for Apply patch',
      description: 'Patch the runner retry loop and keep the diff ready for human review.',
      status: 'in_progress',
      progress: 58,
      left: 33,
      width: 18,
      offset: 2_400,
      dashed: true,
      sourceEvent: 'executor.apply_patch',
      testsPassed: 6,
      testsTotal: 7,
    },
    {
      id: 'executor-run-tests',
      owner: 'Executor',
      agentState: 'Working',
      title: 'Run tests',
      summary: 'Exercise the retry integration path and capture failures for review.',
      status: 'running',
      progress: 66,
      left: 55,
      width: 14,
      offset: 1_700,
      testsPassed: 6,
      testsTotal: 7,
    },
    {
      id: 'executor-build',
      owner: 'Executor',
      agentState: 'Working',
      title: 'Build',
      summary: 'Build the local client bundle after the retry patch fixture is prepared.',
      status: 'planning',
      progress: 18,
      left: 71,
      width: 14,
      offset: 1_200,
    },
    {
      id: 'verifier-queue',
      owner: 'Verifier',
      agentState: 'Idle',
      title: 'Queue (2)',
      summary: 'Two verification tasks are queued for this run.',
      status: 'planning',
      progress: 12,
      left: 11,
      width: 16,
      offset: 4_700,
    },
    {
      id: 'verifier-static-analysis',
      owner: 'Verifier',
      agentState: 'Idle',
      title: 'Static analysis',
      summary: 'Prepare lint, type, and static analysis checks for the run.',
      status: 'review',
      progress: 80,
      left: 30,
      width: 15,
      offset: 3_600,
    },
    {
      id: 'verifier-test-verify',
      owner: 'Verifier',
      agentState: 'Idle',
      title: 'Test verify',
      summary: 'Review regression test results before human approval.',
      status: 'review',
      progress: 72,
      left: 52,
      width: 15,
      offset: 2_600,
      testsPassed: 6,
      testsTotal: 7,
    },
    {
      id: 'verifier-report',
      owner: 'Verifier',
      agentState: 'Idle',
      title: 'Report',
      summary: 'Prepare the final run report after checks complete.',
      status: 'planning',
      progress: 24,
      left: 78,
      width: 14,
      offset: 900,
    },
  ];

  return taskSpecs.map((task, index) => ({
    id: `${runId}:task:${task.id}`,
    workspace_id: workspaceId,
    title: task.title,
    summary: task.summary,
    description: task.description,
    status: task.status,
    owner: task.owner,
    priority: index < 11 ? 'P1' : 'P2',
    progress: task.progress,
    created_at: timestamp(task.offset),
    updated_at: timestamp(Math.max(600, task.offset - 700)),
    metadata: {
      ...baseMetadata,
      agent_lane: task.owner,
      agent_state: task.agentState,
      related_issue: `LOCAL-RUN-${runNumber}`,
      source_event: task.sourceEvent,
      timeline_left: task.left,
      timeline_width: task.width,
      timeline_dashed: task.dashed ?? false,
      tests_passed: task.testsPassed ?? 0,
      tests_total: task.testsTotal ?? 7,
    },
  }));
}

function timelineItemFromSocketEvent(event: unknown): AgentTimelineItem | null {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const type = readStringField(payload, 'type') ?? readStringField(payload, 'event_type');
  if (!type || shouldSkipLiveTimelineEvent(type, payload)) return null;
  const data = objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
  const nowMs = Date.now();
  const eventTimeUs =
    numberField(payload, 'time_us') ??
    numberField(payload, 'event_time_us') ??
    numberField(payload, 'eventTimeUs') ??
    nowMs * 1000;
  const eventCounter =
    numberField(payload, 'counter') ??
    numberField(payload, 'event_counter') ??
    numberField(payload, 'eventCounter') ??
    0;
  const messageId =
    socketMessageId(payload) ??
    readStringField(data, 'message_id') ??
    readStringField(data, 'messageId');
  const item: AgentTimelineItem = {
    id: `${type}-${eventTimeUs}-${eventCounter}`,
    type,
    eventTimeUs,
    eventCounter,
    timestamp: Math.floor(eventTimeUs / 1000),
    message_id: messageId ?? null,
    payload: data,
  };

  if (type === 'user_message' || type === 'assistant_message') {
    item.role = type === 'user_message' ? 'user' : 'assistant';
    item.content =
      readStringField(data, 'content') ??
      readStringField(data, 'answer') ??
      readStringField(payload, 'message') ??
      '';
  } else if (type === 'thought') {
    item.content = readStringField(data, 'thought') ?? readStringField(data, 'content') ?? '';
  } else if (type === 'act' || type === 'act_delta') {
    item.type = 'act';
    item.toolName = readStringField(data, 'tool_name') ?? readStringField(data, 'toolName') ?? '';
    item.toolInput = data.tool_input ?? data.toolInput ?? data.accumulated_arguments ?? {};
  } else if (type === 'observe') {
    item.toolName = readStringField(data, 'tool_name') ?? readStringField(data, 'toolName') ?? '';
    item.toolInput = data.tool_input ?? data.toolInput;
    item.toolOutput = data.observation ?? data.tool_output ?? data.toolOutput ?? '';
    item.isError = Boolean(data.is_error ?? data.isError);
  } else if (type === 'error') {
    item.content = socketErrorDetail(payload) ?? 'Agent run failed.';
    item.error = item.content;
    item.isError = true;
  }

  const display = objectField(data, 'display');
  if (display) item.display = display as AgentTimelineItem['display'];
  const fileMetadata = objectField(data, 'fileMetadata') ?? objectField(data, 'file_metadata');
  if (fileMetadata) item.fileMetadata = fileMetadata as AgentTimelineItem['fileMetadata'];
  const metadata = objectField(data, 'metadata');
  if (metadata) item.metadata = metadata;

  return item;
}

function shouldSkipLiveTimelineEvent(type: string, payload: Record<string, unknown>): boolean {
  if (
    [
      'ack',
      'status',
      'progress',
      'start',
      'complete',
      'cancelled',
      'heartbeat',
      'status_update',
      'lifecycle_state_change',
      'sandbox_event',
    ].includes(type)
  ) {
    return true;
  }
  const action = readStringField(payload, 'action');
  return action === 'subscribe' || action === 'subscribe_workspace';
}

function mergeLiveTimelineEvent(
  existing: AgentTimelineItem[],
  event: unknown,
): AgentTimelineItem[] {
  if (!event || typeof event !== 'object') return existing;
  const payload = event as Record<string, unknown>;
  const type = readStringField(payload, 'type') ?? readStringField(payload, 'event_type');
  if (type === 'text_start' || type === 'text_delta' || type === 'text_end') {
    return mergeStreamingTextEvent(existing, payload, type);
  }
  const timeline =
    type === 'a2ui_action_answered' ? markA2UIActionAnswered(existing, event) : existing;
  const item = timelineItemFromSocketEvent(event);
  return item ? mergeTimelineItems(timeline, [item]) : timeline;
}

function mergeStreamingTextEvent(
  existing: AgentTimelineItem[],
  payload: Record<string, unknown>,
  type: 'text_start' | 'text_delta' | 'text_end',
): AgentTimelineItem[] {
  const data = objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
  const messageId = socketMessageId(payload) ?? `stream-${readStringField(payload, 'conversation_id') ?? 'agent'}`;
  const nowMs = Date.now();
  const eventTimeUs =
    numberField(payload, 'time_us') ??
    numberField(payload, 'event_time_us') ??
    numberField(payload, 'eventTimeUs') ??
    nowMs * 1000;
  const eventCounter =
    numberField(payload, 'counter') ??
    numberField(payload, 'event_counter') ??
    numberField(payload, 'eventCounter') ??
    0;
  const delta =
    readStringField(data, 'delta') ??
    readStringField(data, 'text') ??
    readStringField(data, 'content') ??
    '';
  const existingIndex = existing.findIndex(
    (item) =>
      item.message_id === messageId &&
      item.role === 'assistant' &&
      Boolean(item.metadata?.streaming),
  );

  if (existingIndex < 0) {
    if (type === 'text_end' && !delta) return existing;
    return mergeTimelineItems(existing, [
      {
        id: `streaming-assistant-${messageId}`,
        type: 'assistant_message',
        eventTimeUs,
        eventCounter,
        timestamp: Math.floor(eventTimeUs / 1000),
        message_id: messageId,
        role: 'assistant',
        content: delta,
        metadata: { streaming: type !== 'text_end' },
      },
    ]);
  }

  const updated = existing.map((item, index) => {
    if (index !== existingIndex) return item;
    return {
      ...item,
      eventTimeUs,
      eventCounter,
      timestamp: Math.floor(eventTimeUs / 1000),
      content: type === 'text_delta' ? `${item.content ?? ''}${delta}` : delta || item.content,
      metadata: { ...(item.metadata ?? {}), streaming: type !== 'text_end' },
    };
  });
  return updated.sort((a, b) => {
    if (a.eventTimeUs !== b.eventTimeUs) return a.eventTimeUs - b.eventTimeUs;
    return a.eventCounter - b.eventCounter;
  });
}

function objectField(payload: Record<string, unknown>, key: string): Record<string, unknown> | null {
  const value = payload[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function numberField(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function buildWorkspaceEvents(socketEvents: unknown[]): WorkspaceEventRecord[] {
  return socketEvents
    .map((event, index) => workspaceEventFromSocketEvent(event, index))
    .sort((left, right) => {
      if (left.sortTime !== right.sortTime) return right.sortTime - left.sortTime;
      return left.id.localeCompare(right.id);
    });
}

function reviewFileArtifacts(artifacts: WorkspaceArtifact[]): WorkspaceArtifact[] {
  const fileArtifacts = artifacts.filter((artifact) => artifact.kind === 'Files');
  return fileArtifacts.length
    ? fileArtifacts
    : artifacts.filter((artifact) => artifact.kind === 'Patches');
}

function buildReviewDecisionSummary(
  dataset: RuntimeDataset,
  workspaceEvents: WorkspaceEventRecord[],
  artifacts: WorkspaceArtifact[],
  selectedTask: WorkspaceTask | null,
): ReviewDecisionSummary {
  const task =
    (selectedTask && dataset.tasks.some((candidate) => candidate.id === selectedTask.id)
      ? selectedTask
      : null) ??
    dataset.tasks.find((candidate) => taskStatus(candidate).includes('blocked')) ??
    dataset.tasks[0] ??
    null;
  const fileArtifacts = reviewFileArtifacts(artifacts);
  const displayedArtifacts = (fileArtifacts.length ? fileArtifacts : artifacts).slice(0, 4);
  const reasoningEvent = workspaceEvents.find((event) => event.kind === 'Reasoning');
  const latestEvent = workspaceEvents[0] ?? null;
  const filesChanged = fileArtifacts.length;
  const diffValue = summarizeArtifactDiff(fileArtifacts);
  const errorCount = workspaceEvents.filter((event) => event.kind === 'Errors').length;
  const blockedCount = dataset.tasks.filter((candidate) =>
    taskStatus(candidate).includes('blocked'),
  ).length;
  const risk = reviewDecisionRisk({
    errorCount,
    blockedCount,
    filesChanged,
    artifactCount: artifacts.length,
    eventCount: workspaceEvents.length,
  });
  const title =
    taskTitle(task) ??
    (artifacts.length ? 'Review generated artifacts' : undefined) ??
    (workspaceEvents.length ? 'Review background activity' : undefined) ??
    'No review packet loaded';
  const summary =
    taskSummary(task) ??
    (artifacts.length
      ? `${artifacts.length} artifact${artifacts.length === 1 ? '' : 's'} available for review.`
      : undefined) ??
    (latestEvent ? latestEvent.detail : undefined) ??
    'Connect a workspace session to load changes, agent activity, and decision context.';
  const reasoning =
    reasoningEvent?.detail ??
    latestEvent?.detail ??
    'No agent reasoning event is loaded for this workspace yet.';
  const checks = [
    { label: 'Related issue', value: reviewIssueValue(task) },
    { label: 'Tests', value: reviewTestsValue(dataset, task) },
    { label: 'Checks', value: reviewChecksValue({ artifacts, dataset, errorCount, workspaceEvents }) },
  ];
  if (blockedCount) checks.unshift({ label: 'Blocked tasks', value: String(blockedCount) });
  if (errorCount) checks.unshift({ label: 'Errors', value: String(errorCount) });

  return {
    title,
    summary,
    reasoning,
    risk,
    changeValue: diffValue,
    filesChanged,
    artifacts: displayedArtifacts.map((artifact) => ({
      id: artifact.id,
      name: artifact.name,
      path: artifact.path || artifact.source,
      meta: [artifact.kind, artifact.diff, artifact.status].filter(Boolean).join(' · '),
      diff: artifact.diff,
    })),
    checks,
    canAct: Boolean(dataset.tasks.length || artifacts.length || workspaceEvents.length || dataset.plan),
  };
}

function buildPullRequestSummary(
  dataset: RuntimeDataset,
  workspaceEvents: WorkspaceEventRecord[],
  artifacts: WorkspaceArtifact[],
  decision: ReviewDecisionSummary,
): ReviewPullRequestSummary {
  const fileArtifacts = reviewFileArtifacts(artifacts);
  const displayedFiles = (fileArtifacts.length ? fileArtifacts : artifacts).slice(0, 5);
  const errorCount = workspaceEvents.filter((event) => event.kind === 'Errors').length;
  const blockedCount = dataset.tasks.filter((task) => taskStatus(task).includes('blocked')).length;
  const runningCount = dataset.tasks.filter((task) =>
    ['running', 'active', 'in_progress', 'executing'].some((status) =>
      taskStatus(task).includes(status),
    ),
  ).length;
  const workspaceId =
    dataset.messages.find((message) => message.workspace_id)?.workspace_id ??
    dataset.tasks.find((task) => task.workspace_id)?.workspace_id ??
    dataset.workspaces[0]?.id ??
    'workspace';
  const branchName = `workspace/${workspaceId.slice(0, 8)}`;
  const canAct = decision.canAct || Boolean(displayedFiles.length || workspaceEvents.length);
  const status =
    errorCount || blockedCount
      ? 'needs review'
      : canAct
        ? runningCount
          ? 'checks running'
          : 'ready to review'
        : 'idle';

  return {
    title: decision.title === 'No review packet loaded' ? 'Draft workspace pull request' : decision.title,
    summary: decision.summary,
    status,
    branch: branchName,
    base: 'main',
    risk: decision.risk,
    diff: decision.changeValue,
    filesChanged: Math.max(decision.filesChanged, displayedFiles.length),
    canAct,
    checks: [
      {
        label: 'Agent events',
        value: errorCount ? `${errorCount} errors` : `${workspaceEvents.length} events`,
        status: errorCount ? 'failed' : workspaceEvents.length ? 'passed' : 'pending',
      },
      {
        label: 'Workspace tasks',
        value: blockedCount
          ? `${blockedCount} blocked`
          : runningCount
            ? `${runningCount} running`
            : `${dataset.tasks.length} loaded`,
        status: blockedCount ? 'failed' : dataset.tasks.length ? 'passed' : 'pending',
      },
      {
        label: 'Plan snapshot',
        value: dataset.plan ? `${Object.keys(dataset.plan).length} fields` : 'not loaded',
        status: dataset.plan ? 'passed' : 'pending',
      },
      {
        label: 'Artifacts',
        value: displayedFiles.length ? `${displayedFiles.length} files` : `${artifacts.length} items`,
        status: displayedFiles.length || artifacts.length ? 'passed' : 'pending',
      },
    ],
    files: displayedFiles.map((artifact) => ({
      id: artifact.id,
      name: artifact.name,
      path: artifact.path || artifact.source,
      meta: [artifact.kind, artifact.diff, artifact.status].filter(Boolean).join(' · '),
      diff: artifact.diff,
    })),
    activity: workspaceEvents.slice(0, 4).map((event) => ({
      id: event.id,
      time: event.time,
      label: event.eventType,
      detail: event.detail,
      status: event.status,
    })),
  };
}

function taskStatus(task: WorkspaceTask): string {
  return (task.status ?? '').toLowerCase();
}

function taskTitle(task: WorkspaceTask | null): string | undefined {
  if (!task) return undefined;
  return task.title ?? task.id;
}

function taskSummary(task: WorkspaceTask | null): string | undefined {
  if (!task) return undefined;
  return task.summary ?? task.description ?? undefined;
}

function reviewIssueValue(task: WorkspaceTask | null): string {
  const metadata = asRecordValue(task?.metadata);
  const issue =
    metadata &&
    (readStringField(metadata, 'related_issue') ??
      readStringField(metadata, 'issue') ??
      readStringField(metadata, 'issue_id') ??
      readStringField(metadata, 'issueId'));
  if (issue) return issue;
  const issueNumber =
    metadata &&
    (numberField(metadata, 'issue_number') ??
      numberField(metadata, 'issueNumber') ??
      numberField(metadata, 'issue_id'));
  if (typeof issueNumber === 'number') return `#${issueNumber}`;
  return task?.id ?? 'workspace';
}

function reviewTestsValue(dataset: RuntimeDataset, task: WorkspaceTask | null): string {
  const metadata = asRecordValue(task?.metadata);
  const plan = asRecordValue(dataset.plan);
  const passed =
    (metadata &&
      (numberField(metadata, 'tests_passed') ??
        numberField(metadata, 'testsPassed') ??
        numberField(metadata, 'test_passed_count'))) ??
    (plan &&
      (numberField(plan, 'tests_passed') ??
        numberField(plan, 'testsPassed') ??
        numberField(plan, 'test_passed_count')));
  const total =
    (metadata &&
      (numberField(metadata, 'tests_total') ??
        numberField(metadata, 'testsTotal') ??
        numberField(metadata, 'test_count'))) ??
    (plan &&
      (numberField(plan, 'tests_total') ??
        numberField(plan, 'testsTotal') ??
        numberField(plan, 'test_count')));
  if (typeof passed === 'number') {
    return typeof total === 'number' ? `${passed} / ${total} passed` : `${passed} passed`;
  }
  return 'pending';
}

function reviewChecksValue(input: {
  errorCount: number;
  artifacts: WorkspaceArtifact[];
  dataset: RuntimeDataset;
  workspaceEvents: WorkspaceEventRecord[];
}): string {
  const plan = asRecordValue(input.dataset.plan);
  const passed =
    plan &&
    (numberField(plan, 'checks_passed') ??
      numberField(plan, 'checksPassed') ??
      numberField(plan, 'passed_checks'));
  const total =
    plan &&
    (numberField(plan, 'checks_total') ??
      numberField(plan, 'checksTotal') ??
      numberField(plan, 'check_count'));
  if (typeof passed === 'number') {
    return typeof total === 'number' ? `${passed} / ${total} passed` : `${passed} passed`;
  }
  if (input.errorCount) return `${input.errorCount} failing`;
  const availableSignals =
    input.artifacts.length + input.workspaceEvents.length + (input.dataset.plan ? 1 : 0);
  return availableSignals ? `${availableSignals} ready` : 'pending';
}

function reviewDecisionRisk(input: {
  errorCount: number;
  blockedCount: number;
  filesChanged: number;
  artifactCount: number;
  eventCount: number;
}): ReviewDecisionSummary['risk'] {
  if (input.errorCount || input.blockedCount) return 'High';
  if (input.filesChanged > 2 || input.artifactCount > 4) return 'Medium';
  if (input.filesChanged || input.artifactCount || input.eventCount) return 'Low';
  return 'Low';
}

function summarizeArtifactDiff(artifacts: WorkspaceArtifact[]): string {
  let additions = 0;
  let deletions = 0;
  let hasDiff = false;
  artifacts.forEach((artifact) => {
    const matches = artifact.diff.match(/[+-]\d+/g) ?? [];
    matches.forEach((match) => {
      const value = Number(match);
      if (!Number.isFinite(value)) return;
      hasDiff = true;
      if (value > 0) additions += value;
      if (value < 0) deletions += Math.abs(value);
    });
  });
  if (!hasDiff) return `+0 / -0`;
  return `+${additions} / -${deletions}`;
}

function workspaceEventFromSocketEvent(event: unknown, index: number): WorkspaceEventRecord {
  const record = asRecordValue(event);
  const payload = record ? objectField(record, 'payload') ?? objectField(record, 'data') ?? record : {};
  const eventType =
    (record && (readStringField(record, 'type') ?? readStringField(record, 'event_type'))) ??
    'event';
  const action = record ? readStringField(record, 'action') : undefined;
  const source = workspaceEventSource(eventType, payload, record);
  const detail = workspaceEventDetail(eventType, payload, record, event);
  const eventTimeUs = record ? numberField(record, 'time_us') ?? numberField(record, 'event_time_us') : null;
  const timestamp = record
    ? numberField(record, 'timestamp') ??
      numberField(payload, 'timestamp') ??
      readStringField(payload, 'timestamp')
    : null;
  const sortTime =
    typeof eventTimeUs === 'number' ? Math.floor(eventTimeUs / 1000) : normalizeTimestamp(timestamp);
  const status = workspaceEventStatus(eventType, payload, record);
  const kind = workspaceEventKind(eventType, status, payload);
  const latency = workspaceEventLatency(payload, record);
  return makeWorkspaceEventRecord({
    id: `${eventType}-${action ?? 'event'}-${index}-${sortTime}`,
    kind,
    eventType: action ? `${eventType}:${action}` : eventType,
    source,
    status,
    detail,
    time: formatArtifactTime(sortTime),
    latency,
    sortTime,
    raw: event,
  });
}

function makeWorkspaceEventRecord(
  input: Omit<WorkspaceEventRecord, 'searchableText'>,
): WorkspaceEventRecord {
  return {
    ...input,
    searchableText: [
      input.kind,
      input.eventType,
      input.source,
      input.status,
      input.detail,
      input.time,
      input.latency,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase(),
  };
}

function workspaceEventKind(
  eventType: string,
  status: string,
  payload: Record<string, unknown>,
): WorkspaceEventKind {
  const value = `${eventType} ${status}`.toLowerCase();
  if (value.includes('error') || status.toLowerCase() === 'failed') return 'Errors';
  if (['act', 'observe', 'tool.call', 'tool_call', 'sandbox_event'].some((type) => value.includes(type))) {
    return 'Tools';
  }
  if (
    ['thought', 'reasoning', 'work_plan', 'chain_', 'subagent_'].some((type) => value.includes(type))
  ) {
    return 'Reasoning';
  }
  if (
    ['message', 'ack', 'text_', 'user_message', 'assistant_message', 'decision', 'selection'].some((type) =>
      value.includes(type),
    ) ||
    readStringField(payload, 'content')
  ) {
    return 'Messages';
  }
  return 'System';
}

function workspaceEventStatus(
  eventType: string,
  payload: Record<string, unknown>,
  record: Record<string, unknown> | null,
): string {
  if (eventType.toLowerCase().includes('error')) return 'error';
  const direct =
    readStringField(payload, 'status') ??
    readStringField(payload, 'state') ??
    (record ? readStringField(record, 'status') ?? readStringField(record, 'state') : undefined);
  if (direct) return direct;
  if (payload.is_error === true || payload.isError === true) return 'error';
  const action = record ? readStringField(record, 'action') : undefined;
  if (action) return action;
  return 'received';
}

function workspaceEventLatency(
  payload: Record<string, unknown>,
  record: Record<string, unknown> | null,
): string {
  const direct =
    readStringField(payload, 'latency') ??
    readStringField(payload, 'duration') ??
    (record ? readStringField(record, 'latency') ?? readStringField(record, 'duration') : undefined);
  if (direct) return direct;
  const milliseconds =
    numberField(payload, 'latency_ms') ??
    numberField(payload, 'duration_ms') ??
    numberField(payload, 'elapsed_ms') ??
    (record
      ? numberField(record, 'latency_ms') ??
        numberField(record, 'duration_ms') ??
        numberField(record, 'elapsed_ms')
      : null);
  if (typeof milliseconds === 'number') return `${Math.round(milliseconds)} ms`;
  const seconds =
    numberField(payload, 'latency_s') ??
    numberField(payload, 'duration_s') ??
    (record ? numberField(record, 'latency_s') ?? numberField(record, 'duration_s') : null);
  if (typeof seconds === 'number') return `${Math.round(seconds * 1000)} ms`;
  return '-';
}

function workspaceEventSource(
  eventType: string,
  payload: Record<string, unknown>,
  record: Record<string, unknown> | null,
): string {
  const payloadType = readStringField(payload, 'type');
  const nested = objectField(payload, 'data');
  const nestedType = nested ? readStringField(nested, 'type') : undefined;
  return (
    readStringField(payload, 'source') ??
    readStringField(payload, 'agent') ??
    readStringField(payload, 'agent_id') ??
    readStringField(payload, 'tool_name') ??
    readStringField(payload, 'toolName') ??
    payloadType ??
    nestedType ??
    (record ? readStringField(record, 'source') : undefined) ??
    eventType
  );
}

function workspaceEventDirectDetail(
  payload: Record<string, unknown>,
  record: Record<string, unknown> | null,
): string | undefined {
  return (
    readStringField(payload, 'detail') ??
    readStringField(payload, 'summary') ??
    readStringField(payload, 'message') ??
    readStringField(payload, 'content') ??
    readStringField(payload, 'delta') ??
    readStringField(payload, 'text') ??
    readStringField(payload, 'answer') ??
    (record ? readStringField(record, 'message') : undefined)
  );
}

function workspaceEventDetail(
  eventType: string,
  payload: Record<string, unknown>,
  record: Record<string, unknown> | null,
  raw: unknown,
): string {
  const error = record ? socketErrorDetail(record) : undefined;
  if (error) return error;
  const direct = workspaceEventDirectDetail(payload, record);
  if (['message', 'decision', 'selection'].includes(eventType.toLowerCase()) && direct) {
    return direct;
  }
  const payloadType = readStringField(payload, 'type');
  if (payloadType) {
    const payloadData = objectField(payload, 'data') ?? payload;
    const payloadName =
      readStringField(payloadData, 'filename') ??
      readStringField(payloadData, 'artifact_id') ??
      readStringField(payloadData, 'tool_execution_id') ??
      readStringField(payloadData, 'sandbox_id');
    return payloadName ? `${payloadType}: ${payloadName}` : payloadType;
  }
  const nested = objectField(payload, 'data');
  if (nested) {
    const nestedType = readStringField(nested, 'type');
    const nestedData = objectField(nested, 'data') ?? nested;
    const nestedName =
      readStringField(nestedData, 'filename') ??
      readStringField(nestedData, 'artifact_id') ??
      readStringField(nestedData, 'tool_execution_id') ??
      readStringField(nestedData, 'sandbox_id');
    if (nestedType) return nestedName ? `${nestedType}: ${nestedName}` : nestedType;
  }
  if (direct) return direct;
  const toolName = readStringField(payload, 'tool_name') ?? readStringField(payload, 'toolName');
  if (toolName) return `Tool ${toolName}`;
  const conversationId = record ? readStringField(record, 'conversation_id') : undefined;
  if (conversationId) return `Conversation ${conversationId.slice(0, 8)}`;
  return compactArtifactValue(raw);
}

function buildWorkspaceArtifacts(
  timelineItems: AgentTimelineItem[],
  socketEvents: unknown[],
  plan: PlanSnapshot | null,
): WorkspaceArtifact[] {
  const artifacts = [
    ...timelineItems.flatMap((item) => artifactsFromTimelineItem(item)),
    ...socketEvents.flatMap((event, index) => artifactsFromSocketEvent(event, index)),
    ...artifactsFromPlan(plan),
  ];
  const byKey = new Map<string, WorkspaceArtifact>();

  artifacts.forEach((artifact) => {
    const key = workspaceArtifactIdentity(artifact);
    const existing = byKey.get(key);
    if (!existing || shouldReplaceWorkspaceArtifact(existing, artifact)) {
      byKey.set(key, artifact);
    }
  });

  return [...byKey.values()].sort((left, right) => {
    if (left.sortTime !== right.sortTime) return right.sortTime - left.sortTime;
    return left.name.localeCompare(right.name);
  });
}

function shouldReplaceWorkspaceArtifact(
  existing: WorkspaceArtifact,
  candidate: WorkspaceArtifact,
): boolean {
  const statusDelta = artifactStatusRank(candidate.status) - artifactStatusRank(existing.status);
  if (statusDelta !== 0) return statusDelta > 0;
  return candidate.sortTime >= existing.sortTime;
}

function artifactStatusRank(status: string): number {
  const normalized = status.toLowerCase();
  if (normalized === 'error' || normalized === 'failed') return 5;
  if (normalized === 'ready' || normalized === 'indexed') return 4;
  if (normalized === 'observed') return 3;
  if (normalized === 'created') return 2;
  if (normalized === 'running') return 1;
  return 0;
}

function workspaceArtifactIdentity(artifact: WorkspaceArtifact): string {
  const artifactId = artifactIdFromRaw(artifact.raw);
  if (artifactId) return `${artifact.kind}:id:${artifactId}`;
  if (artifact.source.startsWith('artifact_')) return `${artifact.kind}:name:${artifact.name}`;
  return `${artifact.kind}:${artifact.path || artifact.name || artifact.id}`;
}

function artifactIdFromRaw(value: unknown, depth = 0): string | undefined {
  if (depth > 4) return undefined;
  const record = asRecordValue(value);
  if (!record) return undefined;
  const direct = readStringField(record, 'artifact_id') ?? readStringField(record, 'artifactId');
  if (direct) return direct;
  for (const key of ['payload', 'data', 'artifact']) {
    const nested = artifactIdFromRaw(record[key], depth + 1);
    if (nested) return nested;
  }
  return undefined;
}

function sortWorkspaceArtifacts(
  artifacts: WorkspaceArtifact[],
  sort: WorkspaceArtifactSort,
): WorkspaceArtifact[] {
  const sorted = [...artifacts];
  sorted.sort((left, right) => {
    if (sort === 'largest') {
      const bySize = artifactSizeBytes(right.size) - artifactSizeBytes(left.size);
      if (bySize !== 0) return bySize;
      if (left.sortTime !== right.sortTime) return right.sortTime - left.sortTime;
      return left.name.localeCompare(right.name);
    }
    if (sort === 'name') {
      const byName = left.name.localeCompare(right.name);
      if (byName !== 0) return byName;
      return right.sortTime - left.sortTime;
    }
    if (left.sortTime !== right.sortTime) return right.sortTime - left.sortTime;
    return left.name.localeCompare(right.name);
  });
  return sorted;
}

function artifactSizeBytes(size: string): number {
  const match = size.trim().match(/^([\d.]+)\s*(B|KB|MB)$/i);
  if (!match) return 0;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return 0;
  const unit = match[2].toUpperCase();
  if (unit === 'MB') return value * 1024 * 1024;
  if (unit === 'KB') return value * 1024;
  return value;
}

function formatArtifactTotalSize(artifacts: WorkspaceArtifact[]): string {
  const totalBytes = artifacts.reduce((total, artifact) => total + artifactSizeBytes(artifact.size), 0);
  if (totalBytes >= 1024 * 1024) return `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`;
  if (totalBytes >= 1024) return `${(totalBytes / 1024).toFixed(1)} KB`;
  return `${Math.round(totalBytes)} B`;
}

function artifactsFromTimelineItem(item: AgentTimelineItem): WorkspaceArtifact[] {
  const metadata = artifactFileMetadata(item);
  const operation = readStringField(metadata ?? {}, 'operation') ?? item.toolName ?? item.type;
  const paths = arrayField(metadata ?? {}, 'paths').filter(isRecordValue);
  const isArtifactEvent = item.type.startsWith('artifact_') || Boolean(item.filename || item.artifactId);
  const writesFiles = ['write', 'edit', 'patch', 'export_artifact'].includes(operation);

  if (paths.length && (isArtifactEvent || writesFiles || item.toolName)) {
    return paths.map((path, index) =>
      artifactFromPathMetadata(path, {
        id: `${item.id}:path:${index}`,
        source: item.toolName || item.type,
        status: artifactStatus(item),
        sortTime: artifactSortTime(item),
        raw: item,
        fallbackPreview: timelineArtifactPreview(item),
        diff: diffStatLabel(metadata),
      }),
    );
  }

  if (!isArtifactEvent && !writesFiles) return [];

  const filename = item.filename ?? readStringField(asRecordValue(item.payload) ?? {}, 'filename');
  const artifactId = item.artifactId ?? readStringField(asRecordValue(item.payload) ?? {}, 'artifact_id');
  const name = filename || artifactId || item.toolName || item.type;
  const path = artifactPathFromRecord(asRecordValue(item.payload)) || filename || artifactId || '';
  return [
    makeWorkspaceArtifact({
      id: item.id,
      name,
      path,
      kind: artifactKind(name, operation),
      source: item.toolName || item.type,
      status: artifactStatus(item),
      sortTime: artifactSortTime(item),
      size: artifactSize(asRecordValue(item.payload)),
      diff: diffStatLabel(metadata),
      preview: timelineArtifactPreview(item),
      raw: item,
    }),
  ];
}

function artifactsFromSocketEvent(event: unknown, index: number): WorkspaceArtifact[] {
  const item = timelineItemFromSocketEvent(event);
  if (item) {
    const timelineArtifacts = artifactsFromTimelineItem(item);
    if (timelineArtifacts.length) return timelineArtifacts;
  }
  const record = asRecordValue(event);
  if (!record) return [];
  const candidate = socketArtifactCandidate(record);
  if (!candidate) return [];
  const { type, payload } = candidate;
  const name =
    readStringField(payload, 'filename') ??
    readStringField(payload, 'name') ??
    readStringField(payload, 'artifact_id') ??
    type;
  const eventTimeUs = numberField(record, 'time_us') ?? numberField(record, 'event_time_us');
  const timestamp = numberField(record, 'timestamp');
  const path = artifactPathFromRecord(payload);
  return [
    makeWorkspaceArtifact({
      id: `socket-artifact-${index}-${type}-${path || name}`,
      name,
      path,
      kind: artifactKind(name, type),
      source: type,
      status: socketArtifactStatus(type, payload),
      sortTime:
        typeof eventTimeUs === 'number'
          ? Math.floor(eventTimeUs / 1000)
          : normalizeTimestamp(timestamp),
      size: artifactSize(payload),
      diff: '',
      preview: compactArtifactValue(payload),
      raw: event,
    }),
  ];
}

function socketArtifactCandidate(
  record: Record<string, unknown>,
): { type: string; payload: Record<string, unknown> } | null {
  const topType = readStringField(record, 'type') ?? readStringField(record, 'event_type') ?? 'event';
  const topPayload = objectField(record, 'payload') ?? objectField(record, 'data') ?? record;
  const candidates: Array<{ type: string; payload: Record<string, unknown> }> = [
    { type: topType, payload: topPayload },
  ];
  const payloadType = readStringField(topPayload, 'type');
  if (payloadType) {
    candidates.push({
      type: payloadType,
      payload: objectField(topPayload, 'data') ?? topPayload,
    });
  }
  const nestedData = objectField(topPayload, 'data');
  const nestedDataType = nestedData ? readStringField(nestedData, 'type') : undefined;
  if (nestedData && nestedDataType) {
    candidates.push({
      type: nestedDataType,
      payload: objectField(nestedData, 'data') ?? nestedData,
    });
  }
  const nestedPayload = objectField(topPayload, 'payload');
  const nestedPayloadType = nestedPayload ? readStringField(nestedPayload, 'type') : undefined;
  if (nestedPayload && nestedPayloadType) {
    candidates.push({
      type: nestedPayloadType,
      payload: objectField(nestedPayload, 'data') ?? nestedPayload,
    });
  }

  return (
    candidates.find(({ type, payload }) => {
      const normalizedType = type.toLowerCase();
      const typeHasArtifact = normalizedType.includes('artifact');
      const hasArtifactId = Boolean(readStringField(payload, 'artifact_id'));
      const hasFileSignal = Boolean(
        readStringField(payload, 'filename') ??
          readStringField(payload, 'relativePath') ??
          readStringField(payload, 'relative_path') ??
          readStringField(payload, 'path'),
      );
      return typeHasArtifact || hasArtifactId || (hasFileSignal && normalizedType.includes('file'));
    }) ?? null
  );
}

function socketArtifactStatus(type: string, payload: Record<string, unknown>): string {
  const direct = readStringField(payload, 'status') ?? readStringField(payload, 'state');
  if (direct) return direct;
  if (type === 'artifact_ready') return 'ready';
  if (type === 'artifact_created') return 'created';
  return 'event';
}

function artifactsFromPlan(plan: PlanSnapshot | null): WorkspaceArtifact[] {
  if (!plan) return [];
  const index = plan.artifact_index ?? plan.artifacts;
  if (!index) return [];
  if (Array.isArray(index)) {
    return index.flatMap((entry, position) => artifactFromPlanEntry(entry, String(position)));
  }
  const record = asRecordValue(index);
  if (!record) return [];
  return Object.entries(record).flatMap(([key, value]) => artifactFromPlanEntry(value, key));
}

function artifactFromPlanEntry(entry: unknown, key: string): WorkspaceArtifact[] {
  const record = asRecordValue(entry);
  const name =
    (record &&
      (readStringField(record, 'name') ??
        readStringField(record, 'filename') ??
        readStringField(record, 'id'))) ??
    key;
  const path = record ? artifactPathFromRecord(record) : '';
  return [
    makeWorkspaceArtifact({
      id: `plan-artifact-${key}`,
      name,
      path,
      kind: artifactKind(name, record ? readStringField(record, 'type') : undefined),
      source: 'plan',
      status: record ? readStringField(record, 'status') ?? 'indexed' : 'indexed',
      sortTime: Date.now() - 1,
      size: record ? artifactSize(record) : '',
      diff: record ? readStringField(record, 'diff') ?? '' : '',
      preview: record ? compactArtifactValue(record) : String(entry),
      raw: entry,
    }),
  ];
}

function artifactFromPathMetadata(
  path: Record<string, unknown>,
  base: {
    id: string;
    source: string;
    status: string;
    sortTime: number;
    raw: unknown;
    fallbackPreview: string;
    diff: string;
  },
): WorkspaceArtifact {
  const pathValue =
    readStringField(path, 'relativePath') ??
    readStringField(path, 'relative_path') ??
    readStringField(path, 'path') ??
    'file';
  const name = pathValue.split('/').filter(Boolean).pop() ?? pathValue;
  return makeWorkspaceArtifact({
    id: base.id,
    name,
    path: pathValue,
    kind: artifactKind(pathValue, base.source),
    source: base.source,
    status: pathStatus(path, base.status),
    sortTime: base.sortTime,
    size: artifactSize(path),
    diff: pathDiffStatLabel(path, base.diff),
    preview: readStringField(path, 'preview') ?? base.fallbackPreview,
    raw: base.raw,
  });
}

function makeWorkspaceArtifact(
  input: Omit<WorkspaceArtifact, 'searchableText' | 'time'>,
): WorkspaceArtifact {
  return {
    ...input,
    time: formatArtifactTime(input.sortTime),
    searchableText: [
      input.name,
      input.path,
      input.kind,
      input.source,
      input.status,
      input.size,
      input.diff,
      input.preview,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase(),
  };
}

function artifactFileMetadata(item: AgentTimelineItem): Record<string, unknown> | null {
  const direct = asRecordValue(item.fileMetadata);
  if (direct) return direct;
  const output = asRecordValue(item.toolOutput);
  if (!output) return null;
  return objectField(output, 'fileMetadata') ?? objectField(output, 'file_metadata');
}

function artifactKind(name: string, hint?: string): WorkspaceArtifactKind {
  const value = `${name} ${hint ?? ''}`.toLowerCase();
  if (value.includes('patch') || value.endsWith('.diff') || value.endsWith('.patch')) return 'Patches';
  if (value.includes('report') || value.endsWith('.md') || value.endsWith('.pdf')) return 'Reports';
  if (value.includes('log') || value.endsWith('.log')) return 'Logs';
  if (value.includes('event') || value.includes('artifact_')) return 'Events';
  return 'Files';
}

function artifactStatus(item: AgentTimelineItem): string {
  if (item.isError || item.error || item.type === 'artifact_error') return 'error';
  if (item.type === 'artifact_ready') return 'ready';
  if (item.type === 'artifact_created') return 'created';
  if (item.type === 'observe') return 'observed';
  if (item.type === 'act') return 'running';
  return item.type;
}

function artifactSortTime(item: AgentTimelineItem): number {
  return item.eventTimeUs ? Math.floor(item.eventTimeUs / 1000) : normalizeTimestamp(item.timestamp);
}

function pathStatus(path: Record<string, unknown>, fallback: string): string {
  if (path.deleted === true) return 'deleted';
  if (path.created === true) return 'created';
  if (path.changed === true) return 'changed';
  return fallback;
}

function artifactPathFromRecord(record: Record<string, unknown> | null): string {
  if (!record) return '';
  return (
    readStringField(record, 'path') ??
    readStringField(record, 'relativePath') ??
    readStringField(record, 'relative_path') ??
    readStringField(record, 'url') ??
    ''
  );
}

function artifactSize(record: Record<string, unknown> | null): string {
  if (!record) return '';
  const size =
    numberField(record, 'bytesWritten') ??
    numberField(record, 'bytes_written') ??
    numberField(record, 'bytesRead') ??
    numberField(record, 'bytes_read') ??
    numberField(record, 'size') ??
    numberField(record, 'size_bytes');
  return typeof size === 'number' ? formatBytes(size) : '';
}

function diffStatLabel(metadata: Record<string, unknown> | null): string {
  const diffStat = metadata ? objectField(metadata, 'diffStat') ?? objectField(metadata, 'diff_stat') : null;
  if (!diffStat) return '';
  const files = numberField(diffStat, 'filesChanged') ?? numberField(diffStat, 'files_changed');
  const additions = numberField(diffStat, 'additions');
  const deletions = numberField(diffStat, 'deletions');
  const parts = [];
  if (typeof files === 'number') parts.push(`${files} files`);
  if (typeof additions === 'number') parts.push(`+${additions}`);
  if (typeof deletions === 'number') parts.push(`-${deletions}`);
  return parts.join(' / ');
}

function pathDiffStatLabel(path: Record<string, unknown>, fallback: string): string {
  const direct = readStringField(path, 'diff') ?? readStringField(path, 'diffStatLabel');
  if (direct) return direct;
  const diffStat = objectField(path, 'diffStat') ?? objectField(path, 'diff_stat');
  if (!diffStat) return fallback;
  const additions = numberField(diffStat, 'additions');
  const deletions = numberField(diffStat, 'deletions');
  const parts = [];
  if (typeof additions === 'number') parts.push(`+${additions}`);
  if (typeof deletions === 'number') parts.push(`-${deletions}`);
  return parts.length ? parts.join(' / ') : fallback;
}

function timelineArtifactPreview(item: AgentTimelineItem): string {
  if (item.error) return item.error;
  if (item.content) return item.content;
  const display = asRecordValue(item.display);
  const summary = display ? readStringField(display, 'summary') ?? readStringField(display, 'title') : undefined;
  if (summary) return summary;
  if (item.payload !== undefined) return compactArtifactValue(item.payload);
  if (item.toolOutput !== undefined) return compactArtifactValue(item.toolOutput);
  return item.toolName || item.type;
}

function compactArtifactValue(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > 180 ? `${text.slice(0, 177)}...` : text;
}

function formatArtifactTime(sortTime: number): string {
  const date = new Date(sortTime);
  if (!Number.isFinite(date.getTime())) return 'unknown';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function timestampFromIso(value: string | null | undefined): number {
  if (!value) return 0;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function formatRunTime(value: string | null | undefined): string {
  const timestamp = timestampFromIso(value);
  if (!timestamp) return 'now';
  return formatArtifactTime(timestamp);
}

function normalizeTimestamp(value: number | string | null | undefined): number {
  if (typeof value === 'string') {
    const parsed = timestampFromIso(value);
    return parsed || Date.now();
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) return Date.now();
  return value < 10_000_000_000 ? value * 1000 : value;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}

function arrayField(payload: Record<string, unknown>, key: string): unknown[] {
  const value = payload[key];
  return Array.isArray(value) ? value : [];
}

function asRecordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isRecordValue(value: unknown): value is Record<string, unknown> {
  return Boolean(asRecordValue(value));
}

export function App() {
  const runsInTauri = detectTauriShell();
  const [config, setConfig] = useState<DesktopRuntimeConfig>(DEFAULT_CONFIG);
  const [runtimeApiKeyFocusSignal, setRuntimeApiKeyFocusSignal] = useState(0);
  const [auth, setAuth] = useState<AuthState>(emptyAuthState);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState('');
  const commandInputRef = useRef<HTMLInputElement>(null);
  const commandPaletteTriggerRef = useRef<HTMLElement | null>(null);
  const appShellRef = useRef<HTMLDivElement>(null);
  const loginRestoreTargetRef = useRef<HTMLElement | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [runActionsMenuOpen, setRunActionsMenuOpen] = useState(false);
  const [mobileSectionMenuOpen, setMobileSectionMenuOpen] = useState(false);
  const [activeMobileMenuItemId, setActiveMobileMenuItemId] = useState<string | null>(null);
  const runActionsButtonRef = useRef<HTMLButtonElement>(null);
  const runActionsMenuRef = useRef<HTMLDivElement>(null);
  const mobileSectionButtonRef = useRef<HTMLButtonElement>(null);
  const mobileSectionMenuRef = useRef<HTMLDivElement>(null);
  const mobileTitlebarItemsRef = useRef<MobileTitlebarMenuItem[]>([]);
  const activeMobileMenuOptionId = activeMobileMenuItemId
    ? mobileMenuOptionId(activeMobileMenuItemId)
    : undefined;
  const [sessionGroupMode, setSessionGroupMode] = useState<SessionGroupMode>('project');
  const [expandedProjectIds, setExpandedProjectIds] = useState<Set<string>>(() => new Set());
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState<Set<string>>(() => new Set());
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [dataset, setDataset] = useState<RuntimeDataset>(emptyDataset);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string>('never');
  const [localSidebarRuns, setLocalSidebarRuns] = useState<SidebarRunItem[]>([]);
  const [localRunEvents, setLocalRunEvents] = useState<unknown[]>([]);
  const [localRunTasksById, setLocalRunTasksById] = useState<Record<string, WorkspaceTask[]>>({});
  const [selectedSidebarRunId, setSelectedSidebarRunId] = useState('');
  const [runStateById, setRunStateById] = useState<Record<string, RunControlState>>({});
  const [runControlState, setRunControlState] = useState<RunControlState>('running');
  const [runtimeTarget, setRuntimeTarget] = useState<RuntimeTarget>('local');
  const [runLiveMode, setRunLiveMode] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('workspace');
  const activeSectionRef = useRef<WorkbenchSection>('workspace');
  const [sectionBackStack, setSectionBackStack] = useState<WorkbenchSection[]>([]);
  const [sectionForwardStack, setSectionForwardStack] = useState<WorkbenchSection[]>([]);
  const [reviewTab, setReviewTab] = useState<ReviewTab>('plan');
  const [reviewPanelOpen, setReviewPanelOpen] = useState(true);
  const [boardMode, setBoardMode] = useState<BoardMode>('flow');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [statusTab, setStatusTab] = useState<StatusTab>('overview');
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [desktop, setDesktop] = useState<DesktopServiceResponse | null>(null);
  const [terminal, setTerminal] = useState<TerminalServiceResponse | null>(null);
  const [terminalInput, setTerminalInput] = useState('');
  const [memoryContent, setMemoryContent] = useState('Local-first desktop workspace smoke record');
  const [memoryQuery, setMemoryQuery] = useState('desktop workspace');
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryResult, setMemoryResult] = useState<LocalMemoryResult | null>(null);
  const [newWorkspaceName, setNewWorkspaceName] = useState(DEFAULT_WORKSPACE_NAME);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [creatingSessionWorkspaceId, setCreatingSessionWorkspaceId] = useState<string | null>(null);
  const [agentConversationSession, setAgentConversationSession] =
    useState<AgentConversationSession | null>(null);
  const [conversationTimeline, setConversationTimeline] =
    useState<ConversationTimelineState>(emptyConversationTimeline);
  const [agentTaskSignals, setAgentTaskSignals] = useState<AgentTaskSignal[]>([]);
  const timelineRequestRef = useRef(0);

  const api = useMemo(() => new DesktopApiClient(config), [config]);
  const socket = useAgentSocket(config, connection === 'ready');
  const terminalUrl = useMemo(() => {
    if (!terminal?.success || !terminal.session_id) return null;
    try {
      return api.terminalProxyUrl(terminal.session_id);
    } catch {
      return null;
    }
  }, [api, terminal?.session_id, terminal?.success]);
  const terminalProxy = useTerminalProxy(terminalUrl, desktopApiCredential(config));
  const desktopFrameUrl = useMemo(() => {
    if (!desktop?.success) return null;
    try {
      return api.desktopProxyUrl();
    } catch {
      return null;
    }
  }, [api, desktop?.success]);
  const modalOpen = loginModalOpen || commandPaletteOpen;
  const localRuntimeMode = config.mode === 'local' && runsInTauri;

  const syncLocalRuntimeConfig = useCallback(
    async (nextConfig: DesktopRuntimeConfig): Promise<DesktopRuntimeConfig> => {
      if (!runsInTauri || nextConfig.mode !== 'local') return nextConfig;
      const invoke = window.__TAURI__?.core?.invoke;
      if (!invoke) return nextConfig;
      const status = await invoke<LocalRuntimeStatus>('local_runtime_configure', {
        config: localRuntimeTauriConfig(nextConfig),
      });
      return mergeLocalRuntimeStatus(nextConfig, status);
    },
    [runsInTauri],
  );

  useEffect(() => {
    if (!localRuntimeMode) return;
    let cancelled = false;
    const invoke = window.__TAURI__?.core?.invoke;
    if (!invoke) return;
    invoke<LocalRuntimeStatus>('local_runtime_status')
      .then((status) => {
        if (cancelled) return;
        setConfig((current) => mergeLocalRuntimeStatus(current, status));
        setAuth((current) =>
          current.status === 'signed_out' ? { ...emptyAuthState, status: 'manual' } : current,
        );
      })
      .catch((caught) => {
        if (!cancelled) setError(formatError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [localRuntimeMode]);

  const activeDataset = useMemo<RuntimeDataset>(() => {
    if (!selectedSidebarRunId.startsWith('local-run:')) return dataset;
    return {
      ...dataset,
      tasks: localRunTasksById[selectedSidebarRunId] ?? [],
    };
  }, [dataset, localRunTasksById, selectedSidebarRunId]);
  const selectedTask = useMemo(
    () =>
      activeDataset.tasks.find((task) => task.id === selectedTaskId) ??
      activeDataset.tasks[0] ??
      null,
    [activeDataset.tasks, selectedTaskId],
  );
  const workspaceEventInputs = useMemo(
    () => [...localRunEvents, ...socket.events],
    [localRunEvents, socket.events],
  );
  const workspaceArtifacts = useMemo(
    () => buildWorkspaceArtifacts(conversationTimeline.items, workspaceEventInputs, dataset.plan),
    [conversationTimeline.items, dataset.plan, workspaceEventInputs],
  );
  const chatWorkflowCounts = useMemo<Partial<Record<ChatWorkflowTarget, number>>>(
    () => ({
      background: workspaceEventInputs.length,
      artifacts: workspaceArtifacts.length,
    }),
    [workspaceEventInputs.length, workspaceArtifacts.length],
  );
  const upsertAgentTaskSignal = useCallback((patch: AgentTaskSignalPatch) => {
    setAgentTaskSignals((current) => {
      const existing = current.find((signal) => signal.id === patch.id);
      const next: AgentTaskSignal = {
        id: patch.id,
        content: patch.content ?? existing?.content ?? '',
        status: patch.status ?? existing?.status ?? 'queued',
        detail: patch.detail ?? existing?.detail ?? '',
        createdAt: patch.createdAt ?? existing?.createdAt ?? new Date().toISOString(),
        conversationId: patch.conversationId ?? existing?.conversationId,
        messageId: patch.messageId ?? existing?.messageId,
        eventType: patch.eventType ?? existing?.eventType,
      };
      return [...current.filter((signal) => signal.id !== patch.id), next].slice(-8);
    });
  }, []);

  const loadConversationTimeline = useCallback(
    async (conversation: AgentConversation, projectId: string) => {
      const requestId = timelineRequestRef.current + 1;
      timelineRequestRef.current = requestId;
      setConversationTimeline({
        ...emptyConversationTimeline,
        conversationId: conversation.id,
        loading: true,
      });
      try {
        const response = await api.getConversationMessages(conversation.id, projectId, {
          limit: 50,
        });
        if (timelineRequestRef.current !== requestId) return;
        const responseItems = response.timeline ?? [];
        setConversationTimeline((current) => {
          const items =
            current.conversationId === conversation.id
              ? mergeTimelineItems(responseItems, current.items)
              : responseItems;
          return {
            conversationId: conversation.id,
            items,
            loading: false,
            loadingEarlier: false,
            error: null,
            hasMore: Boolean(response.has_more),
            firstCursor:
              typeof response.first_time_us === 'number' &&
              typeof response.first_counter === 'number'
                ? { timeUs: response.first_time_us, counter: response.first_counter }
                : timelineCursorFromFirst(items),
            lastCursor:
              typeof response.last_time_us === 'number' && typeof response.last_counter === 'number'
                ? { timeUs: response.last_time_us, counter: response.last_counter }
                : timelineCursorFromLast(items),
          };
        });
      } catch (caught) {
        if (timelineRequestRef.current !== requestId) return;
        setConversationTimeline({
          ...emptyConversationTimeline,
          conversationId: conversation.id,
          error: formatConnectionError(caught, config.apiBaseUrl),
        });
      }
    },
    [api, config.apiBaseUrl],
  );

  const loadEarlierTimeline = useCallback(async () => {
    const conversation = agentConversationSession?.conversation;
    const cursor = conversationTimeline.firstCursor;
    if (!conversation || !cursor || conversationTimeline.loadingEarlier) return;
    setConversationTimeline((current) => ({ ...current, loadingEarlier: true, error: null }));
    try {
      const response = await api.getConversationMessages(conversation.id, config.projectId, {
        limit: 50,
        beforeTimeUs: cursor.timeUs,
        beforeCounter: cursor.counter,
      });
      setConversationTimeline((current) => {
        if (current.conversationId !== conversation.id) return current;
        const items = mergeTimelineItems(response.timeline ?? [], current.items);
        return {
          ...current,
          items,
          loadingEarlier: false,
          hasMore: Boolean(response.has_more),
          firstCursor:
            typeof response.first_time_us === 'number' && typeof response.first_counter === 'number'
              ? { timeUs: response.first_time_us, counter: response.first_counter }
              : timelineCursorFromFirst(items),
          lastCursor: timelineCursorFromLast(items),
        };
      });
    } catch (caught) {
      setConversationTimeline((current) => ({
        ...current,
        loadingEarlier: false,
        error: formatConnectionError(caught, config.apiBaseUrl),
      }));
    }
  }, [
    agentConversationSession?.conversation,
    api,
    config.apiBaseUrl,
    config.projectId,
    conversationTimeline.firstCursor,
    conversationTimeline.loadingEarlier,
  ]);

  const respondToHitl = useCallback(
    async (submission: HitlResponseSubmission) => {
      setError(null);
      try {
        await api.respondToHitl(submission);
        setConversationTimeline((current) => ({
          ...current,
          items: current.items.map((item) => {
            const payload = asRecordValue(item.payload);
            const itemRequestId =
              item.requestId ??
              (typeof item.request_id === 'string' ? item.request_id : undefined) ??
              (payload ? readStringField(payload, 'request_id') : undefined);
            return itemRequestId === submission.requestId
              ? { ...item, answered: true, ...submission.responseData }
              : item;
          }),
        }));
      } catch (caught) {
        const message = formatConnectionError(caught, config.apiBaseUrl);
        setError(message);
        throw new Error(message, { cause: caught });
      }
    },
    [api, config.apiBaseUrl],
  );

  const openCommandPalette = useCallback((trigger?: HTMLElement | null) => {
    commandPaletteTriggerRef.current =
      trigger ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setRunActionsMenuOpen(false);
    setSessionMenuOpen(false);
    setMobileSectionMenuOpen(false);
    setActiveMobileMenuItemId(null);
    setCommandPaletteOpen(true);
  }, []);

  const closeCommandPalette = useCallback((restoreFocus = false) => {
    const trigger = commandPaletteTriggerRef.current;
    setCommandPaletteOpen(false);
    setCommandQuery('');
    commandPaletteTriggerRef.current = null;
    if (restoreFocus && trigger?.isConnected) {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          if (trigger.isConnected) {
            trigger.focus();
          }
        });
      });
    }
  }, []);

  const getLoginRestoreTarget = useCallback(() => {
    if (loginRestoreTargetRef.current?.isConnected) {
      return loginRestoreTargetRef.current;
    }
    return (
      document.querySelector<HTMLElement>('[aria-label="Open command palette"]') ??
      document.querySelector<HTMLElement>('[aria-label="Sign in to agi-stack"]')
    );
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === 'k') {
        event.preventDefault();
        openCommandPalette();
        return;
      }
      if (
        event.key === '/' &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey &&
        !commandPaletteOpen &&
        !loginModalOpen &&
        !isEditableEventTarget(event.target)
      ) {
        event.preventDefault();
        setCommandQuery('');
        openCommandPalette();
        return;
      }
      if (event.key === 'Escape' && commandPaletteOpen) {
        event.preventDefault();
        closeCommandPalette(true);
      }
      if (event.key === 'Escape' && sessionMenuOpen) {
        event.preventDefault();
        setSessionMenuOpen(false);
      }
      if (event.key === 'Escape' && runActionsMenuOpen) {
        event.preventDefault();
        setRunActionsMenuOpen(false);
        runActionsButtonRef.current?.focus();
        return;
      }
      if (event.key === 'Escape' && mobileSectionMenuOpen) {
        event.preventDefault();
        setMobileSectionMenuOpen(false);
        setActiveMobileMenuItemId(null);
        mobileSectionButtonRef.current?.focus();
        return;
      }
      if (
        mobileSectionMenuOpen &&
        ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)
      ) {
        const enabledItems = mobileTitlebarItemsRef.current.filter((item) => !item.disabled);
        if (!enabledItems.length) return;
        event.preventDefault();
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          const delta = event.key === 'ArrowDown' ? 1 : -1;
          setActiveMobileMenuItemId((current) => {
            const currentIndex = enabledItems.findIndex((item) => item.id === current);
            const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
            const nextIndex = (startIndex + delta + enabledItems.length) % enabledItems.length;
            return enabledItems[nextIndex].id;
          });
          return;
        }
        if (event.key === 'Home' || event.key === 'End') {
          setActiveMobileMenuItemId(
            event.key === 'Home' ? enabledItems[0].id : enabledItems[enabledItems.length - 1].id,
          );
          return;
        }
        const activeItem =
          enabledItems.find((item) => item.id === activeMobileMenuItemId) ?? enabledItems[0];
        activeItem.onSelect();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    activeMobileMenuItemId,
    closeCommandPalette,
    commandPaletteOpen,
    loginModalOpen,
    mobileSectionMenuOpen,
    openCommandPalette,
    runActionsMenuOpen,
    sessionMenuOpen,
  ]);

  useEffect(() => {
    const shell = appShellRef.current;
    if (!shell) return;
    const backgroundRoots = [
      document.getElementById('root'),
      shell.parentElement,
      shell,
    ].filter(
      (element, index, elements): element is HTMLElement =>
        element instanceof HTMLElement && elements.indexOf(element) === index,
    );

    if (modalOpen) {
      backgroundRoots.forEach((element) => {
        element.setAttribute('aria-hidden', 'true');
        element.setAttribute('inert', '');
      });
      return;
    }

    backgroundRoots.forEach((element) => {
      element.removeAttribute('aria-hidden');
      element.removeAttribute('inert');
    });
  }, [modalOpen]);

  useEffect(() => {
    if (!mobileSectionMenuOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (mobileSectionMenuRef.current?.contains(target)) return;
      if (mobileSectionButtonRef.current?.contains(target)) return;
      setMobileSectionMenuOpen(false);
      setActiveMobileMenuItemId(null);
    };

    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [mobileSectionMenuOpen]);

  useEffect(() => {
    if (!runActionsMenuOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (runActionsMenuRef.current?.contains(target)) return;
      if (runActionsButtonRef.current?.contains(target)) return;
      setRunActionsMenuOpen(false);
    };

    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [runActionsMenuOpen]);

  useEffect(() => {
    if (!mobileSectionMenuOpen || !activeMobileMenuOptionId) return;
    const activeOption = document.getElementById(activeMobileMenuOptionId);
    activeOption?.scrollIntoView({ block: 'nearest' });
    if (activeOption instanceof HTMLElement && document.activeElement !== activeOption) {
      activeOption.focus({ preventScroll: true });
    }
  }, [activeMobileMenuOptionId, mobileSectionMenuOpen]);

  useEffect(() => {
    if (!commandPaletteOpen) return;
    window.requestAnimationFrame(() => commandInputRef.current?.focus());
  }, [commandPaletteOpen]);

  useEffect(() => {
    const update = agentTaskUpdateFromSocketEvent(socket.events[0]);
    if (!update) return;
    setAgentTaskSignals((current) => {
      const matchesConversation = (signal: AgentTaskSignal) =>
        signal.conversationId === update.conversationId && signal.status !== 'failed';
      const exactIndex = update.messageId
        ? current.findIndex(
            (signal) => matchesConversation(signal) && signal.messageId === update.messageId,
          )
        : -1;
      let targetIndex = exactIndex;
      if (targetIndex < 0) {
        for (let index = current.length - 1; index >= 0; index -= 1) {
          const signal = current[index];
          if (signal && matchesConversation(signal)) {
            targetIndex = index;
            break;
          }
        }
      }

      if (targetIndex < 0) return current;

      return current.map((signal, index) =>
        index === targetIndex
          ? {
              ...signal,
              messageId: update.messageId ?? signal.messageId,
              status: update.status,
              detail: update.detail,
              eventType: update.eventType,
            }
          : signal,
      );
    });
  }, [socket.events]);

  useEffect(() => {
    const latest = socket.events[0];
    if (!latest || typeof latest !== 'object') return;
    const payload = latest as Record<string, unknown>;
    const conversationId = readStringField(payload, 'conversation_id');
    const activeConversation =
      agentConversationSession?.scopeKey === agentConversationScopeKey(config)
        ? agentConversationSession.conversation
        : null;
    if (!activeConversation || conversationId !== activeConversation.id) return;
    setConversationTimeline((current) => {
      if (current.conversationId !== activeConversation.id) return current;
      const items = mergeLiveTimelineEvent(current.items, latest);
      if (items === current.items) return current;
      return {
        ...current,
        items,
        firstCursor: timelineCursorFromFirst(items),
        lastCursor: timelineCursorFromLast(items),
      };
    });
  }, [agentConversationSession, config, socket.events]);

  const requiresPlatformApiKey = config.mode !== 'local';
  const showRuntimeConfig =
    localRuntimeMode || auth.status === 'signed_in' || auth.status === 'manual';
  const showReviewPanel = showRuntimeConfig && reviewPanelOpen && activeSection !== 'review';
  const runControlLabel = runControlLabels[runControlState];
  const runtimeDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before connecting.'
    : !config.apiBaseUrl.trim()
      ? 'Local runtime URL is not ready yet.'
    : requiresPlatformApiKey && !config.apiKey.trim()
      ? 'Enter an API key or sign in before connecting.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before connecting.'
        : null;
  const workspaceDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before loading workspaces.'
    : requiresPlatformApiKey && !config.apiKey.trim()
      ? 'Enter an API key before loading workspaces.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before loading workspaces.'
        : null;
  const sandboxDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before starting sandbox services.'
    : requiresPlatformApiKey && !config.apiKey.trim()
      ? 'Enter an API key before starting sandbox services.'
      : !config.projectId.trim()
        ? 'Select a project before starting sandbox services.'
        : null;
  const chatDisabledReason = !showRuntimeConfig
    ? 'Sign in or enter an API key before sending messages.'
    : requiresPlatformApiKey && !config.apiKey.trim()
      ? 'Enter an API key before sending messages.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before chatting.'
    : !config.workspaceId
      ? 'Create or select a workspace before sending messages.'
      : connection !== 'ready'
        ? 'Connect the workspace before sending messages.'
        : !socket.connected && !localRuntimeMode
          ? socket.error
            ? `Agent live connection is unavailable: ${socket.error}`
            : 'Agent live connection is still connecting.'
        : null;

  useEffect(() => {
    if (!activeDataset.tasks.length) {
      setSelectedTaskId('');
      return;
    }
    if (!activeDataset.tasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(activeDataset.tasks[0].id);
    }
  }, [activeDataset.tasks, selectedTaskId]);

  const refreshRuntime = useCallback(
    async (nextConfig: DesktopRuntimeConfig = config, projectOverride?: ProjectSummary[]) => {
      setConnection('loading');
      setError(null);
      try {
        const runtimeConfig = await syncLocalRuntimeConfig(nextConfig);
        const projects =
          projectOverride ?? resolveSidebarProjects(runtimeConfig, auth.status, auth.projects);
        const loadingNodeState: RuntimeNodeLoadState = {
          projects: Object.fromEntries(
            projects.map((project) => [
              project.id,
              { loading: true, error: null },
            ]),
          ),
          workspaces: {},
        };
        setDataset((current) => ({ ...current, nodeState: loadingNodeState }));

        const workspaceResults = await Promise.all(
          projects.map(async (project) => {
            const projectTenantId = project.tenant_id || runtimeConfig.tenantId;
            const client = new DesktopApiClient({
              ...runtimeConfig,
              tenantId: projectTenantId,
              projectId: project.id,
              workspaceId: '',
            });
            try {
              const workspaces = await client.listWorkspacesForProject(project.id, projectTenantId);
              return { project, workspaces, error: null };
            } catch (caught) {
              return { project, workspaces: [] as WorkspaceSummary[], error: formatError(caught) };
            }
          }),
        );

        const workspacesByProject = Object.fromEntries(
          workspaceResults.map((result) => [result.project.id, result.workspaces]),
        );
        const projectNodeState = Object.fromEntries(
          workspaceResults.map((result) => [
            result.project.id,
            { loading: false, error: result.error },
          ]),
        );
        const workspaceProjectIds = new Map<string, string>();
        const workspaces = workspaceResults.flatMap((result) =>
          result.workspaces.map((workspace) => {
            workspaceProjectIds.set(workspace.id, result.project.id);
            return workspace;
          }),
        );
        const resolvedProjectId =
          projects.some((project) => project.id === runtimeConfig.projectId.trim())
            ? runtimeConfig.projectId.trim()
            : projects[0]?.id ?? runtimeConfig.projectId.trim();
        const resolvedProject =
          projects.find((project) => project.id === resolvedProjectId) ?? projects[0] ?? null;
        const projectWorkspaces = workspacesByProject[resolvedProjectId] ?? [];
        const workspaceId =
          runtimeConfig.workspaceId.trim() &&
          projectWorkspaces.some((workspace) => workspace.id === runtimeConfig.workspaceId.trim())
            ? runtimeConfig.workspaceId.trim()
            : projectWorkspaces[0]?.id ?? '';
        const resolvedConfig = {
          ...runtimeConfig,
          tenantId: resolvedProject?.tenant_id || runtimeConfig.tenantId,
          projectId: resolvedProjectId,
          workspaceId,
        };
        const scopedClient = new DesktopApiClient(resolvedConfig);
        const [messages, tasks, plan] = await Promise.all([
          workspaceId ? scopedClient.listMessages() : Promise.resolve([]),
          workspaceId ? scopedClient.listTasks() : Promise.resolve([]),
          workspaceId ? scopedClient.getPlanSnapshot().catch(() => null) : Promise.resolve(null),
        ]);
        const conversationResults = await Promise.all(
          workspaces.map(async (workspace) => {
            const projectId = workspaceProjectIds.get(workspace.id) ?? resolvedProjectId;
            const project = projects.find((item) => item.id === projectId);
            const client = new DesktopApiClient({
              ...runtimeConfig,
              tenantId: project?.tenant_id || runtimeConfig.tenantId,
              projectId,
              workspaceId: workspace.id,
            });
            try {
              const response = await client.listConversations(projectId, workspace.id);
              return { workspaceId: workspace.id, conversations: response.items, error: null };
            } catch (caught) {
              return {
                workspaceId: workspace.id,
                conversations: [] as AgentConversation[],
                error: formatError(caught),
              };
            }
          }),
        );
        const conversationsByWorkspace = Object.fromEntries(
          conversationResults.map((result) => [result.workspaceId, result.conversations]),
        );
        const workspaceNodeState = Object.fromEntries(
          conversationResults.map((result) => [
            result.workspaceId,
            { loading: false, error: result.error },
          ]),
        );

        setConfig(resolvedConfig);
        setDataset({
          workspaces,
          workspacesByProject,
          conversationsByWorkspace,
          nodeState: { projects: projectNodeState, workspaces: workspaceNodeState },
          messages,
          tasks,
          plan,
          sandbox: null,
        });
        if (resolvedProjectId) {
          setExpandedProjectIds((current) => new Set([...current, resolvedProjectId]));
        }
        if (workspaceId) {
          setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
        }
        setConnection('ready');
        setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      } catch (caught) {
        setConnection('error');
        setError(formatConnectionError(caught, nextConfig.apiBaseUrl));
      }
    },
    [auth.projects, auth.status, config, syncLocalRuntimeConfig],
  );

  const login = async () => {
    const username = loginEmail.trim();
    if (!username || !loginPassword) return;

    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    try {
      const loginClient = new DesktopApiClient({ ...config, apiKey: '' });
      const outcome = await loginClient.login(username, loginPassword);
      const tokenConfig = { ...config, apiKey: outcome.access_token, workspaceId: '' };
      const identityClient = new DesktopApiClient(tokenConfig);
      const [user, tenants] = await Promise.all([
        identityClient.currentUser(),
        identityClient.listTenants(),
      ]);
      const firstTenantId = tenants[0]?.id ?? '';
      const projectClient = new DesktopApiClient({ ...tokenConfig, tenantId: firstTenantId });
      const projects = await projectClient.listProjects(firstTenantId || undefined);
      const tenantId = firstTenantId || projects[0]?.tenant_id || '';
      const projectId = projects[0]?.id ?? '';
      const nextConfig = { ...tokenConfig, tenantId, projectId, workspaceId: '' };

      setConfig(nextConfig);
      setAuth({
        status: 'signed_in',
        user,
        tenants,
        projects,
        mustChangePassword: outcome.must_change_password,
        error: null,
      });
      setLoginPassword('');

      if (projectId) {
        await refreshRuntime(nextConfig, projects);
        applySectionSideEffects('chat');
      } else {
        setDataset(emptyDataset);
        setConnection('ready');
        setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
        applySectionSideEffects('settings');
      }
    } catch (caught) {
      const message = formatLoginError(caught, config.apiBaseUrl);
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    }
  };

  const handleConfigChange = (nextConfig: DesktopRuntimeConfig) => {
    const resolvedConfig =
      nextConfig.mode === 'local'
        ? {
            ...nextConfig,
            tenantId: nextConfig.tenantId.trim() || 'local',
            projectId: nextConfig.projectId.trim() || 'local-project',
          }
        : nextConfig;
    setConfig(resolvedConfig);
    setConnection('idle');
    setAgentConversationSession(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
  };

  const useApiKeyManually = () => {
    setAuth({ ...emptyAuthState, status: 'manual' });
    setLoginModalOpen(false);
    setConnection('idle');
    setError(null);
    setSectionBackStack([]);
    setSectionForwardStack([]);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    applySectionSideEffects('settings');
    setRuntimeApiKeyFocusSignal((signal) => signal + 1);
  };

  const logout = () => {
    setAuth(emptyAuthState);
    setLoginModalOpen(false);
    setConfig({
      ...DEFAULT_CONFIG,
      apiBaseUrl: config.apiBaseUrl,
      mode: config.mode,
      llmProvider: config.llmProvider,
      llmBaseUrl: config.llmBaseUrl,
      llmModel: config.llmModel,
      llmApiKey: config.llmApiKey,
      workspaceRoot: config.workspaceRoot,
    });
    setDataset(emptyDataset);
    setConnection('idle');
    setError(null);
    setLastSync('never');
    setChatInput('');
    setSectionBackStack([]);
    setSectionForwardStack([]);
    setLocalSidebarRuns([]);
    setLocalRunEvents([]);
    setSelectedSidebarRunId('');
    setRunStateById({});
    setRunControlState('running');
    setRunLiveMode(true);
    setSelectedTaskId('');
    setDesktop(null);
    setTerminal(null);
    setTerminalInput('');
    setAgentConversationSession(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    setNewWorkspaceName(DEFAULT_WORKSPACE_NAME);
    setCreatingSessionWorkspaceId(null);
    setExpandedProjectIds(new Set());
    setExpandedWorkspaceIds(new Set());
    setActiveSection('workspace');
    setStatusTab('overview');
    terminalProxy.clear();
  };

  const selectProject = (projectId: string) => {
    const project =
      sidebarProjects.find((item) => item.id === projectId) ??
      auth.projects.find((item) => item.id === projectId);
    const workspaces = dataset.workspacesByProject[projectId] ?? [];
    const workspaceId = workspaces[0]?.id ?? '';
    const nextConfig = {
      ...config,
      tenantId: project?.tenant_id || config.tenantId,
      projectId,
      workspaceId,
    };
    setConfig(nextConfig);
    setAgentConversationSession(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    setExpandedProjectIds((current) => new Set([...current, projectId]));
    if (workspaceId) {
      setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
    }
    void refreshRuntime(nextConfig);
  };

  const selectWorkspace = (workspaceId: string, projectId = config.projectId) => {
    const project =
      sidebarProjects.find((item) => item.id === projectId) ??
      auth.projects.find((item) => item.id === projectId);
    const nextConfig = {
      ...config,
      tenantId: project?.tenant_id || config.tenantId,
      projectId,
      workspaceId,
    };
    setConfig(nextConfig);
    setAgentConversationSession(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    setExpandedProjectIds((current) => new Set([...current, projectId]));
    setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
    void refreshRuntime(nextConfig);
  };

  const selectConversation = (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
    targetSection: WorkbenchSection = 'chat',
  ) => {
    const project =
      sidebarProjects.find((item) => item.id === projectId) ??
      auth.projects.find((item) => item.id === projectId);
    const nextConfig = {
      ...config,
      tenantId: project?.tenant_id || config.tenantId,
      projectId,
      workspaceId,
    };
    setConfig(nextConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(projectId, workspaceId),
      conversation,
    });
    setAgentTaskSignals([]);
    setExpandedProjectIds((current) => new Set([...current, projectId]));
    setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
    socket.subscribeConversation(conversation.id);
    applySectionSideEffects(targetSection);
    void loadConversationTimeline(conversation, projectId);
    void refreshRuntime(nextConfig);
  };

  const createWorkspace = async (projectId = config.projectId) => {
    const name = resolveNewWorkspaceName(newWorkspaceName);
    const project =
      sidebarProjects.find((item) => item.id === projectId) ??
      auth.projects.find((item) => item.id === projectId);
    const projectTenantId = project?.tenant_id || config.tenantId;
    setCreatingWorkspace(true);
    setError(null);
    try {
      const client = new DesktopApiClient({
        ...config,
        tenantId: projectTenantId,
        projectId,
        workspaceId: '',
      });
      const created = await client.createWorkspaceForProject(
        projectId,
        name,
        'Created from agi-stack Desktop',
        projectTenantId,
      );
      const nextConfig = {
        ...config,
        tenantId: projectTenantId,
        projectId,
        workspaceId: created.id,
      };
      setConfig(nextConfig);
      setAgentConversationSession(null);
      setConversationTimeline(emptyConversationTimeline);
      setAgentTaskSignals([]);
      setNewWorkspaceName(DEFAULT_WORKSPACE_NAME);
      setExpandedProjectIds((current) => new Set([...current, projectId]));
      setExpandedWorkspaceIds((current) => new Set([...current, created.id]));
      applySectionSideEffects('chat');
      await refreshRuntime(nextConfig);
    } catch (caught) {
      setError(formatConnectionError(caught, config.apiBaseUrl));
    } finally {
      setCreatingWorkspace(false);
    }
  };

  const createSessionForWorkspace = async (projectId: string, workspaceId: string) => {
    const project =
      sidebarProjects.find((item) => item.id === projectId) ??
      auth.projects.find((item) => item.id === projectId);
    const workspace = dataset.workspaces.find((item) => item.id === workspaceId);
    const projectTenantId = project?.tenant_id || config.tenantId;
    const nextConfig = {
      ...config,
      tenantId: projectTenantId,
      projectId,
      workspaceId,
    };
    const workspaceName = workspaceLabel(workspace);
    setCreatingSessionWorkspaceId(workspaceId);
    setError(null);
    try {
      const client = new DesktopApiClient(nextConfig);
      const created = await client.createAgentConversation(
        `${workspaceName}: New session ${new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        })}`,
        projectId,
      );
      const conversation = await client.updateAgentConversationMode(
        created.id,
        { workspace_id: workspaceId },
        projectId,
      );
      setConfig(nextConfig);
      setAgentConversationSession({
        scopeKey: agentConversationScopeKeyFor(projectId, workspaceId),
        conversation,
      });
      setDataset((current) => ({
        ...current,
        conversationsByWorkspace: {
          ...current.conversationsByWorkspace,
          [workspaceId]: [
            conversation,
            ...(current.conversationsByWorkspace[workspaceId] ?? []).filter(
              (item) => item.id !== conversation.id,
            ),
          ],
        },
      }));
      setExpandedProjectIds((current) => new Set([...current, projectId]));
      setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
      socket.subscribeConversation(conversation.id);
      applySectionSideEffects('chat');
      void loadConversationTimeline(conversation, projectId);
      await refreshRuntime(nextConfig);
    } catch (caught) {
      setError(formatConnectionError(caught, config.apiBaseUrl));
    } finally {
      setCreatingSessionWorkspaceId(null);
    }
  };

  const startNewSession = () => {
    setError(null);
    setLoginModalOpen(false);
    setCommandPaletteOpen(false);
    setCommandQuery('');
    setChatInput('');
    setSelectedTaskId('');
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    setStatusTab('overview');
    setReviewTab('plan');
    setSectionBackStack([]);
    setSectionForwardStack([]);

    if (showRuntimeConfig && !workspaceDisabledReason) {
      void createWorkspace(config.projectId);
      return;
    }

    applySectionSideEffects('workspace');
  };

  const ensureAgentConversation = async (firstMessage: string): Promise<AgentConversation> => {
    const scopeKey = agentConversationScopeKey(config);
    if (
      agentConversationSession?.scopeKey === scopeKey &&
      agentConversationSession.conversation.project_id === config.projectId.trim()
    ) {
      return agentConversationSession.conversation;
    }

    const workspace = dataset.workspaces.find((item) => item.id === config.workspaceId.trim());
    const workspaceLabel = workspace?.name || workspace?.title || 'Desktop workspace';
    const titleSource = firstMessage.length > 42 ? `${firstMessage.slice(0, 39)}...` : firstMessage;
    const created = await api.createAgentConversation(
      `${workspaceLabel}: ${titleSource}`,
      config.projectId,
    );
    const conversation = config.workspaceId.trim()
      ? await api.updateAgentConversationMode(
          created.id,
          {
            workspace_id: config.workspaceId.trim(),
          },
          config.projectId,
        )
      : created;
    setAgentConversationSession({ scopeKey, conversation });
    if (config.workspaceId.trim()) {
      setDataset((current) => ({
        ...current,
        conversationsByWorkspace: {
          ...current.conversationsByWorkspace,
          [config.workspaceId.trim()]: [
            conversation,
            ...(current.conversationsByWorkspace[config.workspaceId.trim()] ?? []).filter(
              (item) => item.id !== conversation.id,
            ),
          ],
        },
      }));
    }
    socket.subscribeConversation(conversation.id);
    void loadConversationTimeline(conversation, config.projectId);
    return conversation;
  };

  const sendMessageContent = async (rawContent: string, onWorkspaceMessageSaved?: () => void) => {
    const content = rawContent.trim();
    if (!content) return;
    if (chatDisabledReason) {
      setError(chatDisabledReason);
      return;
    }
    setSending(true);
    setError(null);
    const signalId = `agent-task-${Date.now()}`;
    upsertAgentTaskSignal({
      id: signalId,
      content,
      status: 'saving',
      detail: 'Saving workspace message before handing it to the Agent.',
      createdAt: new Date().toISOString(),
    });
    try {
      const saved = await api.sendMessage(content);
      setDataset((current) => ({ ...current, messages: [...current.messages, saved] }));
      onWorkspaceMessageSaved?.();
      upsertAgentTaskSignal({
        id: signalId,
        messageId: saved.id,
        status: 'queued',
        detail: 'Workspace message saved. Opening the Agent conversation.',
      });

      if (config.projectId.trim()) {
        try {
          const conversation = await ensureAgentConversation(content);
          const messageId = saved.id || `desktop-${Date.now()}`;
          upsertAgentTaskSignal({
            id: signalId,
            conversationId: conversation.id,
            messageId,
            status: 'queued',
            detail: 'Agent conversation opened. Sending task over WebSocket.',
          });
          const queued = socket.sendAgentMessage({
            conversationId: conversation.id,
            projectId: config.projectId,
            message: content,
            messageId,
          });
          setConversationTimeline((current) => {
            if (current.conversationId !== conversation.id) return current;
            const items = mergeTimelineItems(current.items, [
              optimisticUserTimelineItem(messageId, content),
            ]);
            return {
              ...current,
              items,
              firstCursor: timelineCursorFromFirst(items),
              lastCursor: timelineCursorFromLast(items),
            };
          });
          if (!queued && localRuntimeMode) {
            await api.runAgentMessage(conversation.id, content, messageId, config.projectId);
            upsertAgentTaskSignal({
              id: signalId,
              status: 'queued',
              detail: 'Task sent to local Agent runtime over loopback HTTP.',
            });
          } else if (!queued) {
            const websocketMessage = 'Message saved, but the Agent WebSocket is not connected yet.';
            setError(websocketMessage);
            upsertAgentTaskSignal({
              id: signalId,
              status: 'failed',
              detail: websocketMessage,
            });
          } else {
            upsertAgentTaskSignal({
              id: signalId,
              status: 'queued',
              detail: 'Task sent to Agent. Waiting for acknowledgement.',
            });
          }
        } catch (agentError) {
          const detail = `Message saved, but Agent launch failed: ${formatConnectionError(
            agentError,
            config.apiBaseUrl,
          )}`;
          setError(detail);
          upsertAgentTaskSignal({
            id: signalId,
            status: 'failed',
            detail,
          });
        }
      } else {
        upsertAgentTaskSignal({
          id: signalId,
          status: 'failed',
          detail: 'Message saved, but no project is selected for Agent launch.',
        });
      }
    } catch (caught) {
      const detail = formatConnectionError(caught, config.apiBaseUrl);
      setError(detail);
      upsertAgentTaskSignal({
        id: signalId,
        status: 'failed',
        detail,
      });
    } finally {
      setSending(false);
    }
  };

  const sendMessage = async () => {
    await sendMessageContent(chatInput, () => setChatInput(''));
  };

  const ensureSandbox = async () => {
    await runSandboxAction(async () => {
      const sandbox = await api.ensureSandbox();
      setDataset((current) => ({ ...current, sandbox }));
    });
  };

  const startDesktop = async () => {
    await runSandboxAction(async () => {
      await api.seedProxyAuthCookie();
      const response = await api.startDesktop();
      setDesktop(response);
      const sandbox = await api.getSandbox().catch(() => dataset.sandbox);
      setDataset((current) => ({ ...current, sandbox }));
      setStatusTab('sandbox');
    });
  };

  const startTerminal = async () => {
    await runSandboxAction(async () => {
      await api.seedProxyAuthCookie();
      const response = await api.startTerminal();
      setTerminal(response);
      setStatusTab('sandbox');
    });
  };

  const runSandboxAction = async (action: () => Promise<void>) => {
    setSandboxBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(formatConnectionError(caught, config.apiBaseUrl));
    } finally {
      setSandboxBusy(false);
    }
  };

  const sendTerminalInput = () => {
    const input = terminalInput.trimEnd();
    if (!input) return;
    terminalProxy.sendInput(`${input}\n`);
    setTerminalInput('');
  };

  const runMemoryAction = async (action: () => Promise<LocalMemoryResult>) => {
    setMemoryBusy(true);
    setError(null);
    try {
      setMemoryResult(await action());
    } catch (caught) {
      setMemoryResult({ label: 'Error', usedFallback: false, data: formatError(caught) });
    } finally {
      setMemoryBusy(false);
    }
  };

  const memoryProjectId = config.projectId.trim() || 'desktop-local';
  const memoryAuthorId = auth.user?.user_id ?? 'desktop-user';
  const paneStageClassName = 'pane-stage single-stage';
  const configuredProject = useMemo(
    () => projectSummaryFromConfig(config),
    [config.projectId, config.tenantId],
  );
  const sidebarProjects = useMemo(() => {
    if (auth.status === 'signed_in' && auth.projects.length) return auth.projects;
    return configuredProject ? [configuredProject] : [];
  }, [auth.projects, auth.status, configuredProject]);
  const selectedWorkspace = useMemo(
    () => dataset.workspaces.find((workspace) => workspace.id === config.workspaceId) ?? null,
    [config.workspaceId, dataset.workspaces],
  );
  const selectedProject = useMemo(
    () =>
      sidebarProjects.find((project) => project.id === config.projectId) ??
      auth.projects.find((project) => project.id === config.projectId) ??
      null,
    [auth.projects, config.projectId, sidebarProjects],
  );
  const selectedConversation =
    agentConversationSession?.scopeKey === agentConversationScopeKey(config)
      ? agentConversationSession.conversation
      : null;
  const hasWorkspaceScope = Boolean(config.workspaceId.trim());
  const hasProjectScope = Boolean(config.projectId.trim());
  const sessionTitle =
    selectedConversation?.title ??
    selectedWorkspace?.name ??
    selectedWorkspace?.title ??
    selectedWorkspace?.id ??
    (showRuntimeConfig ? 'Connection setup' : 'New session');
  const sessionInfoLabel = hasWorkspaceScope
    ? config.workspaceId.trim()
    : hasProjectScope
      ? config.projectId.trim()
      : 'Not connected';
  const authStatusLabel =
    auth.status === 'signed_in'
      ? auth.user?.email ?? 'signed in'
      : auth.status === 'manual'
        ? 'manual API key'
        : 'signed out';
  const runtimeHealthState: RuntimeHealthState =
    connection === 'error'
      ? 'error'
      : connection === 'loading'
        ? 'starting'
        : localRuntimeMode || connection === 'ready'
          ? 'healthy'
          : runLiveMode
            ? 'waiting'
            : 'offline';
  const runtimeHealthLabel = runtimeHealthLabels[runtimeHealthState];
  const usesLocalCoreMetrics = runtimeTarget === 'local';
  const runtimeMonitorHealthMetrics = [
    { label: 'Version', value: '0.3.1' },
    {
      label: 'Uptime',
      value: usesLocalCoreMetrics ? '2h 14m' : runtimeHealthLabel,
    },
    { label: 'CPU', value: usesLocalCoreMetrics ? '18%' : '0%' },
    { label: 'Memory', value: usesLocalCoreMetrics ? '4.6 / 15.8 GB' : 'idle' },
    { label: 'Workers', value: usesLocalCoreMetrics ? '8 / 16' : '0 / 16' },
  ];
  const sessionGroupLabel = sessionGroupMode === 'recent' ? 'Recent first' : 'Project folders';
  const sidebarRunItems = useMemo<SidebarRunItem[]>(() => {
    if (!showRuntimeConfig) return [];

    const workspaceProjectIds = new Map<string, string>();
    Object.entries(dataset.workspacesByProject).forEach(([projectId, workspaces]) => {
      workspaces.forEach((workspace) => workspaceProjectIds.set(workspace.id, projectId));
    });
    const workspaceById = new Map(dataset.workspaces.map((workspace) => [workspace.id, workspace]));
    const conversationItems = Object.entries(dataset.conversationsByWorkspace)
      .flatMap(([workspaceId, conversations]) =>
        conversations.map((conversation) => {
          const workspace = workspaceById.get(workspaceId);
          const projectId =
            conversation.project_id || workspaceProjectIds.get(workspaceId) || config.projectId;
          const updatedAt = conversation.updated_at ?? conversation.created_at;
          return {
            id: `conversation:${conversation.id}`,
            label: conversation.title || conversation.id,
            status: conversation.status || 'active',
            meta: `${conversation.message_count} ${
              conversation.message_count === 1 ? 'message' : 'messages'
            } · ${workspaceLabel(workspace)}`,
            time: formatRunTime(updatedAt),
            sortTime: timestampFromIso(updatedAt),
            projectId,
            workspaceId,
            conversation,
          };
        }),
      )
      .sort((left, right) => right.sortTime - left.sortTime)
      .slice(0, 6);

    const workspaceItems = dataset.workspaces
      .map((workspace) => {
        const updatedAt = workspace.updated_at ?? workspace.created_at;
        return {
          id: `workspace:${workspace.id}`,
          label: workspaceLabel(workspace),
          status: workspace.status || 'open',
          meta: workspace.description || workspace.id,
          time: formatRunTime(updatedAt),
          sortTime: timestampFromIso(updatedAt),
          projectId:
            workspace.project_id || workspaceProjectIds.get(workspace.id) || config.projectId,
          workspaceId: workspace.id,
        };
      })
      .sort((left, right) => right.sortTime - left.sortTime)
      .slice(0, 6);

    const fallbackItems = [
      {
        id: 'current-session',
        label: sessionTitle,
        status: runControlLabel,
        meta: sessionInfoLabel,
        time: lastSync,
        sortTime: 0,
        projectId: config.projectId,
        workspaceId: config.workspaceId || undefined,
      },
    ];
    const dataRunItems = conversationItems.length
      ? conversationItems
      : workspaceItems.length
        ? workspaceItems
        : fallbackItems;
    const localRunItems = localSidebarRuns.filter(
      (item) =>
        !item.projectId ||
        item.projectId === config.projectId ||
        (item.workspaceId && item.workspaceId === config.workspaceId),
    );
    const seen = new Set<string>();
    return [...localRunItems, ...dataRunItems]
      .filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      })
      .sort((left, right) => right.sortTime - left.sortTime)
      .slice(0, 6);
  }, [
    config.projectId,
    config.workspaceId,
    dataset.conversationsByWorkspace,
    dataset.workspaces,
    dataset.workspacesByProject,
    lastSync,
    localSidebarRuns,
    runControlLabel,
    sessionInfoLabel,
    sessionTitle,
    showRuntimeConfig,
  ]);
  const activeSidebarRunId =
    selectedSidebarRunId && sidebarRunItems.some((item) => item.id === selectedSidebarRunId)
      ? selectedSidebarRunId
      : sidebarRunItems[0]?.id ?? '';
  const activeSidebarRun =
    sidebarRunItems.find((item) => item.id === activeSidebarRunId) ?? null;
  const titlebarPrimaryLabel =
    showRuntimeConfig && activeSection === 'board' && activeSidebarRun
      ? `Run: ${activeSidebarRun.label}`
      : `Session: ${sessionTitle}`;
  const titlebarRunTimeLabel = activeSidebarRun?.time ?? lastSync;
  useEffect(() => {
    if (!showRuntimeConfig) {
      if (selectedSidebarRunId) setSelectedSidebarRunId('');
      return;
    }
    if (activeSidebarRunId !== selectedSidebarRunId) {
      setSelectedSidebarRunId(activeSidebarRunId);
    }
  }, [activeSidebarRunId, selectedSidebarRunId, showRuntimeConfig]);
  const quickLinkItems: QuickLinkItem[] = [
    { id: 'runs', section: 'board', label: 'Runs', icon: <GridIcon key="runs" /> },
    {
      id: 'agents',
      section: 'workspace',
      target: 'background',
      label: 'Agents',
      icon: <ActivityLogIcon key="agents" />,
    },
    { id: 'memory', section: 'memory', label: 'Memory', icon: <MagnifyingGlassIcon key="memory" /> },
    {
      id: 'artifacts',
      section: 'workspace',
      target: 'artifacts',
      label: 'Artifacts',
      icon: <ArchiveIcon key="artifacts" />,
    },
    { id: 'runtime', section: 'settings', label: 'Runtime', icon: <GearIcon key="runtime" /> },
  ];
  const toolItems: Array<[WorkbenchSection, string, ReactNode]> = [
    ['chat', 'Chats', <ChatBubbleIcon key="chat" />],
    ['sandbox', 'Sandbox', <DesktopIcon key="sandbox" />],
    ['terminal', 'Terminal', <CodeIcon key="terminal" />],
    ['settings', 'Settings', <GearIcon key="settings" />],
  ];
  const mobileTitlebarItems: MobileTitlebarMenuItem[] = showRuntimeConfig
    ? [
        ...quickLinkItems.map((item) => ({
          id: `quick-${item.id}`,
          label: item.label,
          icon: item.icon,
          selected: isQuickLinkSelected(item),
          onSelect: () => selectMobileQuickLink(item),
        })),
        ...toolItems.map(([section, label, icon]) => ({
          id: `section-${section}`,
          label,
          icon,
          selected: activeSection === section,
          onSelect: () => selectMobileSection(section),
        })),
      ]
    : [
        {
          id: 'commands',
          label: 'Commands',
          icon: <MagnifyingGlassIcon />,
          onSelect: () => {
            setMobileSectionMenuOpen(false);
            openCommandPalette(mobileSectionButtonRef.current);
          },
        },
        {
          id: 'sign-in',
          label: 'Sign in',
          icon: <RocketIcon />,
          onSelect: () => {
            setMobileSectionMenuOpen(false);
            mobileSectionButtonRef.current?.focus();
            setLoginModalOpen(true);
          },
        },
        {
          id: 'api-key',
          label: 'API key',
          icon: <GearIcon />,
          onSelect: () => {
            setMobileSectionMenuOpen(false);
            useApiKeyManually();
          },
        },
      ];
  mobileTitlebarItemsRef.current = mobileTitlebarItems;

  const changeSessionGroupMode = (mode: SessionGroupMode) => {
    setSessionGroupMode(mode);
    setSessionMenuOpen(false);
  };

  const toggleProject = (projectId: string) => {
    setExpandedProjectIds((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  };

  const toggleWorkspace = (workspaceId: string) => {
    setExpandedWorkspaceIds((current) => {
      const next = new Set(current);
      if (next.has(workspaceId)) next.delete(workspaceId);
      else next.add(workspaceId);
      return next;
    });
  };

  function isQuickLinkSelected(item: QuickLinkItem): boolean {
    if (item.target === 'background' || item.target === 'artifacts') {
      return (
        (activeSection === 'workspace' || activeSection === 'review') &&
        reviewTab === item.target
      );
    }
    return activeSection === item.section;
  }

  function selectQuickLink(item: QuickLinkItem) {
    if (item.target === 'background' || item.target === 'artifacts') {
      setReviewPanelOpen(true);
      setReviewTab(item.target);
      switchSection('workspace');
      return;
    }
    switchSection(item.section);
  }

  function selectMobileQuickLink(item: QuickLinkItem) {
    if (item.target === 'background' || item.target === 'artifacts') {
      setReviewPanelOpen(true);
      setReviewTab(item.target);
      switchSection('review');
      setMobileSectionMenuOpen(false);
      return;
    }
    selectQuickLink(item);
    setMobileSectionMenuOpen(false);
  }

  const setActiveRunControlState = (state: RunControlState) => {
    setRunControlState(state);
    if (!activeSidebarRunId) return;
    setRunStateById((current) => ({ ...current, [activeSidebarRunId]: state }));
  };

  const selectSidebarRun = (item: SidebarRunItem) => {
    setSelectedSidebarRunId(item.id);
    setRunControlState(
      runStateById[item.id] ?? (item.id === activeSidebarRunId ? runControlState : 'running'),
    );
    setRunLiveMode(true);

    if (item.conversation && item.workspaceId) {
      selectConversation(item.projectId, item.workspaceId, item.conversation, 'board');
      return;
    }

    if (item.workspaceId) {
      selectWorkspace(item.workspaceId, item.projectId);
      applySectionSideEffects('board');
      return;
    }

    selectWorkflowTarget('board');
  };

  const createLocalRun = () => {
    const now = Date.now();
    const runId = `local-run:${now}`;
    const projectLabel = config.projectId.trim() || 'local project';
    const runNumber = localSidebarRuns.length + 1;
    const artifactTimelineItems = localRunArtifactTimelineItems(runId, now);
    const localEvents = localRunWorkspaceEvents({
      runId,
      runNumber,
      nowMs: now,
      projectId: config.projectId || undefined,
      workspaceId: config.workspaceId || undefined,
    });
    const localTasks = localRunBoardTasks({
      runId,
      runNumber,
      nowMs: now,
      projectId: config.projectId || undefined,
      workspaceId: config.workspaceId || undefined,
    });
    const nextRun: SidebarRunItem = {
      id: runId,
      label: `Run #${runNumber}`,
      status: 'Planning',
      meta: `Local draft · ${projectLabel}`,
      time: formatArtifactTime(now),
      sortTime: now,
      projectId: config.projectId,
      workspaceId: config.workspaceId || undefined,
    };
    setLocalSidebarRuns((current) => [nextRun, ...current].slice(0, 6));
    setLocalRunEvents((current) => [...localEvents, ...current].slice(0, 18));
    setLocalRunTasksById((current) =>
      Object.fromEntries([[runId, localTasks], ...Object.entries(current)].slice(0, 6)),
    );
    setSelectedSidebarRunId(runId);
    setRunStateById((current) => ({ ...current, [runId]: 'planning' }));
    setRunControlState('planning');
    setRunLiveMode(true);
    setConversationTimeline({
      ...emptyConversationTimeline,
      conversationId: runId,
      items: artifactTimelineItems,
      firstCursor: timelineCursorFromFirst(artifactTimelineItems),
      lastCursor: timelineCursorFromLast(artifactTimelineItems),
    });
    setReviewPanelOpen(true);
    setReviewTab('changes');
    switchSection('board');
  };

  const selectBoardTask = (taskId: string, selectionViewLabel?: string) => {
    setSelectedTaskId(taskId);
    const task = activeDataset.tasks.find((candidate) => candidate.id === taskId);
    if (!task) return;

    const now = Date.now();
    const title = taskTitle(task) ?? task.id;
    const boardLabel = selectionViewLabel ?? (boardMode === 'flow' ? 'Timeline' : 'List');
    const nextEvent = {
      type: 'selection',
      source: task.owner ?? task.assignee_user_id ?? 'Board',
      status: 'selected',
      detail: `${title} selected in ${boardLabel}.`,
      timestamp: now,
      task_id: task.id,
      run_id: activeSidebarRunId || undefined,
      project_id: config.projectId || undefined,
      workspace_id: task.workspace_id ?? (config.workspaceId || undefined),
    };
    setLocalRunEvents((current) => [nextEvent, ...current].slice(0, 12));
  };

  const recordOperatorCommandEvent = (detail: string) => {
    const now = Date.now();
    const nextEvent = {
      type: 'message',
      source: 'Operator',
      status: '',
      detail,
      timestamp: now,
      task_id: selectedTask?.id,
      run_id: activeSidebarRunId || undefined,
      project_id: config.projectId || undefined,
      workspace_id: selectedTask?.workspace_id ?? (config.workspaceId || undefined),
    };
    setLocalRunEvents((current) => [nextEvent, ...current].slice(0, 12));
  };

  const submitBoardCommand = async (command: string) => {
    recordOperatorCommandEvent(command);
    await sendMessageContent(command);
  };

  const applySectionSideEffects = (section: WorkbenchSection) => {
    activeSectionRef.current = section;
    setActiveSection(section);
    if (section === 'sandbox' || section === 'terminal') setStatusTab('sandbox');
    if (section === 'memory') setStatusTab('memory');
    if (section === 'status') setStatusTab('overview');
    if (section === 'terminal') setReviewTab('terminal');
    if (section === 'board') setReviewTab('changes');
    if (section === 'status') setReviewTab('plan');
  };

  const switchSection = (section: WorkbenchSection) => {
    const currentSection = activeSectionRef.current;
    if (section !== currentSection) {
      setSectionBackStack([...sectionBackStack, currentSection].slice(-24));
      setSectionForwardStack([]);
    }
    applySectionSideEffects(section);
  };

  const openConnectionSettings = () => {
    if (!showRuntimeConfig) {
      useApiKeyManually();
      return;
    }
    switchSection('settings');
  };

  const selectMobileSection = (section: WorkbenchSection) => {
    switchSection(section);
    setMobileSectionMenuOpen(false);
  };

  const defaultMobileMenuItemId = () =>
    mobileTitlebarItems.find((item) => item.selected && !item.disabled)?.id ??
    mobileTitlebarItems.find((item) => !item.disabled)?.id ??
    null;

  const toggleMobileSectionMenu = () => {
    const nextOpen = !mobileSectionMenuOpen;
    if (nextOpen) {
      closeCommandPalette();
      setRunActionsMenuOpen(false);
      setSessionMenuOpen(false);
    }
    setMobileSectionMenuOpen(nextOpen);
    setActiveMobileMenuItemId(nextOpen ? defaultMobileMenuItemId() : null);
  };

  const goBackSection = () => {
    const previousSection = sectionBackStack[sectionBackStack.length - 1];
    if (!previousSection) return;
    const leavingSection = activeSectionRef.current;
    setSectionBackStack(sectionBackStack.slice(0, -1));
    setSectionForwardStack([leavingSection, ...sectionForwardStack].slice(0, 24));
    applySectionSideEffects(previousSection);
  };

  const goForwardSection = () => {
    const nextSection = sectionForwardStack[0];
    if (!nextSection) return;
    const leavingSection = activeSectionRef.current;
    setSectionBackStack([...sectionBackStack, leavingSection].slice(-24));
    setSectionForwardStack(sectionForwardStack.slice(1));
    applySectionSideEffects(nextSection);
  };

  const canGoBack = sectionBackStack.length > 0;
  const canGoForward = sectionForwardStack.length > 0;

  const selectWorkflowTarget = (target: WorkflowTarget) => {
    setReviewPanelOpen(true);
    if (target === 'changes') {
      setReviewTab('changes');
      switchSection('workspace');
      return;
    }
    if (target === 'pull') {
      setReviewTab('pull');
      switchSection('workspace');
      return;
    }
    if (target === 'board') {
      setReviewTab('changes');
      switchSection('board');
      return;
    }
    if (target === 'plan') {
      setReviewTab('plan');
      switchSection('workspace');
      return;
    }
    if (target === 'background') {
      setReviewTab('background');
      switchSection('workspace');
      return;
    }
    if (target === 'artifacts') {
      setReviewTab('artifacts');
      switchSection('workspace');
      return;
    }
    setReviewTab('terminal');
    switchSection('terminal');
  };

  const selectChatWorkflowTarget = (target: ChatWorkflowTarget) => {
    setReviewPanelOpen(true);
    if (target === 'changes') {
      setReviewTab('changes');
      return;
    }
    if (target === 'pull') {
      setReviewTab('pull');
      return;
    }
    if (target === 'background') {
      setReviewTab('background');
      return;
    }
    if (target === 'artifacts') {
      setReviewTab('artifacts');
      return;
    }
    setReviewTab('plan');
  };

  const runSelectedSession = () => {
    setError(RUN_CONTROL_UNAVAILABLE);
  };

  const openProject = () => {
    if (!showRuntimeConfig) {
      useApiKeyManually();
      return;
    }
    if (!config.projectId.trim()) {
      switchSection('settings');
      return;
    }
    switchSection(config.workspaceId ? 'workspace' : 'settings');
  };

  const openPullRequestOverview = () => {
    selectWorkflowTarget('pull');
  };

  const openUsagePlan = () => {
    switchSection('settings');
  };

  const openOtherApps = () => {
    openCommandPalette();
  };

  const commandItems: CommandPaletteItem[] = [
    {
      id: 'home',
      label: 'Home',
      description: 'Open the workspace overview.',
      icon: <DashboardIcon />,
      onSelect: () => switchSection('workspace'),
    },
    {
      id: 'my-work',
      label: 'My work',
      description: 'Open tasks, board lanes, and active work.',
      icon: <GridIcon />,
      onSelect: () => switchSection('board'),
    },
    {
      id: 'automations',
      label: 'Automations',
      description: 'Review connection status, live updates, and workflow activity.',
      icon: <ActivityLogIcon />,
      onSelect: () => switchSection('status'),
    },
    {
      id: 'search-memory',
      label: 'Search local memory',
      description: showRuntimeConfig
        ? 'Search local memory records for this desktop session.'
        : 'Sign in or use a manual API key before searching local memory.',
      icon: <MagnifyingGlassIcon />,
      shortcut: '⌘K',
      disabled: !showRuntimeConfig,
      onSelect: () => switchSection('memory'),
    },
    {
      id: 'chats',
      label: 'Chats',
      description: showRuntimeConfig
        ? 'Open the workspace message timeline.'
        : 'Sign in or use a manual API key before opening chats.',
      icon: <ChatBubbleIcon />,
      disabled: !showRuntimeConfig,
      onSelect: () => switchSection('chat'),
    },
    {
      id: 'settings',
      label: showRuntimeConfig ? 'Settings' : 'Use API key manually',
      description: showRuntimeConfig
        ? 'Edit connection, account, project, and workspace settings.'
        : 'Switch to the manual API key fallback without saving secrets.',
      icon: <GearIcon />,
      onSelect: openConnectionSettings,
    },
    {
      id: 'sign-in',
      label: auth.status === 'signed_in' ? 'Account' : 'Sign in to agi-stack',
      description:
        auth.status === 'signed_in'
          ? auth.user?.email ?? 'Review the signed-in account.'
          : 'Open the email/password login dialog.',
      icon: <RocketIcon />,
      onSelect: () => {
        if (auth.status === 'signed_in') {
          switchSection('settings');
          return;
        }
        loginRestoreTargetRef.current = commandPaletteTriggerRef.current?.isConnected
          ? commandPaletteTriggerRef.current
          : getLoginRestoreTarget();
        setLoginModalOpen(true);
      },
    },
    {
      id: 'refresh-runtime',
      label: 'Refresh workspace',
      description: runtimeDisabledReason ?? 'Reload chats, work items, plan, and sandbox.',
      icon: <RocketIcon />,
      disabled: Boolean(runtimeDisabledReason) || connection === 'loading',
      onSelect: () => void refreshRuntime(),
    },
    {
      id: 'run-selected-session',
      label: 'Run selected session',
      description: RUN_CONTROL_UNAVAILABLE,
      icon: <PlayIcon />,
      disabled: true,
      onSelect: runSelectedSession,
    },
    {
      id: 'open-project',
      label: hasProjectScope ? 'Open in VS Code' : 'Configure project',
      description: hasProjectScope
        ? 'Open the selected workspace or project settings.'
        : 'Add a project id before opening workspace files.',
      icon: <CodeIcon />,
      onSelect: openProject,
    },
  ];
  const normalizedCommandQuery = commandQuery.trim().toLowerCase();
  const filteredCommandItems = normalizedCommandQuery
    ? commandItems.filter((item) =>
        `${item.label} ${item.description}`.toLowerCase().includes(normalizedCommandQuery),
      )
    : commandItems;

  const renderChatPanel = () => (
    <ChatPanel
      messages={dataset.messages}
      timelineState={selectedConversation ? conversationTimeline : null}
      agentTaskSignals={agentTaskSignals}
      workflowCounts={chatWorkflowCounts}
      sessionTitle={selectedConversation?.title ?? workspaceLabel(selectedWorkspace ?? undefined)}
      scopeLabel={
        selectedConversation
          ? `Agent session / ${workspaceLabel(selectedWorkspace ?? undefined)}`
          : 'Workspace conversation'
      }
      input={chatInput}
      sending={sending}
      disabledReason={chatDisabledReason}
      activeWorkflowTarget={chatWorkflowTargetForReviewTab(reviewTab)}
      runtimeTargetLabel={runtimeTargetLabels[runtimeTarget]}
      runtimeTargetOptions={runtimeTargetComposerOptions}
      onInputChange={setChatInput}
      onSend={() => void sendMessage()}
      onRefresh={() =>
        selectedConversation
          ? void loadConversationTimeline(selectedConversation, config.projectId)
          : void refreshRuntime()
      }
      onLoadEarlier={() => void loadEarlierTimeline()}
      onRespondToHitl={respondToHitl}
      onWorkflowSelect={selectChatWorkflowTarget}
      onRuntimeTargetChange={(value) =>
        setRuntimeTarget(value === runtimeTargetLabels.staging ? 'staging' : 'local')
      }
      onOpenCommands={openCommandPalette}
      onOpenUsagePlan={openUsagePlan}
    />
  );

  const renderWorkspaceOverview = () => {
    const blockedTasks = activeDataset.tasks.filter((task) => task.status === 'blocked').length;
    const activeTasks = activeDataset.tasks.filter((task) => {
      const status = (task.status ?? '').toLowerCase();
      return status !== 'done' && status !== 'closed' && status !== 'completed';
    }).length;
    const latestMessage = dataset.messages[dataset.messages.length - 1] ?? null;
    const workspaceStatus = selectedWorkspace?.status ?? 'open';

    return (
      <section className="pane-shell overview-shell">
        <header className="pane-head">
          <div>
            <Heading as="h2" size="3">
              Workspace
            </Heading>
            <Text size="1" color="gray">
              Chat, work items, plan, and sandbox status for this session.
            </Text>
          </div>
          <Button
            size="2"
            variant="surface"
            aria-label="Refresh workspace overview"
            onClick={() => void refreshRuntime()}
            disabled={Boolean(runtimeDisabledReason) || connection === 'loading'}
            loading={connection === 'loading'}
          >
            <RocketIcon /> Refresh
          </Button>
        </header>
        <div className="overview-content">
          <section className="overview-summary" aria-label="Workspace summary">
            <div>
              <Text size="1" color="gray">
                Current workspace
              </Text>
              <Heading as="h3" size="4">
                {workspaceLabel(selectedWorkspace ?? undefined)}
              </Heading>
              <Text size="2" color="gray">
                {selectedWorkspace?.description ??
                  (config.workspaceId || 'Select or create a workspace to load live chat and tasks.')}
              </Text>
            </div>
            <Badge color={workspaceStatus === 'closed' ? 'gray' : 'green'} variant="soft">
              {workspaceStatus}
            </Badge>
          </section>

          <div className="overview-metrics">
            <OverviewMetric label="Messages" value={String(dataset.messages.length)} />
            <OverviewMetric label="Active tasks" value={String(activeTasks)} />
            <OverviewMetric label="Blocked" value={String(blockedTasks)} />
            <OverviewMetric label="Sandbox" value={dataset.sandbox?.status ?? 'idle'} />
          </div>

          <div className="overview-actions" aria-label="Workspace actions">
            <button
              type="button"
              aria-label="Open workspace chat"
              onClick={() => switchSection('chat')}
            >
              <span>
                <ChatBubbleIcon />
              </span>
              <strong>Open chat</strong>
              <Text size="1" color="gray">
                {latestMessage
                  ? latestMessage.content
                  : 'No messages loaded for this workspace yet.'}
              </Text>
            </button>
            <button
              type="button"
              aria-label="Review workspace work items"
              onClick={() => switchSection('board')}
            >
              <span>
                <GridIcon />
              </span>
              <strong>Review work</strong>
              <Text size="1" color="gray">
                {activeDataset.tasks.length
                  ? `${activeDataset.tasks.length} tasks across board lanes.`
                  : 'No tasks loaded for this workspace yet.'}
              </Text>
            </button>
            <button
              type="button"
              aria-label="Open workspace sandbox"
              onClick={() => switchSection('sandbox')}
            >
              <span>
                <DesktopIcon />
              </span>
              <strong>Open sandbox</strong>
              <Text size="1" color="gray">
                {dataset.sandbox?.is_healthy
                  ? 'Desktop and terminal services are available.'
                  : 'Start sandbox desktop or terminal when a project is configured.'}
              </Text>
            </button>
            <button
              type="button"
              aria-label="Open connection settings"
              onClick={() => switchSection('settings')}
            >
              <span>
                <GearIcon />
              </span>
              <strong>Connection settings</strong>
              <Text size="1" color="gray">
                {runtimeDisabledReason ?? `${config.apiBaseUrl} / ${config.mode}`}
              </Text>
            </button>
          </div>
        </div>
      </section>
    );
  };

  const renderBoardPanel = () => (
    <BoardPanel
      tasks={activeDataset.tasks}
      boardMode={boardMode}
      selectedTaskId={selectedTaskId}
      activeRunLabel={activeSidebarRun?.label ?? 'Current run'}
      activeRunTimeLabel={titlebarRunTimeLabel}
      commandDisabledReason={chatDisabledReason}
      commandSending={sending}
      runtimeTargetLabel={runtimeTargetLabels[runtimeTarget]}
      runtimeTargetOptions={runtimeTargetComposerOptions}
      onBoardModeChange={setBoardMode}
      onSelectTask={selectBoardTask}
      onOpenCommands={openCommandPalette}
      onRuntimeTargetChange={(value) =>
        setRuntimeTarget(value === runtimeTargetLabels.staging ? 'staging' : 'local')
      }
      onSubmitCommand={submitBoardCommand}
    />
  );

  const renderStatusPanel = () => (
    <StatusPanel
      selectedTask={selectedTask}
      plan={activeDataset.plan}
      events={socket.events}
      wsConnected={socket.connected}
      tab={statusTab}
      sandbox={activeDataset.sandbox}
      desktop={desktop}
      desktopFrameUrl={desktopFrameUrl}
      terminal={terminal}
      terminalConnected={terminalProxy.connected}
      terminalError={terminalProxy.error}
      terminalLines={terminalProxy.lines}
      terminalInput={terminalInput}
      sandboxBusy={sandboxBusy}
      sandboxDisabledReason={sandboxDisabledReason}
      memoryProjectId={memoryProjectId}
      memoryContent={memoryContent}
      memoryQuery={memoryQuery}
      tauriAvailable={runsInTauri}
      memoryBusy={memoryBusy}
      memoryResult={memoryResult}
      onTabChange={setStatusTab}
      onTerminalInputChange={setTerminalInput}
      onEnsureSandbox={() => void ensureSandbox()}
      onStartDesktop={() => void startDesktop()}
      onStartTerminal={() => void startTerminal()}
      onSendTerminalInput={sendTerminalInput}
      onClearTerminal={terminalProxy.clear}
      onMemoryContentChange={setMemoryContent}
      onMemoryQueryChange={setMemoryQuery}
      onMemoryIngest={() =>
        void runMemoryAction(() =>
          ingestLocalMemory(memoryProjectId, memoryAuthorId, memoryContent),
        )
      }
      onMemorySearch={() =>
        void runMemoryAction(() => searchLocalMemory(memoryProjectId, memoryQuery, 10))
      }
      onMemorySemanticSearch={() =>
        void runMemoryAction(() =>
          semanticSearchLocalMemory(memoryProjectId, memoryQuery, 10),
        )
      }
    />
  );

  const renderWorkspaceReviewPanel = (stage = false) => (
    <WorkspaceReviewPanel
      activeTab={reviewTab}
      dataset={activeDataset}
      connection={connection}
      socketConnected={socket.connected}
      socketEvents={workspaceEventInputs}
      localEventCount={localRunEvents.length}
      artifacts={workspaceArtifacts}
      selectedTask={selectedTask}
      terminalConnected={terminalProxy.connected}
      terminalLines={terminalProxy.lines}
      onTabChange={setReviewTab}
      onClose={
        stage
          ? () => {
              setReviewPanelOpen(false);
              switchSection('workspace');
            }
          : () => setReviewPanelOpen(false)
      }
      onClearLocalEvents={() => setLocalRunEvents([])}
      stage={stage}
    />
  );

  const renderWorkbench = () => {
    if (!showRuntimeConfig) {
      return (
        <SignedOutPanel
          activeTarget={signedOutTargetForSection(activeSection, reviewTab)}
          onWorkflowSelect={selectWorkflowTarget}
          onSignIn={() => setLoginModalOpen(true)}
          onUseManualKey={useApiKeyManually}
          onOpenCommands={openCommandPalette}
          onCloseCommands={closeCommandPalette}
        />
      );
    }
    if (activeSection === 'review') return renderWorkspaceReviewPanel(true);
    if (activeSection === 'workspace') return renderWorkspaceOverview();
    if (activeSection === 'chat') return renderChatPanel();
    if (activeSection === 'board') return renderBoardPanel();
    if (
      activeSection === 'status' ||
      activeSection === 'sandbox' ||
      activeSection === 'memory' ||
      activeSection === 'terminal'
    ) {
      return renderStatusPanel();
    }
    if (activeSection === 'settings') {
      return (
        <section className="pane-shell settings-shell">
          <header className="pane-head">
            <div>
              <Heading as="h2" size="3">
                Settings
              </Heading>
              <Text size="1" color="gray">
                Current connection, account, and workspace scope.
              </Text>
            </div>
            <Badge color={connection === 'ready' ? 'green' : 'gray'} variant="soft">
              {connection}
            </Badge>
          </header>
          <div className="settings-content">
            <UsagePlanPanel
              accountLabel={auth.user?.email ?? authStatusLabel}
              planLabel={auth.status === 'signed_in' ? 'Copilot Max' : 'Local development'}
              creditsUsedLabel={
                auth.status === 'signed_in' ? '8 AI credits used' : 'Sign in to view usage'
              }
            />
            <RuntimeConfigPanel
              config={config}
              connection={connection}
              wsConnected={socket.connected}
              wsError={socket.error}
              disabledReason={runtimeDisabledReason}
              focusApiKeySignal={runtimeApiKeyFocusSignal}
              onChange={handleConfigChange}
              onRefresh={() => void refreshRuntime()}
            />
            <div className="settings-grid">
              <SettingMetric label="Server" value={config.apiBaseUrl} />
              <SettingMetric label="Account" value={config.tenantId || '-'} />
              <SettingMetric label="Project" value={config.projectId || '-'} />
              <SettingMetric label="Workspace" value={config.workspaceId || '-'} />
              <SettingMetric label="Connection" value={config.mode} />
              <SettingMetric label="Live events" value={socket.connected ? 'live' : 'idle'} />
            </div>
          </div>
        </section>
      );
    }
    return renderWorkspaceOverview();
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div
        ref={appShellRef}
        className={`app-shell ${runsInTauri ? 'tauri-window' : 'browser-window'} ${
          showRuntimeConfig ? 'runtime-mode' : 'signed-out-mode'
        } ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}
      >
        <header className="titlebar" data-tauri-drag-region>
          <div className="session-crumb">
            {showRuntimeConfig && hasWorkspaceScope ? (
              <Button
                size="2"
                color="purple"
                variant="soft"
                className="pull-request-overview"
                aria-label="View pull request overview"
                onClick={openPullRequestOverview}
              >
                <ReaderIcon /> PR idle
              </Button>
            ) : null}
            {showRuntimeConfig ? (
              <Text size="2" weight="bold">
                {titlebarPrimaryLabel}
              </Text>
            ) : (
              <div className="titlebar-signedout-label" aria-label="New session">
                <Text size="3" weight="bold" className="titlebar-workspace-name">
                  New session
                </Text>
              </div>
            )}
            {showRuntimeConfig ? (
              <button
                className="session-info-button"
                type="button"
                aria-label={`${sessionInfoLabel}, session information`}
                onClick={() => switchSection('settings')}
              >
                {sessionInfoLabel}
              </button>
            ) : null}
            {showRuntimeConfig ? (
              <span
                className={`titlebar-run-status run-state-${runControlState}`}
                aria-label={`Run state ${runControlLabel}`}
              >
                <i aria-hidden />
                <span>{runControlLabel}</span>
              </span>
            ) : null}
            {showRuntimeConfig ? (
              <span
                className="titlebar-run-clock"
                aria-label={`Run time ${titlebarRunTimeLabel}`}
              >
                <ClockIcon />
                <span>{titlebarRunTimeLabel}</span>
              </span>
            ) : null}
          </div>
          {mobileTitlebarItems.length ? (
            <div className="mobile-section-switcher">
              <Tooltip content={showRuntimeConfig ? 'Switch section' : 'Session actions'}>
                <IconButton
                  ref={mobileSectionButtonRef}
                  size="2"
                  variant="soft"
                  color="gray"
                  aria-label={showRuntimeConfig ? 'Switch workspace section' : 'Open session actions'}
                  aria-controls={mobileSectionMenuOpen ? 'mobile-section-menu' : undefined}
                  aria-expanded={mobileSectionMenuOpen}
                  aria-haspopup="menu"
                  onClick={toggleMobileSectionMenu}
                >
                  {showRuntimeConfig ? <ColumnsIcon /> : <DotsHorizontalIcon />}
                </IconButton>
              </Tooltip>
              {mobileSectionMenuOpen ? (
                <div
                  className="mobile-section-menu"
                  id="mobile-section-menu"
                  ref={mobileSectionMenuRef}
                  role="menu"
                  aria-activedescendant={activeMobileMenuOptionId}
                  aria-label={showRuntimeConfig ? 'Workspace sections' : 'Session actions'}
                >
                  {mobileTitlebarItems.map((item) => {
                    const selectable = typeof item.selected === 'boolean';
                    const isActive = activeMobileMenuItemId === item.id;
                    return (
                      <button
                        id={mobileMenuOptionId(item.id)}
                        type="button"
                        role={selectable ? 'menuitemradio' : 'menuitem'}
                        aria-checked={selectable ? item.selected : undefined}
                        disabled={item.disabled}
                        className={[item.selected ? 'selected' : '', isActive ? 'active' : '']
                          .filter(Boolean)
                          .join(' ')}
                        key={item.id}
                        onFocus={() => setActiveMobileMenuItemId(item.id)}
                        onMouseEnter={() => setActiveMobileMenuItemId(item.id)}
                        onClick={item.onSelect}
                      >
                        <span aria-hidden>{item.icon}</span>
                        <strong>{item.label}</strong>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
          {showRuntimeConfig ? (
            <Flex align="center" gap="2" ml="auto" className="titlebar-actions">
              <Tooltip
                content={`${authStatusLabel} / ${config.mode} / ${connection} / last sync ${lastSync}`}
              >
                <IconButton
                  color={connection === 'ready' ? 'green' : connection === 'error' ? 'red' : 'gray'}
                  variant="soft"
                  className="runtime-readout"
                  aria-label={`Refresh workspace, ${connection}`}
                  disabled={Boolean(runtimeDisabledReason) || connection === 'loading'}
                  onClick={() => void refreshRuntime()}
                >
                  <RocketIcon />
                </IconButton>
              </Tooltip>
              <Flex align="center" gap="1" className="run-control-group" role="group" aria-label="Run controls">
                <Button
                  size="2"
                  variant="surface"
                  color={runControlState === 'paused' ? 'green' : 'gray'}
                  aria-label={RUN_CONTROL_UNAVAILABLE}
                  title={RUN_CONTROL_UNAVAILABLE}
                  disabled
                >
                  {runControlState === 'paused' ? <PlayIcon /> : <PauseIcon />}
                  {runControlState === 'paused' ? 'Resume' : 'Pause'}
                </Button>
                <Button
                  size="2"
                  variant="surface"
                  color="gray"
                  aria-label={RUN_CONTROL_UNAVAILABLE}
                  title={RUN_CONTROL_UNAVAILABLE}
                  disabled
                >
                  <PlayIcon /> Resume
                </Button>
                <Button
                  size="2"
                  variant="surface"
                  color="red"
                  aria-label={RUN_CONTROL_UNAVAILABLE}
                  title={RUN_CONTROL_UNAVAILABLE}
                  disabled
                >
                  <StopIcon /> Stop
                </Button>
              </Flex>
              <span className="run-actions-menu-control">
                <Tooltip content="More run actions">
                  <button
                    className="run-actions-button"
                    type="button"
                    aria-label="More run actions"
                    aria-haspopup="menu"
                    aria-expanded={runActionsMenuOpen}
                    ref={runActionsButtonRef}
                    onClick={() => {
                      const nextOpen = !runActionsMenuOpen;
                      if (nextOpen) {
                        closeCommandPalette();
                        setSessionMenuOpen(false);
                        setMobileSectionMenuOpen(false);
                        setActiveMobileMenuItemId(null);
                      }
                      setRunActionsMenuOpen(nextOpen);
                    }}
                  >
                    <DotsHorizontalIcon />
                  </button>
                </Tooltip>
                {runActionsMenuOpen ? (
                  <div
                    className="run-actions-menu"
                    role="menu"
                    aria-label="More run actions"
                    ref={runActionsMenuRef}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      title={RUN_CONTROL_UNAVAILABLE}
                      disabled
                    >
                      {runControlState === 'paused' ? <PlayIcon /> : <PauseIcon />}
                      <span>
                        <strong>
                          {runControlState === 'paused' ? 'Resume run' : 'Pause run'}
                        </strong>
                        <em>{RUN_CONTROL_UNAVAILABLE}</em>
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      title={RUN_CONTROL_UNAVAILABLE}
                      disabled
                    >
                      <StopIcon />
                      <span>
                        <strong>Stop run</strong>
                        <em>{RUN_CONTROL_UNAVAILABLE}</em>
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      title={RUN_CONTROL_UNAVAILABLE}
                      disabled
                    >
                      <PlayIcon />
                      <span>
                        <strong>Run selected session</strong>
                        <em>{RUN_CONTROL_UNAVAILABLE}</em>
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={Boolean(runtimeDisabledReason) || connection === 'loading'}
                      onClick={() => {
                        void refreshRuntime();
                        setRunActionsMenuOpen(false);
                      }}
                    >
                      <RocketIcon />
                      <span>
                        <strong>Refresh workspace</strong>
                        <em>Reload chats, plan, sandbox, and work items.</em>
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        switchSection('chat');
                        setRunActionsMenuOpen(false);
                      }}
                    >
                      <ChatBubbleIcon />
                      <span>
                        <strong>Open chat</strong>
                        <em>Jump to the run command composer.</em>
                      </span>
                    </button>
                  </div>
                ) : null}
              </span>
              <Button
                size="2"
                variant="surface"
                color="gray"
                aria-label={RUN_CONTROL_UNAVAILABLE}
                title={RUN_CONTROL_UNAVAILABLE}
                disabled
              >
                <PlayIcon /> Run
              </Button>
              <label className="titlebar-runtime-select">
                <span>Runtime</span>
                <select
                  aria-label="Runtime"
                  value={runtimeTarget}
                  onChange={(event) => setRuntimeTarget(event.target.value as RuntimeTarget)}
                >
                  <option value="local">{titlebarRuntimeTargetLabels.local}</option>
                  <option value="staging">{titlebarRuntimeTargetLabels.staging}</option>
                </select>
              </label>
              <div className="titlebar-live-toggle" role="group" aria-label="Run update mode">
                <button
                  type="button"
                  className={runLiveMode ? 'active' : ''}
                  aria-label="Use live run updates"
                  aria-pressed={runLiveMode}
                  onClick={() => setRunLiveMode(true)}
                >
                  Live
                </button>
                <button
                  type="button"
                  className={!runLiveMode ? 'active' : ''}
                  aria-label="Use offline run updates"
                  aria-pressed={!runLiveMode}
                  onClick={() => setRunLiveMode(false)}
                >
                  Offline
                </button>
              </div>
              <Flex align="center" gap="1" className="open-action-group">
                <Button
                  size="2"
                  variant="surface"
                  color="gray"
                  aria-label={
                    hasProjectScope
                      ? 'Open in Visual Studio Code'
                      : 'Configure project before opening in Visual Studio Code'
                  }
                  disabled={!hasProjectScope}
                  onClick={openProject}
                >
                  <CodeIcon /> {hasProjectScope ? 'VS Code' : 'Project'}
                </Button>
                <Tooltip
                  content={
                    hasProjectScope
                      ? 'Open in other apps'
                      : 'Configure a project before opening in other apps'
                  }
                >
                  <IconButton
                    variant="surface"
                    color="gray"
                    aria-label={
                      hasProjectScope
                        ? 'Open in other apps'
                        : 'Configure project before opening in other apps'
                    }
                    disabled={!hasProjectScope}
                    onClick={openOtherApps}
                  >
                    <DotsHorizontalIcon />
                  </IconButton>
                </Tooltip>
              </Flex>
              <Tooltip
                content={
                  socket.connected
                    ? 'Live updates connected'
                    : socket.error ?? 'Live updates idle'
                }
              >
                <IconButton
                  variant="surface"
                  color={socket.connected ? 'green' : socket.error ? 'red' : 'gray'}
                  aria-label={
                    socket.connected
                      ? 'Open live updates status, connected'
                      : socket.error
                        ? 'Open live updates status, error'
                        : 'Open live updates status, idle'
                  }
                  onClick={() => switchSection('status')}
                >
                  <CheckCircledIcon />
                </IconButton>
              </Tooltip>
              <Tooltip content={reviewPanelOpen ? 'Hide workspace panel' : 'Show workspace panel'}>
                <IconButton
                  variant="surface"
                  color={reviewPanelOpen ? 'cyan' : 'gray'}
                  aria-label={reviewPanelOpen ? 'Hide workspace panel' : 'Show workspace panel'}
                  aria-pressed={reviewPanelOpen}
                  onClick={() => setReviewPanelOpen((open) => !open)}
                >
                  <ColumnsIcon />
                </IconButton>
              </Tooltip>
            </Flex>
          ) : null}
        </header>

        <section className="desktop-body">
          <aside className="copilot-sidebar">
            <div className="sidebar-chrome" data-tauri-drag-region>
              <div className="sidebar-nav-controls">
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                  aria-pressed={sidebarCollapsed}
                  onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
                >
                  <ViewVerticalIcon />
                </IconButton>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label="Go back"
                  disabled={!canGoBack}
                  onClick={goBackSection}
                >
                  <ChevronLeftIcon />
                </IconButton>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label="Go forward"
                  disabled={!canGoForward}
                  onClick={goForwardSection}
                >
                  <ChevronRightIcon />
                </IconButton>
              </div>
            </div>

            <div className="sidebar-main">
              <nav className="quick-links" aria-label="Primary">
                <div className="sidebar-heading">
                  <Text size="1" weight="bold" color="gray">
                    Quick links
                  </Text>
                </div>
                {quickLinkItems.map((item) => (
                  <button
                    className={`sidebar-row ${isQuickLinkSelected(item) ? 'selected' : ''}`}
                    type="button"
                    key={item.id}
                    aria-label={`${item.label} section`}
                    aria-current={isQuickLinkSelected(item) ? 'page' : undefined}
                    onClick={() => selectQuickLink(item)}
                  >
                    <span className="sidebar-icon">{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </nav>

              {showRuntimeConfig ? (
                <section className="sidebar-runs" aria-label="Runs">
                  <div className="sidebar-heading">
                    <Text size="1" weight="bold" color="gray">
                      Runs
                    </Text>
                    <span className="sidebar-heading-actions">
                      <Badge
                        color={
                          runControlState === 'running'
                            ? 'green'
                            : runControlState === 'planning'
                              ? 'cyan'
                              : 'gray'
                        }
                        variant="soft"
                      >
                        {runControlLabel}
                      </Badge>
                      <IconButton
                        size="1"
                        variant="ghost"
                        color="gray"
                        aria-label="Create new run"
                        onClick={createLocalRun}
                      >
                        <PlusIcon />
                      </IconButton>
                    </span>
                  </div>
                  <div className="sidebar-run-list">
                    {sidebarRunItems.map((item) => {
                      const selected = item.id === activeSidebarRunId;
                      const persistedRunState = runStateById[item.id];
                      const rowState = selected ? runControlState : persistedRunState;
                      const statusLabel = runStatusLabel(rowState, item.status);
                      const tone = rowState ?? runToneFromStatus(item.status);
                      return (
                        <button
                          className={`sidebar-run-row ${selected ? 'selected' : ''}`}
                          type="button"
                          key={item.id}
                          aria-label={`Open ${item.label} run, ${statusLabel}`}
                          onClick={() => selectSidebarRun(item)}
                        >
                          <span className={`run-dot run-state-${tone}`} aria-hidden />
                          <span className="sidebar-run-copy">
                            <strong>{item.label}</strong>
                            <em>{item.meta}</em>
                          </span>
                          <span className="sidebar-run-meta">
                            <strong>{statusLabel}</strong>
                            <em>{item.time}</em>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ) : null}

              {showRuntimeConfig ? (
                <section className="sidebar-runtime-monitor" aria-label="Runtime monitor">
                  <div className="runtime-monitor-head">
                    <span>
                      <DashboardIcon />
                    </span>
                    <div>
                      <strong>{titlebarRuntimeTargetLabels[runtimeTarget]}</strong>
                      <em>{localRuntimeMode ? 'Local core' : config.mode}</em>
                    </div>
                    <Badge
                      color={runtimeHealthBadgeColors[runtimeHealthState]}
                      variant="soft"
                      aria-label={`Runtime health ${runtimeHealthLabel}`}
                    >
                      {runtimeHealthLabel}
                    </Badge>
                  </div>
                  <dl className="runtime-monitor-grid">
                    <div>
                      <dt>Live</dt>
                      <dd>{socket.connected ? 'connected' : runLiveMode ? 'waiting' : 'offline'}</dd>
                    </div>
                    <div>
                      <dt>Scope</dt>
                      <dd>{hasWorkspaceScope ? 'workspace' : hasProjectScope ? 'project' : 'setup'}</dd>
                    </div>
                    <div>
                      <dt>Events</dt>
                      <dd>{workspaceEventInputs.length}</dd>
                    </div>
                    <div>
                      <dt>Queue</dt>
                      <dd>{agentTaskSignals.length}</dd>
                    </div>
                  </dl>
                  <dl className="runtime-monitor-grid" aria-label="Runtime health metrics">
                    {runtimeMonitorHealthMetrics.map((metric) => (
                      <div key={metric.label}>
                        <dt>{metric.label}</dt>
                        <dd>{metric.value}</dd>
                      </div>
                    ))}
                  </dl>
                  <button
                    className="runtime-monitor-action"
                    type="button"
                    aria-label={`Open Runtime Monitor, last sync ${lastSync}`}
                    onClick={() => switchSection('settings')}
                  >
                    <span>Open Runtime Monitor</span>
                    <ChevronRightIcon />
                  </button>
                </section>
              ) : null}

              <section className="sidebar-sessions">
                <div className="sidebar-heading">
                  <Text size="1" weight="bold" color="gray">
                    Sessions
                  </Text>
                  <span className="sidebar-heading-actions">
                    <span className="session-grouping-control">
                      <IconButton
                        size="1"
                        variant="ghost"
                        color={sessionMenuOpen ? 'cyan' : 'gray'}
                        aria-label={`Session grouping, ${sessionGroupLabel}`}
                        aria-haspopup="menu"
                        aria-expanded={sessionMenuOpen}
                        onClick={() => {
                          const nextOpen = !sessionMenuOpen;
                          if (nextOpen) {
                            closeCommandPalette();
                            setRunActionsMenuOpen(false);
                            setMobileSectionMenuOpen(false);
                            setActiveMobileMenuItemId(null);
                          }
                          setSessionMenuOpen(nextOpen);
                        }}
                      >
                        <MixerHorizontalIcon />
                      </IconButton>
                      {sessionMenuOpen ? (
                        <div className="session-group-menu" role="menu" aria-label="Session grouping">
                          <button
                            type="button"
                            role="menuitemradio"
                            aria-checked={sessionGroupMode === 'project'}
                            className={sessionGroupMode === 'project' ? 'selected' : ''}
                            onClick={() => changeSessionGroupMode('project')}
                          >
                            <CheckCircledIcon />
                            <span>
                              <strong>Project folders</strong>
                              <em>Group chats under workspace roots.</em>
                            </span>
                          </button>
                          <button
                            type="button"
                            role="menuitemradio"
                            aria-checked={sessionGroupMode === 'recent'}
                            className={sessionGroupMode === 'recent' ? 'selected' : ''}
                            onClick={() => changeSessionGroupMode('recent')}
                          >
                            <CheckCircledIcon />
                            <span>
                              <strong>Recent first</strong>
                              <em>Show the active session first.</em>
                            </span>
                          </button>
                        </div>
                      ) : null}
                    </span>
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="gray"
                      aria-label={
                        showRuntimeConfig && !workspaceDisabledReason
                          ? 'Create workspace session'
                          : 'New session'
                      }
                      disabled={creatingWorkspace}
                      onClick={startNewSession}
                    >
                      <PlusIcon />
                    </IconButton>
                  </span>
                </div>
                {showRuntimeConfig ? (
                  <WorkspaceDock
                    projects={sidebarProjects}
                    workspacesByProject={dataset.workspacesByProject}
                    conversationsByWorkspace={dataset.conversationsByWorkspace}
                    nodeState={dataset.nodeState}
                    currentProjectId={config.projectId}
                    currentWorkspaceId={config.workspaceId}
                    currentConversationId={selectedConversation?.id ?? null}
                    groupMode={sessionGroupMode}
                    expandedProjectIds={expandedProjectIds}
                    expandedWorkspaceIds={expandedWorkspaceIds}
                    onToggleProject={toggleProject}
                    onToggleWorkspace={toggleWorkspace}
                    onSelectProject={selectProject}
                    onSelectWorkspace={(projectId, workspaceId) =>
                      selectWorkspace(workspaceId, projectId)
                    }
                    onSelectConversation={selectConversation}
                    onRefresh={() => void refreshRuntime()}
                    actionDisabledReason={workspaceDisabledReason}
                    creatingWorkspace={creatingWorkspace}
                    creatingSessionWorkspaceId={creatingSessionWorkspaceId}
                    onCreateWorkspace={(projectId) => void createWorkspace(projectId)}
                    onCreateSession={(projectId, workspaceId) =>
                      void createSessionForWorkspace(projectId, workspaceId)
                    }
                  />
                ) : (
                  <SignedOutSessionTree
                    mode={sessionGroupMode}
                    activeSection={activeSection}
                    onNewSession={startNewSession}
                    onOpenChats={() => switchSection('chat')}
                    onOpenProjectConnection={openConnectionSettings}
                  />
                )}
              </section>
            </div>

            <section className="left-dock">
              <AuthPanel
                auth={auth}
                config={config}
                email={loginEmail}
                password={loginPassword}
                onApiBaseUrlChange={(apiBaseUrl) => handleConfigChange({ ...config, apiBaseUrl })}
                onEmailChange={setLoginEmail}
                onPasswordChange={setLoginPassword}
                onLogin={() => void login()}
                onUseApiKeyManually={useApiKeyManually}
                onLogout={logout}
                onOpenSettings={openConnectionSettings}
                loginOpen={loginModalOpen}
                onLoginOpenChange={setLoginModalOpen}
                getLoginRestoreTarget={getLoginRestoreTarget}
              />
            </section>
          </aside>

          <main className="workbench">
            {error ? (
              <div className="workbench-error" role="alert" aria-live="polite">
                {error}
              </div>
            ) : null}
            <section
              className={`workbench-layout ${showReviewPanel ? '' : 'review-panel-collapsed'}`}
            >
              <section className={paneStageClassName}>{renderWorkbench()}</section>
              {showReviewPanel ? renderWorkspaceReviewPanel() : null}
            </section>
          </main>
        </section>

        {commandPaletteOpen
          ? createPortal(
              <CommandPalette
                inputRef={commandInputRef}
                query={commandQuery}
                items={filteredCommandItems}
                onQueryChange={setCommandQuery}
                onClose={closeCommandPalette}
              />,
              document.body,
            )
          : null}
      </div>
    </Theme>
  );
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function formatConnectionError(error: unknown, apiBaseUrl: string): string {
  const message = formatError(error);
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return `Cannot reach ${apiBaseUrl}. Start the agi-stack server or update the Server URL.`;
  }
  return message;
}

function formatLoginError(error: unknown, apiBaseUrl: string): string {
  return formatConnectionError(error, apiBaseUrl);
}

function SignedOutSessionTree({
  mode,
  activeSection,
  onNewSession,
  onOpenChats,
  onOpenProjectConnection,
}: {
  mode: SessionGroupMode;
  activeSection: WorkbenchSection;
  onNewSession: () => void;
  onOpenChats: () => void;
  onOpenProjectConnection: () => void;
}) {
  const chatsSelected = activeSection === 'chat';
  const projectSelected = activeSection === 'settings';
  const newSessionSelected = !chatsSelected && !projectSelected;
  const newSessionRow = (
    <button
      className={`sidebar-row ${newSessionSelected ? 'selected' : ''} ${
        mode === 'project' ? 'session-child-row' : ''
      }`}
      type="button"
      aria-label="Current new session"
      aria-current={newSessionSelected ? 'page' : undefined}
      onClick={onNewSession}
    >
      <span className="sidebar-icon">
        <CommitIcon />
      </span>
      <span>New session</span>
    </button>
  );
  const chatsRow = (
    <button
      className={`sidebar-row ${chatsSelected ? 'selected' : ''}`}
      type="button"
      aria-label="Chats collection"
      aria-current={chatsSelected ? 'page' : undefined}
      onClick={onOpenChats}
    >
      <span className="sidebar-icon">
        <ChatBubbleIcon />
      </span>
      <span>Chats</span>
    </button>
  );
  const projectRow = (
    <button
      className={`sidebar-row ${projectSelected ? 'selected' : ''}`}
      type="button"
      aria-label="Project connection"
      aria-current={projectSelected ? 'page' : undefined}
      onClick={onOpenProjectConnection}
    >
      <span className="sidebar-icon">
        <ArchiveIcon />
      </span>
      <span>Connect project</span>
    </button>
  );

  return (
    <div className={`signed-out-session-tree ${mode === 'recent' ? 'recent-first' : ''}`}>
      {mode === 'recent' ? (
        <>
          {newSessionRow}
          {chatsRow}
          {projectRow}
        </>
      ) : (
        <>
          {chatsRow}
          {projectRow}
          {newSessionRow}
        </>
      )}
    </div>
  );
}

function workspaceLabel(workspace: { id: string; name?: string; title?: string } | undefined): string {
  return workspace?.name ?? workspace?.title ?? workspace?.id ?? 'No workspace';
}

function projectSummaryFromConfig(config: DesktopRuntimeConfig): ProjectSummary | null {
  const projectId = config.projectId.trim();
  if (!projectId) return null;
  return {
    id: projectId,
    tenant_id: config.tenantId.trim(),
    name: projectId,
  };
}

function resolveSidebarProjects(
  config: DesktopRuntimeConfig,
  authStatus: AuthState['status'],
  projects: ProjectSummary[],
): ProjectSummary[] {
  if (authStatus === 'signed_in' && projects.length) return projects;
  const configured = projectSummaryFromConfig(config);
  return configured ? [configured] : [];
}

function SignedOutPanel({
  activeTarget,
  onWorkflowSelect,
  onSignIn,
  onUseManualKey,
  onOpenCommands,
  onCloseCommands,
}: {
  activeTarget: WorkflowTarget;
  onWorkflowSelect: (target: WorkflowTarget) => void;
  onSignIn: () => void;
  onUseManualKey: () => void;
  onOpenCommands: () => void;
  onCloseCommands: () => void;
}) {
  const context = signedOutWorkflowContext(activeTarget);
  const [warningVisible, setWarningVisible] = useState(true);
  const [scopeMenu, setScopeMenu] = useState<SessionScopeKind | null>(null);
  const [activeScopeOption, setActiveScopeOption] = useState<string | null>(null);
  const [composerDraft, setComposerDraft] = useState('');
  const [referenceMenu, setReferenceMenu] = useState<ComposerReferenceKind | null>(null);
  const [activeReferenceId, setActiveReferenceId] = useState<string | null>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const composerDraftRef = useRef<HTMLTextAreaElement>(null);
  const referenceOptions = useMemo(
    () => (referenceMenu ? composerReferenceOptions[referenceMenu] : []),
    [referenceMenu],
  );
  const activeReference =
    referenceOptions.find((option) => option.id === activeReferenceId) ?? referenceOptions[0];
  const activeReferenceOptionId = activeReference
    ? `composer-reference-option-${activeReference.id}`
    : undefined;
  const [sessionScope, setSessionScope] = useState<Record<SessionScopeKind, string>>({
    project: 'No project',
    worktree: 'New worktree',
    branch: 'Default branch',
  });
  const activeScopeOptionId =
    scopeMenu && activeScopeOption ? sessionScopeOptionId(scopeMenu, activeScopeOption) : undefined;

  const selectScopeValue = useCallback((kind: SessionScopeKind, value: string) => {
    setSessionScope((current) => ({ ...current, [kind]: value }));
    setScopeMenu(null);
    setActiveScopeOption(null);
  }, []);

  const openCommands = () => {
    setScopeMenu(null);
    setActiveScopeOption(null);
    setReferenceMenu(null);
    onOpenCommands();
  };

  const openReferenceMenu = (kind: ComposerReferenceKind) => {
    onCloseCommands();
    setScopeMenu(null);
    setActiveScopeOption(null);
    setReferenceMenu(kind);
  };

  useEffect(() => {
    if (!scopeMenu) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const options = sessionScopeOptions[scopeMenu];
      if (event.key === 'Escape') {
        event.preventDefault();
        setScopeMenu(null);
        setActiveScopeOption(null);
        return;
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        setActiveScopeOption((current) => {
          const currentOption = current ?? sessionScope[scopeMenu];
          const currentIndex = options.findIndex((option) => option === currentOption);
          const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
          const nextIndex = (startIndex + delta + options.length) % options.length;
          return options[nextIndex];
        });
        return;
      }
      if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        setActiveScopeOption(event.key === 'Home' ? options[0] : options[options.length - 1]);
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectScopeValue(scopeMenu, activeScopeOption ?? sessionScope[scopeMenu]);
      }
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest('.session-scope-control')) return;
      setScopeMenu(null);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [activeScopeOption, scopeMenu, selectScopeValue, sessionScope]);

  useEffect(() => {
    if (!scopeMenu) {
      setActiveScopeOption(null);
      return;
    }
    setActiveScopeOption(sessionScope[scopeMenu]);
  }, [scopeMenu, sessionScope]);

  useEffect(() => {
    setActiveReferenceId(referenceOptions[0]?.id ?? null);
  }, [referenceOptions]);

  useEffect(() => {
    if (!activeReferenceOptionId) return;
    document.getElementById(activeReferenceOptionId)?.scrollIntoView({ block: 'nearest' });
  }, [activeReferenceOptionId]);

  useEffect(() => {
    if (!referenceMenu) return;

    const closeIfOutsideComposer = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (composerRef.current?.contains(target)) return;
      setReferenceMenu(null);
    };

    document.addEventListener('pointerdown', closeIfOutsideComposer, true);
    document.addEventListener('focusin', closeIfOutsideComposer);
    return () => {
      document.removeEventListener('pointerdown', closeIfOutsideComposer, true);
      document.removeEventListener('focusin', closeIfOutsideComposer);
    };
  }, [referenceMenu]);

  useEffect(() => {
    if (!activeScopeOptionId) return;
    document.getElementById(activeScopeOptionId)?.scrollIntoView({ block: 'nearest' });
  }, [activeScopeOptionId]);

  const updateComposerDraft = (value: string, caret: number) => {
    if (value === '/' && caret === 1) {
      setComposerDraft('');
      openCommands();
      requestAnimationFrame(() => composerDraftRef.current?.focus());
      return;
    }

    setComposerDraft(value);
    const token = value.slice(0, caret).split(/\s/).pop() ?? '';
    if (token.startsWith('@')) {
      openReferenceMenu('files');
      return;
    }
    if (token.startsWith('#')) {
      openReferenceMenu('issues');
      return;
    }
    setReferenceMenu(null);
  };

  const moveActiveReference = (delta: number) => {
    setActiveReferenceId((current) => {
      if (referenceOptions.length === 0) return null;
      const currentIndex = referenceOptions.findIndex((option) => option.id === current);
      const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
      const nextIndex = (startIndex + delta + referenceOptions.length) % referenceOptions.length;
      return referenceOptions[nextIndex].id;
    });
  };

  const insertComposerReference = (label: string) => {
    const input = composerDraftRef.current;
    const selectionStart = input?.selectionStart ?? composerDraft.length;
    const selectionEnd = input?.selectionEnd ?? selectionStart;
    const beforeSelection = composerDraft.slice(0, selectionStart);
    const afterSelection = composerDraft.slice(selectionEnd);
    const tokenMatch = beforeSelection.match(/(^|\s)([@#][^\s]*)$/);
    const tokenStart = tokenMatch ? beforeSelection.length - tokenMatch[2].length : selectionStart;
    const insertLabel = referenceMenu === 'files' ? `@${label}` : label;
    const nextDraft = `${composerDraft.slice(0, tokenStart)}${insertLabel} ${
      afterSelection.startsWith(' ') ? afterSelection.slice(1) : afterSelection
    }`;
    const nextCursor = tokenStart + insertLabel.length + 1;
    setComposerDraft(nextDraft);
    setReferenceMenu(null);
    requestAnimationFrame(() => {
      composerDraftRef.current?.focus();
      composerDraftRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const renderScopeControl = (
    kind: SessionScopeKind,
    label: string,
    icon: ReactNode,
  ) => {
    const options = sessionScopeOptions[kind];
    const isOpen = scopeMenu === kind;
    const menuId = `session-scope-menu-${kind}`;

    return (
      <span className="session-scope-control" data-scope-kind={kind}>
        <button
          type="button"
          aria-label={`Choose ${label}`}
          aria-haspopup="menu"
          aria-controls={isOpen ? menuId : undefined}
          aria-expanded={isOpen}
          onClick={() => {
            const nextMenu = isOpen ? null : kind;
            if (nextMenu) {
              onCloseCommands();
              setReferenceMenu(null);
            }
            setScopeMenu(nextMenu);
            setActiveScopeOption(nextMenu ? sessionScope[kind] : null);
          }}
        >
          {icon}
          <span className="session-scope-label">{sessionScope[kind]}</span>
          <ChevronDownIcon className="footer-chevron" aria-hidden />
        </button>
        {isOpen ? (
          <div
            className="session-scope-menu"
            id={menuId}
            role="menu"
            aria-label={`${label} options`}
            aria-activedescendant={activeScopeOptionId}
          >
            {options.map((option) => {
              const isSelected = sessionScope[kind] === option;
              const isActive = activeScopeOption === option;
              return (
                <button
                  id={sessionScopeOptionId(kind, option)}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isSelected}
                  className={[isSelected ? 'selected' : '', isActive ? 'active' : '']
                    .filter(Boolean)
                    .join(' ')}
                  key={option}
                  onFocus={() => setActiveScopeOption(option)}
                  onMouseEnter={() => setActiveScopeOption(option)}
                  onClick={() => selectScopeValue(kind, option)}
                >
                  <span>{option}</span>
                  {isSelected ? <CheckCircledIcon /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </span>
    );
  };

  return (
    <section className="pane-shell welcome-shell">
      <div className="signed-out-canvas" aria-hidden="true">
        <div className="signed-out-mark">
          <span />
          <span />
          <span />
        </div>
      </div>
      <section className="welcome-timeline" aria-label="Conversation transcript">
        <div className="session-empty-hint">
          <span>Open any file in the repo with</span>
          <kbd aria-label="Command P">⌘ P</kbd>
          <span>.</span>
        </div>
      </section>
      <div
        className={`signed-out-dock ${warningVisible ? '' : 'warning-hidden'}`}
        aria-label="New session composer"
      >
        <WorkflowStrip activeTarget={activeTarget} onSelect={onWorkflowSelect} />
        {warningVisible ? (
          <div className="usage-warning">
            <div className="usage-warning-copy">
              <ExclamationTriangleIcon />
              <Text size="2">
                Sign in to connect workspace, sandbox, and terminal.
              </Text>
            </div>
            <div className="usage-warning-actions">
              <Button
                size="2"
                color="gray"
                variant="surface"
                aria-label="Sign in from connection warning"
                onClick={onSignIn}
              >
                Sign in
              </Button>
              <Button
                size="2"
                color="gray"
                variant="ghost"
                aria-label="Use API key from connection warning"
                onClick={onUseManualKey}
              >
                API key
              </Button>
              <IconButton
                size="1"
                color="gray"
                variant="ghost"
                className="usage-warning-dismiss"
                aria-label="Dismiss connection warning"
                onClick={() => setWarningVisible(false)}
              >
                <Cross2Icon />
              </IconButton>
            </div>
          </div>
        ) : null}
        <div className="composer signed-out-composer" ref={composerRef}>
          <textarea
            ref={composerDraftRef}
            className="composer-draft-input"
            value={composerDraft}
            rows={2}
            aria-label="New session prompt"
            aria-controls={referenceMenu ? 'composer-reference-menu' : undefined}
            aria-expanded={Boolean(referenceMenu)}
            aria-haspopup="listbox"
            aria-activedescendant={referenceMenu ? activeReferenceOptionId : undefined}
            placeholder="Ask anything. Type / for commands, @ to add files, or # to reference issues..."
            onChange={(event) =>
              updateComposerDraft(event.currentTarget.value, event.currentTarget.selectionStart)
            }
            onKeyDown={(event) => {
              const draftIsEmpty = event.currentTarget.value.trim() === '';
              if (event.key === '/' && draftIsEmpty) {
                event.preventDefault();
                setComposerDraft('');
                openCommands();
                return;
              }
              if (referenceMenu && event.key === 'ArrowDown') {
                event.preventDefault();
                moveActiveReference(1);
                return;
              }
              if (referenceMenu && event.key === 'ArrowUp') {
                event.preventDefault();
                moveActiveReference(-1);
                return;
              }
              if (referenceMenu && (event.key === 'Enter' || event.key === 'Tab')) {
                event.preventDefault();
                if (activeReference) {
                  insertComposerReference(activeReference.label);
                }
                return;
              }
              if (event.key === 'Escape' && referenceMenu) {
                event.preventDefault();
                setReferenceMenu(null);
              }
            }}
          />
          {referenceMenu ? (
            <div
              className="composer-reference-menu"
              id="composer-reference-menu"
              role="listbox"
              aria-label={referenceMenu === 'files' ? 'Files to add' : 'Issues to reference'}
            >
              <strong>{referenceMenu === 'files' ? 'Files' : 'Issues'}</strong>
              {referenceOptions.map((option) => (
                <button
                  id={`composer-reference-option-${option.id}`}
                  key={option.id}
                  type="button"
                  role="option"
                  aria-selected={option.id === activeReference?.id}
                  className={option.id === activeReference?.id ? 'selected' : ''}
                  onMouseEnter={() => setActiveReferenceId(option.id)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => insertComposerReference(option.label)}
                >
                  <span className="reference-icon">{option.icon}</span>
                  <span className="reference-copy">
                    <span>{option.label}</span>
                    <em>{option.description}</em>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <Flex align="center" justify="between" className="composer-toolbar">
            <ComposerControls
              disabledHint={context.body}
              effortLabel="Max"
              modeLabel="Interactive"
              modelLabel="Claude Fable 5 · 1M"
            />
            <Flex align="center" gap="2" className="composer-right-actions">
              <button
                className="composer-ring-button"
                type="button"
                aria-label="Open command palette"
                title="Open command palette"
                onClick={openCommands}
              >
                <ActivityLogIcon />
              </button>
              <Button
                size="2"
                color="green"
                className="send-pill"
                aria-label="Send message, sign in required"
                disabled
              >
                <ArrowUpIcon />
              </Button>
            </Flex>
          </Flex>
        </div>
        <div
          className={`signed-out-session-footer ${
            warningVisible ? '' : 'auth-fallback-visible'
          }`}
          aria-label={warningVisible ? 'Session scope' : 'Connection actions'}
        >
          {warningVisible ? (
            <>
              {renderScopeControl('project', 'project', <ArchiveIcon />)}
              {renderScopeControl('worktree', 'worktree', <EnterFullScreenIcon />)}
              {renderScopeControl('branch', 'branch', <CommitIcon />)}
            </>
          ) : (
            <>
              <button type="button" aria-label="Sign in from connection footer" onClick={onSignIn}>
                <ChatBubbleIcon /> Sign in
              </button>
              <button
                type="button"
                aria-label="Use API key from connection footer"
                onClick={onUseManualKey}
              >
                <GearIcon /> API key
              </button>
              <button
                type="button"
                aria-label="Open command palette for project setup"
                onClick={openCommands}
              >
                <ArchiveIcon /> No project
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function WorkflowStrip({
  activeTarget,
  onSelect,
}: {
  activeTarget: WorkflowTarget;
  onSelect: (target: WorkflowTarget) => void;
}) {
  const items: Array<[WorkflowTarget, string, string, ReactNode]> = [
    ['changes', 'Changes', '+0 -0', <CodeIcon key="changes" />],
    ['pull', 'PR', 'idle', <ReaderIcon key="pull" />],
    ['plan', 'Plan', 'idle', <ActivityLogIcon key="plan" />],
    ['background', 'Tool events', '0', <DotsHorizontalIcon key="background" />],
    ['artifacts', 'Artifacts', '0', <ArchiveIcon key="artifacts" />],
  ];

  return (
    <div className="composer-workflows signed-out-workflows" aria-label="session workflow shortcuts">
      {items.map(([target, label, value, icon]) => (
        <button
          className={activeTarget === target ? 'selected' : ''}
          type="button"
          aria-label={`${label} ${value}`}
          key={target}
          onClick={() => onSelect(target)}
        >
          <span>{icon}</span>
          <strong>{label}</strong>
          <em>{value}</em>
        </button>
      ))}
    </div>
  );
}

function WorkspaceReviewPanel({
  activeTab,
  dataset,
  connection,
  socketConnected,
  socketEvents,
  localEventCount,
  artifacts,
  selectedTask,
  terminalConnected,
  terminalLines,
  onTabChange,
  onClose,
  onClearLocalEvents,
  stage = false,
}: {
  activeTab: ReviewTab;
  dataset: RuntimeDataset;
  connection: ConnectionState;
  socketConnected: boolean;
  socketEvents: unknown[];
  localEventCount: number;
  artifacts: WorkspaceArtifact[];
  selectedTask: WorkspaceTask | null;
  terminalConnected: boolean;
  terminalLines: string[];
  onTabChange: (tab: ReviewTab) => void;
  onClose: () => void;
  onClearLocalEvents: () => void;
  stage?: boolean;
}) {
  const [showMoreTabs, setShowMoreTabs] = useState(false);
  const [showAddTabs, setShowAddTabs] = useState(false);
  const [panelMode, setPanelMode] = useState<'normal' | 'maximized' | 'fullscreen'>('normal');
  const [eventFilter, setEventFilter] = useState<WorkspaceEventKind | 'All'>('All');
  const [eventQuery, setEventQuery] = useState('');
  const [eventAutoScroll, setEventAutoScroll] = useState(true);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [artifactFilter, setArtifactFilter] = useState<WorkspaceArtifactKind | 'All'>('All');
  const [artifactQuery, setArtifactQuery] = useState('');
  const [artifactSort, setArtifactSort] = useState<WorkspaceArtifactSort>('recent');
  const [artifactView, setArtifactView] = useState<WorkspaceArtifactView>('list');
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [decisionStatus, setDecisionStatus] = useState<ReviewDecisionStatus>('pending');
  const [decisionRunScopeOnly, setDecisionRunScopeOnly] = useState(true);
  const [decisionRecords, setDecisionRecords] = useState<ReviewDecisionRecord[]>([]);
  const reviewContentRef = useRef<HTMLDivElement>(null);
  const moreTabsButtonRef = useRef<HTMLButtonElement>(null);
  const moreTabsMenuRef = useRef<HTMLDivElement>(null);
  const addTabButtonRef = useRef<HTMLButtonElement>(null);
  const addTabMenuRef = useRef<HTMLDivElement>(null);
  const planRows = dataset.plan ? buildPlanDisplayRows(dataset.plan) : [];
  const workspaceEvents = useMemo(() => buildWorkspaceEvents(socketEvents), [socketEvents]);
  const normalizedEventQuery = eventQuery.trim().toLowerCase();
  const visibleEvents = useMemo(
    () =>
      workspaceEvents.filter((event) => {
        const matchesKind = eventFilter === 'All' || event.kind === eventFilter;
        const matchesQuery =
          !normalizedEventQuery || event.searchableText.includes(normalizedEventQuery);
        return matchesKind && matchesQuery;
      }),
    [eventFilter, normalizedEventQuery, workspaceEvents],
  );
  const selectedEvent = visibleEvents.find((event) => event.id === selectedEventId) ?? null;
  const eventKindCounts = useMemo(() => {
    const counts: Record<WorkspaceEventKind | 'All', number> = {
      All: workspaceEvents.length,
      Tools: 0,
      Reasoning: 0,
      Messages: 0,
      System: 0,
      Errors: 0,
    };
    workspaceEvents.forEach((event) => {
      counts[event.kind] += 1;
    });
    return counts;
  }, [workspaceEvents]);
  const eventFilterItems = useMemo<Array<WorkspaceEventKind | 'All'>>(
    () =>
      workspaceEventFilterItems.filter(
        (item) => item !== 'Errors' || eventKindCounts.Errors > 0,
      ),
    [eventKindCounts.Errors],
  );
  const eventSummaryItems = useMemo(
    () =>
      eventFilterItems
        .filter((item): item is WorkspaceEventKind => item !== 'All')
        .map((kind) => ({ kind, count: eventKindCounts[kind] }))
        .filter(({ count }) => count > 0),
    [eventFilterItems, eventKindCounts],
  );
  const normalizedArtifactQuery = artifactQuery.trim().toLowerCase();
  const visibleArtifacts = useMemo(
    () => {
      const filtered = artifacts.filter((artifact) => {
        const matchesKind = artifactFilter === 'All' || artifact.kind === artifactFilter;
        const matchesQuery =
          !normalizedArtifactQuery || artifact.searchableText.includes(normalizedArtifactQuery);
        return matchesKind && matchesQuery;
      });
      return sortWorkspaceArtifacts(filtered, artifactSort);
    },
    [artifactFilter, artifactSort, artifacts, normalizedArtifactQuery],
  );
  const reviewDecision = useMemo(
    () => buildReviewDecisionSummary(dataset, workspaceEvents, artifacts, selectedTask),
    [artifacts, dataset, selectedTask, workspaceEvents],
  );
  const pullRequestSummary = useMemo(
    () => buildPullRequestSummary(dataset, workspaceEvents, artifacts, reviewDecision),
    [artifacts, dataset, reviewDecision, workspaceEvents],
  );
  const visibleArtifactTotalSize = useMemo(
    () => formatArtifactTotalSize(visibleArtifacts),
    [visibleArtifacts],
  );
  const selectedArtifact =
    visibleArtifacts.find((artifact) => artifact.id === selectedArtifactId) ?? null;
  const hasEventScan = eventFilter !== 'All' || eventQuery.trim().length > 0;
  const canClearEvents = hasEventScan || localEventCount > 0;
  const artifactFilterItems = useMemo<Array<WorkspaceArtifactKind | 'All'>>(() => {
    const availableKinds = new Set(artifacts.map((artifact) => artifact.kind));
    return [
      'All',
      'Files',
      'Patches',
      'Reports',
      'Logs',
      ...(availableKinds.has('Events') ? (['Events'] as const) : []),
    ];
  }, [artifacts]);
  const reviewTabs: Array<{
    tab: ReviewTab;
    label: string;
    value?: string;
  }> = [
    { tab: 'changes', label: 'Changes', value: reviewDecision.changeValue },
    { tab: 'pull', label: 'Pull request', value: 'idle' },
    { tab: 'plan', label: 'Plan', value: dataset.plan ? 'active' : 'idle' },
    { tab: 'terminal', label: 'Terminal', value: terminalConnected ? 'live' : 'idle' },
  ];
  const overflowReviewTabs: Array<{
    tab: ReviewTab;
    label: string;
    value: string;
  }> = [
    {
      tab: 'background',
      label: 'Tool events',
      value: workspaceEvents.length ? `${workspaceEvents.length} events` : 'idle',
    },
    {
      tab: 'artifacts',
      label: 'Artifacts',
      value: artifacts.length ? `${artifacts.length} items` : socketConnected ? 'subscribed' : 'idle',
    },
  ];
  const moreTabs: Array<{
    tab: ReviewTab;
    label: string;
    value: string;
  }> = overflowReviewTabs;
  const addableTabs: Array<{
    tab: ReviewTab;
    label: string;
    value: string;
  }> = [...reviewTabs, ...overflowReviewTabs].map(({ tab, label, value }) => ({
    tab,
    label,
    value: value ?? 'tab',
  }));
  const panelClassName = [
    'review-panel',
    stage ? 'review-panel-stage' : '',
    panelMode === 'fullscreen' ? 'full-screen' : '',
    panelMode === 'maximized' ? 'maximized' : '',
  ]
    .filter(Boolean)
    .join(' ');
  const pinnedReviewTabs = reviewTabs.slice(0, 4);
  const activeReviewTab = [...reviewTabs, ...overflowReviewTabs].find(
    ({ tab }) => tab === activeTab,
  );
  const visibleReviewTabs =
    activeReviewTab && !pinnedReviewTabs.some(({ tab }) => tab === activeReviewTab.tab)
      ? [...reviewTabs.slice(0, 3), activeReviewTab]
      : pinnedReviewTabs;

  const selectTab = (tab: ReviewTab) => {
    onTabChange(tab);
    setShowMoreTabs(false);
    setShowAddTabs(false);
  };
  const clearEventScan = () => {
    setEventFilter('All');
    setEventQuery('');
    onClearLocalEvents();
  };
  const snoozeReviewDecision = () => {
    const scope = decisionRunScopeOnly ? 'this run' : 'the workspace packet';
    const record: ReviewDecisionRecord = {
      id: `snoozed-${Date.now()}`,
      status: 'snoozed',
      label: 'Snoozed',
      detail: `Workspace review reminder snoozed locally for ${scope}.`,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };
    setDecisionStatus('pending');
    setDecisionRecords((current) => [record, ...current].slice(0, 4));
  };

  useEffect(() => {
    if (activeTab !== 'background' || !eventAutoScroll) return;
    reviewContentRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [activeTab, eventAutoScroll, visibleEvents.length, workspaceEvents.length]);

  useEffect(() => {
    if (eventFilterItems.includes(eventFilter)) return;
    setEventFilter('All');
  }, [eventFilter, eventFilterItems]);

  useEffect(() => {
    if (!visibleEvents.length) {
      if (selectedEventId) setSelectedEventId(null);
      return;
    }
    if (!selectedEventId || !visibleEvents.some((event) => event.id === selectedEventId)) {
      setSelectedEventId(visibleEvents[0].id);
    }
  }, [selectedEventId, visibleEvents]);

  useEffect(() => {
    if (!visibleArtifacts.length) {
      if (selectedArtifactId) setSelectedArtifactId(null);
      return;
    }
    if (!selectedArtifactId || !visibleArtifacts.some((artifact) => artifact.id === selectedArtifactId)) {
      setSelectedArtifactId(visibleArtifacts[0].id);
    }
  }, [selectedArtifactId, visibleArtifacts]);

  useEffect(() => {
    if (!showMoreTabs) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setShowMoreTabs(false);
      moreTabsButtonRef.current?.focus();
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (moreTabsMenuRef.current?.contains(target)) return;
      if (moreTabsButtonRef.current?.contains(target)) return;
      setShowMoreTabs(false);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [showMoreTabs]);

  useEffect(() => {
    if (!showAddTabs) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setShowAddTabs(false);
      addTabButtonRef.current?.focus();
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (addTabMenuRef.current?.contains(target)) return;
      if (addTabButtonRef.current?.contains(target)) return;
      setShowAddTabs(false);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [showAddTabs]);

  return (
    <aside className={panelClassName} aria-label="Workspace review panel">
      <header className="review-head">
        <div>
          <Heading as="h2" size="3">
            Workspace
          </Heading>
          <Text size="1" color="gray">
            Review changes, pull requests, plans, background agents, artifacts, and terminal output.
          </Text>
        </div>
        <div className="review-head-actions">
          <Badge color={connection === 'ready' ? 'green' : 'gray'} variant="soft">
            {connection}
          </Badge>
          <Tooltip content="Close workspace panel">
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              aria-label="Close drawer"
              onClick={onClose}
            >
              <Cross2Icon />
            </IconButton>
          </Tooltip>
        </div>
      </header>

      <div className="review-tabs" aria-label="Workspace tabs">
        <nav className="review-tab-scroll">
          {visibleReviewTabs.map(({ tab, label, value }) => (
            <button
              className={`review-tab ${activeTab === tab ? 'selected' : ''}`}
              type="button"
              aria-label={`Open ${label} tab${value ? `, ${value}` : ''}`}
              key={tab}
              onClick={() => selectTab(tab)}
            >
              <span>{label}</span>
              {value ? <em>{value}</em> : null}
            </button>
          ))}
        </nav>
        <div className="review-tab-actions" aria-label="Workspace tab actions">
          <Tooltip content="More tabs">
            <IconButton
              ref={moreTabsButtonRef}
              size="1"
              variant="ghost"
              color="gray"
              aria-label="More tabs"
              aria-controls={showMoreTabs ? 'workspace-more-tabs-menu' : undefined}
              aria-expanded={showMoreTabs}
              aria-haspopup="menu"
              onClick={() => {
                setShowAddTabs(false);
                setShowMoreTabs((open) => !open);
              }}
            >
              <DotsHorizontalIcon />
            </IconButton>
          </Tooltip>
          <Tooltip content="Add tab">
            <IconButton
              ref={addTabButtonRef}
              size="1"
              variant="ghost"
              color="gray"
              aria-label="Add workspace tab"
              aria-controls={showAddTabs ? 'workspace-add-tabs-menu' : undefined}
              aria-expanded={showAddTabs}
              aria-haspopup="menu"
              onClick={() => {
                setShowMoreTabs(false);
                setShowAddTabs((open) => !open);
              }}
            >
              <PlusIcon />
            </IconButton>
          </Tooltip>
          <Tooltip content={panelMode === 'fullscreen' ? 'Exit full screen' : 'Enter full screen'}>
            <IconButton
              size="1"
              variant="ghost"
              color={panelMode === 'fullscreen' ? 'cyan' : 'gray'}
              aria-label={panelMode === 'fullscreen' ? 'Exit full screen' : 'Enter full screen'}
              aria-pressed={panelMode === 'fullscreen'}
              onClick={() =>
                setPanelMode((mode) => (mode === 'fullscreen' ? 'normal' : 'fullscreen'))
              }
            >
              {panelMode === 'fullscreen' ? <ExitFullScreenIcon /> : <EnterFullScreenIcon />}
            </IconButton>
          </Tooltip>
          <Tooltip content={panelMode === 'maximized' ? 'Restore panel' : 'Maximize panel'}>
            <IconButton
              size="1"
              variant="ghost"
              color={panelMode === 'maximized' ? 'cyan' : 'gray'}
              aria-label={panelMode === 'maximized' ? 'Restore panel' : 'Maximize panel'}
              aria-pressed={panelMode === 'maximized'}
              onClick={() =>
                setPanelMode((mode) => (mode === 'maximized' ? 'normal' : 'maximized'))
              }
            >
              <FrameIcon />
            </IconButton>
          </Tooltip>
        </div>
        {showMoreTabs ? (
          <div
            className="review-tab-menu"
            id="workspace-more-tabs-menu"
            ref={moreTabsMenuRef}
            role="menu"
            aria-label="More workspace tabs"
          >
            {moreTabs.map(({ tab, label, value }) => (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={activeTab === tab}
                aria-label={`Open ${label} workspace tab, ${value}`}
                key={tab}
                onClick={() => selectTab(tab)}
              >
                <span>{label}</span>
                <em>{value}</em>
              </button>
            ))}
          </div>
        ) : null}
        {showAddTabs ? (
          <div
            className="review-tab-menu review-add-tab-menu"
            id="workspace-add-tabs-menu"
            ref={addTabMenuRef}
            role="menu"
            aria-label="Add workspace tab"
          >
            {addableTabs.map(({ tab, label, value }) => (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={activeTab === tab}
                aria-label={`Add ${label} workspace tab, ${value}`}
                key={tab}
                onClick={() => selectTab(tab)}
              >
                <span>{label}</span>
                <em>{value}</em>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="review-content" ref={reviewContentRef}>
        {activeTab === 'changes' ? (
          <ReviewDecisionPanel
            summary={reviewDecision}
            status={decisionStatus}
            records={decisionRecords}
            runScopeOnly={decisionRunScopeOnly}
            onRunScopeChange={setDecisionRunScopeOnly}
            onSnooze={snoozeReviewDecision}
            onReset={() => setDecisionStatus('pending')}
            onOpenArtifacts={() => selectTab('artifacts')}
          />
        ) : null}

        {activeTab === 'pull' ? (
          <PullRequestReviewPanel
            summary={pullRequestSummary}
            onOpenChanges={() => selectTab('changes')}
            onOpenArtifacts={() => selectTab('artifacts')}
          />
        ) : null}

        {activeTab === 'plan' ? (
          <div className="review-plan">
            {dataset.plan ? (
              <>
                <div className="review-section-title">
                  <Text size="1" weight="bold" color="gray">
                    Active plan snapshot
                  </Text>
                  <Badge color="green" variant="soft">
                    loaded
                  </Badge>
                </div>
                <div
                  className="review-plan-tree"
                  aria-label={`Plan showing ${planRows.length} snapshot fields`}
                >
                  <div className="plan-node complete">
                    <CheckCircledIcon />
                    <span>Workspace plan snapshot</span>
                  </div>
                  <div className="plan-branch">
                    {planRows.map((row) => (
                      <div className="plan-node with-detail" key={row.key}>
                        <CheckCircledIcon />
                        <span>{row.label}</span>
                        <small>{row.detail}</small>
                      </div>
                    ))}
                  </div>
                </div>
                <details className="plan-json-details">
                  <summary>Raw snapshot</summary>
                  <pre className="review-json">{JSON.stringify(dataset.plan, null, 2)}</pre>
                </details>
              </>
            ) : (
              <div className="review-plan-tree">
                <div className="plan-node complete">
                  <CheckCircledIcon />
                  <span>Start desktop shell</span>
                </div>
                <div className="plan-branch">
                  <div className="plan-node">
                    <CheckCircledIcon />
                    <span>Sign in or configure API key</span>
                  </div>
                  <div className="plan-node">
                    <CheckCircledIcon />
                    <span>Select account, project, and workspace</span>
                  </div>
                  <div className="plan-node">
                    <CheckCircledIcon />
                    <span>Load work items, plan, sandbox, and terminal state</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : null}

        {activeTab === 'background' ? (
          <section className="review-background" aria-label="Tool events">
            <div className="review-section-title">
              <Text size="1" weight="bold" color="gray">
                Tool events
              </Text>
              <Badge color={workspaceEvents.length ? 'green' : 'gray'} variant="soft">
                {workspaceEvents.length ? `${visibleEvents.length} of ${workspaceEvents.length}` : 'idle'}
              </Badge>
            </div>
            <div className="review-event-toolbar">
              <div className="review-event-filters" aria-label="Background event filters">
                {eventFilterItems.map((item) => (
                  <button
                    className={eventFilter === item ? 'selected' : ''}
                    type="button"
                    aria-pressed={eventFilter === item}
                    aria-label={`${item} events, ${eventKindCounts[item]} available`}
                    key={item}
                    onClick={() => setEventFilter(item)}
                  >
                    <span>{item}</span>
                  </button>
                ))}
              </div>
              <label className="review-event-search">
                <MagnifyingGlassIcon aria-hidden />
                <input
                  aria-label="Search background events"
                  value={eventQuery}
                  onChange={(event) => setEventQuery(event.target.value)}
                  placeholder="Search events..."
                />
              </label>
              <div className="review-event-actions">
                <label className="review-event-toggle">
                  <span>Auto-scroll</span>
                  <button
                    className={`review-event-switch ${eventAutoScroll ? 'on' : ''}`}
                    type="button"
                    aria-label="Toggle background event auto-scroll"
                    aria-pressed={eventAutoScroll}
                    onClick={() => setEventAutoScroll((enabled) => !enabled)}
                  />
                </label>
                <button
                  className="review-event-clear"
                  type="button"
                  disabled={!canClearEvents}
                  onClick={clearEventScan}
                >
                  Clear
                </button>
              </div>
            </div>
            {eventSummaryItems.length ? (
              <div className="review-event-summary" aria-label="Background event mix">
                {eventSummaryItems.map(({ kind, count }) => (
                  <button
                    className={`review-event-summary-item ${kind.toLowerCase()} ${
                      eventFilter === kind ? 'selected' : ''
                    }`}
                    type="button"
                    aria-pressed={eventFilter === kind}
                    key={kind}
                    onClick={() => setEventFilter(kind)}
                  >
                    <span>{kind}</span>
                    <strong>{count}</strong>
                    <em>{Math.round((count / workspaceEvents.length) * 100)}%</em>
                  </button>
                ))}
              </div>
            ) : null}
            {workspaceEvents.length ? (
              visibleEvents.length ? (
                <div className="review-event-list" role="list">
                  {visibleEvents.slice(0, 24).map((event) => (
                    <article
                      className={`review-event-row ${event.kind.toLowerCase()} ${
                        selectedEventId === event.id ? 'selected' : ''
                      }`}
                      role="listitem"
                      key={event.id}
                    >
                      <button
                        className="review-event-button"
                        type="button"
                        aria-pressed={selectedEventId === event.id}
                        aria-label={`Select event ${event.eventType}`}
                        onClick={() => setSelectedEventId(event.id)}
                      >
                        <div className="review-event-head">
                          <Badge color={event.kind === 'Errors' ? 'red' : 'gray'} variant="soft">
                            {event.kind}
                          </Badge>
                          <strong>{event.eventType}</strong>
                          <span>{event.time}</span>
                        </div>
                        <div className="review-event-body">
                          <span>{event.source}</span>
                          <em>{event.status}</em>
                          <p>{event.detail}</p>
                        </div>
                        <span className="review-event-latency">{event.latency}</span>
                        <ChevronRightIcon className="review-event-chevron" aria-hidden />
                      </button>
                      <details className="review-event-raw">
                        <summary>Raw event</summary>
                        <pre>{JSON.stringify(event.raw, null, 2)}</pre>
                      </details>
                    </article>
                  ))}
                </div>
              ) : (
                <ReviewEmpty
                  icon={<DotsHorizontalIcon />}
                  title="No matching events"
                  body="Adjust the event filter or search query to inspect background activity."
                />
              )
            ) : (
                <ReviewEmpty
                  icon={<DotsHorizontalIcon />}
                  title="No tool events"
                  body="Tool calls, reasoning updates, queued checks, and progress events appear here after connection."
                />
            )}
            {workspaceEvents.length ? (
              <div className="review-event-footer">
                <span>
                  {visibleEvents.length} event{visibleEvents.length === 1 ? '' : 's'}
                </span>
                <span>
                  {eventFilter === 'All' ? 'All types' : eventFilter}
                  {eventQuery.trim() ? ` / ${eventQuery.trim()}` : ''}
                </span>
                {selectedEvent ? (
                  <span title={selectedEvent.detail}>Selected {selectedEvent.eventType}</span>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {activeTab === 'artifacts' ? (
          <section className="review-artifacts" aria-label="Artifacts">
            <div className="review-section-title">
              <Text size="1" weight="bold" color="gray">
                Artifacts
              </Text>
              <Badge color={socketConnected ? 'green' : 'gray'} variant="soft">
                {artifacts.length ? `${visibleArtifacts.length} of ${artifacts.length}` : socketConnected ? 'subscribed' : 'idle'}
              </Badge>
            </div>
            <div className="review-artifact-toolbar">
              <div className="review-artifact-filters" aria-label="Artifact filters">
                {artifactFilterItems.map((item) => (
                  <button
                    className={artifactFilter === item ? 'selected' : ''}
                    type="button"
                    aria-pressed={artifactFilter === item}
                    key={item}
                    onClick={() => setArtifactFilter(item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
              <label className="review-artifact-search">
                <MagnifyingGlassIcon aria-hidden />
                <input
                  aria-label="Search artifacts"
                  value={artifactQuery}
                  onChange={(event) => setArtifactQuery(event.target.value)}
                  placeholder="Search artifacts..."
                />
              </label>
              <div className="review-artifact-actions">
                <label className="review-artifact-sort">
                  <span>Sort</span>
                  <select
                    aria-label="Artifact sort"
                    value={artifactSort}
                    onChange={(event) =>
                      setArtifactSort(event.target.value as WorkspaceArtifactSort)
                    }
                  >
                    <option value="recent">Recent first</option>
                    <option value="largest">Largest first</option>
                    <option value="name">Name</option>
                  </select>
                </label>
                <Tooltip content={artifactView === 'grid' ? 'Show list view' : 'Show grid view'}>
                  <button
                    className="review-artifact-view-button"
                    type="button"
                    aria-label="Grid view"
                    aria-pressed={artifactView === 'grid'}
                    onClick={() =>
                      setArtifactView((view) => (view === 'grid' ? 'list' : 'grid'))
                    }
                  >
                    {artifactView === 'grid' ? <ViewVerticalIcon /> : <GridIcon />}
                  </button>
                </Tooltip>
              </div>
            </div>
            {artifacts.length ? (
              visibleArtifacts.length ? (
                <div className={`review-artifact-list ${artifactView}`} role="list">
                  {visibleArtifacts.map((artifact) => (
                    <div className="review-artifact-item" role="listitem" key={artifact.id}>
                      <button
                        className={`review-artifact-row ${
                          selectedArtifactId === artifact.id ? 'selected' : ''
                        }`}
                        type="button"
                        aria-pressed={selectedArtifactId === artifact.id}
                        aria-label={`Select artifact ${artifact.name}`}
                        onClick={() => setSelectedArtifactId(artifact.id)}
                      >
                        <div className="review-artifact-icon" aria-hidden>
                          {artifact.kind === 'Patches' ? (
                            <CodeIcon />
                          ) : artifact.kind === 'Reports' ? (
                            <ReaderIcon />
                          ) : artifact.kind === 'Logs' ? (
                            <ActivityLogIcon />
                          ) : (
                            <ArchiveIcon />
                          )}
                        </div>
                        <div className="review-artifact-main">
                          <div className="review-artifact-title">
                            <strong title={artifact.path || artifact.name}>{artifact.name}</strong>
                            <Badge color={artifact.status === 'error' ? 'red' : 'gray'} variant="soft">
                              {artifact.status}
                            </Badge>
                          </div>
                          <Text size="1" color="gray" title={artifact.path}>
                            {artifact.path || artifact.source}
                          </Text>
                          <code>{artifact.preview}</code>
                        </div>
                        <div className="review-artifact-meta">
                          <span>{workspaceArtifactKindLabels[artifact.kind]}</span>
                          {artifact.diff ? <span>{artifact.diff}</span> : null}
                          {artifact.size ? <span>{artifact.size}</span> : null}
                          <span>{artifact.time}</span>
                        </div>
                        <DotsHorizontalIcon className="review-artifact-more" aria-hidden />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <ReviewEmpty
                  icon={<ArchiveIcon />}
                  title="No matching artifacts"
                  body="Adjust the artifact filter or search query to see generated files and events."
                />
              )
            ) : (
              <ReviewEmpty
                icon={<ArchiveIcon />}
                title="No artifacts yet"
                body="Generated files, patch metadata, reports, and artifact events will appear here after connection."
              />
            )}
            {artifacts.length ? (
              <div className="review-artifact-footer">
                <span>
                  {visibleArtifacts.length} item{visibleArtifacts.length === 1 ? '' : 's'}
                </span>
                <span>Total {visibleArtifactTotalSize}</span>
                {selectedArtifact ? (
                  <span title={selectedArtifact.path || selectedArtifact.name}>
                    Selected {selectedArtifact.name}
                  </span>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {activeTab === 'terminal' ? (
          <div className="review-terminal">
            <div className="review-section-title">
              <Text size="1" weight="bold" color="gray">
                Terminal
              </Text>
              <Badge color={terminalConnected ? 'green' : 'gray'} variant="soft">
                {terminalConnected ? 'connected' : 'idle'}
              </Badge>
            </div>
            <pre className="terminal-preview">
              {terminalLines.length
                ? terminalLines.slice(-20).join('\n')
                : 'Start a sandbox terminal to stream output here.'}
            </pre>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function PullRequestReviewPanel({
  summary,
  onOpenChanges,
  onOpenArtifacts,
}: {
  summary: ReviewPullRequestSummary;
  onOpenChanges: () => void;
  onOpenArtifacts: () => void;
}) {
  const statusColor =
    summary.status === 'needs review' ? 'red' : summary.status === 'idle' ? 'gray' : 'green';
  const riskClassName = `risk-${summary.risk.toLowerCase()}`;

  return (
    <div className="review-pr">
      <section className="pr-summary-panel">
        <div className="pr-summary-head">
          <div>
            <span className="pr-kicker">
              <ReaderIcon />
              Pull request packet
            </span>
            <Heading as="h3" size="3">
              {summary.title}
            </Heading>
            <p>{summary.summary}</p>
          </div>
          <Badge color={statusColor} variant="soft">
            {summary.status}
          </Badge>
        </div>

        <div className="pr-branch-strip" aria-label="Pull request branch summary">
          <div>
            <span>Branch</span>
            <strong>{summary.branch}</strong>
          </div>
          <ChevronRightIcon aria-hidden />
          <div>
            <span>Base</span>
            <strong>{summary.base}</strong>
          </div>
          <div>
            <span>Diff</span>
            <strong>{summary.diff}</strong>
          </div>
        </div>

        <div className="pr-metric-grid" aria-label="Pull request review metrics">
          <div>
            <CommitIcon />
            <span>Files changed</span>
            <strong>{summary.filesChanged}</strong>
          </div>
          <div>
            <ExclamationTriangleIcon />
            <span>Estimated risk</span>
            <strong className={riskClassName}>{summary.risk}</strong>
          </div>
          <div>
            <ActivityLogIcon />
            <span>Checks</span>
            <strong>{summary.checks.filter((check) => check.status === 'passed').length} passed</strong>
          </div>
        </div>

        <section className="pr-section">
          <div className="pr-section-head">
            <strong>Checks</strong>
            <button type="button" onClick={onOpenChanges}>
              Open review
              <ChevronRightIcon />
            </button>
          </div>
          <div className="pr-check-list">
            {summary.checks.map((check) => (
              <div className={`pr-check-row ${check.status}`} key={check.label}>
                <CheckCircledIcon />
                <span>{check.label}</span>
                <strong>{check.value}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="pr-section">
          <div className="pr-section-head">
            <strong>Files</strong>
            <button type="button" onClick={onOpenArtifacts}>
              Open artifacts
              <ChevronRightIcon />
            </button>
          </div>
          {summary.files.length ? (
            <div className="pr-file-list">
              {summary.files.map((file) => (
                <div className="pr-file-row" key={file.id}>
                  <FileTextIcon />
                  <span>
                    <strong>{file.name}</strong>
                    <small title={file.path}>{file.path}</small>
                  </span>
                  <em>{file.meta || 'tracked'}</em>
                </div>
              ))}
            </div>
          ) : (
            <p className="pr-empty-copy">No file artifacts are attached to this workspace yet.</p>
          )}
        </section>
      </section>

      <section className="pr-actions-panel">
        <div>
          <Heading as="h3" size="2">
            Review actions
          </Heading>
          <Text size="1" color="gray">
            Read-only packet — no backend PR review contract
          </Text>
        </div>
        <button
          className="decision-approve-button"
          type="button"
          title={REVIEW_ACTION_UNAVAILABLE}
          disabled
        >
          <CheckCircledIcon />
          <span>
            <strong>Approve</strong>
            <small>{REVIEW_ACTION_UNAVAILABLE}</small>
          </span>
        </button>
        <button
          className="decision-request-button"
          type="button"
          title={REVIEW_ACTION_UNAVAILABLE}
          disabled
        >
          <MixerHorizontalIcon />
          <span>
            <strong>Request changes</strong>
            <small>{REVIEW_ACTION_UNAVAILABLE}</small>
          </span>
        </button>

        <div className="pr-activity-list" aria-label="Recent pull request activity">
          <strong>Recent activity</strong>
          {summary.activity.length ? (
            summary.activity.map((event) => (
              <div className="pr-activity-row" key={event.id}>
                <span>{event.time}</span>
                <em>{event.status}</em>
                <strong>{event.label}</strong>
                <small title={event.detail}>{event.detail}</small>
              </div>
            ))
          ) : (
            <p>No background activity loaded.</p>
          )}
        </div>
      </section>
    </div>
  );
}

function ReviewDecisionPanel({
  summary,
  status,
  records,
  runScopeOnly,
  onRunScopeChange,
  onSnooze,
  onReset,
  onOpenArtifacts,
}: {
  summary: ReviewDecisionSummary;
  status: ReviewDecisionStatus;
  records: ReviewDecisionRecord[];
  runScopeOnly: boolean;
  onRunScopeChange: (runScopeOnly: boolean) => void;
  onSnooze: () => void;
  onReset: () => void;
  onOpenArtifacts: () => void;
}) {
  const resolved = status !== 'pending';
  const impactLabel = `${summary.risk} impact`;
  const statusLabel = resolved ? 'Resolved' : impactLabel;
  const statusColor =
    resolved ? 'green' : summary.risk === 'High' ? 'red' : summary.risk === 'Medium' ? 'amber' : 'gray';
  const decisionCopy =
    status === 'approved'
      ? 'A local display marker was recorded; it did not change the backend run.'
      : status === 'changes'
        ? 'A local display marker was recorded; it did not pause the backend run.'
        : REVIEW_ACTION_UNAVAILABLE;

  return (
    <div className="review-decision" aria-label="Human decision">
      <section className="decision-summary">
        <div className="decision-summary-head">
          <div>
            <span className="decision-kicker">
              <ExclamationTriangleIcon />
              Human decision
            </span>
            <small className="decision-request-source">Request from Executor</small>
            <Heading as="h3" size="3">
              {resolved ? 'Decision recorded' : 'Approve patch'}
            </Heading>
          </div>
          <Badge color={statusColor} variant="soft">
            {statusLabel}
          </Badge>
        </div>

        <Text as="p" size="2" color="gray">
          {decisionCopy}
        </Text>

        <div className="decision-risk-strip" aria-label="Review impact summary">
          <div>
            <FileTextIcon />
            <span>Files changed</span>
            <strong>{summary.filesChanged}</strong>
          </div>
          <div>
            <CommitIcon />
            <span>Insertions / Deletions</span>
            <strong>{summary.changeValue}</strong>
          </div>
          <div>
            <ActivityLogIcon />
            <span>Estimated risk</span>
            <strong className={`risk-${summary.risk.toLowerCase()}`}>{summary.risk}</strong>
          </div>
        </div>

        <div className="decision-section">
          <strong>Summary</strong>
          <p>{summary.summary}</p>
        </div>

        <div className="decision-section">
          <div className="decision-section-head">
            <strong>Files</strong>
            <button
              type="button"
              aria-label="View full diff in artifacts"
              onClick={onOpenArtifacts}
            >
              View full diff
              <ChevronRightIcon aria-hidden />
            </button>
          </div>
          {summary.artifacts.length ? (
            <div className="decision-file-list">
              {summary.artifacts.map((artifact) => (
                <div className="decision-file-row" key={artifact.id}>
                  <span>{artifact.name}</span>
                  <strong>{artifact.diff || artifact.meta || 'tracked'}</strong>
                  <small title={artifact.path}>{artifact.path}</small>
                </div>
              ))}
            </div>
          ) : (
            <p>No changed files detected.</p>
          )}
        </div>

        <div className="decision-section">
          <strong>Agent reasoning</strong>
          <p className="decision-reasoning">{summary.reasoning}</p>
        </div>

        <div className="decision-section">
          <strong>Context</strong>
          <div className="decision-context-grid" aria-label="Review context">
            {summary.checks.map((check) => (
              <div key={check.label}>
                <span>{check.label}</span>
                <strong>{check.value}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="decision-actions-panel">
        <div>
          <Heading as="h3" size="2">
            Choose an action
          </Heading>
        </div>
        <button
          className="decision-approve-button"
          type="button"
          title={REVIEW_ACTION_UNAVAILABLE}
          disabled
        >
          <CheckCircledIcon />
          <span>
            <strong>Approve patch</strong>
            <small>{REVIEW_ACTION_UNAVAILABLE}</small>
          </span>
        </button>
        <button
          className="decision-request-button"
          type="button"
          title={REVIEW_ACTION_UNAVAILABLE}
          disabled
        >
          <MixerHorizontalIcon />
          <span>
            <strong>Request changes</strong>
            <small>{REVIEW_ACTION_UNAVAILABLE}</small>
          </span>
        </button>
        <button className="decision-reset-button" type="button" disabled={!resolved} onClick={onReset}>
          Reset decision
        </button>
        <div className="decision-scope-row">
          <label>
            <input
              type="checkbox"
              checked={runScopeOnly}
              disabled
              onChange={(event) => onRunScopeChange(event.currentTarget.checked)}
            />
            <span>Backend review scope unavailable</span>
          </label>
          <button
            className="decision-snooze-button"
            type="button"
            onClick={onSnooze}
          >
            Snooze
          </button>
        </div>

        {records.length ? (
          <div className="decision-history" aria-label="Decision history">
            <strong>Decision history</strong>
            {records.map((record) => (
              <div className={`decision-history-row ${record.status}`} key={record.id}>
                <span>{record.time}</span>
                <em>{record.label}</em>
                <small>{record.detail}</small>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function buildPlanDisplayRows(plan: PlanSnapshot) {
  const orderedKeys = [
    'root_goal',
    'plan',
    'iteration',
    'delivery',
    'blackboard',
    'outbox',
    'events',
    'plan_history',
    'iteration_runs',
    'run_health',
    'artifact_index',
    'workspace_id',
  ];
  const seen = new Set<string>();
  const rows = orderedKeys.flatMap((key) => {
    if (!(key in plan)) return [];
    seen.add(key);
    return [buildPlanDisplayRow(key, plan[key])];
  });
  Object.keys(plan)
    .filter((key) => !seen.has(key))
    .slice(0, Math.max(0, 12 - rows.length))
    .forEach((key) => rows.push(buildPlanDisplayRow(key, plan[key])));
  return rows.slice(0, 12);
}

function buildPlanDisplayRow(key: string, value: unknown) {
  return {
    key,
    label: humanizePlanKey(key),
    detail: summarizePlanValue(value),
  };
}

function humanizePlanKey(key: string) {
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(' ');
}

function summarizePlanValue(value: unknown) {
  if (value === null || value === undefined) return 'Not loaded';
  if (Array.isArray(value)) return value.length ? `${value.length} items` : 'No items';
  if (typeof value === 'object') return `${Object.keys(value).length} fields`;
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  return String(value);
}

function ReviewEmpty({
  icon,
  title,
  body,
}: {
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="review-empty">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function reviewTabToWorkflowTarget(tab: ReviewTab): WorkflowTarget {
  if (tab === 'pull') return 'pull';
  if (tab === 'plan') return 'plan';
  if (tab === 'background') return 'background';
  if (tab === 'artifacts') return 'artifacts';
  if (tab === 'terminal') return 'runtime';
  return 'changes';
}

function chatWorkflowTargetForReviewTab(tab: ReviewTab): ChatWorkflowTarget {
  if (tab === 'pull') return 'pull';
  if (tab === 'background') return 'background';
  if (tab === 'artifacts') return 'artifacts';
  if (tab === 'changes') return 'changes';
  return 'plan';
}

function signedOutTargetForSection(section: WorkbenchSection, tab: ReviewTab): WorkflowTarget {
  if (section === 'board') return 'changes';
  if (section === 'status') return 'background';
  if (section === 'memory') return 'runtime';
  return reviewTabToWorkflowTarget(tab);
}

function signedOutWorkflowContext(target: WorkflowTarget): { title: string; body: string } {
  if (target === 'plan') {
    return {
      title: 'Plan snapshot',
      body: 'Sign in to load the active plan, checkpoints, and open decisions.',
    };
  }
  if (target === 'pull') {
    return {
      title: 'Pull request',
      body: 'Connect a GitHub-backed workspace to show PR overview, checks, branch state, and review actions.',
    };
  }
  if (target === 'board') {
    return {
      title: 'Task board',
      body: 'Sign in to show workspace tasks as board lanes with status, progress, and priority.',
    };
  }
  if (target === 'background') {
    return {
      title: 'Tool events',
      body: 'Tool calls, reasoning updates, queued checks, and progress events appear here after connection.',
    };
  }
  if (target === 'artifacts') {
    return {
      title: 'Artifacts and events',
      body: 'Generated files, event updates, and background activity appear here after connection.',
    };
  }
  if (target === 'runtime') {
    return {
      title: 'Local workspace',
      body: 'Sign in or configure a connection to start the sandbox desktop and terminal.',
    };
  }
  return {
    title: 'Workspace changes',
    body: 'No repository diff is loaded yet. Sign in or configure a connection to sync this session.',
  };
}

function CommandPalette({
  inputRef,
  query,
  items,
  onQueryChange,
  onClose,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  items: CommandPaletteItem[];
  onQueryChange: (query: string) => void;
  onClose: (restoreFocus?: boolean) => void;
}) {
  const paletteRef = useRef<HTMLElement>(null);
  const enabledItems = useMemo(() => items.filter((item) => !item.disabled), [items]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const activeItem = enabledItems.find((item) => item.id === activeItemId) ?? enabledItems[0];
  const activeOptionId = activeItem ? `command-option-${activeItem.id}` : undefined;

  useEffect(() => {
    setActiveItemId((current) => {
      if (current && enabledItems.some((item) => item.id === current)) {
        return current;
      }
      return enabledItems[0]?.id ?? null;
    });
  }, [enabledItems]);

  useEffect(() => {
    if (!activeOptionId) return;
    document.getElementById(activeOptionId)?.scrollIntoView({ block: 'nearest' });
  }, [activeOptionId]);

  useEffect(() => {
    const keepFocusInsidePalette = (event: FocusEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (paletteRef.current?.contains(target)) return;
      inputRef.current?.focus();
    };

    window.addEventListener('focusin', keepFocusInsidePalette);
    return () => window.removeEventListener('focusin', keepFocusInsidePalette);
  }, [inputRef]);

  const runItem = (item: CommandPaletteItem) => {
    if (item.disabled) return;
    item.onSelect();
    onClose(false);
  };

  const moveActiveItem = (delta: number) => {
    setActiveItemId((current) => {
      if (enabledItems.length === 0) return null;
      const currentIndex = enabledItems.findIndex((item) => item.id === current);
      const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
      const nextIndex = (startIndex + delta + enabledItems.length) % enabledItems.length;
      return enabledItems[nextIndex].id;
    });
  };

  const containTabFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.key !== 'Tab') return;
    const focusableElements = getCommandPaletteFocusableElements(paletteRef.current);
    if (!focusableElements.length) return;
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;

    if (event.shiftKey && activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
      return;
    }
    if (!event.shiftKey && activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  return (
    <div className="command-palette-backdrop" onMouseDown={() => onClose(true)}>
      <section
        ref={paletteRef}
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onKeyDown={containTabFocus}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <label className="command-search">
          <MagnifyingGlassIcon />
          <input
            ref={inputRef}
            value={query}
            aria-label="Search commands"
            placeholder="Search commands, sessions, tools..."
            aria-activedescendant={activeOptionId}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                moveActiveItem(1);
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault();
                moveActiveItem(-1);
              }
              if (event.key === 'Home' && enabledItems[0]) {
                event.preventDefault();
                setActiveItemId(enabledItems[0].id);
              }
              if (event.key === 'End' && enabledItems[enabledItems.length - 1]) {
                event.preventDefault();
                setActiveItemId(enabledItems[enabledItems.length - 1].id);
              }
              if (event.key === 'Enter' && activeItem) {
                event.preventDefault();
                runItem(activeItem);
              }
              if (event.key === 'Escape') {
                event.preventDefault();
                onClose(true);
              }
            }}
          />
        </label>
        <div className="command-list" role="listbox" aria-label="Command results">
          {items.length === 0 ? (
            <div className="command-empty">No commands found.</div>
          ) : (
            items.map((item) => (
              <button
                id={`command-option-${item.id}`}
                className={`command-row ${item.disabled ? 'disabled' : ''} ${
                  item.id === activeItem?.id ? 'selected' : ''
                }`}
                type="button"
                role="option"
                aria-selected={item.id === activeItem?.id}
                key={item.id}
                disabled={item.disabled}
                onMouseEnter={() => {
                  if (!item.disabled) {
                    setActiveItemId(item.id);
                  }
                }}
                onClick={() => runItem(item)}
              >
                <span className="command-icon">{item.icon}</span>
                <span className="command-copy">
                  <strong>{item.label}</strong>
                  <em>{item.description}</em>
                </span>
              </button>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function getCommandPaletteFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  const selectors = [
    'button:not(:disabled)',
    'input:not(:disabled)',
    'textarea:not(:disabled)',
    'select:not(:disabled)',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  return Array.from(container.querySelectorAll<HTMLElement>(selectors)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  );
}

function OverviewMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric overview-metric">
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="2" weight="bold">
        {value}
      </Text>
    </div>
  );
}

function SettingMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric setting-metric">
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="2" weight="bold">
        {value}
      </Text>
    </div>
  );
}

function UsagePlanPanel({
  accountLabel,
  planLabel,
  creditsUsedLabel,
}: {
  accountLabel: string;
  planLabel: string;
  creditsUsedLabel: string;
}) {
  return (
    <section className="usage-plan-panel" aria-labelledby="usage-plan-heading">
      <div className="usage-plan-header">
        <div>
          <Text size="1" color="gray">
            Accounts /
          </Text>
          <Heading id="usage-plan-heading" as="h3" size="3">
            Usage & Plan
          </Heading>
        </div>
        <Badge color="gray" variant="soft">
          100%
        </Badge>
      </div>
      <div className="usage-account-card">
        <div className="account-avatar" aria-hidden>
          {accountLabel.slice(0, 1).toUpperCase()}
        </div>
        <div className="usage-account-copy">
          <Text size="2" weight="bold">
            {accountLabel}
          </Text>
          <Text size="1" color="gray">
            Default
          </Text>
        </div>
      </div>
      <div className="usage-plan-row">
        <Text size="1" color="gray">
          Plan
        </Text>
        <Text size="2">{planLabel}</Text>
      </div>
      <div className="usage-plan-row">
        <Text size="1" color="gray">
          AI credits
        </Text>
        <Text size="2">100% quota used</Text>
      </div>
      <div className="usage-plan-meter" aria-label="100% quota used">
        <span />
      </div>
      <Text size="1" color="gray">
        AI credits are consumed based on model and token usage.
      </Text>
      <div className="usage-plan-row">
        <Text size="1" color="gray">
          Additional usage
        </Text>
        <Text size="2">{creditsUsedLabel}</Text>
      </div>
    </section>
  );
}
