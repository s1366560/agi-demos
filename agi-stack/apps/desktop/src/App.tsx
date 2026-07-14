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
  FileTextIcon,
  FrameIcon,
  GearIcon,
  GridIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PauseIcon,
  PlayIcon,
  ReaderIcon,
  ReloadIcon,
  RocketIcon,
  ExclamationTriangleIcon,
  StopIcon,
  ViewVerticalIcon,
} from '@radix-ui/react-icons';

import {
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiClient,
  isLegacyWorkspaceContextRouteMissing,
} from './api/client';
import {
  ingestLocalMemory,
  searchLocalMemory,
  semanticSearchLocalMemory,
} from './api/localMemory';
import { AuthPanel } from './features/auth/AuthPanel';
import { AutomationsPage } from './features/automations/AutomationsPage';
import {
  isCurrentContextRevision,
  isSameDesktopRequestScope,
  isWorkspaceAuthenticated,
  nextRemoteWorkspaceContext,
} from './features/auth/authContextModel';
import { LoginScreen } from './features/auth/LoginScreen';
import {
  clearTrustedLocalSessionReference,
  readTrustedLocalSessionReference,
  writeTrustedLocalSessionReference,
} from './features/auth/trustedLocalSessionReference';
import {
  ChatPanel,
  type AgentTaskSignal,
  type AgentTaskSignalStatus,
  type ChatWorkflowTarget,
} from './features/chat/ChatPanel';
import { ComposerControls } from './features/chat/ComposerControls';
import { markA2UIActionAnswered } from './features/chat/a2uiAction';
import { SessionEvidenceCanvas } from './features/session/SessionEvidenceCanvas';
import { SessionChangesCanvas } from './features/session/SessionChangesCanvas';
import { SessionInvocationActivity } from './features/session/SessionInvocationLedger';
import { SessionTerminalCanvas } from './features/session/SessionTerminalCanvas';
import { SessionWorkspace } from './features/session/SessionWorkspace';
import {
  artifactDeliveryRequest,
  artifactReviewRequest,
  artifactVersionActions,
  currentArtifactVersions,
  deliveryForArtifactVersion,
  type ArtifactVersionAction,
} from './features/session/sessionArtifactModel';
import {
  hasAuthoritativeChangeReview,
  sessionCanvasTabs,
  shouldShowSessionCanvas,
  type SessionCanvasTabId,
} from './features/session/sessionCanvasModel';
import {
  effectiveRunInputDelivery,
  snapshotMatchesRun,
  toggleRunInputReference,
} from './features/session/sessionChangesModel';
import {
  approvalResponseSubmission,
  latestPendingApproval,
  validateApprovalRequest,
} from './features/session/sessionDecisionModel';
import { artifactEvidenceForCurrentVersions } from './features/session/sessionEvidenceModel';
import {
  buildSessionInvocationLedger,
  sessionInvocationLedgerSummary,
} from './features/session/sessionInvocationLedgerModel';
import {
  decodeConversationSessionProjection,
  socketEventInvalidatesSessionProjectionForScope,
} from './features/session/sessionProjectionModel';
import {
  emptySessionProjectionState,
  type ConversationSessionProjection,
  type SessionProjectionCapabilities,
  type SessionProjectionLoadState,
} from './features/session/sessionProjectionTypes';
import {
  terminalBindingState,
  terminalRunScopeKey,
  terminalSessionMatchesRun,
  type TerminalBindingState,
} from './features/session/sessionTerminalModel';
import {
  authoritativeRunsFromSocketEvents,
  buildSessionDetailViewModel,
  conversationWithAuthoritativeRun,
  type SessionCapabilityMode,
  type SessionDetailViewModel,
  type SessionRunAction,
} from './features/session/sessionViewModel';
import {
  workspaceReviewPanelChrome,
  type SessionCanvasControls,
} from './features/session/workspaceReviewPanelModel';
import { socketEventMatchesSessionScope } from './features/session/sessionScope';
import { MyWorkQueue } from './features/my-work/MyWorkQueue';
import {
  myWorkConversationMatchesScope,
  myWorkRefreshScopeIsCurrent,
  socketEventInvalidatesMyWork,
  type MyWorkRefreshScope,
} from './features/my-work/myWorkModel';
import { DesktopSidebar } from './features/navigation/DesktopSidebar';
import {
  settingsSectionForEntry,
  type SettingsEntry,
} from './features/settings/settingsEntryRouting';
import { SettingsWindow, type SettingsSection } from './features/settings/SettingsWindow';
import { StatusPanel } from './features/status/StatusPanel';
import {
  NewTaskFlow,
  type NewTaskAgentTurnInput,
  type NewTaskSession,
} from './features/task/NewTaskFlow';
import {
  newTaskAgentTurnResolution,
  newTaskAgentTurnTransport,
} from './features/task/newTaskPlanModel';
import { WorkspaceDock } from './features/workspace/WorkspaceDock';
import { WorkspaceOverview } from './features/workspace/WorkspaceOverview';
import { socketEventsSince, useAgentSocket } from './hooks/useAgentSocket';
import { useTerminalProxy } from './hooks/useTerminalProxy';
import { useI18n } from './i18n';
import type {
  AgentConversation,
  AgentTimelineItem,
  AgentWsEvent,
  AuthState,
  ConnectionState,
  ConversationTimelineState,
  ChangeSnapshot,
  CodeRangeReference,
  DesktopApprovalRequest,
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
  DesktopRunInput,
  DesktopRuntimeConfig,
  DesktopServiceResponse,
  DesktopToolInvocation,
  HitlResponseSubmission,
  LoginOutcome,
  LocalRuntimeStatus,
  LocalMemoryResult,
  PlanSnapshot,
  ProjectSummary,
  ProjectSandbox,
  ProjectWorkItem,
  RuntimeNodeLoadState,
  RuntimeDataset,
  RunInputDelivery,
  StatusTab,
  TerminalServiceResponse,
  WorkbenchSection,
  WorkspaceContextSnapshot,
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
  myWork: [],
  myWorkError: null,
};

const emptyAuthState: AuthState = {
  status: 'signed_out',
  credentialKind: null,
  session: null,
  context: null,
  user: null,
  tenants: [],
  projects: [],
  mustChangePassword: false,
  error: null,
};

const emptyConversationTimeline: ConversationTimelineState = {
  conversationId: null,
  items: [],
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

function titlebarRunStateFromStatus(status: string): RunControlState {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'queued') return 'planning';
  if (normalized === 'running' || normalized === 'active') return 'running';
  if (
    normalized === 'needs_input' ||
    normalized === 'needs_approval' ||
    normalized === 'paused' ||
    normalized === 'interrupted'
  ) {
    return 'paused';
  }
  if (normalized === 'ready_review' || normalized === 'completed') return 'running';
  if (
    normalized === 'failed' ||
    normalized === 'disconnected' ||
    normalized === 'cancelled'
  ) {
    return 'stopped';
  }
  return 'stopped';
}

function titlebarRunLabelFromStatus(
  status: string,
  translate: (key: string) => string,
): string {
  const normalized = status.trim().toLowerCase();
  const labels: Record<string, string> = {
    active: 'session.statusActive',
    queued: 'session.statusQueued',
    running: 'session.statusRunning',
    needs_input: 'session.statusNeedsInput',
    needs_approval: 'session.statusNeedsApproval',
    paused: 'session.statusPaused',
    ready_review: 'session.statusReadyReview',
    completed: 'session.statusCompleted',
    failed: 'session.statusFailed',
    interrupted: 'session.statusInterrupted',
    disconnected: 'session.statusDisconnected',
    cancelled: 'session.statusCancelled',
  };
  return labels[normalized] ? translate(labels[normalized]) : runLabelFromStatus(status);
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
  settingsSection?: SettingsSection;
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
type ReviewTab = SessionCanvasTabId | 'pull' | 'background';
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
type WorkspaceArtifactKind = 'Files' | 'Patches' | 'Reports' | 'Logs' | 'Events';
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
  risk: 'Low' | 'Medium' | 'High' | 'Unassessed';
  changeValue: string;
  filesChanged: number;
  artifacts: ReviewDecisionArtifact[];
  checks: Array<{ label: string; value: string }>;
  canAct: boolean;
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

function buildReviewDecisionSummary(
  approvalRequest: DesktopApprovalRequest | null,
): ReviewDecisionSummary {
  const decision = approvalRequest?.decision ?? null;
  const fileIds = decision?.scope.kind === 'files' ? decision.scope.ids : [];
  const risk =
    decision?.risk.level === 'high'
      ? 'High'
      : decision?.risk.level === 'medium'
        ? 'Medium'
        : decision?.risk.level === 'low'
          ? 'Low'
          : 'Unassessed';

  return {
    title: decision?.action.label ?? 'No review packet loaded',
    summary:
      decision?.data.summary ??
      'The backend has not supplied a complete structured approval packet.',
    reasoning:
      decision?.reason ??
      'No agent-authored rationale is available for this approval request.',
    risk,
    changeValue: '+0 / -0',
    filesChanged: fileIds.length,
    artifacts: (decision?.evidence ?? []).map((evidence) => ({
      id: evidence.id,
      name: evidence.label,
      path: evidence.uri ?? evidence.id,
      meta: [evidence.kind, evidence.digest].filter(Boolean).join(' · '),
      diff: '',
    })),
    checks: decision
      ? [
          { label: 'Target', value: `${decision.target.kind} · ${decision.target.id}` },
          { label: 'Scope', value: `${decision.scope.kind} · ${decision.scope.ids.length}` },
          {
            label: 'Reversibility',
            value: decision.reversibility.mode,
          },
        ]
      : [],
    canAct: hasAuthoritativeChangeReview({
      changedFileCount: 0,
      hasPendingHitlRequest: Boolean(approvalRequest),
    }),
  };
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
  const { t } = useI18n();
  const [config, setConfig] = useState<DesktopRuntimeConfig>(DEFAULT_CONFIG);
  const [auth, setAuth] = useState<AuthState>(emptyAuthState);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [newTaskPreferredWorkspaceId, setNewTaskPreferredWorkspaceId] = useState('');
  const [preferredTaskMode, setPreferredTaskMode] = useState<'work' | 'code'>('work');
  const [settingsWindowOpen, setSettingsWindowOpen] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] = useState<SettingsSection>('account');
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
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState<Set<string>>(() => new Set());
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [dataset, setDataset] = useState<RuntimeDataset>(emptyDataset);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string>('never');
  const [localRuntimeStatus, setLocalRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [selectedSidebarRunId, setSelectedSidebarRunId] = useState('');
  const [runStateById, setRunStateById] = useState<Record<string, RunControlState>>({});
  const [runControlState, setRunControlState] = useState<RunControlState>('running');
  const [runtimeTarget, setRuntimeTarget] = useState<RuntimeTarget>('local');
  const [runLiveMode, setRunLiveMode] = useState(true);
  const [myWorkRefreshing, setMyWorkRefreshing] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const [changeSnapshot, setChangeSnapshot] = useState<ChangeSnapshot | null>(null);
  const [changeSnapshotLoading, setChangeSnapshotLoading] = useState(false);
  const [changeSnapshotError, setChangeSnapshotError] = useState<string | null>(null);
  const [runInputReferences, setRunInputReferences] = useState<CodeRangeReference[]>([]);
  const [runInputDelivery, setRunInputDelivery] = useState<RunInputDelivery | null>(null);
  const [runInputs, setRunInputs] = useState<DesktopRunInput[]>([]);
  const [runInputsLoading, setRunInputsLoading] = useState(false);
  const [runInputsError, setRunInputsError] = useState<string | null>(null);
  const [promotingRunInputId, setPromotingRunInputId] = useState<string | null>(null);
  const [sessionRunActionPending, setSessionRunActionPending] =
    useState<SessionRunAction | null>(null);
  const [artifactActionPending, setArtifactActionPending] = useState<{
    versionId: string;
    action: ArtifactVersionAction;
  } | null>(null);
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('workspace');
  const activeSectionRef = useRef<WorkbenchSection>('workspace');
  const [sectionBackStack, setSectionBackStack] = useState<WorkbenchSection[]>([]);
  const [sectionForwardStack, setSectionForwardStack] = useState<WorkbenchSection[]>([]);
  const [reviewTab, setReviewTab] = useState<ReviewTab>('overview');
  const [reviewPanelOpen, setReviewPanelOpen] = useState(true);
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
  const [sessionProjectionState, setSessionProjectionState] =
    useState<SessionProjectionLoadState>(emptySessionProjectionState);
  const [sessionDisplayProjection, setSessionDisplayProjection] =
    useState<ConversationSessionProjection | null>(null);
  const [sessionProjectionRefreshRevision, setSessionProjectionRefreshRevision] = useState(0);
  const [conversationTimeline, setConversationTimeline] =
    useState<ConversationTimelineState>(emptyConversationTimeline);
  const [agentTaskSignals, setAgentTaskSignals] = useState<AgentTaskSignal[]>([]);
  const pendingNewTaskAgentTurnsRef = useRef(
    new Map<
      string,
      {
        conversationId: string;
        messageId: string;
        timeoutId: number;
        resolve: () => void;
        reject: (error: Error) => void;
      }
    >(),
  );
  const timelineRequestRef = useRef(0);
  const sessionProjectionRequestRef = useRef(0);
  const sessionProjectionRefreshTimerRef = useRef<number | null>(null);
  const agentTaskEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const sessionEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const myWorkRequestRef = useRef(0);
  const myWorkAbortRef = useRef<AbortController | null>(null);
  const myWorkRefreshTimerRef = useRef<number | null>(null);
  const myWorkEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const contextRevisionRef = useRef(0);
  const configRef = useRef(config);
  const configScopeEpochRef = useRef(0);
  const localResumeAttemptRef = useRef('');
  const runInputRequestRef = useRef<{
    signature: string;
    messageId: string;
    idempotencyKey: string;
  } | null>(null);
  const terminalStartGenerationRef = useRef(0);
  const currentArtifactRunRef = useRef<DesktopRun | null>(null);
  const terminalRunScopeKeyRef = useRef('');

  const commitRuntimeConfig = useCallback((nextConfig: DesktopRuntimeConfig) => {
    if (!isSameDesktopRequestScope(configRef.current, nextConfig)) {
      configScopeEpochRef.current += 1;
    }
    configRef.current = nextConfig;
    setConfig(nextConfig);
  }, []);

  const api = useMemo(() => new DesktopApiClient(config), [config]);
  const socket = useAgentSocket(
    config,
    connection === 'ready',
    auth.context?.revision ?? null,
  );
  const desktopFrameUrl = useMemo(() => {
    if (!desktop?.success) return null;
    try {
      return api.desktopProxyUrl();
    } catch {
      return null;
    }
  }, [api, desktop?.success]);
  const modalOpen = loginModalOpen || commandPaletteOpen || newTaskOpen || settingsWindowOpen;
  const localRuntimeMode = config.mode === 'local' && runsInTauri;

  const syncLocalRuntimeConfig = useCallback(
    async (nextConfig: DesktopRuntimeConfig): Promise<DesktopRuntimeConfig> => {
      if (!runsInTauri || nextConfig.mode !== 'local') return nextConfig;
      const invoke = window.__TAURI__?.core?.invoke;
      if (!invoke) return nextConfig;
      const status = await invoke<LocalRuntimeStatus>('local_runtime_configure', {
        config: localRuntimeTauriConfig(nextConfig),
      });
      setLocalRuntimeStatus(status);
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
        setLocalRuntimeStatus(status);
        commitRuntimeConfig(mergeLocalRuntimeStatus(configRef.current, status));
      })
      .catch((caught) => {
        if (!cancelled) setError(formatError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [commitRuntimeConfig, localRuntimeMode]);

  const scopedConversation =
    agentConversationSession?.scopeKey === agentConversationScopeKey(config)
      ? agentConversationSession.conversation
      : null;
  const scopedConversationId = scopedConversation?.id ?? '';
  const invalidateSessionAuthority = useCallback(() => {
    if (!scopedConversationId) return;
    sessionProjectionRequestRef.current += 1;
    setSessionProjectionState({
      status: 'loading',
      conversationId: scopedConversationId,
      projection: null,
      error: null,
    });
    setSessionProjectionRefreshRevision((revision) => revision + 1);
  }, [scopedConversationId]);
  useEffect(() => {
    if (!scopedConversationId) {
      sessionProjectionRequestRef.current += 1;
      setSessionProjectionState(emptySessionProjectionState);
      setSessionDisplayProjection(null);
      return;
    }
    const requestId = sessionProjectionRequestRef.current + 1;
    sessionProjectionRequestRef.current = requestId;
    const controller = new AbortController();
    setSessionDisplayProjection((current) =>
      current?.conversation.id === scopedConversationId ? current : null,
    );
    setSessionProjectionState({
      status: 'loading',
      conversationId: scopedConversationId,
      projection: null,
      error: null,
    });
    void api
      .getConversationSession(
        scopedConversationId,
        {
          tenantId: config.tenantId,
          projectId: config.projectId,
          workspaceId: config.workspaceId || null,
        },
        controller.signal,
      )
      .then((payload) => {
        if (controller.signal.aborted || sessionProjectionRequestRef.current !== requestId) return;
        const projection = decodeConversationSessionProjection(payload, {
          conversationId: scopedConversationId,
          projectId: config.projectId,
          tenantId: config.tenantId,
          workspaceId: config.workspaceId || null,
        });
        if (projection) setSessionDisplayProjection(projection);
        setSessionProjectionState(
          projection
            ? {
                status: 'ready',
                conversationId: scopedConversationId,
                projection,
                error: null,
              }
            : {
                status: 'error',
                conversationId: scopedConversationId,
                projection: null,
                error: 'invalid_projection',
              },
        );
      })
      .catch((caught) => {
        if (controller.signal.aborted || sessionProjectionRequestRef.current !== requestId) return;
        setSessionProjectionState({
          status: 'error',
          conversationId: scopedConversationId,
          projection: null,
          error: formatConnectionError(caught, config.apiBaseUrl),
        });
      });
    return () => controller.abort();
  }, [
    api,
    config.apiBaseUrl,
    config.projectId,
    config.tenantId,
    config.workspaceId,
    scopedConversationId,
    sessionProjectionRefreshRevision,
  ]);
  const sessionProjection =
    sessionProjectionState.status === 'ready' &&
    sessionProjectionState.conversationId === scopedConversationId
      ? sessionProjectionState.projection
      : null;
  const displaySessionProjection =
    sessionDisplayProjection?.conversation.id === scopedConversationId
      ? sessionDisplayProjection
      : null;
  const respondableHitlRequestIds = useMemo(
    () =>
      sessionProjection?.capabilities.canRespondToHitl &&
      sessionProjection.capabilities.allowedActions.includes('respond_to_hitl')
        ? sessionProjection.pendingHitl.map((request) => request.id)
        : [],
    [sessionProjection],
  );
  const respondableHitlRequestIdSet = useMemo(
    () => new Set(respondableHitlRequestIds),
    [respondableHitlRequestIds],
  );
  const activeDataset = dataset;
  const sessionTasks = useMemo<WorkspaceTask[]>(
    () =>
      displaySessionProjection?.tasks.map((task) => {
        const content = typeof task.content === 'string' ? task.content : undefined;
        return {
          id: task.id,
          conversation_id: displaySessionProjection.conversation.id,
          title: content,
          description: content,
          status: typeof task.status === 'string' ? task.status : undefined,
          priority:
            typeof task.priority === 'string' || typeof task.priority === 'number'
              ? task.priority
              : undefined,
          created_at: typeof task.created_at === 'string' ? task.created_at : undefined,
          updated_at: typeof task.updated_at === 'string' ? task.updated_at : undefined,
          plan_version_id: displaySessionProjection.currentPlan?.id,
          plan_version: displaySessionProjection.currentPlan?.version,
          plan_status: displaySessionProjection.currentPlan?.status,
          run_id: displaySessionProjection.currentRun?.id ?? null,
          run_status: displaySessionProjection.currentRun?.status ?? null,
          run_revision: displaySessionProjection.currentRun?.revision ?? null,
          source: 'agent_plan_task',
          task,
        };
      }) ?? [],
    [displaySessionProjection],
  );
  const sessionPlan = useMemo<PlanSnapshot | null>(() => {
    if (!displaySessionProjection) return null;
    return {
      conversation_id: displaySessionProjection.conversation.id,
      project_id: displaySessionProjection.conversation.project_id,
      workspace_id: displaySessionProjection.conversation.workspace_id ?? undefined,
      plan: displaySessionProjection.currentPlan
        ? { ...displaySessionProjection.currentPlan }
        : null,
      plan_history: displaySessionProjection.planHistory.map((plan) => ({ ...plan })),
      run_health: displaySessionProjection.runHistory,
      pending_hitl: displaySessionProjection.pendingHitl.map((request) => ({ ...request })),
      delivery: displaySessionProjection.artifactDeliveries,
      artifact_index: displaySessionProjection.artifactVersions,
    };
  }, [displaySessionProjection]);
  const sessionDataset = useMemo<RuntimeDataset>(() => {
    if (!scopedConversation) return activeDataset;
    return {
      ...activeDataset,
      tasks: sessionTasks,
      plan: sessionPlan,
    };
  }, [activeDataset, scopedConversation, sessionPlan, sessionTasks]);
  const sessionTimeline = useMemo<ConversationTimelineState>(
    () => ({
      ...conversationTimeline,
      approvalRequests: displaySessionProjection?.pendingHitl ?? [],
      artifactVersions: displaySessionProjection?.artifactVersions ?? [],
      artifactDeliveries: displaySessionProjection?.artifactDeliveries ?? [],
      toolInvocations: displaySessionProjection?.toolInvocations ?? [],
    }),
    [conversationTimeline, displaySessionProjection],
  );
  const selectedTask = useMemo(
    () =>
      activeDataset.tasks.find((task) => task.id === selectedTaskId) ??
      activeDataset.tasks[0] ??
      null,
    [activeDataset.tasks, selectedTaskId],
  );
  const workspaceEventInputs = useMemo(
    () =>
      scopedConversation
        ? socket.events.filter((event) =>
            socketEventMatchesSessionScope(
              event,
              {
                conversationId: scopedConversation.id,
                workspaceId:
                  scopedConversation.workspace_id ?? (config.workspaceId.trim() || null),
              },
              false,
            ),
          )
        : socket.events,
    [config.workspaceId, scopedConversation, socket.events],
  );
  const workspaceArtifacts = useMemo(
    () =>
      scopedConversation
        ? []
        : buildWorkspaceArtifacts(
            conversationTimeline.items,
            workspaceEventInputs,
            sessionDataset.plan,
          ),
    [conversationTimeline.items, scopedConversation, sessionDataset.plan, workspaceEventInputs],
  );
  const chatWorkflowCounts = useMemo<Partial<Record<ChatWorkflowTarget, number | string>>>(
    () => ({
      plan: sessionDataset.plan ? 'ready' : 'idle',
      background: workspaceEventInputs.length,
      artifacts: displaySessionProjection?.artifactVersions.length ?? workspaceArtifacts.length,
    }),
    [
      sessionDataset.plan,
      displaySessionProjection?.artifactVersions.length,
      workspaceArtifacts.length,
      workspaceEventInputs.length,
    ],
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
            approvalRequests: response.approval_requests ?? [],
            artifactVersions: response.artifact_versions ?? [],
            artifactDeliveries: response.artifact_deliveries ?? [],
            toolInvocations: response.tool_invocations ?? [],
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
          approvalRequests: response.approval_requests ?? current.approvalRequests,
          artifactVersions: response.artifact_versions ?? current.artifactVersions,
          artifactDeliveries: response.artifact_deliveries ?? current.artifactDeliveries,
          toolInvocations: response.tool_invocations ?? current.toolInvocations,
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
      if (scopedConversation) {
        const request = sessionProjection?.pendingHitl.find(
          (candidate) => candidate.id === submission.requestId,
        );
        const revisionMatches = request?.run_id
          ? request.run_revision === submission.expectedRevision
          : submission.expectedRevision === undefined;
        if (
          !request ||
          request.status !== 'pending' ||
          request.kind !== submission.hitlType ||
          !revisionMatches ||
          !respondableHitlRequestIdSet.has(submission.requestId)
        ) {
          throw new Error(t('session.authorityActionUnavailable'));
        }
      }
      setError(null);
      try {
        await api.respondToHitl(submission);
        invalidateSessionAuthority();
        const conversation = agentConversationSession?.conversation;
        if (conversation) {
          await loadConversationTimeline(conversation, config.projectId);
        }
      } catch (caught) {
        const message = formatConnectionError(caught, config.apiBaseUrl);
        setError(message);
        throw new Error(message, { cause: caught });
      }
    },
    [
      agentConversationSession?.conversation,
      api,
      config.apiBaseUrl,
      config.projectId,
      invalidateSessionAuthority,
      loadConversationTimeline,
      respondableHitlRequestIdSet,
      scopedConversation,
      sessionProjection,
      t,
    ],
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
    const events = socketEventsSince(socket.events, agentTaskEventsHeadRef.current);
    agentTaskEventsHeadRef.current = socket.events[0] ?? null;
    for (const event of events) {
      const update = agentTaskUpdateFromSocketEvent(event);
      if (!update) continue;
      if (update.status === 'acknowledged' || update.status === 'failed') {
        for (const [key, pending] of pendingNewTaskAgentTurnsRef.current) {
          const resolution = newTaskAgentTurnResolution(
            update,
            pending.conversationId,
            pending.messageId,
          );
          if (!resolution) continue;
          window.clearTimeout(pending.timeoutId);
          pendingNewTaskAgentTurnsRef.current.delete(key);
          if (resolution === 'acknowledged') pending.resolve();
          else pending.reject(new Error(update.detail));
        }
      }
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
    }
  }, [socket.events]);

  useEffect(() => {
    if (socket.connected) return;
    for (const [key, pending] of pendingNewTaskAgentTurnsRef.current) {
      window.clearTimeout(pending.timeoutId);
      pending.reject(new Error(t('task.liveConnectionRequired')));
      pendingNewTaskAgentTurnsRef.current.delete(key);
    }
  }, [socket.connected, t]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, sessionEventsHeadRef.current);
    sessionEventsHeadRef.current = socket.events[0] ?? null;
    if (!events.length) return;
    const activeConversation = scopedConversation;
    if (!activeConversation) return;
    const scope = {
      conversationId: activeConversation.id,
      workspaceId:
        activeConversation.workspace_id ?? (config.workspaceId.trim() || null),
    };
    const timelineEvents = events.filter((event) =>
      socketEventMatchesSessionScope(event, scope, false),
    );
    if (timelineEvents.length) {
      setConversationTimeline((current) => {
        if (current.conversationId !== activeConversation.id) return current;
        let items = current.items;
        for (const event of timelineEvents) items = mergeLiveTimelineEvent(items, event);
        if (items === current.items) return current;
        return {
          ...current,
          items,
          firstCursor: timelineCursorFromFirst(items),
          lastCursor: timelineCursorFromLast(items),
        };
      });
    }
    if (
      events.some((event) =>
        socketEventInvalidatesSessionProjectionForScope(event, scope),
      ) &&
      sessionProjectionRefreshTimerRef.current === null
    ) {
      sessionProjectionRefreshTimerRef.current = window.setTimeout(() => {
        sessionProjectionRefreshTimerRef.current = null;
        invalidateSessionAuthority();
      }, 150);
    }
  }, [config.workspaceId, invalidateSessionAuthority, scopedConversation, socket.events]);

  useEffect(
    () => () => {
      if (sessionProjectionRefreshTimerRef.current !== null) {
        window.clearTimeout(sessionProjectionRefreshTimerRef.current);
        sessionProjectionRefreshTimerRef.current = null;
      }
    },
    [scopedConversationId],
  );

  useEffect(() => {
    const runs = authoritativeRunsFromSocketEvents(socket.events);
    if (!runs.length) return;
    setAgentConversationSession((current) => {
      if (!current) return current;
      const run = runs.find((candidate) => candidate.conversation_id === current.conversation.id);
      if (!run) return current;
      const conversation = conversationWithAuthoritativeRun(current.conversation, run);
      return conversation === current.conversation ? current : { ...current, conversation };
    });
    setDataset((current) => {
      let changed = false;
      const conversationsByWorkspace = Object.fromEntries(
        Object.entries(current.conversationsByWorkspace).map(([workspaceId, conversations]) => [
          workspaceId,
          conversations.map((conversation) => {
            const run = runs.find((candidate) => candidate.conversation_id === conversation.id);
            if (!run) return conversation;
            const updated = conversationWithAuthoritativeRun(conversation, run);
            changed ||= updated !== conversation;
            return updated;
          }),
        ]),
      );
      return changed ? { ...current, conversationsByWorkspace } : current;
    });
  }, [socket.events]);

  const showRuntimeConfig = isWorkspaceAuthenticated(auth);
  const showReviewPanel = shouldShowSessionCanvas({
    authenticated: showRuntimeConfig,
    canvasOpen: reviewPanelOpen,
    sessionSelected: Boolean(scopedConversation),
    surface:
      activeSection === 'chat'
        ? 'conversation'
        : activeSection === 'workspace'
          ? 'workspace'
          : 'other',
  });
  const runControlLabel = runControlLabels[runControlState];
  const runtimeDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before connecting.'
    : !config.apiBaseUrl.trim()
      ? 'Local runtime URL is not ready yet.'
    : !config.apiKey.trim()
      ? 'An authenticated session is required before connecting.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before connecting.'
        : null;
  const workspaceDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before loading workspaces.'
    : !config.apiKey.trim()
      ? 'An authenticated session is required before loading workspaces.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before loading workspaces.'
        : null;
  const newTaskDisabledReason = !showRuntimeConfig
    ? t('task.disabledSignIn')
    : !config.apiKey.trim()
      ? t('task.disabledAuthRequired')
      : !config.tenantId.trim() || !config.projectId.trim()
        ? t('task.disabledProjectRequired')
        : newTaskAgentTurnTransport(config.mode, socket.connected) === 'live_socket_required'
          ? t('task.liveConnectionRequired')
          : null;
  const sandboxDisabledReason = !showRuntimeConfig
    ? t('sandbox.disabled.signIn')
    : !config.apiKey.trim()
      ? t('sandbox.disabled.authRequired')
      : !config.projectId.trim()
        ? t('sandbox.disabled.projectRequired')
        : null;
  const chatDisabledReason = !showRuntimeConfig
    ? 'Sign in or enter an API key before sending messages.'
    : !config.apiKey.trim()
      ? 'An authenticated session is required before sending messages.'
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

  const resetProjectScopedState = () => {
    myWorkAbortRef.current?.abort();
    myWorkAbortRef.current = null;
    myWorkRequestRef.current += 1;
    if (myWorkRefreshTimerRef.current !== null) {
      window.clearTimeout(myWorkRefreshTimerRef.current);
      myWorkRefreshTimerRef.current = null;
    }
    setMyWorkRefreshing(false);
    setDataset(emptyDataset);
    setConnection('idle');
    setError(null);
    setLastSync('never');
    setChatInput('');
    setSelectedSidebarRunId('');
    setRunStateById({});
    setRunControlState('running');
    setRunLiveMode(true);
    setSelectedTaskId('');
    setReviewTab('overview');
    setReviewPanelOpen(true);
    setDesktop(null);
    setTerminal(null);
    setTerminalInput('');
    setMemoryResult(null);
    setAgentConversationSession(null);
    setSessionProjectionState(emptySessionProjectionState);
    setSessionDisplayProjection(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    setChangeSnapshot(null);
    setChangeSnapshotError(null);
    setRunInputReferences([]);
    setRunInputDelivery(null);
    setRunInputs([]);
    setRunInputsLoading(false);
    setRunInputsError(null);
    setPromotingRunInputId(null);
    runInputRequestRef.current = null;
    setNewWorkspaceName(DEFAULT_WORKSPACE_NAME);
    setCreatingSessionWorkspaceId(null);
    setExpandedWorkspaceIds(new Set());
    terminalProxy.clear();
  };

  const refreshRuntime = useCallback(
    async (nextConfig: DesktopRuntimeConfig = config, projectOverride?: ProjectSummary[]) => {
      const expectedContextRevision = contextRevisionRef.current;
      const expectedScopeEpoch = configScopeEpochRef.current;
      const contextIsCurrent = () =>
        isCurrentContextRevision(expectedContextRevision, contextRevisionRef.current) &&
        expectedScopeEpoch === configScopeEpochRef.current;
      setConnection('loading');
      setError(null);
      try {
        const runtimeConfig = await syncLocalRuntimeConfig(nextConfig);
        if (!contextIsCurrent()) return false;
        const availableProjects =
          projectOverride ?? resolveSidebarProjects(runtimeConfig, auth.status, auth.projects);
        const resolvedProjectId = availableProjects.some(
          (project) => project.id === runtimeConfig.projectId.trim(),
        )
          ? runtimeConfig.projectId.trim()
          : availableProjects[0]?.id ?? runtimeConfig.projectId.trim();
        const resolvedProject =
          availableProjects.find((project) => project.id === resolvedProjectId) ??
          availableProjects[0] ??
          null;
        const projects = resolvedProject ? [resolvedProject] : [];
        const loadingNodeState: RuntimeNodeLoadState = {
          projects: Object.fromEntries(
            projects.map((project) => [
              project.id,
              { loading: true, error: null },
            ]),
          ),
          workspaces: {},
        };
        if (!contextIsCurrent()) return false;
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
        if (!contextIsCurrent()) return false;
        const selectedProjectError = workspaceResults.find(
          (result) => result.project.id === resolvedProjectId,
        )?.error;
        if (selectedProjectError) {
          throw new Error(selectedProjectError);
        }

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
        const [messages, tasks, plan, myWorkResult] = await Promise.all([
          workspaceId ? scopedClient.listMessages() : Promise.resolve([]),
          workspaceId ? scopedClient.listTasks() : Promise.resolve([]),
          workspaceId ? scopedClient.getPlanSnapshot().catch(() => null) : Promise.resolve(null),
          resolvedProjectId
            ? scopedClient
                .listMyWork(resolvedProjectId)
                .then((response) => ({ items: response.items, error: null }))
                .catch((caught) => ({ items: [] as ProjectWorkItem[], error: formatError(caught) }))
            : Promise.resolve({ items: [] as ProjectWorkItem[], error: null }),
        ]);
        if (!contextIsCurrent()) return false;
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
        if (!contextIsCurrent()) return false;
        const conversationsByWorkspace = Object.fromEntries(
          conversationResults.map((result) => [result.workspaceId, result.conversations]),
        );
        const workspaceNodeState = Object.fromEntries(
          conversationResults.map((result) => [
            result.workspaceId,
            { loading: false, error: result.error },
          ]),
        );

        if (!contextIsCurrent()) return false;
        commitRuntimeConfig(resolvedConfig);
        setDataset({
          workspaces,
          workspacesByProject,
          conversationsByWorkspace,
          nodeState: { projects: projectNodeState, workspaces: workspaceNodeState },
          messages,
          tasks,
          plan,
          sandbox: null,
          myWork: myWorkResult.items,
          myWorkError: myWorkResult.error,
        });
        setExpandedWorkspaceIds(new Set(projectWorkspaces.map((workspace) => workspace.id)));
        setConnection('ready');
        setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
        return true;
      } catch (caught) {
        if (!contextIsCurrent()) return false;
        setConnection('error');
        setError(formatConnectionError(caught, nextConfig.apiBaseUrl));
        return false;
      }
    },
    [auth.projects, auth.status, commitRuntimeConfig, config, syncLocalRuntimeConfig],
  );

  const refreshMyWork = useCallback(async (scheduledScope?: MyWorkRefreshScope) => {
    const projectId = config.projectId.trim();
    if (!projectId) return;
    const expectedScope = scheduledScope ?? {
      contextRevision: contextRevisionRef.current,
      scopeEpoch: configScopeEpochRef.current,
    };
    const scopeIsCurrent = () =>
      myWorkRefreshScopeIsCurrent(expectedScope, {
        contextRevision: contextRevisionRef.current,
        scopeEpoch: configScopeEpochRef.current,
      });
    if (!scopeIsCurrent()) return;
    const requestId = myWorkRequestRef.current + 1;
    myWorkRequestRef.current = requestId;
    myWorkAbortRef.current?.abort();
    const controller = new AbortController();
    myWorkAbortRef.current = controller;
    setMyWorkRefreshing(true);
    try {
      const response = await api.listMyWork(projectId, controller.signal);
      if (
        controller.signal.aborted ||
        myWorkRequestRef.current !== requestId ||
        !scopeIsCurrent()
      ) {
        return;
      }
      setDataset((current) => ({
        ...current,
        myWork: response.items,
        myWorkError: null,
      }));
    } catch (caught) {
      if (
        controller.signal.aborted ||
        myWorkRequestRef.current !== requestId ||
        !scopeIsCurrent()
      ) {
        return;
      }
      setDataset((current) => ({
        ...current,
        myWorkError: formatError(caught),
      }));
    } finally {
      if (myWorkRequestRef.current === requestId) {
        myWorkAbortRef.current = null;
        setMyWorkRefreshing(false);
      }
    }
  }, [api, config.projectId]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, myWorkEventsHeadRef.current);
    myWorkEventsHeadRef.current = socket.events[0] ?? null;
    if (!events.some((event) => socketEventInvalidatesMyWork(event))) return;
    if (myWorkRefreshTimerRef.current !== null) {
      window.clearTimeout(myWorkRefreshTimerRef.current);
    }
    const scheduledScope: MyWorkRefreshScope = {
      contextRevision: contextRevisionRef.current,
      scopeEpoch: configScopeEpochRef.current,
    };
    myWorkRefreshTimerRef.current = window.setTimeout(() => {
      myWorkRefreshTimerRef.current = null;
      void refreshMyWork(scheduledScope);
    }, 180);
  }, [refreshMyWork, socket.events]);

  useEffect(
    () => () => {
      myWorkAbortRef.current?.abort();
      if (myWorkRefreshTimerRef.current !== null) {
        window.clearTimeout(myWorkRefreshTimerRef.current);
        myWorkRefreshTimerRef.current = null;
      }
    },
    [refreshMyWork],
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
      const [user, tenants, authoritativeContext] = await Promise.all([
        identityClient.currentUser(),
        identityClient.listTenants(),
        identityClient
          .getWorkspaceContext()
          .then((response) => response.context)
          .catch((caught) => {
            if (isLegacyWorkspaceContextRouteMissing(caught)) return null;
            throw caught;
          }),
      ]);
      const preferredTenantId =
        authoritativeContext?.tenant_id ?? outcome.context?.tenant_id ?? tenants[0]?.id ?? '';
      const projectClient = new DesktopApiClient({ ...tokenConfig, tenantId: preferredTenantId });
      const projects = await projectClient.listProjects(preferredTenantId || undefined);
      const tenantId = preferredTenantId || projects[0]?.tenant_id || '';
      const preferredProjectId =
        authoritativeContext?.project_id ?? outcome.context?.project_id ?? '';
      const projectId = projects.some((project) => project.id === preferredProjectId)
        ? preferredProjectId
        : projects[0]?.id ?? '';
      if (authoritativeContext && authoritativeContext.project_id !== projectId) {
        throw new Error('The authoritative workspace project is no longer available.');
      }
      const context = authoritativeContext
        ? authoritativeContext
        : outcome.context?.tenant_id === tenantId && outcome.context.project_id === projectId
          ? outcome.context
          : {
              tenant_id: tenantId,
              project_id: projectId,
              revision: 0,
              updated_at: new Date().toISOString(),
            };
      const nextConfig = { ...tokenConfig, tenantId, projectId, workspaceId: '' };

      contextRevisionRef.current = context.revision;
      resetProjectScopedState();
      commitRuntimeConfig(nextConfig);
      setAuth({
        status: 'signed_in',
        credentialKind: 'cloud_session',
        session: outcome.session ?? null,
        context,
        user,
        tenants,
        projects,
        mustChangePassword: outcome.must_change_password,
        error: null,
      });
      setLoginPassword('');

      if (projectId) {
        await refreshRuntime(nextConfig, projects);
        applySectionSideEffects('workspace');
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

  const hydrateLocalSession = async (
    outcome: LoginOutcome,
    runtimeConfig: DesktopRuntimeConfig,
  ) => {
    if (!outcome.context) {
      throw new Error('The local session did not return an authoritative workspace context.');
    }
    const tokenConfig = {
      ...runtimeConfig,
      apiKey: outcome.access_token,
      tenantId: outcome.context.tenant_id,
      projectId: outcome.context.project_id,
      workspaceId: '',
    };
    const identityClient = new DesktopApiClient(tokenConfig);
    const [user, tenants, projects] = await Promise.all([
      identityClient.currentUser(),
      identityClient.listTenants(),
      identityClient.listProjects(outcome.context.tenant_id),
    ]);
    const selectedProject = projects.find((project) => project.id === outcome.context?.project_id);
    if (!selectedProject) {
      throw new Error('The active local project is not available to this user.');
    }

    contextRevisionRef.current = outcome.context.revision;
    resetProjectScopedState();
    commitRuntimeConfig(tokenConfig);
    setAuth({
      status: 'signed_in',
      credentialKind: 'local_session',
      session: outcome.session ?? null,
      context: outcome.context,
      user,
      tenants,
      projects,
      mustChangePassword: false,
      error: null,
    });
    await refreshRuntime(tokenConfig, [selectedProject]);
  };

  const loginLocalSession = async (trustedDevice: boolean) => {
    if (!localRuntimeMode || !config.localApiToken.trim()) {
      setAuth((current) => ({
        ...current,
        error: 'The trusted local runtime is not ready yet.',
      }));
      return;
    }

    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    try {
      if (!trustedDevice) clearTrustedLocalSessionReference(window.localStorage);
      const bootstrapClient = new DesktopApiClient({ ...config, apiKey: '' });
      const outcome = await bootstrapClient.createLocalSession(trustedDevice);
      await hydrateLocalSession(outcome, config);
      writeTrustedLocalSessionReference(window.localStorage, outcome.session);
      applySectionSideEffects('workspace');
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
    const requestScopeChanged = !isSameDesktopRequestScope(configRef.current, resolvedConfig);
    commitRuntimeConfig(resolvedConfig);
    if (requestScopeChanged) {
      resetProjectScopedState();
      return;
    }
    setConnection('idle');
    setAgentConversationSession(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
  };

  const useApiKeyManually = () => {
    setLoginModalOpen(false);
    setAuth((current) => ({
      ...current,
      error: 'Manual API keys must be validated by the server before opening a workspace.',
    }));
  };

  const logout = async () => {
    const authenticatedClient = api;
    const shouldRevoke = Boolean(config.apiKey.trim());
    if (auth.credentialKind === 'local_session') {
      clearTrustedLocalSessionReference(window.localStorage);
    }
    contextRevisionRef.current += 1;
    setAuth(emptyAuthState);
    setLoginModalOpen(false);
    commitRuntimeConfig({
      ...DEFAULT_CONFIG,
      apiBaseUrl: config.apiBaseUrl,
      localApiToken: config.localApiToken,
      mode: config.mode,
      llmProvider: config.llmProvider,
      llmBaseUrl: config.llmBaseUrl,
      llmModel: config.llmModel,
      llmApiKey: config.llmApiKey,
      workspaceRoot: config.workspaceRoot,
    });
    resetProjectScopedState();
    setSectionBackStack([]);
    setSectionForwardStack([]);
    activeSectionRef.current = 'workspace';
    setActiveSection('workspace');
    setStatusTab('overview');
    if (shouldRevoke) {
      try {
        await authenticatedClient.signOut();
      } catch {
        // The local UI is signed out even if the runtime is already unavailable.
      }
    }
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
    commitRuntimeConfig(nextConfig);
    setAgentConversationSession(null);
    setConversationTimeline(emptyConversationTimeline);
    setAgentTaskSignals([]);
    setReviewTab('overview');
    setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
    applySectionSideEffects('workspace');
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
    commitRuntimeConfig(nextConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(projectId, workspaceId),
      conversation,
    });
    setAgentTaskSignals([]);
    setReviewTab('overview');
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
      commitRuntimeConfig(nextConfig);
      setAgentConversationSession(null);
      setConversationTimeline(emptyConversationTimeline);
      setAgentTaskSignals([]);
      setNewWorkspaceName(DEFAULT_WORKSPACE_NAME);
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
      commitRuntimeConfig(nextConfig);
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

  const openNewTask = (workspaceId = config.workspaceId) => {
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
    setNewTaskPreferredWorkspaceId(workspaceId);
    setNewTaskOpen(true);
  };

  const startNewSession = () => openNewTask();

  const adoptNewTaskSession = (session: NewTaskSession) => {
    const { workspace, conversation, config: sessionConfig } = session;
    commitRuntimeConfig(sessionConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(sessionConfig.projectId, workspace.id),
      conversation,
    });
    setDataset((current) => ({
      ...current,
      workspaces: [workspace, ...current.workspaces.filter((item) => item.id !== workspace.id)],
      workspacesByProject: {
        ...current.workspacesByProject,
        [sessionConfig.projectId]: [
          workspace,
          ...(current.workspacesByProject[sessionConfig.projectId] ?? []).filter(
            (item) => item.id !== workspace.id,
          ),
        ],
      },
      conversationsByWorkspace: {
        ...current.conversationsByWorkspace,
        [workspace.id]: [
          conversation,
          ...(current.conversationsByWorkspace[workspace.id] ?? []).filter(
            (item) => item.id !== conversation.id,
          ),
        ],
      },
    }));
    setExpandedWorkspaceIds((current) => new Set([...current, workspace.id]));
    socket.subscribeConversation(conversation.id);
    applySectionSideEffects('chat');
    void loadConversationTimeline(conversation, sessionConfig.projectId);
    void refreshRuntime(sessionConfig);
  };

  const runNewTaskAgentTurn = async (input: NewTaskAgentTurnInput) => {
    const queued = socket.sendAgentMessage({
      conversationId: input.conversationId,
      projectId: input.projectId,
      message: input.message,
      messageId: input.messageId,
    });
    const transport = newTaskAgentTurnTransport(input.config.mode, queued);
    if (transport === 'socket') {
      await new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          pendingNewTaskAgentTurnsRef.current.delete(input.messageId);
          reject(new Error(t('task.agentTurnAckTimeout')));
        }, 10_000);
        pendingNewTaskAgentTurnsRef.current.set(input.messageId, {
          conversationId: input.conversationId,
          messageId: input.messageId,
          timeoutId,
          resolve,
          reject,
        });
      });
      return;
    }
    if (transport === 'local_http') {
      const client = new DesktopApiClient(input.config);
      await client.runAgentMessage(
        input.conversationId,
        input.message,
        input.messageId,
        input.projectId,
      );
      return;
    }
    throw new Error(t('task.liveConnectionRequired'));
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
    const canSendConversationMessage = Boolean(
      sessionProjection?.capabilities.canSendMessage &&
        sessionProjection.capabilities.allowedActions.includes('send_message'),
    );
    const canSendRunInput = Boolean(
      localRuntimeMode &&
        currentArtifactRun &&
        selectedConversation?.id === currentArtifactRun.conversation_id &&
        effectiveRunInputDeliveryValue,
    );
    if (selectedConversation && !canSendConversationMessage && !canSendRunInput) {
      setError(t('session.authorityActionUnavailable'));
      return;
    }
    if (sessionChatDisabledReason) {
      setError(sessionChatDisabledReason);
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
      const sendsRunInput = Boolean(
        canSendRunInput && currentArtifactRun && effectiveRunInputDeliveryValue,
      );
      if (sendsRunInput && currentArtifactRun && effectiveRunInputDeliveryValue) {
        const signature = JSON.stringify({
          runId: currentArtifactRun.id,
          revision: currentArtifactRun.revision,
          delivery: effectiveRunInputDeliveryValue,
          content,
          references: runInputReferences,
        });
        if (runInputRequestRef.current?.signature !== signature) {
          const requestId =
            globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          runInputRequestRef.current = {
            signature,
            messageId: `desktop-run-input-${requestId}`,
            idempotencyKey: `desktop-run-input:${currentArtifactRun.id}:${requestId}`,
          };
        }
        const request = runInputRequestRef.current;
        const acknowledgement = await api.createRunInput(currentArtifactRun.id, {
          expectedRunRevision: currentArtifactRun.revision,
          message: content,
          messageId: request.messageId,
          idempotencyKey: request.idempotencyKey,
          delivery: effectiveRunInputDeliveryValue,
          references: runInputReferences,
        });
        onWorkspaceMessageSaved?.();
        setRunInputReferences([]);
        setRunInputs((current) =>
          [...current.filter((input) => input.id !== acknowledgement.input.id), acknowledgement.input]
            .sort((left, right) => left.sequence - right.sequence),
        );
        runInputRequestRef.current = null;
        upsertAgentTaskSignal({
          id: signalId,
          conversationId: acknowledgement.conversation_id,
          messageId: acknowledgement.message_id,
          status: 'acknowledged',
          detail:
            acknowledgement.delivery_mode === 'steer_now'
              ? t('session.steeringAccepted')
              : t('session.queueAccepted', {
                  position: acknowledgement.queue_position ?? '—',
                }),
        });
        invalidateSessionAuthority();
        if (selectedConversation) {
          await loadConversationTimeline(selectedConversation, config.projectId);
        }
        return;
      }
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
            invalidateSessionAuthority();
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
      const sourceRun = currentArtifactRunRef.current;
      if (!sourceRun) {
        throw new Error(t('session.terminalRequiresActiveRun'));
      }
      const requestGeneration = terminalStartGenerationRef.current + 1;
      terminalStartGenerationRef.current = requestGeneration;
      await api.seedProxyAuthCookie();
      const response = await api.startTerminal(
        sourceRun.id,
        sourceRun.revision,
      );
      if (terminalStartGenerationRef.current !== requestGeneration) return;
      if (!terminalSessionMatchesRun(response, currentArtifactRunRef.current)) {
        throw new Error(t('session.terminalAuthorityMismatch'));
      }
      terminalProxy.clear();
      setTerminalInput('');
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
    if (terminalProxy.sendInput(`${input}\n`)) setTerminalInput('');
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
  const paneStageClassName =
    activeSection === 'board' ? 'pane-stage single-stage my-work-stage' : 'pane-stage single-stage';
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
  const myWorkWorkspaceLabels = useMemo(
    () =>
      Object.fromEntries(
        (dataset.workspacesByProject[config.projectId] ?? []).map((workspace) => [
          workspace.id,
          workspaceLabel(workspace),
        ]),
      ),
    [config.projectId, dataset.workspacesByProject],
  );
  const selectedConversation = scopedConversation;
  const sessionDetailViewModel = useMemo(
    () =>
      selectedConversation
        ? buildSessionDetailViewModel({
            conversation: selectedConversation,
            workspace: selectedWorkspace,
            timeline: conversationTimeline,
            projection: displaySessionProjection,
            authorityAvailable: sessionProjection !== null,
          })
        : null,
    [
      conversationTimeline,
      selectedConversation,
      selectedWorkspace,
      displaySessionProjection,
      sessionProjection,
    ],
  );
  const currentArtifactRun = sessionProjection?.currentRun ?? null;
  const sessionInspectorEvidence = useMemo(() => {
    const evidence = displaySessionProjection?.evidenceSummary;
    return {
      artifacts: evidence?.artifactVersionCount ?? null,
      changedFiles: changeSnapshot?.status === 'ready' ? changeSnapshot.files_changed : null,
      checks: evidence?.checks?.total ?? null,
    };
  }, [changeSnapshot, displaySessionProjection?.evidenceSummary]);
  currentArtifactRunRef.current = currentArtifactRun;
  const currentTerminalRunScopeKey = terminalRunScopeKey(currentArtifactRun);
  if (terminalRunScopeKeyRef.current !== currentTerminalRunScopeKey) {
    terminalRunScopeKeyRef.current = currentTerminalRunScopeKey;
    terminalStartGenerationRef.current += 1;
  }
  const terminalMatchesCurrentRun = terminalSessionMatchesRun(terminal, currentArtifactRun);
  const terminalUrl = useMemo(() => {
    if (!terminalMatchesCurrentRun || !terminal?.session_id) return null;
    try {
      return api.terminalProxyUrl(terminal.session_id, terminal.project_id);
    } catch {
      return null;
    }
  }, [api, terminal?.project_id, terminal?.session_id, terminalMatchesCurrentRun]);
  const terminalProxy = useTerminalProxy(
    terminalUrl,
    desktopApiCredential(config),
    desktopLaunchCapability(config),
  );
  const terminalBinding = useMemo(
    () => terminalBindingState(terminal, currentArtifactRun, terminalProxy.status),
    [currentArtifactRun, terminal, terminalProxy.status],
  );
  const runInputDeliveryOptions = useMemo(
    () => {
      if (!localRuntimeMode || sessionDetailViewModel?.capabilityMode !== 'code') return [];
      const options: RunInputDelivery[] = [];
      if (
        sessionProjection?.capabilities.canSteerNow &&
        sessionProjection.capabilities.allowedActions.includes('steer_now')
      ) {
        options.push('steer_now');
      }
      if (
        sessionProjection?.capabilities.canQueueNext &&
        sessionProjection.capabilities.allowedActions.includes('queue_next')
      ) {
        options.push('queue_next');
      }
      return options;
    },
    [localRuntimeMode, sessionDetailViewModel?.capabilityMode, sessionProjection?.capabilities],
  );
  const effectiveRunInputDeliveryValue = effectiveRunInputDelivery(
    runInputDelivery,
    runInputDeliveryOptions,
  );
  const sessionChatDisabledReason =
    chatDisabledReason ??
    (selectedConversation
      ? sessionProjectionState.status === 'idle' || sessionProjectionState.status === 'loading'
        ? t('session.authorityLoading')
        : sessionProjectionState.status === 'error'
          ? t('session.authorityError')
          : !(
                sessionProjection?.capabilities.canSendMessage &&
                sessionProjection.capabilities.allowedActions.includes('send_message')
              ) && !runInputDeliveryOptions.length
            ? t('session.composerBlockedByRunState')
            : null
      : null);
  const sessionAuthorityNotice = useMemo(() => {
    if (!selectedConversation || sessionProjectionState.status === 'ready') return null;
    if (
      sessionProjectionState.status === 'idle' ||
      sessionProjectionState.status === 'loading'
    ) {
      return {
        tone: 'loading' as const,
        title: t('session.authorityLoading'),
        description: t('session.authorityLoadingDescription'),
      };
    }
    return {
      tone: 'error' as const,
      title: t('session.authorityError'),
      description: t('session.authorityErrorDescription'),
      actionLabel: t('session.authorityRetry'),
    };
  }, [selectedConversation, sessionProjectionState.status, t]);
  const loadRunChanges = useCallback(async () => {
    if (!currentArtifactRun || sessionDetailViewModel?.capabilityMode !== 'code') {
      setChangeSnapshot(null);
      setChangeSnapshotError(null);
      setChangeSnapshotLoading(false);
      return;
    }
    setChangeSnapshotLoading(true);
    setChangeSnapshotError(null);
    try {
      const snapshot = await api.getRunChanges(currentArtifactRun.id, currentArtifactRun.revision);
      setChangeSnapshot(snapshot);
      setRunInputReferences((current) =>
        current.filter(
          (reference) =>
            reference.snapshot_id === snapshot.id &&
            reference.environment_id === snapshot.environment_id,
        ),
      );
    } catch (caught) {
      setChangeSnapshotError(formatConnectionError(caught, config.apiBaseUrl));
    } finally {
      setChangeSnapshotLoading(false);
    }
  }, [api, config.apiBaseUrl, currentArtifactRun, sessionDetailViewModel?.capabilityMode]);
  useEffect(() => {
    void loadRunChanges();
  }, [loadRunChanges]);
  useEffect(() => {
    setTerminalInput('');
  }, [currentTerminalRunScopeKey]);
  useEffect(() => {
    let active = true;
    if (!localRuntimeMode || !currentArtifactRun) {
      setRunInputs([]);
      setRunInputsLoading(false);
      setRunInputsError(null);
      return () => {
        active = false;
      };
    }
    setRunInputsLoading(true);
    setRunInputsError(null);
    void api
      .listRunInputs(currentArtifactRun.id)
      .then((response) => {
        if (active) setRunInputs(response.inputs);
      })
      .catch((caught) => {
        if (active) setRunInputsError(formatConnectionError(caught, config.apiBaseUrl));
      })
      .finally(() => {
        if (active) setRunInputsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, config.apiBaseUrl, currentArtifactRun, localRuntimeMode]);
  useEffect(() => {
    setRunInputDelivery((current) =>
      current && runInputDeliveryOptions.includes(current)
        ? current
        : (runInputDeliveryOptions[0] ?? null),
    );
  }, [runInputDeliveryOptions]);
  useEffect(() => {
    if (
      snapshotMatchesRun(
        changeSnapshot,
        currentArtifactRun?.id,
        currentArtifactRun?.revision,
      )
    ) {
      return;
    }
    setRunInputReferences([]);
    runInputRequestRef.current = null;
  }, [changeSnapshot, currentArtifactRun?.id, currentArtifactRun?.revision]);
  const promoteQueuedRunInput = useCallback(
    async (input: DesktopRunInput) => {
      if (!currentArtifactRun || currentArtifactRun.id !== input.run_id) {
        setError(t('session.queueSourceRunUnavailable'));
        return;
      }
      setPromotingRunInputId(input.id);
      setError(null);
      try {
        const outcome = await api.promoteRunInput(
          input.id,
          currentArtifactRun.revision,
          `desktop-run-input-promotion:${input.id}`,
        );
        invalidateSessionAuthority();
        setRunInputs((current) =>
          current.map((candidate) =>
            candidate.id === outcome.input.id ? outcome.input : candidate,
          ),
        );
        setAgentConversationSession((current) =>
          current?.conversation.id === outcome.conversation.id
            ? { ...current, conversation: outcome.conversation }
            : current,
        );
        setDataset((current) => ({
          ...current,
          conversationsByWorkspace: Object.fromEntries(
            Object.entries(current.conversationsByWorkspace).map(
              ([workspaceId, conversations]) => [
                workspaceId,
                conversations.map((conversation) =>
                  conversation.id === outcome.conversation.id
                    ? outcome.conversation
                    : conversation,
                ),
              ],
            ),
          ),
        }));
        setReviewTab('plan');
        await loadConversationTimeline(outcome.conversation, config.projectId);
      } catch (caught) {
        setError(formatConnectionError(caught, config.apiBaseUrl));
      } finally {
        setPromotingRunInputId(null);
      }
    },
    [
      api,
      config.apiBaseUrl,
      config.projectId,
      currentArtifactRun,
      invalidateSessionAuthority,
      loadConversationTimeline,
      t,
    ],
  );
  const titlebarRunState = sessionDetailViewModel
    ? titlebarRunStateFromStatus(sessionDetailViewModel.status)
    : runControlState;
  const titlebarRunLabel = sessionDetailViewModel
    ? titlebarRunLabelFromStatus(sessionDetailViewModel.status, t)
    : runControlLabel;
  const applyAuthoritativeRun = useCallback((run: DesktopRun) => {
    setAgentConversationSession((current) => {
      if (!current || current.conversation.id !== run.conversation_id) return current;
      const conversation = conversationWithAuthoritativeRun(current.conversation, run);
      return conversation === current.conversation ? current : { ...current, conversation };
    });
    setDataset((current) => {
      let changed = false;
      const conversationsByWorkspace = Object.fromEntries(
        Object.entries(current.conversationsByWorkspace).map(([workspaceId, conversations]) => [
          workspaceId,
          conversations.map((conversation) => {
            if (conversation.id !== run.conversation_id) return conversation;
            const updated = conversationWithAuthoritativeRun(conversation, run);
            changed ||= updated !== conversation;
            return updated;
          }),
        ]),
      );
      return changed ? { ...current, conversationsByWorkspace } : current;
    });
  }, []);
  const handleSessionRunAction = useCallback(
    async (action: SessionRunAction, feedback?: string) => {
      const runId = sessionDetailViewModel?.runId;
      const revision = sessionDetailViewModel?.runRevision;
      if (!runId || revision === null || revision === undefined) {
        setError(t('session.runControlUnavailable'));
        return;
      }
      if (!sessionDetailViewModel.runActions.includes(action)) {
        setError(t('session.authorityActionUnavailable'));
        return;
      }
      setSessionRunActionPending(action);
      setError(null);
      try {
        const outcome =
          action === 'pause'
            ? await api.pauseRun(runId, revision)
            : action === 'resume' || action === 'reconnect'
              ? await api.resumeRun(runId, revision)
              : action === 'fork'
                ? await api.forkRecoveryRun(
                    runId,
                    revision,
                    `desktop-recovery-fork:${runId}:${revision}`,
                  )
              : action === 'cancel'
                ? await api.cancelRun(runId, revision)
                : await api.reviewRun(runId, {
                    action: action === 'approve' ? 'approve' : 'request_changes',
                    expectedRevision: revision,
                    ...(feedback ? { feedback } : {}),
                  });
        applyAuthoritativeRun(outcome.run);
        invalidateSessionAuthority();
      } catch (caught) {
        setError(formatError(caught));
      } finally {
        setSessionRunActionPending(null);
      }
    },
    [api, applyAuthoritativeRun, invalidateSessionAuthority, sessionDetailViewModel, t],
  );
  const handleArtifactAction = useCallback(
    async (
      version: DesktopArtifactVersion,
      action: ArtifactVersionAction,
      feedback?: string,
    ) => {
      const capabilities = sessionProjection?.capabilities;
      const authoritativeVersion = selectedConversation
        ? sessionProjection?.artifactVersions.find((candidate) => candidate.id === version.id)
        : version;
      const actionAllowed =
        Boolean(authoritativeVersion) &&
        authoritativeVersion?.revision === version.revision &&
        artifactVersionActions(authoritativeVersion, currentArtifactRun).includes(action) &&
        (!selectedConversation ||
          (action === 'deliver'
            ? Boolean(
                capabilities?.canDeliverArtifacts &&
                  capabilities.allowedActions.includes('deliver_artifact'),
              )
            : Boolean(
                capabilities?.canReviewArtifacts &&
                  capabilities.allowedActions.includes('review_artifact'),
              )));
      if (!actionAllowed || !authoritativeVersion) {
        setError(t('session.authorityActionUnavailable'));
        return;
      }
      setArtifactActionPending({ versionId: authoritativeVersion.id, action });
      setError(null);
      try {
        if (action === 'deliver') {
          const outcome = await api.deliverArtifactVersion(
            authoritativeVersion.id,
            artifactDeliveryRequest(authoritativeVersion),
          );
          if (!outcome.accepted) throw new Error(t('session.authorityActionUnavailable'));
        } else {
          const outcome = await api.reviewArtifactVersion(
            authoritativeVersion.id,
            artifactReviewRequest(authoritativeVersion, action, currentArtifactRun, feedback),
          );
          if (outcome.run) applyAuthoritativeRun(outcome.run);
        }
        invalidateSessionAuthority();
      } catch (caught) {
        setError(formatConnectionError(caught, config.apiBaseUrl));
      } finally {
        setArtifactActionPending(null);
      }
    },
    [
      api,
      applyAuthoritativeRun,
      config.apiBaseUrl,
      currentArtifactRun,
      invalidateSessionAuthority,
      selectedConversation,
      sessionProjection?.capabilities,
      t,
    ],
  );
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
  const runtimeMonitorHealthMetrics = [
    {
      label: 'Provider',
      value: localRuntimeMode
        ? localRuntimeStatus?.config.provider || config.llmProvider || 'not configured'
        : config.mode,
    },
    {
      label: 'Model',
      value: localRuntimeMode
        ? localRuntimeStatus?.config.model || config.llmModel || 'not configured'
        : 'server managed',
    },
    {
      label: 'Tools',
      value: localRuntimeMode ? String(localRuntimeStatus?.tool_count ?? 'unavailable') : 'server',
    },
    {
      label: 'Root',
      value: localRuntimeMode
        ? localRuntimeStatus?.workspace_root || config.workspaceRoot || 'not configured'
        : config.projectId || 'not selected',
    },
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
    const seen = new Set<string>();
    return dataRunItems
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
    showRuntimeConfig && activeSection === 'board'
      ? t('myWork.title')
      : showRuntimeConfig && activeSection === 'automations'
        ? t('automations.title')
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
    { id: 'home', section: 'workspace', label: t('nav.home'), icon: <DashboardIcon key="home" /> },
    { id: 'my-work', section: 'board', label: t('nav.myWork'), icon: <GridIcon key="my-work" /> },
    {
      id: 'automations',
      section: 'automations',
      label: t('nav.automations'),
      icon: <ActivityLogIcon key="automations" />,
    },
    { id: 'search', section: 'memory', label: t('nav.search'), icon: <MagnifyingGlassIcon key="search" /> },
    {
      id: 'projects',
      section: 'settings',
      settingsSection: 'workspace',
      label: t('nav.projects'),
      icon: <ArchiveIcon key="projects" />,
    },
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

  const toggleWorkspace = (workspaceId: string) => {
    setExpandedWorkspaceIds((current) => {
      const next = new Set(current);
      if (next.has(workspaceId)) next.delete(workspaceId);
      else next.add(workspaceId);
      return next;
    });
  };

  function isQuickLinkSelected(item: QuickLinkItem): boolean {
    if (item.settingsSection) return settingsWindowOpen && settingsInitialSection === item.settingsSection;
    if (item.target === 'background' || item.target === 'artifacts') {
      return (
        activeSection === 'workspace' && reviewTab === item.target
      );
    }
    return activeSection === item.section;
  }

  function selectQuickLink(item: QuickLinkItem) {
    if (item.settingsSection) {
      setSettingsInitialSection(item.settingsSection);
      setSettingsWindowOpen(true);
      return;
    }
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
      switchSection('workspace');
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

  const applySectionSideEffects = (section: WorkbenchSection) => {
    activeSectionRef.current = section;
    setActiveSection(section);
    if (section === 'sandbox' || section === 'terminal') setStatusTab('sandbox');
    if (section === 'memory') setStatusTab('memory');
    if (section === 'status') setStatusTab('overview');
    if (section === 'terminal') setReviewTab('terminal');
    if (section === 'board') {
      setReviewTab('changes');
      setReviewPanelOpen(false);
    }
    if (section === 'status') setReviewTab('plan');
  };

  useEffect(() => {
    if (!localRuntimeMode || auth.status !== 'signed_out' || !config.localApiToken.trim()) return;
    const reference = readTrustedLocalSessionReference(window.localStorage);
    if (!reference) return;
    const attemptKey = `${config.apiBaseUrl}|${config.localApiToken}|${reference.sessionId}`;
    if (localResumeAttemptRef.current === attemptKey) return;
    localResumeAttemptRef.current = attemptKey;

    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    void (async () => {
      try {
        const bootstrapClient = new DesktopApiClient({ ...config, apiKey: '' });
        const outcome = await bootstrapClient.resumeLocalSession(reference.sessionId);
        if (localResumeAttemptRef.current !== attemptKey) return;
        if (!outcome) {
          clearTrustedLocalSessionReference(window.localStorage);
          setAuth(emptyAuthState);
          setConnection('idle');
          return;
        }
        writeTrustedLocalSessionReference(window.localStorage, outcome.session);
        await hydrateLocalSession(outcome, config);
        applySectionSideEffects('workspace');
      } catch (caught) {
        if (localResumeAttemptRef.current !== attemptKey) return;
        const message = formatLoginError(caught, config.apiBaseUrl);
        setAuth({ ...emptyAuthState, error: message });
        setConnection('error');
        setError(message);
      }
    })();
  }, [
    auth.status,
    config.apiBaseUrl,
    config.localApiToken,
    config.mode,
    localRuntimeMode,
  ]);

  const switchSection = (section: WorkbenchSection) => {
    if (section === 'settings') {
      setSettingsWindowOpen(true);
      return;
    }
    const currentSection = activeSectionRef.current;
    if (section !== currentSection) {
      setSectionBackStack([...sectionBackStack, currentSection].slice(-24));
      setSectionForwardStack([]);
    }
    applySectionSideEffects(section);
  };

  const openSettingsEntry = (entry: SettingsEntry) => {
    setSettingsInitialSection(settingsSectionForEntry(entry));
    setSettingsWindowOpen(true);
  };

  const openSidebarSettings = () => openSettingsEntry('sidebar');
  const openWorkspaceSettings = () => openSettingsEntry('workspace_overview');

  const openConnectionSettings = () => {
    if (!showRuntimeConfig) {
      useApiKeyManually();
    }
    openSettingsEntry('runtime_connection');
  };

  const applySettingsContext = async (tenantId: string, projectId: string) => {
    if (!auth.context) {
      throw new Error('An authenticated workspace context is required.');
    }
    const contextClient = new DesktopApiClient({
      ...config,
      tenantId,
      projectId: '',
      workspaceId: '',
    });
    const projects = await contextClient.listProjects(tenantId);
    const selectedProject = projects.find((project) => project.id === projectId);
    if (!selectedProject) {
      throw new Error('The selected project is not available for this tenant.');
    }

    let nextContext: WorkspaceContextSnapshot;
    try {
      nextContext = (
        await api.switchWorkspaceContext(
          tenantId,
          projectId,
          auth.context.revision,
          globalThis.crypto.randomUUID(),
        )
      ).context;
    } catch (caught) {
      if (
        auth.credentialKind !== 'cloud_session' ||
        !isLegacyWorkspaceContextRouteMissing(caught)
      ) {
        throw caught;
      }
      nextContext = nextRemoteWorkspaceContext(
        auth.context,
        tenantId,
        projectId,
        new Date().toISOString(),
      );
    }
    const nextConfig = { ...config, tenantId, projectId, workspaceId: '' };
    contextRevisionRef.current = nextContext.revision;
    resetProjectScopedState();
    commitRuntimeConfig(nextConfig);
    setAuth((current) => ({ ...current, context: nextContext, projects }));
    applySectionSideEffects('workspace');
    const applied = await refreshRuntime(nextConfig, [selectedProject]);
    if (!applied) {
      throw new Error(
        'The context was switched, but the selected project could not be loaded. Refresh to retry.',
      );
    }
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
      label: t('myWork.title'),
      description: t('myWork.commandDescription'),
      icon: <GridIcon />,
      onSelect: () => switchSection('board'),
    },
    {
      id: 'automations',
      label: t('automations.title'),
      description: t('automations.commandDescription'),
      icon: <ActivityLogIcon />,
      onSelect: () => switchSection('automations'),
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
      timelineState={selectedConversation ? sessionTimeline : null}
      agentTaskSignals={agentTaskSignals}
      workflowCounts={chatWorkflowCounts}
      sessionTitle={selectedConversation?.title ?? workspaceLabel(selectedWorkspace ?? undefined)}
      scopeLabel={
        selectedConversation
          ? `Agent session / ${workspaceLabel(selectedWorkspace ?? undefined)}`
          : 'Workspace conversation'
      }
      composerVariant={selectedConversation ? 'session' : 'workspace'}
      input={chatInput}
      sending={sending}
      disabledReason={sessionChatDisabledReason}
      activeWorkflowTarget={chatWorkflowTargetForReviewTab(reviewTab)}
      modelLabel={config.llmModel.trim() || undefined}
      runtimeTargetLabel={runtimeTargetLabels[runtimeTarget]}
      runtimeTargetOptions={runtimeTargetComposerOptions}
      runInputDelivery={effectiveRunInputDeliveryValue}
      runInputDeliveryOptions={runInputDeliveryOptions}
      runInputs={runInputs}
      runInputsLoading={runInputsLoading}
      runInputsError={runInputsError}
      promotingRunInputId={promotingRunInputId}
      runInputAuthorityRunId={currentArtifactRun?.id ?? null}
      references={runInputReferences}
      onInputChange={setChatInput}
      onRunInputDeliveryChange={setRunInputDelivery}
      onPromoteRunInput={(input) => void promoteQueuedRunInput(input)}
      onRemoveReference={(reference) =>
        setRunInputReferences((current) => toggleRunInputReference(current, reference))
      }
      onSend={() => void sendMessage()}
      onRefresh={() => {
        if (selectedConversation) {
          void loadConversationTimeline(selectedConversation, config.projectId);
          invalidateSessionAuthority();
          return;
        }
        void refreshRuntime();
      }}
      onLoadEarlier={() => void loadEarlierTimeline()}
      onRespondToHitl={respondToHitl}
      respondableHitlRequestIds={respondableHitlRequestIds}
      authorityNotice={sessionAuthorityNotice}
      onAuthorityAction={
        sessionProjectionState.status === 'error' ? invalidateSessionAuthority : undefined
      }
      onWorkflowSelect={selectChatWorkflowTarget}
      onRuntimeTargetChange={(value) =>
        setRuntimeTarget(value === runtimeTargetLabels.staging ? 'staging' : 'local')
      }
      onOpenCommands={openCommandPalette}
    />
  );

  const renderWorkspaceOverview = () => {
    return (
      <WorkspaceOverview
        workspace={selectedWorkspace}
        project={selectedProject}
        tenantName={
          auth.tenants.find((tenant) => tenant.id === config.tenantId)?.name ??
          config.tenantId ??
          t('overview.none')
        }
        conversations={dataset.conversationsByWorkspace[config.workspaceId] ?? []}
        plan={activeDataset.plan}
        sandboxStatus={dataset.sandbox?.status ?? null}
        connection={connection}
        onNewTask={() => openNewTask(config.workspaceId)}
        onOpenConversation={(conversationId) => {
          const conversation = (dataset.conversationsByWorkspace[config.workspaceId] ?? []).find(
            (item) => item.id === conversationId,
          );
          if (!conversation) {
            setError(t('myWork.sessionUnavailable'));
            return;
          }
          selectConversation(config.projectId, config.workspaceId, conversation, 'chat');
        }}
        onOpenSettings={openWorkspaceSettings}
      />
    );
  };

  const openMyWorkSession = async (item: ProjectWorkItem) => {
    const workspaceId = item.workspace_id ?? '';
    const expectedContextRevision = contextRevisionRef.current;
    const expectedScopeEpoch = configScopeEpochRef.current;
    let conversation = (dataset.conversationsByWorkspace[workspaceId] ?? []).find(
      (candidate) => candidate.id === item.conversation_id,
    );
    if (!workspaceId || item.project_id !== config.projectId) {
      setError(t('myWork.sessionUnavailable'));
      return;
    }
    if (!conversation) {
      try {
        const response = await api.listConversations(item.project_id, workspaceId);
        conversation = response.items.find((candidate) => candidate.id === item.conversation_id);
      } catch (caught) {
        if (
          !isCurrentContextRevision(expectedContextRevision, contextRevisionRef.current) ||
          expectedScopeEpoch !== configScopeEpochRef.current
        ) {
          return;
        }
        setError(formatError(caught));
        return;
      }
    }
    if (
      !isCurrentContextRevision(expectedContextRevision, contextRevisionRef.current) ||
      expectedScopeEpoch !== configScopeEpochRef.current
    ) {
      return;
    }
    if (
      !conversation ||
      !myWorkConversationMatchesScope(item, conversation, {
        tenantId: config.tenantId,
        projectId: config.projectId,
      })
    ) {
      setError(t('myWork.sessionUnavailable'));
      return;
    }
    selectConversation(item.project_id, workspaceId, conversation, 'chat');
  };

  const renderBoardPanel = () => (
    <MyWorkQueue
      items={dataset.myWork}
      error={dataset.myWorkError}
      loading={connection === 'loading' || myWorkRefreshing}
      mode={preferredTaskMode}
      projectName={selectedProject?.name ?? selectedProject?.id ?? t('overview.none')}
      workspaceLabels={myWorkWorkspaceLabels}
      onRefresh={() => void refreshMyWork()}
      onOpenSession={(item) => void openMyWorkSession(item)}
    />
  );

  const renderAutomationsPage = () => (
    <AutomationsPage
      api={api}
      projectId={config.projectId}
      projectName={auth.projects.find((project) => project.id === config.projectId)?.name}
      onOpenConnection={openConnectionSettings}
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
      terminalBinding={terminalBinding}
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

  const renderWorkspaceReviewPanel = (sessionControls?: SessionCanvasControls) => (
    <WorkspaceReviewPanel
      activeTab={reviewTab}
      dataset={sessionDataset}
      socketEvents={workspaceEventInputs}
      timelineItems={conversationTimeline.items}
      artifacts={workspaceArtifacts}
      artifactVersions={displaySessionProjection?.artifactVersions ?? []}
      artifactDeliveries={displaySessionProjection?.artifactDeliveries ?? []}
      toolInvocations={displaySessionProjection?.toolInvocations ?? []}
      currentRun={currentArtifactRun}
      changeSnapshot={changeSnapshot}
      changeSnapshotLoading={changeSnapshotLoading}
      changeSnapshotError={changeSnapshotError}
      changeReferences={runInputReferences}
      artifactActionPending={artifactActionPending}
      terminal={terminal}
      terminalBinding={terminalBinding}
      terminalError={terminalProxy.error}
      terminalLines={terminalProxy.lines}
      terminalBusy={sandboxBusy}
      capabilityMode={sessionDetailViewModel?.capabilityMode ?? 'unavailable'}
      approvalRequests={displaySessionProjection?.pendingHitl ?? []}
      sessionCapabilities={sessionProjection?.capabilities ?? null}
      respondableHitlRequestIds={respondableHitlRequestIds}
      sessionDataAvailable={displaySessionProjection !== null}
      authorityNotice={sessionAuthorityNotice}
      onAuthorityAction={
        sessionProjectionState.status === 'error' ? invalidateSessionAuthority : undefined
      }
      currentRunId={sessionDetailViewModel?.runId ?? null}
      sessionViewModel={sessionDetailViewModel}
      onRespondToHitl={respondToHitl}
      onArtifactAction={handleArtifactAction}
      onStartTerminal={() => void startTerminal()}
      onRefreshChanges={() => void loadRunChanges()}
      onToggleChangeReference={(reference) =>
        setRunInputReferences((current) => toggleRunInputReference(current, reference))
      }
      onTabChange={setReviewTab}
      sessionControls={sessionControls}
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
    if (activeSection === 'workspace') return renderWorkspaceOverview();
    if (activeSection === 'chat') return renderChatPanel();
    if (activeSection === 'board') return renderBoardPanel();
    if (activeSection === 'automations') return renderAutomationsPage();
    if (
      activeSection === 'status' ||
      activeSection === 'sandbox' ||
      activeSection === 'memory' ||
      activeSection === 'terminal'
    ) {
      return renderStatusPanel();
    }
    return renderWorkspaceOverview();
  };

  if (!showRuntimeConfig) {
    return (
      <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
        <LoginScreen
          auth={auth}
          mode={config.mode}
          localReady={localRuntimeMode && Boolean(config.localApiToken.trim())}
          email={loginEmail}
          password={loginPassword}
          onEmailChange={setLoginEmail}
          onPasswordChange={setLoginPassword}
          onEmailLogin={() => void login()}
          onLocalSession={(trustedDevice) => void loginLocalSession(trustedDevice)}
        />
      </Theme>
    );
  }

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div
        ref={appShellRef}
        className={`app-shell hierarchy-shell ${runsInTauri ? 'tauri-window' : 'browser-window'} ${
          showRuntimeConfig ? 'runtime-mode' : 'signed-out-mode'
        } ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${
          activeSection === 'board' ? 'my-work-mode' : ''
        } ${activeSection === 'automations' ? 'automations-mode' : ''}`}
      >

        <section className="desktop-body">
          <DesktopSidebar
            activeSection={
              activeSection === 'board'
                ? 'my-work'
                : activeSection === 'automations'
                  ? 'automations'
                  : null
            }
            mode={preferredTaskMode}
            taskCount={dataset.myWork.length}
            tenantName={
              auth.tenants.find((tenant) => tenant.id === config.tenantId)?.name ??
              config.tenantId
            }
            projectName={selectedProject?.name ?? selectedProject?.id ?? t('overview.none')}
            user={auth.user}
            workspaces={dataset.workspacesByProject[config.projectId] ?? []}
            conversationsByWorkspace={dataset.conversationsByWorkspace}
            nodeState={dataset.nodeState}
            currentProjectId={config.projectId}
            currentWorkspaceId={config.workspaceId}
            currentConversationId={selectedConversation?.id ?? null}
            expandedWorkspaceIds={expandedWorkspaceIds}
            onModeChange={setPreferredTaskMode}
            onNavigate={(section) => {
              if (section === 'home') switchSection('workspace');
              if (section === 'my-work') switchSection('board');
              if (section === 'automations') switchSection('automations');
              if (section === 'search') openCommandPalette();
            }}
            onToggleWorkspace={toggleWorkspace}
            onSelectWorkspace={(projectId, workspaceId) => selectWorkspace(workspaceId, projectId)}
            onSelectConversation={selectConversation}
            onNewTask={startNewSession}
            onOpenSettings={openSidebarSettings}
            onSignOut={() => void logout()}
          />

          <main className="workbench">
            {error ? (
              <div className="workbench-error" role="alert" aria-live="polite">
                {error}
              </div>
            ) : null}
            {activeSection === 'chat' && sessionDetailViewModel ? (
              <SessionWorkspace
                viewModel={sessionDetailViewModel}
                thread={<section className={paneStageClassName}>{renderWorkbench()}</section>}
                canvas={
                  showReviewPanel
                    ? (controls) => renderWorkspaceReviewPanel(controls)
                    : null
                }
                evidence={sessionInspectorEvidence}
                onOpenCanvas={(tab) => {
                  if (tab) setReviewTab(tab);
                  setReviewPanelOpen(true);
                }}
                onCloseCanvas={() => setReviewPanelOpen(false)}
                runActionPending={sessionRunActionPending}
                liveConnected={socket.connected}
                liveError={socket.error}
                onRunAction={(action, feedback) =>
                  void handleSessionRunAction(action, feedback)
                }
              />
            ) : (
              <section className="workbench-layout">
                <section className={paneStageClassName}>{renderWorkbench()}</section>
              </section>
            )}
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
        <NewTaskFlow
          open={newTaskOpen}
          config={config}
          workspaces={dataset.workspacesByProject[config.projectId] ?? []}
          preferredWorkspaceId={newTaskPreferredWorkspaceId}
          preferredKind={preferredTaskMode === 'code' ? 'programming' : 'general'}
          disabledReason={newTaskDisabledReason}
          onClose={() => setNewTaskOpen(false)}
          onSessionReady={adoptNewTaskSession}
          onRunAgentTurn={runNewTaskAgentTurn}
          onError={setError}
        />
        <SettingsWindow
          open={settingsWindowOpen}
          initialSection={settingsInitialSection}
          auth={auth}
          config={config}
          connection={connection}
          wsConnected={socket.connected}
          wsError={socket.error}
          runtimeDisabledReason={runtimeDisabledReason}
          onClose={() => setSettingsWindowOpen(false)}
          onConfigChange={handleConfigChange}
          onRefreshRuntime={() => void refreshRuntime()}
          onContextChange={applySettingsContext}
          onSignOut={() => void logout()}
        />
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
  socketEvents,
  timelineItems,
  artifacts,
  artifactVersions,
  artifactDeliveries,
  toolInvocations,
  currentRun,
  changeSnapshot,
  changeSnapshotLoading,
  changeSnapshotError,
  changeReferences,
  artifactActionPending,
  terminal,
  terminalBinding,
  terminalError,
  terminalLines,
  terminalBusy,
  capabilityMode,
  approvalRequests,
  sessionCapabilities,
  respondableHitlRequestIds,
  sessionDataAvailable,
  authorityNotice,
  onAuthorityAction,
  currentRunId,
  sessionViewModel,
  onRespondToHitl,
  onArtifactAction,
  onStartTerminal,
  onRefreshChanges,
  onToggleChangeReference,
  onTabChange,
  sessionControls,
}: {
  activeTab: ReviewTab;
  dataset: RuntimeDataset;
  socketEvents: unknown[];
  timelineItems: AgentTimelineItem[];
  artifacts: WorkspaceArtifact[];
  artifactVersions: DesktopArtifactVersion[];
  artifactDeliveries: DesktopArtifactDelivery[];
  toolInvocations: DesktopToolInvocation[];
  currentRun: DesktopRun | null;
  changeSnapshot: ChangeSnapshot | null;
  changeSnapshotLoading: boolean;
  changeSnapshotError: string | null;
  changeReferences: CodeRangeReference[];
  artifactActionPending: { versionId: string; action: ArtifactVersionAction } | null;
  terminal: TerminalServiceResponse | null;
  terminalBinding: TerminalBindingState;
  terminalError: string | null;
  terminalLines: string[];
  terminalBusy: boolean;
  capabilityMode: SessionCapabilityMode;
  approvalRequests: DesktopApprovalRequest[];
  sessionCapabilities: SessionProjectionCapabilities | null;
  respondableHitlRequestIds: readonly string[];
  sessionDataAvailable: boolean;
  authorityNotice: {
    tone: 'loading' | 'warning' | 'error';
    title: string;
    description: string;
    actionLabel?: string;
  } | null;
  onAuthorityAction?: () => void;
  currentRunId: string | null;
  sessionViewModel: SessionDetailViewModel | null;
  onRespondToHitl: (submission: HitlResponseSubmission) => Promise<void>;
  onArtifactAction: (
    version: DesktopArtifactVersion,
    action: ArtifactVersionAction,
    feedback?: string,
  ) => Promise<void>;
  onStartTerminal: () => void;
  onRefreshChanges: () => void;
  onToggleChangeReference: (reference: CodeRangeReference) => void;
  onTabChange: (tab: ReviewTab) => void;
  sessionControls?: SessionCanvasControls;
}) {
  const { t } = useI18n();
  const [focusedArtifactVersionId, setFocusedArtifactVersionId] = useState<string | null>(null);
  const sessionTabListRef = useRef<HTMLElement>(null);
  const planRows = dataset.plan ? buildPlanDisplayRows(dataset.plan) : [];
  const workspaceEvents = useMemo(() => buildWorkspaceEvents(socketEvents), [socketEvents]);
  const invocationLedger = useMemo(
    () =>
      buildSessionInvocationLedger(timelineItems, {
        runId: sessionViewModel?.runId,
        revision: sessionViewModel?.runRevision,
      }, toolInvocations),
    [sessionViewModel?.runId, sessionViewModel?.runRevision, timelineItems, toolInvocations],
  );
  const invocationSummary = useMemo(
    () => sessionInvocationLedgerSummary(invocationLedger),
    [invocationLedger],
  );
  const sourceEvidence = useMemo(
    () => artifactEvidenceForCurrentVersions(artifactVersions, 'sources'),
    [artifactVersions],
  );
  const checkEvidence = useMemo(
    () => artifactEvidenceForCurrentVersions(artifactVersions, 'checks'),
    [artifactVersions],
  );
  const approvalRequest = useMemo(
    () => latestPendingApproval(approvalRequests, currentRunId),
    [approvalRequests, currentRunId],
  );
  const canRespondToApproval = Boolean(
    approvalRequest && respondableHitlRequestIds.includes(approvalRequest.id),
  );
  const reviewDecision = useMemo(
    () => buildReviewDecisionSummary(approvalRequest),
    [approvalRequest],
  );
  const configuredCanvasTabs = useMemo(() => sessionCanvasTabs(capabilityMode), [capabilityMode]);
  const chrome = workspaceReviewPanelChrome(Boolean(sessionControls));
  const tabValue = (tab: SessionCanvasTabId): string | undefined => {
    if (tab === 'changes' && changeSnapshot?.status === 'ready') {
      return `+${changeSnapshot.additions} / −${changeSnapshot.deletions}`;
    }
    if (tab === 'activity' && invocationSummary.total) return `${invocationSummary.total}`;
    if (tab === 'checks' || tab === 'verification') {
      const failed = checkEvidence.rows.filter((row) => {
        const status = row.status?.toLowerCase();
        return status === 'failed' || status === 'error';
      }).length;
      if (failed) return `${failed} ${t('session.failedShort')}`;
      if (checkEvidence.rows.length) return `${checkEvidence.rows.length}`;
      return checkEvidence.missing.length ? t('session.evidence.missing') : undefined;
    }
    if (tab === 'artifacts' && artifactVersions.length) {
      return `${currentArtifactVersions(artifactVersions).length}`;
    }
    if (tab === 'sources') {
      if (sourceEvidence.rows.length) return `${sourceEvidence.rows.length}`;
      return sourceEvidence.missing.length ? t('session.evidence.missing') : undefined;
    }
    return undefined;
  };
  const reviewTabs: Array<{
    tab: ReviewTab;
    label: string;
    value?: string;
  }> = configuredCanvasTabs.primary.map((tab) => ({
    tab: tab.id,
    label: t(tab.labelKey),
    value: tabValue(tab.id),
  }));
  const panelClassName = 'review-panel review-panel-session';

  const selectTab = (tab: ReviewTab) => {
    onTabChange(tab);
  };
  useEffect(() => {
    const availableTabs = new Set(
      [...configuredCanvasTabs.primary, ...configuredCanvasTabs.secondary].map((tab) => tab.id),
    );
    if (activeTab === 'background' && availableTabs.has('activity')) {
      onTabChange('activity');
      return;
    }
    if (activeTab === 'pull' && availableTabs.has('checks')) {
      onTabChange('checks');
      return;
    }
    if (!availableTabs.has(activeTab as SessionCanvasTabId)) {
      onTabChange(configuredCanvasTabs.primary[0]?.id ?? 'plan');
    }
  }, [activeTab, configuredCanvasTabs, onTabChange]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      sessionTabListRef.current
        ?.querySelector<HTMLButtonElement>('.review-tab.selected')
        ?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  return (
    <aside className={panelClassName} aria-label={t('session.canvas')}>
      <div className="review-tabs" aria-label={t('session.canvas')}>
        <nav className="review-tab-scroll" ref={sessionTabListRef}>
          {reviewTabs.map(({ tab, label, value }) => (
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
        {chrome.showSessionLayoutActions && sessionControls ? (
          <div className="review-tab-actions" aria-label={t('session.canvas')}>
            <Tooltip
              content={
                sessionControls.layout === 'focus'
                  ? t('session.splitView')
                  : t('session.focusCanvas')
              }
            >
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                aria-label={
                  sessionControls.layout === 'focus'
                    ? t('session.splitView')
                    : t('session.focusCanvas')
                }
                onClick={() =>
                  sessionControls.onLayoutChange(
                    sessionControls.layout === 'focus' ? 'split' : 'focus',
                  )
                }
              >
                {sessionControls.layout === 'focus' ? <ColumnsIcon /> : <EnterFullScreenIcon />}
              </IconButton>
            </Tooltip>
            <Tooltip content={t('session.closeCanvas')}>
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                aria-label={t('session.closeCanvas')}
                onClick={sessionControls.onClose}
              >
                <Cross2Icon />
              </IconButton>
            </Tooltip>
          </div>
        ) : null}
      </div>

      <div className="review-content">
        {authorityNotice ? (
          <div
            className={`session-authority-notice review-authority-notice tone-${authorityNotice.tone}`}
            role={authorityNotice.tone === 'error' ? 'alert' : 'status'}
            aria-live="polite"
          >
            <ReloadIcon aria-hidden="true" />
            <span>
              <strong>{authorityNotice.title}</strong>
              <small>{authorityNotice.description}</small>
            </span>
            {authorityNotice.actionLabel && onAuthorityAction ? (
              <Button type="button" size="1" variant="soft" onClick={onAuthorityAction}>
                {authorityNotice.actionLabel}
              </Button>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'overview' ? (
          <section className="session-overview-canvas" aria-label={t('session.canvasOverview')}>
            <header>
              <span>{t('session.overviewKicker')}</span>
              <h2>{sessionViewModel?.title ?? t('session.workspaceOverview')}</h2>
              <p>{t('session.overviewDescription')}</p>
            </header>
            <div className="session-overview-metrics">
              <article>
                <span>{t('session.overviewStatus')}</span>
                <strong>{sessionViewModel?.status ?? t('session.notAvailable')}</strong>
                <small>{sessionViewModel?.executionMode ?? t('session.notAvailable')}</small>
              </article>
              <article>
                <span>{t('session.overviewStage')}</span>
                <strong>{sessionViewModel?.stage ?? t('session.notAvailable')}</strong>
                <small>{sessionViewModel?.elapsedLabel ?? t('session.notAvailable')}</small>
              </article>
              <article>
                <span>{t('session.overviewEvidence')}</span>
                <strong>
                  {t('session.overviewEvidenceCount', {
                    artifacts: sessionDataAvailable
                      ? artifactVersions.length || artifacts.length
                      : t('session.notAvailable'),
                    events: workspaceEvents.length,
                  })}
                </strong>
                <small>{sessionViewModel?.usageLabel ?? t('session.notAvailable')}</small>
              </article>
            </div>
            <div className="session-overview-jump-grid">
              <button type="button" onClick={() => selectTab('plan')}>
                <ActivityLogIcon />
                <span>
                  <strong>{t('session.canvasPlan')}</strong>
                  <small>
                    {sessionDataAvailable
                      ? dataset.plan
                        ? t('session.planReady')
                        : t('session.noPlanShort')
                      : t('session.notAvailable')}
                  </small>
                </span>
                <ChevronRightIcon />
              </button>
              <button type="button" onClick={() => selectTab('activity')}>
                <DotsHorizontalIcon />
                <span>
                  <strong>{t('session.canvasActivity')}</strong>
                  <small>{t('session.overviewEventCount', { count: workspaceEvents.length })}</small>
                </span>
                <ChevronRightIcon />
              </button>
              <button type="button" onClick={() => selectTab('artifacts')}>
                <ArchiveIcon />
                <span>
                  <strong>{t('session.canvasArtifacts')}</strong>
                  <small>
                    {t('session.overviewArtifactCount', {
                      count: sessionDataAvailable
                        ? artifactVersions.length || artifacts.length
                        : t('session.notAvailable'),
                    })}
                  </small>
                </span>
                <ChevronRightIcon />
              </button>
            </div>
            <dl className="session-overview-facts">
              <div>
                <dt>{t('session.overviewEnvironment')}</dt>
                <dd>{sessionViewModel?.environmentLabel ?? t('session.notAvailable')}</dd>
              </div>
              <div>
                <dt>{t('session.overviewModel')}</dt>
                <dd>{sessionViewModel?.modelLabel ?? t('session.notAvailable')}</dd>
              </div>
              <div>
                <dt>{t('session.overviewPermission')}</dt>
                <dd>{sessionViewModel?.permissionLabel ?? t('session.notAvailable')}</dd>
              </div>
              <div>
                <dt>{t('session.overviewRun')}</dt>
                <dd>
                  {sessionViewModel?.runId
                    ? `${sessionViewModel.runId.slice(0, 8)} · r${sessionViewModel.runRevision ?? '—'}`
                    : t('session.notAvailable')}
                </dd>
              </div>
            </dl>
          </section>
        ) : null}

        {activeTab === 'changes' ? (
          <SessionChangesCanvas
            snapshot={changeSnapshot}
            loading={changeSnapshotLoading}
            error={changeSnapshotError}
            references={changeReferences}
            onRefresh={onRefreshChanges}
            onToggleReference={onToggleChangeReference}
            decision={
              reviewDecision.canAct && approvalRequest ? (
                <ReviewDecisionPanel
                  summary={reviewDecision}
                  request={approvalRequest}
                  canRespond={canRespondToApproval}
                  onRespond={onRespondToHitl}
                  onOpenArtifacts={() => selectTab('artifacts')}
                />
              ) : undefined
            }
          />
        ) : null}

        {activeTab === 'verification' && approvalRequest ? (
          <ReviewDecisionPanel
            summary={reviewDecision}
            request={approvalRequest}
            canRespond={canRespondToApproval}
            onRespond={onRespondToHitl}
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
              <ReviewEmpty
                icon={<ActivityLogIcon />}
                title={
                  sessionDataAvailable ? t('session.noPlan') : t('session.notAvailable')
                }
                body={
                  sessionDataAvailable
                    ? t('session.noPlanDescription')
                    : (authorityNotice?.description ?? t('session.authorityErrorDescription'))
                }
              />
            )}
          </div>
        ) : null}

        {activeTab === 'activity' || activeTab === 'background' ? (
          <SessionInvocationActivity entries={invocationLedger} />
        ) : null}

        {activeTab === 'artifacts' ? (
          <ArtifactLifecyclePanel
            versions={artifactVersions}
            deliveries={artifactDeliveries}
            currentRun={currentRun}
            capabilities={sessionCapabilities}
            enforceCapabilities
            available={sessionDataAvailable}
            focusVersionId={focusedArtifactVersionId}
            unversionedEvidenceCount={artifacts.length}
            pending={artifactActionPending}
            onAction={onArtifactAction}
          />
        ) : null}

        {activeTab === 'terminal' ? (
          <SessionTerminalCanvas
            terminal={terminal}
            binding={terminalBinding}
            error={terminalError}
            lines={terminalLines}
            busy={terminalBusy}
            currentRun={currentRun}
            onStart={onStartTerminal}
          />
        ) : null}

        {activeTab === 'checks' ? (
          <SessionEvidenceCanvas
            collection="checks"
            presentation="checks"
            versions={artifactVersions}
            available={sessionDataAvailable}
            onOpenArtifact={(artifactVersionId) => {
              setFocusedArtifactVersionId(artifactVersionId);
              selectTab('artifacts');
            }}
          />
        ) : null}

        {activeTab === 'sources' ? (
          <SessionEvidenceCanvas
            collection="sources"
            presentation="sources"
            versions={artifactVersions}
            available={sessionDataAvailable}
            onOpenArtifact={(artifactVersionId) => {
              setFocusedArtifactVersionId(artifactVersionId);
              selectTab('artifacts');
            }}
          />
        ) : null}

        {activeTab === 'verification' ? (
          <SessionEvidenceCanvas
            collection="checks"
            presentation="verification"
            versions={artifactVersions}
            available={sessionDataAvailable}
            onOpenArtifact={(artifactVersionId) => {
              setFocusedArtifactVersionId(artifactVersionId);
              selectTab('artifacts');
            }}
          />
        ) : null}
      </div>
    </aside>
  );
}

function ArtifactLifecyclePanel({
  versions,
  deliveries,
  currentRun,
  capabilities,
  enforceCapabilities,
  available,
  focusVersionId,
  unversionedEvidenceCount,
  pending,
  onAction,
}: {
  versions: DesktopArtifactVersion[];
  deliveries: DesktopArtifactDelivery[];
  currentRun: DesktopRun | null;
  capabilities: SessionProjectionCapabilities | null;
  enforceCapabilities: boolean;
  available: boolean;
  focusVersionId: string | null;
  unversionedEvidenceCount: number;
  pending: { versionId: string; action: ArtifactVersionAction } | null;
  onAction: (
    version: DesktopArtifactVersion,
    action: ArtifactVersionAction,
    feedback?: string,
  ) => Promise<void>;
}) {
  const { t } = useI18n();
  const currentVersions = useMemo(() => currentArtifactVersions(versions), [versions]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedback, setFeedback] = useState('');

  useEffect(() => {
    if (!focusVersionId) return;
    const focusedVersion = versions.find((version) => version.id === focusVersionId);
    if (!focusedVersion) return;
    setSelectedArtifactId(focusedVersion.artifact_id);
    setSelectedVersionId(focusedVersion.id);
  }, [focusVersionId, versions]);

  useEffect(() => {
    if (!currentVersions.length) {
      setSelectedArtifactId(null);
      setSelectedVersionId(null);
      return;
    }
    if (!selectedArtifactId || !currentVersions.some((item) => item.artifact_id === selectedArtifactId)) {
      setSelectedArtifactId(currentVersions[0].artifact_id);
      setSelectedVersionId(currentVersions[0].id);
    }
  }, [currentVersions, selectedArtifactId]);

  const artifactVersions = useMemo(
    () =>
      versions
        .filter((version) => version.artifact_id === selectedArtifactId)
        .sort((left, right) => right.version - left.version),
    [selectedArtifactId, versions],
  );
  const selectedVersion =
    artifactVersions.find((version) => version.id === selectedVersionId) ??
    artifactVersions[0] ??
    null;
  const actions = selectedVersion
    ? artifactVersionActions(selectedVersion, currentRun).filter((action) =>
        !enforceCapabilities
          ? true
          : capabilities === null
            ? false
          : action === 'deliver'
            ? capabilities.canDeliverArtifacts &&
              capabilities.allowedActions.includes('deliver_artifact')
            : capabilities.canReviewArtifacts &&
              capabilities.allowedActions.includes('review_artifact'),
      )
    : [];
  const delivery = selectedVersion
    ? deliveryForArtifactVersion(deliveries, selectedVersion.id)
    : null;
  const isPending = Boolean(selectedVersion && pending?.versionId === selectedVersion.id);

  useEffect(() => {
    if (!selectedVersion) return;
    setSelectedVersionId(selectedVersion.id);
    setFeedbackOpen(false);
    setFeedback('');
  }, [selectedVersion?.id]);

  if (!available) {
    return (
      <section
        className="artifact-lifecycle artifact-lifecycle-empty"
        aria-label={t('artifact.title')}
      >
        <ReviewEmpty
          icon={<ExclamationTriangleIcon />}
          title={t('session.dataUnavailableTitle')}
          body={t('session.dataUnavailableDescription')}
        />
      </section>
    );
  }

  if (!versions.length) {
    return (
      <section className="artifact-lifecycle artifact-lifecycle-empty" aria-label={t('artifact.title')}>
        <ReviewEmpty
          icon={<ArchiveIcon />}
          title={t('artifact.emptyTitle')}
          body={t('artifact.emptyDescription')}
        />
        {unversionedEvidenceCount ? (
          <p>{t('artifact.unversionedEvidence', { count: unversionedEvidenceCount })}</p>
        ) : null}
      </section>
    );
  }

  return (
    <section className="artifact-lifecycle" aria-label={t('artifact.title')}>
      <header className="artifact-lifecycle-header">
        <span>
          <ArchiveIcon />
          <strong>{t('artifact.title')}</strong>
          <small>{t('artifact.description')}</small>
        </span>
        <Badge color="cyan" variant="soft">
          {t('artifact.currentCount', { count: currentVersions.length })}
        </Badge>
      </header>

      <div className="artifact-lifecycle-layout">
        <nav className="artifact-lifecycle-list" aria-label={t('artifact.currentVersions')}>
          {currentVersions.map((version) => (
            <button
              type="button"
              className={version.artifact_id === selectedArtifactId ? 'selected' : ''}
              aria-pressed={version.artifact_id === selectedArtifactId}
              key={version.artifact_id}
              onClick={() => {
                setSelectedArtifactId(version.artifact_id);
                setSelectedVersionId(version.id);
              }}
            >
              <FileTextIcon />
              <span>
                <strong>{version.filename}</strong>
                <small>
                  v{version.version} · {formatBytes(version.bytes)}
                </small>
              </span>
              <Badge color={artifactStatusColor(version.status)} variant="soft">
                {t(`artifact.status.${version.status}`)}
              </Badge>
            </button>
          ))}
        </nav>

        {selectedVersion ? (
          <article className="artifact-version-detail">
            <header className="artifact-version-heading">
              <span>
                <small>{t('artifact.immutableVersion')}</small>
                <strong>{selectedVersion.filename}</strong>
                <code>{selectedVersion.source_artifact_id}</code>
              </span>
              <label>
                <span>{t('artifact.version')}</span>
                <select
                  aria-label={t('artifact.version')}
                  value={selectedVersion.id}
                  onChange={(event) => setSelectedVersionId(event.target.value)}
                >
                  {artifactVersions.map((version) => (
                    <option value={version.id} key={version.id}>
                      v{version.version} · {t(`artifact.status.${version.status}`)}
                    </option>
                  ))}
                </select>
              </label>
            </header>

            <div className="artifact-status-track" aria-label={t('artifact.lifecycle')}>
              {(['ready', 'approved', 'delivered'] as const).map((status, index) => {
                const reached = artifactStatusReached(selectedVersion.status, status);
                return (
                  <span className={reached ? 'reached' : ''} key={status}>
                    {reached ? <CheckCircledIcon /> : <ClockIcon />}
                    <small>0{index + 1}</small>
                    <strong>{t(`artifact.status.${status}`)}</strong>
                  </span>
                );
              })}
            </div>

            <dl className="artifact-version-facts">
              <div>
                <dt>{t('artifact.location')}</dt>
                <dd title={selectedVersion.path}>{selectedVersion.relative_path}</dd>
              </div>
              <div>
                <dt>{t('artifact.type')}</dt>
                <dd>{selectedVersion.mime_type}</dd>
              </div>
              <div>
                <dt>{t('artifact.revision')}</dt>
                <dd>r{selectedVersion.revision}</dd>
              </div>
              <div>
                <dt>{t('artifact.created')}</dt>
                <dd>{new Date(selectedVersion.created_at).toLocaleString()}</dd>
              </div>
            </dl>

            <div className="artifact-evidence-grid">
              <ArtifactEvidenceSection
                title={t('artifact.sources')}
                empty={t('artifact.sourcesMissing')}
                items={selectedVersion.sources}
              />
              <ArtifactEvidenceSection
                title={t('artifact.checks')}
                empty={t('artifact.checksMissing')}
                items={selectedVersion.checks}
              />
            </div>

            {selectedVersion.feedback ? (
              <div className="artifact-feedback-record">
                <MixerHorizontalIcon />
                <span>
                  <strong>{t('artifact.changesRequested')}</strong>
                  <small>{selectedVersion.feedback}</small>
                </span>
              </div>
            ) : null}

            {delivery ? (
              <div className="artifact-delivery-receipt">
                <RocketIcon />
                <span>
                  <strong>{t('artifact.deliveryReceipt')}</strong>
                  <small>{delivery.destination}</small>
                  <code>{artifactDeliveryReceiptPath(delivery.receipt)}</code>
                </span>
                <time>{new Date(delivery.created_at).toLocaleString()}</time>
              </div>
            ) : null}

            {feedbackOpen && actions.includes('request_changes') ? (
              <form
                className="artifact-feedback-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!feedback.trim()) return;
                  void onAction(selectedVersion, 'request_changes', feedback.trim()).then(() => {
                    setFeedbackOpen(false);
                    setFeedback('');
                  });
                }}
              >
                <label htmlFor="artifact-review-feedback">{t('artifact.feedbackLabel')}</label>
                <textarea
                  id="artifact-review-feedback"
                  value={feedback}
                  placeholder={t('artifact.feedbackPlaceholder')}
                  onChange={(event) => setFeedback(event.target.value)}
                />
                <div>
                  <Button type="button" variant="ghost" onClick={() => setFeedbackOpen(false)}>
                    {t('session.cancelAction')}
                  </Button>
                  <Button type="submit" disabled={!feedback.trim() || isPending}>
                    {isPending ? t('artifact.submitting') : t('artifact.sendChanges')}
                  </Button>
                </div>
              </form>
            ) : null}

            <footer className="artifact-version-actions">
              <span>
                {t('artifact.versionIdentity', {
                  version: selectedVersion.version,
                  revision: selectedVersion.revision,
                })}
              </span>
              <div>
                {actions.includes('request_changes') && !feedbackOpen ? (
                  <Button
                    variant="surface"
                    disabled={isPending}
                    onClick={() => setFeedbackOpen(true)}
                  >
                    <MixerHorizontalIcon /> {t('artifact.requestChanges')}
                  </Button>
                ) : null}
                {actions.includes('approve') ? (
                  <Button
                    color="green"
                    disabled={isPending}
                    onClick={() => void onAction(selectedVersion, 'approve')}
                  >
                    <CheckCircledIcon />
                    {isPending && pending?.action === 'approve'
                      ? t('artifact.approving')
                      : t('artifact.approveVersion')}
                  </Button>
                ) : null}
                {actions.includes('deliver') ? (
                  <Button
                    color="cyan"
                    disabled={isPending}
                    onClick={() => void onAction(selectedVersion, 'deliver')}
                  >
                    <RocketIcon />
                    {isPending && pending?.action === 'deliver'
                      ? t('artifact.delivering')
                      : t('artifact.deliverVersion')}
                  </Button>
                ) : null}
              </div>
            </footer>
          </article>
        ) : null}
      </div>

      {unversionedEvidenceCount ? (
        <p className="artifact-unversioned-note">
          {t('artifact.unversionedEvidence', { count: unversionedEvidenceCount })}
        </p>
      ) : null}
    </section>
  );
}

function artifactDeliveryReceiptPath(receipt: unknown): string {
  if (receipt === null || typeof receipt !== 'object' || Array.isArray(receipt)) return '';
  const value = receipt as Record<string, unknown>;
  const path = value.relative_path ?? value.path;
  return typeof path === 'string' ? path : '';
}

function ArtifactEvidenceSection({
  title,
  empty,
  items,
}: {
  title: string;
  empty: string;
  items: unknown[];
}) {
  return (
    <section>
      <strong>{title}</strong>
      {items.length ? (
        <ul>
          {items.map((item, index) => {
            const record = asRecordValue(item);
            const label = record
              ? readStringField(record, 'label') ??
                readStringField(record, 'id') ??
                readStringField(record, 'kind') ??
                compactArtifactValue(record)
              : compactArtifactValue(item);
            const status = record ? readStringField(record, 'status') : undefined;
            return (
              <li key={`${label}-${index}`}>
                <CheckCircledIcon />
                <span>
                  <strong>{label}</strong>
                  {status ? <small>{status}</small> : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </section>
  );
}

function artifactStatusReached(
  current: DesktopArtifactVersion['status'],
  target: 'ready' | 'approved' | 'delivered',
): boolean {
  const order = { draft: 0, ready: 1, approved: 2, delivered: 3, superseded: 0 };
  return order[current] >= order[target];
}

function artifactStatusColor(
  status: DesktopArtifactVersion['status'],
): 'gray' | 'cyan' | 'green' | 'amber' {
  if (status === 'delivered') return 'green';
  if (status === 'approved') return 'cyan';
  if (status === 'ready') return 'amber';
  return 'gray';
}

function ReviewDecisionPanel({
  summary,
  request,
  canRespond,
  onRespond,
  onOpenArtifacts,
}: {
  summary: ReviewDecisionSummary;
  request: DesktopApprovalRequest;
  canRespond: boolean;
  onRespond: (submission: HitlResponseSubmission) => Promise<void>;
  onOpenArtifacts: () => void;
}) {
  const { t } = useI18n();
  const [feedback, setFeedback] = useState('');
  const [submitting, setSubmitting] = useState<'approve' | 'request_changes' | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const validation = validateApprovalRequest(request);
  const decision = request.decision;
  const statusColor =
    summary.risk === 'High' ? 'red' : summary.risk === 'Medium' ? 'amber' : 'gray';

  const submit = async (action: 'approve' | 'request_changes') => {
    if (!canRespond || submitting) return;
    if (action === 'approve' && !validation.canApprove) return;
    if (action === 'request_changes' && !feedback.trim()) return;
    setSubmitting(action);
    setSubmissionError(null);
    try {
      await onRespond(approvalResponseSubmission(request, action, feedback));
    } catch (caught) {
      setSubmissionError(caught instanceof Error ? caught.message : t('approval.submitFailed'));
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <div className="review-decision" aria-label={t('approval.humanDecision')}>
      <section className="decision-summary">
        <div className="decision-summary-head">
          <div>
            <span className="decision-kicker">
              <ExclamationTriangleIcon />
              {t('approval.humanDecision')}
            </span>
            <small className="decision-request-source">
              {t('approval.requestIdentity', {
                requestId: request.id,
                revision: request.run_revision ?? '—',
              })}
            </small>
            <Heading as="h3" size="3">
              {decision?.action.label ?? request.prompt}
            </Heading>
          </div>
          <Badge color={statusColor} variant="soft">
            {summary.risk === 'Unassessed'
              ? t('approval.unassessed')
              : t('approval.riskBadge', { risk: summary.risk })}
          </Badge>
        </div>

        <Text as="p" size="2" color="gray">
          {request.prompt}
        </Text>

        <div className="decision-risk-strip" aria-label={t('approval.reviewSummary')}>
          <div>
            <ActivityLogIcon />
            <span>{t('approval.action')}</span>
            <strong>{decision?.action.name ?? t('approval.notProvided')}</strong>
          </div>
          <div>
            <FileTextIcon />
            <span>{t('approval.target')}</span>
            <strong>
              {decision
                ? `${decision.target.kind} · ${decision.target.id}`
                : t('approval.notProvided')}
            </strong>
          </div>
          <div>
            <ExclamationTriangleIcon />
            <span>{t('approval.agentRisk')}</span>
            <strong className={`risk-${summary.risk.toLowerCase()}`}>{summary.risk}</strong>
          </div>
        </div>

        <div className="decision-section">
          <strong>{t('approval.whatWillHappen')}</strong>
          <p>{summary.summary}</p>
          {decision?.data.redacted_fields?.length ? (
            <small>
              {t('approval.redactedFields', {
                fields: decision.data.redacted_fields.join(', '),
              })}
            </small>
          ) : null}
        </div>

        <div className="decision-section">
          <strong>{t('approval.reason')}</strong>
          <p className="decision-reasoning">{summary.reasoning}</p>
        </div>

        <div className="decision-section">
          <strong>{t('approval.riskScope')}</strong>
          <div className="decision-context-grid" aria-label={t('approval.riskScope')}>
            <div>
              <span>{t('approval.riskRationale')}</span>
              <strong>{decision?.risk.rationale ?? t('approval.notProvided')}</strong>
            </div>
            <div>
              <span>{t('approval.reversibility')}</span>
              <strong>{decision?.reversibility.mode ?? t('approval.notProvided')}</strong>
            </div>
            <div>
              <span>{t('approval.recovery')}</span>
              <strong>{decision?.reversibility.recovery ?? t('approval.notProvided')}</strong>
            </div>
            <div>
              <span>{t('approval.scope')}</span>
              <strong>
                {decision
                  ? `${decision.scope.kind} · ${decision.scope.ids.join(', ')}`
                  : t('approval.notProvided')}
              </strong>
            </div>
          </div>
        </div>

        <div className="decision-section">
          <div className="decision-section-head">
            <strong>{t('approval.evidence')}</strong>
            {summary.artifacts.length ? (
              <button type="button" onClick={onOpenArtifacts}>
                {t('approval.openArtifacts')}
                <ChevronRightIcon aria-hidden />
              </button>
            ) : null}
          </div>
          {summary.artifacts.length ? (
            <div className="decision-file-list">
              {summary.artifacts.map((artifact) => (
                <div className="decision-file-row" key={artifact.id}>
                  <span>{artifact.name}</span>
                  <strong>{artifact.meta}</strong>
                  <small title={artifact.path}>{artifact.path}</small>
                </div>
              ))}
            </div>
          ) : (
            <p>{t('approval.noEvidence')}</p>
          )}
        </div>
      </section>

      <section className="decision-actions-panel">
        <div>
          <Heading as="h3" size="2">
            {t('approval.chooseAction')}
          </Heading>
          {!validation.complete ? (
            <Text as="p" size="1" color="red">
              {t('approval.incomplete', { fields: validation.missing.join(', ') })}
            </Text>
          ) : null}
          {!canRespond ? (
            <Text as="p" size="1" color="amber">
              {t('session.authorityActionUnavailable')}
            </Text>
          ) : null}
        </div>
        <button
          className="decision-approve-button"
          type="button"
          disabled={!canRespond || !validation.canApprove || Boolean(submitting)}
          onClick={() => void submit('approve')}
        >
          <CheckCircledIcon />
          <span>
            <strong>
              {submitting === 'approve' ? t('approval.submitting') : t('approval.approve')}
            </strong>
            <small>{t('approval.approveDescription')}</small>
          </span>
        </button>
        <label className="decision-feedback-field">
          <span>{t('approval.feedback')}</span>
          <textarea
            value={feedback}
            disabled={!canRespond || Boolean(submitting)}
            placeholder={t('approval.feedbackPlaceholder')}
            onChange={(event) => setFeedback(event.currentTarget.value)}
          />
        </label>
        <button
          className="decision-request-button"
          type="button"
          disabled={!canRespond || !feedback.trim() || Boolean(submitting)}
          onClick={() => void submit('request_changes')}
        >
          <MixerHorizontalIcon />
          <span>
            <strong>
              {submitting === 'request_changes'
                ? t('approval.submitting')
                : t('approval.requestChanges')}
            </strong>
            <small>{t('approval.requestChangesDescription')}</small>
          </span>
        </button>
        {submissionError ? <p className="decision-submit-error">{submissionError}</p> : null}
        <small>{t('approval.authoritativeNotice')}</small>
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
  if (tab === 'pull' || tab === 'checks') return 'pull';
  if (tab === 'plan') return 'plan';
  if (tab === 'background' || tab === 'activity') return 'background';
  if (tab === 'artifacts') return 'artifacts';
  if (tab === 'terminal') return 'runtime';
  if (tab === 'sources' || tab === 'verification') return 'artifacts';
  return 'changes';
}

function chatWorkflowTargetForReviewTab(tab: ReviewTab): ChatWorkflowTarget {
  if (tab === 'pull' || tab === 'checks') return 'pull';
  if (tab === 'background' || tab === 'activity') return 'background';
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
