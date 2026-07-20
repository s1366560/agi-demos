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
  Button,
  Heading,
  IconButton,
  Text,
  Theme,
  Tooltip,
} from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  CheckCircledIcon,
  ClockIcon,
  ChevronRightIcon,
  ColumnsIcon,
  Cross2Icon,
  DashboardIcon,
  DotsHorizontalIcon,
  EnterFullScreenIcon,
  FileTextIcon,
  GearIcon,
  GridIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  ReloadIcon,
  RocketIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import {
  classifyDeviceTokenError,
  desktopApiCredential,
  desktopLaunchCapability,
  DesktopApiClient,
  isWorkspaceContextUnavailableError,
} from './api/client';
import {
  ingestLocalMemory,
  searchLocalMemory,
  semanticSearchLocalMemory,
} from './api/localMemory';
import {
  clearNativeTrustedSession,
  hasNativeTrustedSessionBroker,
  loadNativeTrustedSession,
  saveNativeTrustedSession,
  type NativeTrustedSession,
} from './api/trustedSession';
import {
  findWorkspaceProject,
  isCurrentContextRevision,
  isCurrentLocalRuntimeAuthority,
  isIdentityAuthenticated,
  isSameDesktopProjectRequestScope,
  isSameDesktopRequestScope,
  isWorkspaceReady,
  resolveSignOutDisposition,
  workspaceContextMatchesSelection,
} from './features/auth/authContextModel';
import {
  LoginScreen,
  type WorkspaceSsoPresentation,
} from './features/auth/LoginScreen';
import {
  normalizeDeviceAuthorizationInterval,
  resolveDeviceAuthorizationUrl,
} from './features/auth/loginScreenModel';
import {
  ChatPanel,
  type AgentTaskSignal,
  type AgentTaskSignalStatus,
  type ChatWorkflowTarget,
} from './features/chat/ChatPanel';
import { markA2UIActionAnswered } from './features/chat/a2uiAction';
import { SessionEvidenceCanvas } from './features/session/SessionEvidenceCanvas';
import { SessionChangesCanvas } from './features/session/SessionChangesCanvas';
import { SessionInvocationActivity } from './features/session/SessionInvocationLedger';
import {
  SessionPlanReview,
  SessionTaskListReview,
} from './features/session/SessionPlanReview';
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
  signedSessionSnapshotRevision,
  socketEventInvalidatesSessionProjectionForScope,
} from './features/session/sessionProjectionModel';
import {
  canApproveSessionPlan,
  normalizeSessionTaskListPlan,
  sessionPlanApprovalIdentity,
  sessionPlanApprovalRequest,
  type SessionPlanApprovalSelection,
} from './features/session/sessionPlanApprovalModel';
import {
  emptySessionProjectionState,
  type ConversationSessionProjection,
  type SessionProjectionCapabilities,
  type SessionProjectionLoadState,
  type SessionProjectionPlan,
  type SessionProjectionTask,
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
  mergeConversationListWithCurrentRunAuthority,
  type SessionCapabilityMode,
  type SessionDetailViewModel,
  type SessionRunAction,
} from './features/session/sessionViewModel';
import {
  workspaceReviewPanelChrome,
  type SessionCanvasControls,
} from './features/session/workspaceReviewPanelModel';
import { socketEventMatchesSessionScope } from './features/session/sessionScope';
import { sessionActivityPresence } from './features/session/sessionNarrativeModel';
import {
  sessionSelectionRequiresRuntimeRefresh,
  sessionTimelineRequestIsCurrent,
} from './features/session/sessionSelectionModel';
import {
  failEarlierTimelinePage,
  resolveEarlierTimelinePage,
} from './features/session/sessionTimelinePaginationModel';
import { MyWorkQueue } from './features/my-work/MyWorkQueue';
import { runtimeTransportIdentityChanged } from './features/runtime/runtimeConfigModel';
import {
  countMyWorkGroups,
  myWorkConversationMatchesScope,
  myWorkRefreshScopeIsCurrent,
  socketEventInvalidatesMyWork,
  type MyWorkRefreshScope,
} from './features/my-work/myWorkModel';
import { AuxiliaryView } from './features/navigation/AuxiliaryView';
import { DesktopSidebar } from './features/navigation/DesktopSidebar';
import {
  settingsSectionForEntry,
  type SettingsEntry,
} from './features/settings/settingsEntryRouting';
import { SettingsWindow, type SettingsSection } from './features/settings/SettingsWindow';
import { useWorkspaceRuntimeProvider } from './features/settings/useWorkspaceRuntimeProvider';
import { StatusPanel } from './features/status/StatusPanel';
import {
  NewTaskFlow,
  type NewTaskAgentTurnInput,
  type NewTaskResumeDraft,
  type NewTaskSession,
} from './features/task/NewTaskFlow';
import {
  browserLegacyPlanApprovalStorage,
  canResumeLegacyPlanApproval,
  clearLegacyPlanApprovalRecovery,
  legacyPlanApprovalRuntimeScope,
  newTaskAgentTurnResolution,
  newTaskAgentTurnTransport,
  planTaskSignature,
  readLegacyPlanApprovalRecovery,
  type NewTaskAgentTurnOutcome,
} from './features/task/newTaskPlanModel';
import { resolveNewTaskWorkspaceAuthority } from './features/task/newTaskSessionModel';
import { WorkspaceOverview } from './features/workspace/WorkspaceOverview';
import { beginDesktopRuntimeScopeTransition } from './features/workspace/workspaceOverviewModel';
import {
  beginWorkspaceConversationRequest,
  isCurrentWorkspaceConversationRequest,
  reconcileExpandedWorkspaceIds,
  reconcileWorkspaceConversationRowsAfterRefresh,
  shouldClearConversationSelectionAfterRefresh,
  shouldLoadWorkspaceConversations,
  supersedeWorkspaceConversationRequests,
  workspaceConversationLoadTargets,
  workspaceTreeRefreshFailed,
} from './features/workspace/workspaceTreeModel';
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
  ProjectWorkItem,
  RuntimeNodeLoadState,
  RuntimeDataset,
  RunInputDelivery,
  StatusTab,
  TerminalServiceResponse,
  WorkbenchSection,
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
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
  workspaceMembers: unavailableWorkspaceAuthority(),
  workspaceAgents: unavailableWorkspaceAuthority(),
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
type RunControlState = 'planning' | 'running' | 'paused' | 'stopped';
type RunDotTone = RunControlState | 'completed' | 'failed' | 'idle';
const runControlLabels: Record<RunControlState, string> = {
  planning: 'Planning',
  running: 'Running',
  paused: 'Paused',
  stopped: 'Stopped',
};
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
type ReviewTab = SessionCanvasTabId | 'pull' | 'background';
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

function agentConversationSelectionIdentity(session: AgentConversationSession | null) {
  return session
    ? { scopeKey: session.scopeKey, conversationId: session.conversation.id }
    : null;
}

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
    workspace_root: config.workspaceRoot,
  };
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
  const messageId = streamingMessageId(payload);
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
  let alreadySorted = true;
  for (let index = 1; index < updated.length; index += 1) {
    const previous = updated[index - 1];
    const current = updated[index];
    if (
      previous.eventTimeUs > current.eventTimeUs ||
      (previous.eventTimeUs === current.eventTimeUs &&
        previous.eventCounter > current.eventCounter)
    ) {
      alreadySorted = false;
      break;
    }
  }
  if (alreadySorted) return updated;
  return updated.sort((a, b) => {
    if (a.eventTimeUs !== b.eventTimeUs) return a.eventTimeUs - b.eventTimeUs;
    return a.eventCounter - b.eventCounter;
  });
}

function streamingMessageId(payload: Record<string, unknown>): string {
  return (
    socketMessageId(payload) ??
    `stream-${readStringField(payload, 'conversation_id') ?? 'agent'}`
  );
}

function streamingTextDeltaParts(
  event: unknown,
): { messageId: string; delta: string; payload: Record<string, unknown> } | null {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const type = readStringField(payload, 'type') ?? readStringField(payload, 'event_type');
  if (type !== 'text_delta') return null;
  const data = objectField(payload, 'data') ?? objectField(payload, 'payload') ?? {};
  const delta =
    readStringField(data, 'delta') ??
    readStringField(data, 'text') ??
    readStringField(data, 'content') ??
    '';
  return { messageId: streamingMessageId(payload), delta, payload };
}

// Collapse runs of consecutive text_delta events for the same message into one
// synthetic delta carrying the latest event's time/counter. Sequential merging
// runs a findIndex + full-array map copy + sortedness scan per token — a burst
// of K deltas over N timeline items costs O(K·N) per animation frame. The
// merged event applies the identical final content, time, counter and sort
// position in a single merge pass (only pure delta runs are folded;
// text_start/text_end pass through untouched).
function coalesceStreamingTextEvents(events: unknown[]): unknown[] {
  const out: unknown[] = [];
  let runIndex = -1;
  let runMessageId: string | null = null;
  for (const event of events) {
    const parts = streamingTextDeltaParts(event);
    if (!parts) {
      runIndex = -1;
      runMessageId = null;
      out.push(event);
      continue;
    }
    if (runIndex >= 0 && runMessageId === parts.messageId) {
      const previous = out[runIndex] as Record<string, unknown>;
      const previousData = objectField(previous, 'data') ?? {};
      const previousDelta = readStringField(previousData, 'delta') ?? '';
      out[runIndex] = {
        ...parts.payload,
        data: {
          ...(objectField(parts.payload, 'data') ?? {}),
          delta: previousDelta + parts.delta,
        },
      };
      continue;
    }
    runIndex = out.length;
    runMessageId = parts.messageId;
    out.push({
      ...parts.payload,
      data: { ...(objectField(parts.payload, 'data') ?? {}), delta: parts.delta },
    });
  }
  return out;
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

function waitForAbortableDelay(delayMs: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', cancel);
      resolve(true);
    }, delayMs);
    const cancel = () => {
      window.clearTimeout(timer);
      resolve(false);
    };
    signal.addEventListener('abort', cancel, { once: true });
  });
}

type WorkspaceSsoFlowErrorCode = 'credential_store' | 'invalid_url' | 'expired';

class WorkspaceSsoFlowError extends Error {
  readonly code: WorkspaceSsoFlowErrorCode;

  constructor(code: WorkspaceSsoFlowErrorCode) {
    super(code);
    this.name = 'WorkspaceSsoFlowError';
    this.code = code;
  }
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
  const [newTaskResumeDraft, setNewTaskResumeDraft] =
    useState<NewTaskResumeDraft | null>(null);
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
  const runActionsButtonRef = useRef<HTMLButtonElement>(null);
  const runActionsMenuRef = useRef<HTMLDivElement>(null);
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState<Set<string>>(() => new Set());
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [workspaceSso, setWorkspaceSso] = useState<WorkspaceSsoPresentation | null>(null);
  const [dataset, setDataset] = useState<RuntimeDataset>(emptyDataset);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string>('never');
  const [localRuntimeStatus, setLocalRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [runtimeProjectionRefreshRevision, setRuntimeProjectionRefreshRevision] = useState(0);
  const [selectedSidebarRunId, setSelectedSidebarRunId] = useState('');
  const [runStateById, setRunStateById] = useState<Record<string, RunControlState>>({});
  const [runControlState, setRunControlState] = useState<RunControlState>('running');
  const [runtimeTarget, setRuntimeTarget] = useState<RuntimeTarget>('local');
  const [runLiveMode, setRunLiveMode] = useState(true);
  const [myWorkRefreshing, setMyWorkRefreshing] = useState(false);
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
  const [sessionPlanApprovalPending, setSessionPlanApprovalPending] = useState(false);
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
  const [agentConversationSession, setAgentConversationSession] =
    useState<AgentConversationSession | null>(null);
  const agentConversationSessionRef = useRef(agentConversationSession);
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
        resolve: (outcome: NewTaskAgentTurnOutcome) => void;
        reject: (error: Error) => void;
      }
    >(),
  );
  const timelineRequestRef = useRef(0);
  const sessionProjectionRequestRef = useRef(0);
  const sessionProjectionRevisionRef = useRef<{
    scopeKey: string;
    snapshotRevision: string;
    projection: ConversationSessionProjection;
  } | null>(null);
  const sessionProjectionRefreshTimerRef = useRef<number | null>(null);
  const agentTaskEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const sessionEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const authoritativeRunEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const myWorkRequestRef = useRef(0);
  const myWorkAbortRef = useRef<AbortController | null>(null);
  const myWorkRefreshTimerRef = useRef<number | null>(null);
  const myWorkEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const contextRevisionRef = useRef(0);
  const configRef = useRef(config);
  const datasetRef = useRef(dataset);
  const expandedWorkspaceIdsRef = useRef(expandedWorkspaceIds);
  const runtimeRefreshRequestRef = useRef(0);
  const activeRuntimeConversationRequestsRef = useRef(new Map<string, number>());
  const workspaceConversationRequestGenerationsRef = useRef(new Map<string, number>());
  const configScopeEpochRef = useRef(0);
  const workspaceExpansionScopeRef = useRef('');
  const localResumeAttemptRef = useRef('');
  const authAttemptRevisionRef = useRef(0);
  const deviceAuthAttemptIdRef = useRef(0);
  const deviceAuthAttemptRef = useRef<{
    attemptId: number;
    authRevision: number;
    controller: AbortController;
    authorizationUrl: string;
    userCode: string;
    openInFlight: boolean;
  } | null>(null);
  const runInputRequestRef = useRef<{
    signature: string;
    messageId: string;
    idempotencyKey: string;
  } | null>(null);
  const sessionPlanApprovalAttemptRef = useRef<{
    identity: string;
    requestId: string;
  } | null>(null);
  const terminalStartGenerationRef = useRef(0);
  const currentArtifactRunRef = useRef<DesktopRun | null>(null);
  const terminalRunScopeKeyRef = useRef('');
  const workbenchRef = useRef<HTMLElement>(null);

  useEffect(() => {
    datasetRef.current = dataset;
  }, [dataset]);

  useEffect(() => {
    agentConversationSessionRef.current = agentConversationSession;
  }, [agentConversationSession]);

  useEffect(() => {
    expandedWorkspaceIdsRef.current = expandedWorkspaceIds;
  }, [expandedWorkspaceIds]);

  useEffect(
    () => () => {
      deviceAuthAttemptRef.current?.controller.abort();
      deviceAuthAttemptRef.current = null;
    },
    [],
  );

  const updateDataset = useCallback((updater: (current: RuntimeDataset) => RuntimeDataset) => {
    setDataset((current) => {
      const nextDataset = updater(current);
      datasetRef.current = nextDataset;
      return nextDataset;
    });
  }, []);

  const commitRuntimeConfig = useCallback((nextConfig: DesktopRuntimeConfig) => {
    const previousConfig = configRef.current;
    if (!isSameDesktopProjectRequestScope(previousConfig, nextConfig)) {
      runtimeRefreshRequestRef.current += 1;
      activeRuntimeConversationRequestsRef.current = new Map();
      workspaceConversationRequestGenerationsRef.current = new Map();
    }
    if (!isSameDesktopRequestScope(previousConfig, nextConfig)) {
      configScopeEpochRef.current += 1;
      updateDataset((current) =>
        beginDesktopRuntimeScopeTransition(current, previousConfig, nextConfig),
      );
    }
    configRef.current = nextConfig;
    setConfig(nextConfig);
  }, [updateDataset]);

  const identityAuthenticated = isIdentityAuthenticated(auth);
  const showRuntimeConfig = isWorkspaceReady(auth, config);
  const scopedConversation =
    agentConversationSession?.scopeKey === agentConversationScopeKey(config)
      ? agentConversationSession.conversation
      : null;
  const scopedConversationId = scopedConversation?.id ?? '';
  const api = useMemo(() => new DesktopApiClient(config), [config]);
  const socket = useAgentSocket(
    config,
    showRuntimeConfig && connection === 'ready',
    auth.context?.revision ?? null,
    scopedConversation?.id ?? null,
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
  const localRuntimeAuthorityReady = isCurrentLocalRuntimeAuthority(
    config,
    localRuntimeStatus,
    runsInTauri,
  );
  const runtimeProvider = useWorkspaceRuntimeProvider(
    config,
    identityAuthenticated && localRuntimeMode && localRuntimeAuthorityReady,
    runtimeProjectionRefreshRevision,
  );

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

  const refreshLocalRuntimeStatus = useCallback(async (): Promise<void> => {
    if (!runsInTauri || configRef.current.mode !== 'local') return;
    const invoke = window.__TAURI__?.core?.invoke;
    if (!invoke) return;
    try {
      const status = await invoke<LocalRuntimeStatus>('local_runtime_status');
      if (configRef.current.mode !== 'local') return;
      setLocalRuntimeStatus(status);
      setRuntimeProjectionRefreshRevision((current) => current + 1);
      commitRuntimeConfig(mergeLocalRuntimeStatus(configRef.current, status));
    } catch (caught) {
      const message = formatError(caught);
      setError(message);
      throw caught instanceof Error ? caught : new Error(message);
    }
  }, [commitRuntimeConfig, runsInTauri]);

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
        // A schema_version 1 snapshot_revision is the canonical digest of the payload,
        // so an unchanged revision means the already-decoded projection still holds;
        // skip the canonicalize + SHA-256 + validate pass entirely in that case.
        const scopeKey = [
          scopedConversationId,
          config.tenantId,
          config.projectId,
          config.workspaceId || '',
        ].join('\n');
        const payloadRevision = signedSessionSnapshotRevision(payload);
        const seen = sessionProjectionRevisionRef.current;
        const projection =
          payloadRevision !== null &&
          seen !== null &&
          seen.scopeKey === scopeKey &&
          seen.snapshotRevision === payloadRevision
            ? seen.projection
            : decodeConversationSessionProjection(payload, {
                conversationId: scopedConversationId,
                projectId: config.projectId,
                tenantId: config.tenantId,
                workspaceId: config.workspaceId || null,
              });
        if (projection) {
          sessionProjectionRevisionRef.current = {
            scopeKey,
            snapshotRevision: projection.snapshotRevision,
            projection,
          };
          setSessionDisplayProjection(projection);
        }
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
  const sessionTaskListPlanRecovery = useMemo(() => {
    if (sessionProjection?.planAuthority.kind !== 'agent_task_list') return null;
    const tasks = normalizeSessionTaskListPlan(
      sessionProjection.tasks,
      sessionProjection.conversation.id,
    );
    if (!tasks) return null;
    const signature = planTaskSignature(tasks);
    const recovery = readLegacyPlanApprovalRecovery(
      browserLegacyPlanApprovalStorage(),
      sessionProjection.conversation.id,
      signature,
      legacyPlanApprovalRuntimeScope(config),
    );
    return {
      tasks,
      canResume: canResumeLegacyPlanApproval(
        sessionProjection.conversation.current_mode ?? '',
        sessionProjection.executionAuthority.currentAttempt !== null,
        signature,
        recovery,
      ),
    };
  }, [config, sessionProjection]);
  useEffect(() => {
    if (
      sessionProjection?.planAuthority.kind !== 'agent_task_list' ||
      sessionProjection.executionAuthority.currentAttempt === null
    ) {
      return;
    }
    clearLegacyPlanApprovalRecovery(
      browserLegacyPlanApprovalStorage(),
      sessionProjection.conversation.id,
    );
  }, [sessionProjection]);
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

  const resetConversationTimeline = useCallback(() => {
    timelineRequestRef.current += 1;
    setConversationTimeline(emptyConversationTimeline);
  }, []);

  const clearMissingConversationSelection = useCallback(
    (
      selectionAtRequest: ReturnType<typeof agentConversationSelectionIdentity>,
      refreshedScopeKey: string,
      conversations: readonly AgentConversation[],
    ) => {
      if (
        !shouldClearConversationSelectionAfterRefresh(
          selectionAtRequest,
          agentConversationSelectionIdentity(agentConversationSessionRef.current),
          refreshedScopeKey,
          conversations,
        )
      ) {
        return;
      }
      agentConversationSessionRef.current = null;
      setAgentConversationSession(null);
      resetConversationTimeline();
      setAgentTaskSignals([]);
      if (activeSectionRef.current === 'chat') {
        activeSectionRef.current = 'workspace';
        setActiveSection('workspace');
        setReviewTab('overview');
        workbenchRef.current?.focus();
      }
    },
    [resetConversationTimeline],
  );

  const loadConversationTimeline = useCallback(
    async (
      conversation: AgentConversation,
      projectId: string,
      requestConfig: DesktopRuntimeConfig = configRef.current,
    ) => {
      const requestId = timelineRequestRef.current + 1;
      timelineRequestRef.current = requestId;
      const expectedRequest = {
        requestId,
        scopeEpoch: configScopeEpochRef.current,
      };
      const requestIsCurrent = () =>
        sessionTimelineRequestIsCurrent(expectedRequest, {
          requestId: timelineRequestRef.current,
          scopeEpoch: configScopeEpochRef.current,
        });
      setConversationTimeline({
        ...emptyConversationTimeline,
        conversationId: conversation.id,
        loading: true,
      });
      try {
        const client = new DesktopApiClient(requestConfig);
        const response = await client.getConversationMessages(conversation.id, projectId, {
          limit: 50,
        });
        if (!requestIsCurrent()) return;
        const responseItems = response.timeline ?? [];
        setConversationTimeline((current) => {
          if (!requestIsCurrent() || current.conversationId !== conversation.id) return current;
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
        if (!requestIsCurrent()) return;
        setConversationTimeline((current) =>
          requestIsCurrent() && current.conversationId === conversation.id
            ? {
                ...emptyConversationTimeline,
                conversationId: conversation.id,
                error: formatConnectionError(caught, requestConfig.apiBaseUrl),
              }
            : current,
        );
      }
    },
    [],
  );

  const loadEarlierTimeline = useCallback(async () => {
    const conversation = scopedConversation;
    const cursor = conversationTimeline.firstCursor;
    if (!conversation || !cursor || conversationTimeline.loadingEarlier) return;
    const requestId = timelineRequestRef.current + 1;
    timelineRequestRef.current = requestId;
    const expectedRequest = {
      requestId,
      scopeEpoch: configScopeEpochRef.current,
    };
    const requestIsCurrent = () =>
      sessionTimelineRequestIsCurrent(expectedRequest, {
        requestId: timelineRequestRef.current,
        scopeEpoch: configScopeEpochRef.current,
      });
    setConversationTimeline((current) =>
      current.conversationId === conversation.id
        ? { ...current, loadingEarlier: true, error: null }
        : current,
    );
    try {
      const response = await api.getConversationMessages(conversation.id, config.projectId, {
        limit: 50,
        beforeTimeUs: cursor.timeUs,
        beforeCounter: cursor.counter,
      });
      setConversationTimeline((current) => {
        if (!requestIsCurrent() || current.conversationId !== conversation.id) return current;
        const items = mergeTimelineItems(response.timeline ?? [], current.items);
        const pageResolution = resolveEarlierTimelinePage({
          requestedCursor: cursor,
          previousItemCount: current.items.length,
          nextItemCount: items.length,
          nextFirstCursor: timelineCursorFromFirst(items),
          responseHasMore: Boolean(response.has_more),
        });
        if (pageResolution.kind === 'stalled') {
          return failEarlierTimelinePage(current, t('session.earlierHistoryNoProgress'));
        }
        return {
          ...current,
          items,
          approvalRequests: response.approval_requests ?? current.approvalRequests,
          artifactVersions: response.artifact_versions ?? current.artifactVersions,
          artifactDeliveries: response.artifact_deliveries ?? current.artifactDeliveries,
          toolInvocations: response.tool_invocations ?? current.toolInvocations,
          loadingEarlier: false,
          error: null,
          hasMore: pageResolution.hasMore,
          firstCursor: pageResolution.firstCursor,
          lastCursor: timelineCursorFromLast(items),
        };
      });
    } catch (caught) {
      setConversationTimeline((current) =>
        requestIsCurrent() && current.conversationId === conversation.id
          ? failEarlierTimelinePage(
              current,
              formatConnectionError(caught, config.apiBaseUrl),
            )
          : current,
      );
    }
  }, [
    api,
    config.apiBaseUrl,
    config.projectId,
    conversationTimeline.firstCursor,
    conversationTimeline.loadingEarlier,
    scopedConversation,
    t,
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
        if (activeSectionRef.current === 'board') {
          const search = document.querySelector<HTMLInputElement>('input[name="my-work-search"]');
          if (search) {
            event.preventDefault();
            search.focus();
            return;
          }
        }
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
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    closeCommandPalette,
    commandPaletteOpen,
    loginModalOpen,
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
          if (resolution === 'acknowledged') pending.resolve('acknowledged');
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
      pending.resolve('unknown_outcome');
      pendingNewTaskAgentTurnsRef.current.delete(key);
    }
  }, [socket.connected]);

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
        for (const event of coalesceStreamingTextEvents(timelineEvents))
          items = mergeLiveTimelineEvent(items, event);
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
    const events = socketEventsSince(socket.events, authoritativeRunEventsHeadRef.current);
    authoritativeRunEventsHeadRef.current = socket.events[0] ?? null;
    if (!authoritativeRunsFromSocketEvents(events).length) return;
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
  const runtimeDisabledReason = !identityAuthenticated
    ? 'Sign in or use a manual API key before connecting.'
    : !showRuntimeConfig
      ? 'Select an account and project before connecting.'
    : !config.apiBaseUrl.trim()
      ? 'Local runtime URL is not ready yet.'
    : !config.apiKey.trim()
      ? 'An authenticated session is required before connecting.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before connecting.'
        : null;
  const workspaceDisabledReason = !identityAuthenticated
    ? 'Sign in or use a manual API key before loading workspaces.'
    : !showRuntimeConfig
      ? 'Select an account and project before loading workspaces.'
    : !config.apiKey.trim()
      ? 'An authenticated session is required before loading workspaces.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before loading workspaces.'
        : null;
  const newTaskWorkspaces = dataset.workspacesByProject[config.projectId] ?? [];
  const newTaskWorkspaceAuthority = resolveNewTaskWorkspaceAuthority(
    dataset.nodeState.projects[config.projectId],
    newTaskWorkspaces,
  );
  const newTaskDisabledReason = !identityAuthenticated
    ? t('task.disabledSignIn')
    : !showRuntimeConfig
      ? t('task.disabledProjectRequired')
    : !config.apiKey.trim()
      ? t('task.disabledAuthRequired')
      : !config.tenantId.trim() || !config.projectId.trim()
        ? t('task.disabledProjectRequired')
        : newTaskAgentTurnTransport(config.mode, socket.connected) === 'live_socket_required'
          ? t('task.liveConnectionRequired')
          : null;
  const sandboxDisabledReason = !identityAuthenticated
    ? t('sandbox.disabled.signIn')
    : !showRuntimeConfig
      ? t('sandbox.disabled.projectRequired')
    : !config.apiKey.trim()
      ? t('sandbox.disabled.authRequired')
      : !config.projectId.trim()
        ? t('sandbox.disabled.projectRequired')
        : null;
  const chatDisabledReason = !identityAuthenticated
    ? 'Sign in or enter an API key before sending messages.'
    : !showRuntimeConfig
      ? 'Select an account and project before chatting.'
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
    runtimeRefreshRequestRef.current += 1;
    activeRuntimeConversationRequestsRef.current = new Map();
    workspaceConversationRequestGenerationsRef.current = new Map();
    myWorkAbortRef.current?.abort();
    myWorkAbortRef.current = null;
    myWorkRequestRef.current += 1;
    if (myWorkRefreshTimerRef.current !== null) {
      window.clearTimeout(myWorkRefreshTimerRef.current);
      myWorkRefreshTimerRef.current = null;
    }
    setMyWorkRefreshing(false);
    datasetRef.current = emptyDataset;
    setDataset(emptyDataset);
    setConnection('idle');
    setError(null);
    setLastSync('never');
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
    resetConversationTimeline();
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
    const clearedExpandedWorkspaceIds = new Set<string>();
    expandedWorkspaceIdsRef.current = clearedExpandedWorkspaceIds;
    setExpandedWorkspaceIds(clearedExpandedWorkspaceIds);
    workspaceExpansionScopeRef.current = '';
    terminalProxy.clear();
  };

  const refreshRuntime = useCallback(
    async (nextConfig: DesktopRuntimeConfig = config, projectOverride?: ProjectSummary[]) => {
      const refreshRequestGeneration = runtimeRefreshRequestRef.current + 1;
      runtimeRefreshRequestRef.current = refreshRequestGeneration;
      const expectedContextRevision = contextRevisionRef.current;
      const expectedScopeEpoch = configScopeEpochRef.current;
      const contextIsCurrent = () =>
        isCurrentContextRevision(expectedContextRevision, contextRevisionRef.current) &&
        expectedScopeEpoch === configScopeEpochRef.current &&
        refreshRequestGeneration === runtimeRefreshRequestRef.current;
      setConnection('loading');
      setError(null);
      let refreshProjectId = nextConfig.projectId.trim();
      let conversationRequestGenerations = supersedeWorkspaceConversationRequests(
        workspaceConversationRequestGenerationsRef.current,
        activeRuntimeConversationRequestsRef.current,
      );
      activeRuntimeConversationRequestsRef.current = conversationRequestGenerations;
      try {
        const runtimeConfig = await syncLocalRuntimeConfig(nextConfig);
        if (!contextIsCurrent()) return false;
        const availableProjects =
          projectOverride ?? resolveSidebarProjects(runtimeConfig, auth.status, auth.projects);
        const requestedTenantId = runtimeConfig.tenantId.trim();
        const requestedProjectId = runtimeConfig.projectId.trim();
        if (
          auth.status === 'signed_in' &&
          !auth.tenants.some((tenant) => tenant.id === requestedTenantId)
        ) {
          throw new Error(t('runtime.activeTenantUnavailable'));
        }
        const resolvedProject = findWorkspaceProject(
          availableProjects,
          requestedTenantId,
          requestedProjectId,
        );
        if (!resolvedProject) {
          throw new Error(t('runtime.activeProjectUnavailable'));
        }
        const resolvedProjectId = resolvedProject.id;
        refreshProjectId = resolvedProjectId;
        const expansionScope = `${resolvedProject.tenant_id}\u0000${resolvedProjectId}`;
        const expandSelectedWorkspace = workspaceExpansionScopeRef.current !== expansionScope;
        const projects = [resolvedProject];
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
        updateDataset((current) => ({
          ...current,
          nodeState: {
            projects: { ...current.nodeState.projects, ...loadingNodeState.projects },
            workspaces: current.nodeState.workspaces,
          },
        }));

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
        const workspaces = workspaceResults.flatMap((result) => result.workspaces);
        const projectWorkspaces = workspacesByProject[resolvedProjectId] ?? [];
        const workspaceId =
          runtimeConfig.workspaceId.trim() &&
          projectWorkspaces.some((workspace) => workspace.id === runtimeConfig.workspaceId.trim())
            ? runtimeConfig.workspaceId.trim()
            : projectWorkspaces[0]?.id ?? '';
        const nextExpandedWorkspaceIds = reconcileExpandedWorkspaceIds(
          expandedWorkspaceIdsRef.current,
          projectWorkspaces.map((workspace) => workspace.id),
          workspaceId,
          expandSelectedWorkspace,
        );
        const conversationLoadTargets = workspaceConversationLoadTargets(
          projectWorkspaces,
          workspaceId,
          nextExpandedWorkspaceIds,
        );
        const conversationLoadTargetIds = new Set(conversationLoadTargets);
        const supersededRefreshWorkspaceIds = [...conversationRequestGenerations.keys()].filter(
          (targetWorkspaceId) => !conversationLoadTargetIds.has(targetWorkspaceId),
        );
        conversationRequestGenerations = new Map(
          conversationLoadTargets.map((targetWorkspaceId) => [
            targetWorkspaceId,
            beginWorkspaceConversationRequest(
              workspaceConversationRequestGenerationsRef.current,
              targetWorkspaceId,
            ),
          ]),
        );
        activeRuntimeConversationRequestsRef.current = conversationRequestGenerations;
        const resolvedConfig = {
          ...runtimeConfig,
          tenantId: resolvedProject.tenant_id,
          projectId: resolvedProjectId,
          workspaceId,
        };
        const scopedClient = new DesktopApiClient(resolvedConfig);
        if (!contextIsCurrent()) return false;
        updateDataset((current) => {
          const workspaceNodeState = { ...current.nodeState.workspaces };
          for (const targetWorkspaceId of supersededRefreshWorkspaceIds) {
            if ((current.conversationsByWorkspace[targetWorkspaceId] ?? []).length > 0) {
              workspaceNodeState[targetWorkspaceId] = { loading: false, error: null };
            } else {
              delete workspaceNodeState[targetWorkspaceId];
            }
          }
          for (const targetWorkspaceId of conversationLoadTargets) {
            workspaceNodeState[targetWorkspaceId] = { loading: true, error: null };
          }
          return {
            ...current,
            nodeState: {
              projects: { ...current.nodeState.projects, ...projectNodeState },
              workspaces: workspaceNodeState,
            },
            workspaceMembers: workspaceId
              ? loadingWorkspaceAuthority()
              : unavailableWorkspaceAuthority(),
            workspaceAgents: workspaceId
              ? loadingWorkspaceAuthority()
              : unavailableWorkspaceAuthority(),
          };
        });
        const selectionAtRequest = agentConversationSelectionIdentity(
          agentConversationSessionRef.current,
        );
        const conversationResultsPromise = Promise.all(
          conversationLoadTargets.map(async (targetWorkspaceId) => {
            const requestGeneration = conversationRequestGenerations.get(targetWorkspaceId);
            const client = new DesktopApiClient({
              ...resolvedConfig,
              workspaceId: targetWorkspaceId,
            });
            try {
              const response = await client.listConversations(
                resolvedProjectId,
                targetWorkspaceId,
              );
              return {
                workspaceId: targetWorkspaceId,
                requestGeneration,
                conversations: response.items,
                error: null,
              };
            } catch (caught) {
              return {
                workspaceId: targetWorkspaceId,
                requestGeneration,
                conversations: [] as AgentConversation[],
                error: formatError(caught),
              };
            }
          }),
        );
        const [
          messages,
          tasks,
          plan,
          workspaceMembers,
          workspaceAgents,
          myWorkResult,
          conversationResults,
        ] = await Promise.all([
          workspaceId ? scopedClient.listMessages() : Promise.resolve([]),
          workspaceId ? scopedClient.listTasks() : Promise.resolve([]),
          workspaceId
            ? scopedClient.getPlanSnapshot().catch(() => null)
            : Promise.resolve(null),
          workspaceId
            ? resolveWorkspaceAuthority(scopedClient.listWorkspaceMembers())
            : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceMemberSummary>()),
          workspaceId
            ? resolveWorkspaceAuthority(scopedClient.listWorkspaceAgents())
            : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceAgentBinding>()),
          resolvedProjectId
            ? scopedClient
                .listMyWork(resolvedProjectId)
                .then((response) => ({ items: response.items, error: null }))
                .catch((caught) => ({
                  items: [] as ProjectWorkItem[],
                  error: formatError(caught),
                }))
            : Promise.resolve({ items: [] as ProjectWorkItem[], error: null }),
          conversationResultsPromise,
        ]);
        if (!contextIsCurrent()) return false;
        const validWorkspaceIds = new Set(projectWorkspaces.map((workspace) => workspace.id));
        const currentConversationResults = conversationResults.filter(
          (result) =>
            result.requestGeneration !== undefined &&
            isCurrentWorkspaceConversationRequest(
              workspaceConversationRequestGenerationsRef.current,
              result.workspaceId,
              result.requestGeneration,
            ),
        );

        if (!contextIsCurrent()) return false;
        commitRuntimeConfig(resolvedConfig);
        updateDataset((current) => {
          const conversationsByWorkspace = {
            ...Object.fromEntries(
              Object.entries(current.conversationsByWorkspace).filter(([targetWorkspaceId]) =>
                validWorkspaceIds.has(targetWorkspaceId),
              ),
            ),
            ...Object.fromEntries(
              currentConversationResults.map((result) => {
                const currentRows = current.conversationsByWorkspace[result.workspaceId] ?? [];
                return [
                  result.workspaceId,
                  reconcileWorkspaceConversationRowsAfterRefresh(
                    currentRows,
                    mergeConversationListWithCurrentRunAuthority(result.conversations, currentRows),
                    result.error,
                  ),
                ];
              }),
            ),
          };
          const workspaceNodeState = {
            ...Object.fromEntries(
              Object.entries(current.nodeState.workspaces).filter(([targetWorkspaceId]) =>
                validWorkspaceIds.has(targetWorkspaceId),
              ),
            ),
            ...Object.fromEntries(
              currentConversationResults.map((result) => [
                result.workspaceId,
                { loading: false, error: result.error },
              ]),
            ),
          };
          const nextDataset = {
            workspaces,
            workspacesByProject,
            conversationsByWorkspace,
            nodeState: { projects: projectNodeState, workspaces: workspaceNodeState },
            messages,
            tasks,
            plan,
            workspaceMembers,
            workspaceAgents,
            sandbox: null,
            myWork: myWorkResult.items,
            myWorkError: myWorkResult.error,
          } satisfies RuntimeDataset;
          return nextDataset;
        });
        for (const result of currentConversationResults) {
          if (result.error !== null) continue;
          clearMissingConversationSelection(
            selectionAtRequest,
            agentConversationScopeKeyFor(resolvedProjectId, result.workspaceId),
            result.conversations,
          );
        }
        const committedExpandedWorkspaceIds = reconcileExpandedWorkspaceIds(
          expandedWorkspaceIdsRef.current,
          projectWorkspaces.map((workspace) => workspace.id),
          workspaceId,
          expandSelectedWorkspace,
        );
        expandedWorkspaceIdsRef.current = committedExpandedWorkspaceIds;
        setExpandedWorkspaceIds(committedExpandedWorkspaceIds);
        if (workspaceId) workspaceExpansionScopeRef.current = expansionScope;
        if (runtimeRefreshRequestRef.current === refreshRequestGeneration) {
          activeRuntimeConversationRequestsRef.current = new Map();
        }
        setConnection('ready');
        setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
        return true;
      } catch (caught) {
        if (!contextIsCurrent()) return false;
        const connectionError = formatConnectionError(caught, nextConfig.apiBaseUrl);
        updateDataset((current) => {
          const failedWorkspaceNodeState = { ...current.nodeState.workspaces };
          for (const [workspaceId, generation] of conversationRequestGenerations) {
            if (
              isCurrentWorkspaceConversationRequest(
                workspaceConversationRequestGenerationsRef.current,
                workspaceId,
                generation,
              )
            ) {
              failedWorkspaceNodeState[workspaceId] = {
                loading: false,
                error: connectionError,
              };
            }
          }
          return {
            ...current,
            nodeState: {
              ...workspaceTreeRefreshFailed(
                current.nodeState,
                refreshProjectId,
                connectionError,
              ),
              workspaces: failedWorkspaceNodeState,
            },
            workspaceMembers: failLoadingWorkspaceAuthority(
              current.workspaceMembers,
              connectionError,
            ),
            workspaceAgents: failLoadingWorkspaceAuthority(
              current.workspaceAgents,
              connectionError,
            ),
          };
        });
        activeRuntimeConversationRequestsRef.current = new Map();
        setConnection('error');
        setError(connectionError);
        return false;
      }
    },
    [
      auth.projects,
      auth.status,
      auth.tenants,
      clearMissingConversationSelection,
      commitRuntimeConfig,
      config,
      syncLocalRuntimeConfig,
      t,
      updateDataset,
    ],
  );

  const loadWorkspaceConversations = useCallback(async (workspaceId: string) => {
    const requestConfig = configRef.current;
    const projectId = requestConfig.projectId.trim();
    const tenantId = requestConfig.tenantId.trim();
    const currentDataset = datasetRef.current;
    const workspaceExists = (currentDataset.workspacesByProject[projectId] ?? []).some(
      (workspace) => workspace.id === workspaceId,
    );
    if (!tenantId || !projectId || !workspaceExists) return;
    if (!shouldLoadWorkspaceConversations(currentDataset.nodeState.workspaces[workspaceId])) {
      return;
    }
    const selectionAtRequest = agentConversationSelectionIdentity(
      agentConversationSessionRef.current,
    );

    const requestGeneration = beginWorkspaceConversationRequest(
      workspaceConversationRequestGenerationsRef.current,
      workspaceId,
    );
    const expectedContextRevision = contextRevisionRef.current;
    const requestIsCurrent = () =>
      isCurrentContextRevision(expectedContextRevision, contextRevisionRef.current) &&
      isSameDesktopProjectRequestScope(requestConfig, configRef.current) &&
      isCurrentWorkspaceConversationRequest(
        workspaceConversationRequestGenerationsRef.current,
        workspaceId,
        requestGeneration,
      );
    updateDataset((current) => ({
      ...current,
      nodeState: {
        ...current.nodeState,
        workspaces: {
          ...current.nodeState.workspaces,
          [workspaceId]: { loading: true, error: null },
        },
      },
    }));

    try {
      const client = new DesktopApiClient({ ...requestConfig, workspaceId });
      const response = await client.listConversations(projectId, workspaceId);
      if (!requestIsCurrent()) return;
      updateDataset((current) => {
        if (
          !requestIsCurrent() ||
          !(current.workspacesByProject[projectId] ?? []).some(
            (workspace) => workspace.id === workspaceId,
          )
        ) {
          return current;
        }
        const nextDataset: RuntimeDataset = {
          ...current,
          conversationsByWorkspace: {
            ...current.conversationsByWorkspace,
            [workspaceId]: mergeConversationListWithCurrentRunAuthority(
              response.items,
              current.conversationsByWorkspace[workspaceId] ?? [],
            ),
          },
          nodeState: {
            ...current.nodeState,
            workspaces: {
              ...current.nodeState.workspaces,
              [workspaceId]: { loading: false, error: null },
            },
          },
        };
        return nextDataset;
      });
      clearMissingConversationSelection(
        selectionAtRequest,
        agentConversationScopeKeyFor(projectId, workspaceId),
        response.items,
      );
    } catch (caught) {
      if (!requestIsCurrent()) return;
      updateDataset((current) => {
        if (
          !requestIsCurrent() ||
          !(current.workspacesByProject[projectId] ?? []).some(
            (workspace) => workspace.id === workspaceId,
          )
        ) {
          return current;
        }
        const nextDataset: RuntimeDataset = {
          ...current,
          nodeState: {
            ...current.nodeState,
            workspaces: {
              ...current.nodeState.workspaces,
              [workspaceId]: { loading: false, error: formatError(caught) },
            },
          },
        };
        return nextDataset;
      });
    }
  }, [clearMissingConversationSelection, updateDataset]);

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

  const hydrateCloudSession = async (
    outcome: LoginOutcome,
    runtimeConfig: DesktopRuntimeConfig,
    authAttemptRevision: number,
  ): Promise<boolean> => {
    const tokenConfig = { ...runtimeConfig, apiKey: outcome.access_token, workspaceId: '' };
    const identityClient = new DesktopApiClient(tokenConfig);
    const [user, tenants, authoritativeContextResponse] = await Promise.all([
      identityClient.currentUser(),
      identityClient.listTenants(),
      identityClient.getWorkspaceContext().catch((caught) => {
        if (isWorkspaceContextUnavailableError(caught)) return null;
        throw caught;
      }),
    ]);
    if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
    if (!authoritativeContextResponse) {
      const nextConfig = {
        ...tokenConfig,
        tenantId: '',
        projectId: '',
        workspaceId: '',
      };
      contextRevisionRef.current = 0;
      resetProjectScopedState();
      commitRuntimeConfig(nextConfig);
      setAuth({
        status: 'signed_in',
        credentialKind: 'cloud_session',
        session: outcome.session ?? null,
        context: null,
        user,
        tenants,
        projects: [],
        mustChangePassword: outcome.must_change_password,
        error: null,
      });
      setLoginPassword('');
      setDataset(emptyDataset);
      setConnection('idle');
      setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      applySectionSideEffects('workspace');
      setSettingsInitialSection('workspace');
      setSettingsWindowOpen(true);
      return true;
    }
    const authoritativeContext = authoritativeContextResponse.context;
    const tenantId = authoritativeContext.tenant_id;
    const projectClient = new DesktopApiClient({ ...tokenConfig, tenantId });
    const projects = tenantId ? await projectClient.listProjects(tenantId) : [];
    if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
    if (tenantId && !tenants.some((tenant) => tenant.id === tenantId)) {
      throw new Error(t('login.authenticatedTenantUnavailable'));
    }
    const scopedProjects = projects.filter((project) => project.tenant_id === tenantId);
    const preferredProjectId = authoritativeContext.project_id;
    const preferredProject = findWorkspaceProject(
      scopedProjects,
      tenantId,
      preferredProjectId,
    );
    const projectId = preferredProject?.id ?? '';
    if (!workspaceContextMatchesSelection(authoritativeContext, tenantId, projectId)) {
      throw new Error(t('login.authoritativeProjectUnavailable'));
    }
    const context = authoritativeContext;
    if (!workspaceContextMatchesSelection(context, tenantId, projectId)) {
      throw new Error(t('login.authenticatedContextMismatch'));
    }
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
      projects: scopedProjects,
      mustChangePassword: outcome.must_change_password,
      error: null,
    });
    setLoginPassword('');

    if (projectId) {
      await refreshRuntime(nextConfig, scopedProjects);
      if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
      applySectionSideEffects('workspace');
    } else {
      setDataset(emptyDataset);
      setConnection('idle');
      setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      applySectionSideEffects('workspace');
      setSettingsInitialSection('workspace');
      setSettingsWindowOpen(true);
    }
    return true;
  };

  const deviceAuthAttemptIsCurrent = (
    attemptId: number,
    authRevision: number,
    controller: AbortController,
  ): boolean => {
    const current = deviceAuthAttemptRef.current;
    return Boolean(
      current?.attemptId === attemptId &&
        current.authRevision === authRevision &&
        authAttemptRevisionRef.current === authRevision &&
        !controller.signal.aborted,
    );
  };

  const supersedeWorkspaceSsoAttempt = (clearPresentation = true) => {
    deviceAuthAttemptRef.current?.controller.abort();
    deviceAuthAttemptRef.current = null;
    if (clearPresentation) setWorkspaceSso(null);
  };

  const revokeUnadoptedDeviceToken = async (
    accessToken: string,
    runtimeConfig: DesktopRuntimeConfig,
  ): Promise<void> => {
    if (!accessToken) return;
    try {
      await new DesktopApiClient({ ...runtimeConfig, apiKey: accessToken }).signOut();
    } catch {
      // Best effort only. Device-grant cancellation below independently retries revocation.
    }
  };

  const cancelIssuedDeviceCodeBestEffort = async (
    deviceCode: string,
    runtimeConfig: DesktopRuntimeConfig,
  ): Promise<void> => {
    if (!deviceCode) return;
    const cancelController = new AbortController();
    const timeoutId = window.setTimeout(() => cancelController.abort(), 3_000);
    try {
      const cancelClient = new DesktopApiClient({ ...runtimeConfig, apiKey: '' });
      await cancelClient.cancelDeviceCode(deviceCode, cancelController.signal);
    } catch {
      // Best effort only. Pending grants expire, and an issued bearer is revoked separately above.
    } finally {
      window.clearTimeout(timeoutId);
    }
  };

  const openWorkspaceSsoUrl = async (
    authorizationUrl: string,
    expectedUserCode: string,
    apiBaseUrl: string,
    attemptId: number,
    authRevision: number,
  ): Promise<void> => {
    const current = deviceAuthAttemptRef.current;
    if (
      current?.attemptId !== attemptId ||
      current.authRevision !== authRevision ||
      current.authorizationUrl !== authorizationUrl ||
      current.userCode !== expectedUserCode ||
      current.openInFlight
    ) {
      return;
    }
    current.openInFlight = true;
    try {
      const invoke = window.__TAURI__?.core?.invoke;
      if (runsInTauri && invoke) {
        await invoke('open_device_authorization_url', {
          url: authorizationUrl,
          apiBaseUrl,
          expectedUserCode,
        });
      } else {
        const opened = window.open('about:blank', '_blank');
        if (!opened) throw new Error('popup_blocked');
        try {
          opened.opener = null;
          opened.location.replace(authorizationUrl);
        } catch (error) {
          opened.close();
          throw error;
        }
      }
      if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, current.controller)) return;
      setWorkspaceSso((presentation) =>
        presentation?.authorizationUrl === authorizationUrl
          ? { ...presentation, openError: null }
          : presentation,
      );
    } catch {
      if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, current.controller)) return;
      setWorkspaceSso((presentation) =>
        presentation?.authorizationUrl === authorizationUrl
          ? { ...presentation, openError: t('login.deviceOpenFailed') }
          : presentation,
      );
    } finally {
      const activeAttempt = deviceAuthAttemptRef.current;
      if (activeAttempt?.attemptId === attemptId) activeAttempt.openInFlight = false;
    }
  };

  const openCurrentWorkspaceSso = () => {
    const current = deviceAuthAttemptRef.current;
    if (!current?.authorizationUrl) return;
    void openWorkspaceSsoUrl(
      current.authorizationUrl,
      current.userCode,
      configRef.current.apiBaseUrl,
      current.attemptId,
      current.authRevision,
    );
  };

  const cancelWorkspaceSso = () => {
    const current = deviceAuthAttemptRef.current;
    if (!current) {
      setWorkspaceSso(null);
      return;
    }
    authAttemptRevisionRef.current += 1;
    supersedeWorkspaceSsoAttempt();
    setAuth(emptyAuthState);
    setConnection('idle');
    setError(null);
  };

  const loginWithWorkspaceSso = async (trustedDevice: boolean) => {
    const runtimeConfig = configRef.current;
    if (runtimeConfig.mode !== 'cloud') return;

    const preserveExpiredPresentation = Boolean(
      workspaceSso && workspaceSso.expiresAt <= Date.now(),
    );
    supersedeWorkspaceSsoAttempt(!preserveExpiredPresentation);
    const authRevision = ++authAttemptRevisionRef.current;
    const attemptId = ++deviceAuthAttemptIdRef.current;
    const controller = new AbortController();
    deviceAuthAttemptRef.current = {
      attemptId,
      authRevision,
      controller,
      authorizationUrl: '',
      userCode: '',
      openInFlight: false,
    };
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);

    let issuedDeviceCode = '';
    let issuedAccessToken = '';
    let tokenAdopted = false;
    let keepExpiredPresentation = false;
    try {
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          throw new WorkspaceSsoFlowError('credential_store');
        }
        if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;
      }

      const loginClient = new DesktopApiClient({ ...runtimeConfig, apiKey: '' });
      const deviceAuthorization = await loginClient.createDeviceCode(controller.signal);
      issuedDeviceCode = deviceAuthorization.device_code;
      if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;

      const authorizationUrl = resolveDeviceAuthorizationUrl(
        runtimeConfig.apiBaseUrl,
        deviceAuthorization.verification_uri_complete,
        deviceAuthorization.user_code,
      );
      if (!authorizationUrl) throw new WorkspaceSsoFlowError('invalid_url');

      const activeAttempt = deviceAuthAttemptRef.current;
      if (!activeAttempt || activeAttempt.attemptId !== attemptId) return;
      activeAttempt.authorizationUrl = authorizationUrl;
      activeAttempt.userCode = deviceAuthorization.user_code;
      const deadline = Date.now() + deviceAuthorization.expires_in * 1000;
      setWorkspaceSso({
        userCode: deviceAuthorization.user_code,
        authorizationUrl,
        expiresAt: deadline,
        openError: null,
      });
      void openWorkspaceSsoUrl(
        authorizationUrl,
        deviceAuthorization.user_code,
        runtimeConfig.apiBaseUrl,
        attemptId,
        authRevision,
      );

      let intervalSeconds = normalizeDeviceAuthorizationInterval(deviceAuthorization.interval);
      while (deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
        const remainingMs = deadline - Date.now();
        if (remainingMs <= 0) {
          throw new WorkspaceSsoFlowError('expired');
        }
        const waited = await waitForAbortableDelay(
          Math.min(remainingMs, intervalSeconds * 1000),
          controller.signal,
        );
        if (!waited || !deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;

        try {
          const token = await loginClient.pollDeviceToken(
            deviceAuthorization.device_code,
            controller.signal,
          );
          issuedAccessToken = token.access_token;
          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;
          setWorkspaceSso(null);

          const hydrated = await hydrateCloudSession(
            {
              access_token: token.access_token,
              token_type: token.token_type,
              must_change_password: false,
            },
            runtimeConfig,
            authRevision,
          );
          if (!hydrated || !deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;

          let persistenceWarning: string | null = null;
          let persistedNativeSession = false;
          if (trustedDevice && hasNativeTrustedSessionBroker()) {
            try {
              await saveNativeTrustedSession({
                version: 1,
                api_base_url: runtimeConfig.apiBaseUrl,
                runtime_mode: 'cloud',
                credential_kind: 'cloud_bearer',
                credential: token.access_token,
                expires_at: null,
              });
              persistedNativeSession = true;
            } catch {
              persistenceWarning = t('login.persistenceUnavailable');
            }
          }
          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) {
            if (persistedNativeSession) {
              try {
                await clearNativeTrustedSession();
              } catch {
                // The issued cloud credential is revoked in finally, so a stale broker record
                // cannot recover an authenticated session even if this best-effort clear fails.
              }
            }
            return;
          }
          tokenAdopted = true;
          deviceAuthAttemptRef.current = null;
          controller.abort();
          if (persistenceWarning) setError(persistenceWarning);
          return;
        } catch (caught) {
          if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;
          const deviceError = classifyDeviceTokenError(caught);
          if (deviceError?.code === 'authorization_pending') {
            intervalSeconds = normalizeDeviceAuthorizationInterval(deviceError.interval);
            continue;
          }
          if (deviceError?.code === 'expired_token') {
            throw new WorkspaceSsoFlowError('expired');
          }
          throw caught;
        }
      }
    } catch (caught) {
      if (!deviceAuthAttemptIsCurrent(attemptId, authRevision, controller)) return;
      if (caught instanceof WorkspaceSsoFlowError && caught.code === 'expired') {
        keepExpiredPresentation = true;
        setWorkspaceSso((presentation) =>
          presentation ? { ...presentation, expiresAt: Date.now(), openError: null } : presentation,
        );
        setAuth(emptyAuthState);
        setConnection('idle');
        setError(null);
        return;
      }
      const message =
        caught instanceof WorkspaceSsoFlowError && caught.code === 'invalid_url'
          ? t('login.deviceInvalidUrl')
          : caught instanceof WorkspaceSsoFlowError && caught.code === 'credential_store'
            ? t('login.credentialStoreUnavailable')
            : t('login.workspaceSsoFailed');
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    } finally {
      if (issuedAccessToken && !tokenAdopted) {
        await revokeUnadoptedDeviceToken(issuedAccessToken, runtimeConfig);
      }
      if (issuedDeviceCode && !tokenAdopted) {
        await cancelIssuedDeviceCodeBestEffort(issuedDeviceCode, runtimeConfig);
      }
      const current = deviceAuthAttemptRef.current;
      if (current?.attemptId === attemptId) {
        current.controller.abort();
        deviceAuthAttemptRef.current = null;
        if (!keepExpiredPresentation) setWorkspaceSso(null);
      }
    }
  };

  const login = async (trustedDevice: boolean) => {
    supersedeWorkspaceSsoAttempt();
    const username = loginEmail.trim();
    if (!username || !loginPassword) return;

    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    let persistenceWarning: string | null = null;
    try {
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          // An uncleared record may belong to another identity. Fail closed before account switch.
          throw new Error(t('login.credentialStoreUnavailable'));
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const loginClient = new DesktopApiClient({ ...config, apiKey: '' });
      const outcome = await loginClient.login(username, loginPassword);
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      if (outcome.must_change_password) {
        throw new Error(t('login.passwordChangeRequired'));
      }
      if (trustedDevice && hasNativeTrustedSessionBroker()) {
        const trustedSession: NativeTrustedSession = {
          version: 1,
          api_base_url: config.apiBaseUrl,
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: outcome.access_token,
          expires_at: outcome.session?.expires_at ?? null,
        };
        try {
          await saveNativeTrustedSession(trustedSession);
        } catch {
          persistenceWarning = t('login.persistenceUnavailable');
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const hydrated = await hydrateCloudSession(outcome, config, authAttemptRevision);
      if (!hydrated) return;
      if (persistenceWarning) setError(persistenceWarning);
    } catch (caught) {
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          // Preserve the original authentication failure without exposing credential-store detail.
        }
      }
      const message = formatLoginError(caught, config.apiBaseUrl);
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    }
  };

  const hydrateLocalSession = async (
    outcome: LoginOutcome,
    runtimeConfig: DesktopRuntimeConfig,
    authAttemptRevision: number,
  ): Promise<boolean> => {
    if (!outcome.context) {
      throw new Error(t('login.localContextMissing'));
    }
    const localContext = outcome.context;
    const tokenConfig = {
      ...runtimeConfig,
      apiKey: outcome.access_token,
      tenantId: localContext.tenant_id,
      projectId: localContext.project_id,
      workspaceId: '',
    };
    const identityClient = new DesktopApiClient(tokenConfig);
    const [user, tenants, projects] = await Promise.all([
      identityClient.currentUser(),
      identityClient.listTenants(),
      identityClient.listProjects(localContext.tenant_id),
    ]);
    if (authAttemptRevisionRef.current !== authAttemptRevision) return false;
    if (!tenants.some((tenant) => tenant.id === localContext.tenant_id)) {
      throw new Error(t('login.localTenantUnavailable'));
    }
    const scopedProjects = projects.filter(
      (project) => project.tenant_id === localContext.tenant_id,
    );
    const selectedProject = findWorkspaceProject(
      scopedProjects,
      localContext.tenant_id,
      localContext.project_id,
    );
    if (!selectedProject) {
      throw new Error(t('login.localProjectUnavailable'));
    }

    contextRevisionRef.current = localContext.revision;
    resetProjectScopedState();
    commitRuntimeConfig(tokenConfig);
    setAuth({
      status: 'signed_in',
      credentialKind: 'local_session',
      session: outcome.session ?? null,
      context: localContext,
      user,
      tenants,
      projects: scopedProjects,
      mustChangePassword: false,
      error: null,
    });
    await refreshRuntime(tokenConfig, [selectedProject]);
    return authAttemptRevisionRef.current === authAttemptRevision;
  };

  const loginLocalSession = async (trustedDevice: boolean) => {
    supersedeWorkspaceSsoAttempt();
    if (!localRuntimeAuthorityReady) {
      setAuth((current) => ({
        ...current,
        error: t('login.localRuntimeNotReady'),
      }));
      return;
    }

    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    let persistenceWarning: string | null = null;
    try {
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          // An uncleared record may belong to another identity. Fail closed before account switch.
          throw new Error(t('login.credentialStoreUnavailable'));
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const bootstrapClient = new DesktopApiClient({ ...config, apiKey: '' });
      const outcome = await bootstrapClient.createLocalSession(trustedDevice);
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      const sessionId = outcome.session?.session_id?.trim();
      if (trustedDevice && hasNativeTrustedSessionBroker() && sessionId) {
        const trustedSession: NativeTrustedSession = {
          version: 1,
          api_base_url: config.apiBaseUrl,
          runtime_mode: 'local',
          credential_kind: 'local_session_reference',
          credential: sessionId,
          expires_at: outcome.session?.expires_at ?? null,
        };
        try {
          await saveNativeTrustedSession(trustedSession);
        } catch {
          persistenceWarning = t('login.persistenceUnavailable');
        }
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      }
      const hydrated = await hydrateLocalSession(outcome, config, authAttemptRevision);
      if (!hydrated) return;
      applySectionSideEffects('workspace');
      if (persistenceWarning) setError(persistenceWarning);
    } catch (caught) {
      if (authAttemptRevisionRef.current !== authAttemptRevision) return;
      if (hasNativeTrustedSessionBroker()) {
        try {
          await clearNativeTrustedSession();
        } catch {
          // Preserve the original authentication failure without exposing credential-store detail.
        }
      }
      const message = formatLoginError(caught, config.apiBaseUrl);
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    }
  };

  const handleConfigChange = (nextConfig: DesktopRuntimeConfig) => {
    const previousConfig = configRef.current;
    const transportIdentityChanged = runtimeTransportIdentityChanged(
      previousConfig,
      nextConfig,
    );
    const transportSafeConfig = transportIdentityChanged
      ? { ...nextConfig, apiKey: '', localApiToken: '' }
      : nextConfig;
    const resolvedConfig =
      transportSafeConfig.mode === 'local'
        ? {
            ...transportSafeConfig,
            tenantId: transportSafeConfig.tenantId.trim() || 'local',
            projectId: transportSafeConfig.projectId.trim() || 'local-project',
          }
        : transportSafeConfig;
    const requestScopeChanged = !isSameDesktopRequestScope(previousConfig, resolvedConfig);
    if (transportIdentityChanged) {
      supersedeWorkspaceSsoAttempt();
      const authAttemptRevision = ++authAttemptRevisionRef.current;
      localResumeAttemptRef.current = '';
      setAuth(emptyAuthState);
      if (hasNativeTrustedSessionBroker()) {
        void clearNativeTrustedSession().catch(() => {
          if (authAttemptRevisionRef.current === authAttemptRevision) {
            setError(t('login.persistenceUnavailable'));
          }
        });
      }
    }
    commitRuntimeConfig(resolvedConfig);
    if (requestScopeChanged) {
      resetProjectScopedState();
      return;
    }
    setConnection('idle');
    setAgentConversationSession(null);
    resetConversationTimeline();
    setAgentTaskSignals([]);
  };

  const useApiKeyManually = () => {
    setLoginModalOpen(false);
    setAuth((current) => ({
      ...current,
      error: t('login.manualApiKeyRequiresValidation'),
    }));
  };

  const logout = async () => {
    supersedeWorkspaceSsoAttempt();
    const authAttemptRevision = ++authAttemptRevisionRef.current;
    localResumeAttemptRef.current = '';
    const authenticatedClient = api;
    const shouldRevoke = Boolean(config.apiKey.trim());
    const hasCredentialBroker = hasNativeTrustedSessionBroker();
    const [credentialRevoked, persistedCredentialCleared] = await Promise.all([
      shouldRevoke
        ? authenticatedClient
            .signOut()
            .then((outcome) => outcome.success === true)
            .catch(() => false)
        : Promise.resolve(false),
      hasCredentialBroker
        ? clearNativeTrustedSession()
            .then(() => true)
            .catch(() => false)
        : Promise.resolve(true),
    ]);
    if (authAttemptRevisionRef.current !== authAttemptRevision) return;
    const signOutDisposition = resolveSignOutDisposition(
      hasCredentialBroker,
      persistedCredentialCleared,
      credentialRevoked,
    );
    if (signOutDisposition === 'blocked') {
      setError(t('login.signOutPersistenceFailed'));
      return;
    }
    const persistenceWarning =
      signOutDisposition === 'complete_with_persistence_warning'
        ? t('login.signOutPersistenceWarning')
        : null;
    localResumeAttemptRef.current = `${config.mode}|${config.apiBaseUrl}|${config.localApiToken}`;
    contextRevisionRef.current += 1;
    setAuth(persistenceWarning ? { ...emptyAuthState, error: persistenceWarning } : emptyAuthState);
    setLoginModalOpen(false);
    commitRuntimeConfig({
      ...DEFAULT_CONFIG,
      apiBaseUrl: config.apiBaseUrl,
      localApiToken: config.localApiToken,
      mode: config.mode,
      workspaceRoot: config.workspaceRoot,
    });
    resetProjectScopedState();
    setSectionBackStack([]);
    setSectionForwardStack([]);
    activeSectionRef.current = 'workspace';
    setActiveSection('workspace');
    setStatusTab('overview');
    setError(persistenceWarning);
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
    resetConversationTimeline();
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
    const requiresRuntimeRefresh = sessionSelectionRequiresRuntimeRefresh(
      configRef.current,
      nextConfig,
    );
    commitRuntimeConfig(nextConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(projectId, workspaceId),
      conversation,
    });
    setAgentTaskSignals([]);
    setReviewTab('overview');
    setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
    applySectionSideEffects(targetSection);
    void loadConversationTimeline(conversation, projectId, nextConfig);
    if (requiresRuntimeRefresh) void refreshRuntime(nextConfig);
  };

  const openNewTask = (
    workspaceId = config.workspaceId,
    resumeDraft: NewTaskResumeDraft | null = null,
  ) => {
    setError(null);
    setLoginModalOpen(false);
    setCommandPaletteOpen(false);
    setCommandQuery('');
    setNewTaskPreferredWorkspaceId(workspaceId);
    setNewTaskResumeDraft(resumeDraft);
    setNewTaskOpen(true);
  };

  const startNewSession = () => openNewTask();

  const resumeSessionTaskListReview = () => {
    const projection = sessionProjection;
    if (
      projection?.planAuthority.kind !== 'agent_task_list' ||
      !sessionTaskListPlanRecovery?.canResume
    ) {
      setError(t('session.authorityActionUnavailable'));
      return;
    }
    const conversation = projection.conversation;
    const workspaceId = conversation.workspace_id?.trim() || config.workspaceId.trim();
    const workspace = (
      dataset.workspacesByProject[conversation.project_id] ?? dataset.workspaces
    ).find((item) => item.id === workspaceId);
    const tasks = sessionTaskListPlanRecovery.tasks;
    if (!workspace || !workspaceId || !tasks) {
      setError(t('session.authorityActionUnavailable'));
      return;
    }
    const capabilityMode = conversation.agent_config?.capability_mode;
    const kind =
      capabilityMode === 'code' || conversation.conversation_mode === 'code'
        ? 'programming'
        : 'general';
    const sessionConfig = {
      ...config,
      tenantId: conversation.tenant_id || config.tenantId,
      projectId: conversation.project_id,
      workspaceId,
    };
    const resumeDraft: NewTaskResumeDraft = {
      session: { workspace, conversation, config: sessionConfig },
      definition: {
        title: conversation.title,
        objective:
          conversation.summary?.trim() ||
          workspace.description?.trim() ||
          conversation.title,
        kind,
        workspaceRoot: config.workspaceRoot,
        contextSources: ['project_memory', 'project_files'],
      },
      tasks,
    };
    openNewTask(workspaceId, resumeDraft);
  };

  const persistNewTaskSession = (session: NewTaskSession) => {
    const { workspace, conversation, config: sessionConfig } = session;
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
  };

  const activateNewTaskSession = (session: NewTaskSession) => {
    const { workspace, conversation, config: sessionConfig } = session;
    setSelectedTaskId('');
    resetConversationTimeline();
    setAgentTaskSignals([]);
    setStatusTab('overview');
    setReviewTab('plan');
    setSectionBackStack([]);
    setSectionForwardStack([]);
    persistNewTaskSession(session);
    commitRuntimeConfig(sessionConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(sessionConfig.projectId, workspace.id),
      conversation,
    });
    setExpandedWorkspaceIds((current) => new Set([...current, workspace.id]));
    applySectionSideEffects('chat');
    void loadConversationTimeline(conversation, sessionConfig.projectId);
  };

  const runNewTaskAgentTurn = async (
    input: NewTaskAgentTurnInput,
  ): Promise<NewTaskAgentTurnOutcome> => {
    const acknowledgment = new Promise<NewTaskAgentTurnOutcome>((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        pendingNewTaskAgentTurnsRef.current.delete(input.messageId);
        resolve('unknown_outcome');
      }, 10_000);
      pendingNewTaskAgentTurnsRef.current.set(input.messageId, {
        conversationId: input.conversationId,
        messageId: input.messageId,
        timeoutId,
        resolve,
        reject,
      });
    });
    const clearPendingAgentTurn = () => {
      const pending = pendingNewTaskAgentTurnsRef.current.get(input.messageId);
      if (!pending) return;
      window.clearTimeout(pending.timeoutId);
      pendingNewTaskAgentTurnsRef.current.delete(input.messageId);
    };
    const queued = socket.sendAgentMessage({
      conversationId: input.conversationId,
      projectId: input.projectId,
      message: input.message,
      messageId: input.messageId,
    });
    const transport = newTaskAgentTurnTransport(input.config.mode, queued);
    if (transport === 'socket') {
      return acknowledgment;
    }
    clearPendingAgentTurn();
    if (transport === 'local_http') {
      const client = new DesktopApiClient(input.config);
      await client.runAgentMessage(
        input.conversationId,
        input.message,
        input.messageId,
        input.projectId,
      );
      return 'acknowledged';
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

  const sendMessageContentRef = useRef(sendMessageContent);
  sendMessageContentRef.current = sendMessageContent;
  const sendChatMessage = useCallback(
    (content: string, onWorkspaceMessageSaved?: () => void) => {
      void sendMessageContentRef.current(content, onWorkspaceMessageSaved);
    },
    [],
  );

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
    activeSection === 'board'
      ? 'pane-stage single-stage my-work-stage'
      : activeSection === 'home' || activeSection === 'automations' || activeSection === 'search'
        ? 'pane-stage single-stage auxiliary-stage'
        : 'pane-stage single-stage';
  const configuredProject = useMemo(
    () => projectSummaryFromConfig(config),
    [config.projectId, config.tenantId],
  );
  const sidebarProjects = useMemo(() => {
    if (auth.status === 'signed_in') return auth.projects;
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
  const myWorkCounts = useMemo(() => countMyWorkGroups(dataset.myWork), [dataset.myWork]);
  const myWorkMetricStatus =
    connection === 'loading' || myWorkRefreshing
      ? 'loading'
      : dataset.myWorkError
        ? 'error'
        : 'ready';
  const auxiliaryUserName =
    auth.user?.name?.trim().split(/\s+/)[0] ||
    auth.user?.email?.split('@')[0] ||
    t('sidebar.account');
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
  currentArtifactRunRef.current = currentArtifactRun;
  const sessionActivityStructuredEvidence = useMemo(() => {
    const summary = sessionProjection?.evidenceSummary;
    if (
      !currentArtifactRun ||
      !summary ||
      typeof summary.artifactVersionCount !== 'number' ||
      typeof summary.toolInvocationCount !== 'number'
    ) {
      return null;
    }
    return {
      artifactCount: summary.artifactVersionCount,
      checkCount: summary.checks?.total ?? null,
      toolActivityCount: summary.toolInvocationCount,
    };
  }, [currentArtifactRun, sessionProjection?.evidenceSummary]);
  const sessionActivityState = sessionActivityPresence(
    currentArtifactRun?.status ?? null,
    socket.connected,
  );
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
  const approveSessionPlan = useCallback(
    async (plan: SessionProjectionPlan, selection: SessionPlanApprovalSelection) => {
      const authoritativeProjection = sessionProjection;
      const authoritativePlan = authoritativeProjection?.currentPlan ?? null;
      const capabilities = authoritativeProjection?.capabilities ?? null;
      const conversation = authoritativeProjection?.conversation ?? null;
      if (
        authoritativeProjection?.planAuthority.kind !== 'desktop_plan_version' ||
        !authoritativePlan ||
        authoritativePlan.id !== plan.id ||
        authoritativePlan.version !== plan.version ||
        authoritativePlan.status !== plan.status ||
        !conversation ||
        !canApproveSessionPlan(authoritativePlan, capabilities)
      ) {
        setError(t('session.authorityActionUnavailable'));
        return;
      }

      const identity = sessionPlanApprovalIdentity({
        conversationId: conversation.id,
        plan: authoritativePlan,
        ...selection,
      });
      if (sessionPlanApprovalAttemptRef.current?.identity !== identity) {
        sessionPlanApprovalAttemptRef.current = {
          identity,
          requestId: globalThis.crypto.randomUUID(),
        };
      }
      const requestId = sessionPlanApprovalAttemptRef.current.requestId;
      setSessionPlanApprovalPending(true);
      setError(null);
      try {
        const outcome = await api.approvePlanAndStart(
          sessionPlanApprovalRequest({
            conversationId: conversation.id,
            projectId: conversation.project_id,
            plan: authoritativePlan,
            requestId,
            ...selection,
          }),
        );
        const nextConversation = conversationWithAuthoritativeRun(
          outcome.conversation,
          outcome.run,
        );
        const workspaceId = nextConversation.workspace_id ?? config.workspaceId.trim();
        if (workspaceId) {
          selectConversation(
            nextConversation.project_id,
            workspaceId,
            nextConversation,
            'chat',
          );
        } else {
          setAgentConversationSession((current) =>
            current?.conversation.id === nextConversation.id
              ? { ...current, conversation: nextConversation }
              : current,
          );
          applySectionSideEffects('chat');
          void loadConversationTimeline(nextConversation, nextConversation.project_id);
        }
        applyAuthoritativeRun(outcome.run);
        invalidateSessionAuthority();
      } catch (caught) {
        setError(formatConnectionError(caught, config.apiBaseUrl));
      } finally {
        setSessionPlanApprovalPending(false);
      }
    },
    [
      api,
      applyAuthoritativeRun,
      config.apiBaseUrl,
      config.workspaceId,
      invalidateSessionAuthority,
      sessionProjection,
      t,
    ],
  );
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
  const localRuntimeProviderLabel =
    runtimeProvider?.provider_type.trim() || t('providers.notAvailable');
  const localRuntimeModelLabel =
    runtimeProvider?.model.trim() || t('providers.notAvailable');
  const runtimeMonitorHealthMetrics = [
    {
      label: 'Provider',
      value: config.mode === 'local' ? localRuntimeProviderLabel : config.mode,
    },
    {
      label: 'Model',
      value: config.mode === 'local' ? localRuntimeModelLabel : 'server managed',
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
  const toggleWorkspace = (workspaceId: string) => {
    const wasExpanded = expandedWorkspaceIds.has(workspaceId);
    setExpandedWorkspaceIds((current) => {
      const next = new Set(current);
      if (next.has(workspaceId)) next.delete(workspaceId);
      else next.add(workspaceId);
      expandedWorkspaceIdsRef.current = next;
      return next;
    });
    if (!wasExpanded) void loadWorkspaceConversations(workspaceId);
  };

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
    if (!runsInTauri || auth.status !== 'signed_out' || !hasNativeTrustedSessionBroker()) return;
    const attemptKey = `${config.mode}|${config.apiBaseUrl}|${config.localApiToken}`;
    if (localResumeAttemptRef.current === attemptKey) return;
    localResumeAttemptRef.current = attemptKey;
    const authAttemptRevision = ++authAttemptRevisionRef.current;

    void (async () => {
      try {
        const trustedSession = await loadNativeTrustedSession();
        if (!trustedSession) return;
        if (
          localResumeAttemptRef.current !== attemptKey ||
          authAttemptRevisionRef.current !== authAttemptRevision
        ) {
          return;
        }

        setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
        setConnection('loading');
        setError(null);

        if (trustedSession.credential_kind === 'cloud_bearer') {
          if (trustedSession.runtime_mode !== 'cloud') {
            await clearNativeTrustedSession();
            if (authAttemptRevisionRef.current !== authAttemptRevision) return;
            setAuth(emptyAuthState);
            setConnection('idle');
            return;
          }
          const restoredConfig: DesktopRuntimeConfig = {
            ...config,
            apiBaseUrl: trustedSession.api_base_url,
            apiKey: trustedSession.credential,
            tenantId: '',
            projectId: '',
            workspaceId: '',
            mode: 'cloud',
          };
          await hydrateCloudSession(
            {
              access_token: trustedSession.credential,
              token_type: 'bearer',
              must_change_password: false,
            },
            restoredConfig,
            authAttemptRevision,
          );
          return;
        }

        if (trustedSession.runtime_mode !== 'local' || !localRuntimeAuthorityReady) {
          localResumeAttemptRef.current = '';
          setAuth(emptyAuthState);
          setConnection('idle');
          return;
        }

        // The native local runtime uses an ephemeral port after each launch. Bind recovery to the
        // exact live endpoint and launch capability reported by Tauri, then rotate the saved record.
        const bootstrapClient = new DesktopApiClient({ ...config, apiKey: '' });
        const outcome = await bootstrapClient.resumeLocalSession(trustedSession.credential);
        if (
          localResumeAttemptRef.current !== attemptKey ||
          authAttemptRevisionRef.current !== authAttemptRevision
        ) {
          return;
        }
        if (!outcome?.session?.session_id) {
          await clearNativeTrustedSession();
          if (authAttemptRevisionRef.current !== authAttemptRevision) return;
          setAuth(emptyAuthState);
          setConnection('idle');
          return;
        }
        await saveNativeTrustedSession({
          version: 1,
          api_base_url: config.apiBaseUrl,
          runtime_mode: 'local',
          credential_kind: 'local_session_reference',
          credential: outcome.session.session_id,
          expires_at: outcome.session.expires_at ?? null,
        });
        if (authAttemptRevisionRef.current !== authAttemptRevision) return;
        const hydrated = await hydrateLocalSession(outcome, config, authAttemptRevision);
        if (!hydrated) return;
        applySectionSideEffects('workspace');
      } catch (caught) {
        if (
          localResumeAttemptRef.current !== attemptKey ||
          authAttemptRevisionRef.current !== authAttemptRevision
        ) {
          return;
        }
        try {
          await clearNativeTrustedSession();
        } catch {
          // The original restore failure remains the user-facing error.
        }
        const message = t('login.restoreFailed');
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
    localRuntimeAuthorityReady,
    runsInTauri,
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
  const openProfileWorkspaceSettings = () => openSettingsEntry('profile_workspace_switch');

  const openConnectionSettings = () => {
    if (!identityAuthenticated) {
      useApiKeyManually();
    }
    openSettingsEntry('runtime_connection');
  };

  const applySettingsContext = async (tenantId: string, projectId: string) => {
    const requestConfig = configRef.current;
    const authAttemptRevision = authAttemptRevisionRef.current;
    const requestIsCurrent = () =>
      authAttemptRevisionRef.current === authAttemptRevision &&
      isSameDesktopRequestScope(requestConfig, configRef.current);
    if (!auth.tenants.some((tenant) => tenant.id === tenantId)) {
      throw new Error(t('settings.selectedTenantUnavailable'));
    }
    const contextClient = new DesktopApiClient({
      ...requestConfig,
      tenantId,
      projectId: '',
      workspaceId: '',
    });
    const listedProjects = await contextClient.listProjects(tenantId);
    if (!requestIsCurrent()) return;
    const scopedProjects = listedProjects.filter((project) => project.tenant_id === tenantId);
    const selectedProject = findWorkspaceProject(scopedProjects, tenantId, projectId);
    if (!selectedProject) {
      throw new Error(t('settings.selectedProjectUnavailable'));
    }

    let currentContext = auth.context;
    if (!currentContext) {
      const currentContextResponse = await contextClient.getWorkspaceContext();
      if (!requestIsCurrent()) return;
      currentContext = currentContextResponse.context;
    }
    let nextContext = currentContext;
    if (!workspaceContextMatchesSelection(currentContext, tenantId, projectId)) {
      const nextContextResponse = await contextClient.switchWorkspaceContext(
        tenantId,
        projectId,
        currentContext.revision,
        globalThis.crypto.randomUUID(),
      );
      if (!requestIsCurrent()) return;
      nextContext = nextContextResponse.context;
    }
    if (!workspaceContextMatchesSelection(nextContext, tenantId, projectId)) {
      throw new Error(t('settings.contextResponseMismatch'));
    }
    if (!requestIsCurrent()) return;
    const nextConfig = { ...requestConfig, tenantId, projectId, workspaceId: '' };
    contextRevisionRef.current = nextContext.revision;
    resetProjectScopedState();
    commitRuntimeConfig(nextConfig);
    setAuth((current) => ({ ...current, context: nextContext, projects: scopedProjects }));
    applySectionSideEffects('workspace');
    await refreshRuntime(nextConfig, [selectedProject]);
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

  const selectChatWorkflowTarget = useCallback((target: ChatWorkflowTarget) => {
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
  }, []);

  const handleChatRemoveReference = useCallback((reference: CodeRangeReference) => {
    setRunInputReferences((current) => toggleRunInputReference(current, reference));
  }, []);

  const handleChatRefresh = useCallback(() => {
    if (selectedConversation) {
      void loadConversationTimeline(selectedConversation, config.projectId);
      invalidateSessionAuthority();
      return;
    }
    void refreshRuntime();
  }, [
    config.projectId,
    invalidateSessionAuthority,
    loadConversationTimeline,
    refreshRuntime,
    selectedConversation,
  ]);

  const handleChatRuntimeTargetChange = useCallback((value: string) => {
    setRuntimeTarget(value === runtimeTargetLabels.staging ? 'staging' : 'local');
  }, []);

  const commandItems: CommandPaletteItem[] = [
    {
      id: 'home',
      label: t('nav.home'),
      description: t('commandPalette.homeDescription'),
      icon: <DashboardIcon />,
      onSelect: () => switchSection('home'),
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
      id: 'settings',
      label: identityAuthenticated
        ? t('settings.title')
        : t('commandPalette.useApiKey'),
      description: identityAuthenticated
        ? t('commandPalette.settingsDescription')
        : t('commandPalette.apiKeyDescription'),
      icon: <GearIcon />,
      onSelect: identityAuthenticated ? openSidebarSettings : openConnectionSettings,
    },
    {
      id: 'sign-in',
      label:
        auth.status === 'signed_in'
          ? t('settings.account')
          : t('login.signInTitle'),
      description:
        auth.status === 'signed_in'
          ? auth.user?.email ?? t('commandPalette.accountDescription')
          : t('commandPalette.signInDescription'),
      icon: <RocketIcon />,
      onSelect: () => {
        if (auth.status === 'signed_in') {
          openSidebarSettings();
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
      label: t('commandPalette.refreshWorkspace'),
      description: runtimeDisabledReason ?? t('commandPalette.refreshDescription'),
      icon: <RocketIcon />,
      disabled: Boolean(runtimeDisabledReason) || connection === 'loading',
      onSelect: () => void refreshRuntime(),
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
      composerResetKey={selectedConversation?.id ?? config.workspaceId}
      activityPresence={sessionActivityState}
      activityStructuredEvidence={sessionActivityStructuredEvidence}
      sending={sending}
      disabledReason={sessionChatDisabledReason}
      activeWorkflowTarget={chatWorkflowTargetForReviewTab(reviewTab)}
      modelLabel={config.mode === 'local' ? localRuntimeModelLabel : undefined}
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
      onRunInputDeliveryChange={setRunInputDelivery}
      onPromoteRunInput={promoteQueuedRunInput}
      onRemoveReference={handleChatRemoveReference}
      onSend={sendChatMessage}
      onRefresh={handleChatRefresh}
      onLoadEarlier={loadEarlierTimeline}
      onRespondToHitl={respondToHitl}
      respondableHitlRequestIds={respondableHitlRequestIds}
      authorityNotice={sessionAuthorityNotice}
      onAuthorityAction={
        sessionProjectionState.status === 'error' ? invalidateSessionAuthority : undefined
      }
      onWorkflowSelect={selectChatWorkflowTarget}
      onRuntimeTargetChange={handleChatRuntimeTargetChange}
      onOpenCommands={openCommandPalette}
    />
  );

  const renderWorkspaceOverview = () => {
    return (
      <WorkspaceOverview
        workspace={selectedWorkspace}
        project={selectedProject}
        tenantName={
          auth.tenants.find((tenant) => tenant.id === config.tenantId)?.name ||
          config.tenantId ||
          t('settings.noTenantSelected')
        }
        workspaceAuthority={newTaskWorkspaceAuthority}
        conversations={dataset.conversationsByWorkspace[config.workspaceId] ?? []}
        members={dataset.workspaceMembers}
        agents={dataset.workspaceAgents}
        plan={activeDataset.plan}
        sandboxStatus={dataset.sandbox?.status ?? null}
        newTaskDisabledReason={newTaskDisabledReason}
        onNewTask={() => openNewTask(config.workspaceId)}
        onRetryWorkspaces={() => void refreshRuntime()}
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

  const renderAuxiliaryView = (section: 'home' | 'automations' | 'search') => (
    <AuxiliaryView
      section={section}
      userName={auxiliaryUserName}
      runningCount={myWorkCounts.running}
      needsInputCount={myWorkCounts.needs_input + myWorkCounts.needs_approval}
      readyCount={myWorkCounts.ready_review}
      metricStatus={myWorkMetricStatus}
      onOpenMyWork={() => switchSection('board')}
      onRetryMyWork={() => void refreshMyWork()}
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
      currentPlan={displaySessionProjection?.currentPlan ?? null}
      taskListPlanTasks={
        displaySessionProjection?.planAuthority.kind === 'agent_task_list'
          ? displaySessionProjection.tasks
          : []
      }
      canResumeTaskListReview={
        displaySessionProjection?.planAuthority.kind === 'agent_task_list' &&
        sessionTaskListPlanRecovery?.canResume === true
      }
      sessionCapabilities={sessionProjection?.capabilities ?? null}
      sessionPlanApprovalPending={sessionPlanApprovalPending}
      respondableHitlRequestIds={respondableHitlRequestIds}
      sessionDataAvailable={displaySessionProjection !== null}
      authorityNotice={sessionAuthorityNotice}
      onAuthorityAction={
        sessionProjectionState.status === 'error' ? invalidateSessionAuthority : undefined
      }
      currentRunId={sessionDetailViewModel?.runId ?? null}
      sessionViewModel={sessionDetailViewModel}
      onRespondToHitl={respondToHitl}
      onApprovePlan={approveSessionPlan}
      onResumeTaskListReview={resumeSessionTaskListReview}
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
    if (!showRuntimeConfig) return renderWorkspaceOverview();
    if (activeSection === 'workspace') return renderWorkspaceOverview();
    if (activeSection === 'chat') return renderChatPanel();
    if (activeSection === 'board') return renderBoardPanel();
    if (
      activeSection === 'home' ||
      activeSection === 'automations' ||
      activeSection === 'search'
    ) {
      return renderAuxiliaryView(activeSection);
    }
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

  if (!identityAuthenticated) {
    return (
      <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
        <LoginScreen
          auth={auth}
          mode={config.mode}
          localReady={localRuntimeAuthorityReady}
          email={loginEmail}
          password={loginPassword}
          onEmailChange={setLoginEmail}
          onPasswordChange={setLoginPassword}
          onEmailLogin={(trustedDevice) => void login(trustedDevice)}
          onLocalSession={(trustedDevice) => void loginLocalSession(trustedDevice)}
          onWorkspaceSso={(trustedDevice) => void loginWithWorkspaceSso(trustedDevice)}
          workspaceSso={workspaceSso}
          onOpenWorkspaceSso={openCurrentWorkspaceSso}
          onCancelWorkspaceSso={cancelWorkspaceSso}
        />
      </Theme>
    );
  }

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div
        ref={appShellRef}
        className={`app-shell hierarchy-shell runtime-mode ${
          runsInTauri ? 'tauri-window' : 'browser-window'
        } ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${
          activeSection === 'board' ? 'my-work-mode' : ''
        }`}
      >

        <section className="desktop-body">
          <DesktopSidebar
            activeSection={
              activeSection === 'board'
                ? 'my-work'
                : activeSection === 'home' ||
                    activeSection === 'automations' ||
                    activeSection === 'search'
                  ? activeSection
                  : null
            }
            mode={preferredTaskMode}
            taskCount={dataset.myWork.length}
            tenantName={
              auth.tenants.find((tenant) => tenant.id === config.tenantId)?.name ||
              config.tenantId ||
              t('settings.noTenantSelected')
            }
            projectName={
              selectedProject?.name ?? selectedProject?.id ?? t('settings.noProjectSelected')
            }
            user={auth.user}
            workspaces={dataset.workspacesByProject[config.projectId] ?? []}
            conversationsByWorkspace={dataset.conversationsByWorkspace}
            nodeState={dataset.nodeState}
            currentProjectId={config.projectId}
            currentWorkspaceId={config.workspaceId}
            currentConversationId={selectedConversation?.id ?? null}
            workspaceTreeSelectionMode={
              activeSection === 'workspace'
                ? 'overview'
                : activeSection === 'chat'
                  ? 'conversation'
                  : activeSection === 'board'
                    ? 'my-work'
                    : 'none'
            }
            expandedWorkspaceIds={expandedWorkspaceIds}
            newTaskDisabledReason={newTaskDisabledReason}
            onModeChange={(mode) => {
              setPreferredTaskMode(mode);
              switchSection('board');
            }}
            onNavigate={(section) => {
              if (section === 'home') switchSection('home');
              if (section === 'my-work') switchSection('board');
              if (section === 'automations') switchSection('automations');
              if (section === 'search') switchSection('search');
              if (section === 'notifications') openSettingsEntry('sidebar_notifications');
            }}
            onToggleWorkspace={toggleWorkspace}
            onRetryProject={() => void refreshRuntime()}
            onRetryWorkspace={(workspaceId) => void loadWorkspaceConversations(workspaceId)}
            onSelectWorkspace={(projectId, workspaceId) => selectWorkspace(workspaceId, projectId)}
            onSelectConversation={selectConversation}
            onNewTask={startNewSession}
            onOpenAccountSettings={openSidebarSettings}
            onSwitchWorkspace={openProfileWorkspaceSettings}
            onSignOut={() => void logout()}
          />

          <main ref={workbenchRef} className="workbench" tabIndex={-1}>
            {error ? (
              <div className="workbench-error" role="alert" aria-live="polite">
                <span>{error}</span>
                {connection === 'error' && showRuntimeConfig ? (
                  <button
                    type="button"
                    onClick={() => {
                      workbenchRef.current?.focus();
                      void refreshRuntime();
                    }}
                  >
                    {t('runtime.retryWorkspace')}
                  </button>
                ) : null}
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
                onOpenTask={
                  sessionDetailViewModel.linkedTaskId
                    ? () => {
                        setSelectedTaskId(sessionDetailViewModel.linkedTaskId!);
                        switchSection('board');
                      }
                    : undefined
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
          actorId={auth.user?.user_id}
          workspaceAuthority={newTaskWorkspaceAuthority}
          resumeDraft={newTaskResumeDraft}
          preferredWorkspaceId={newTaskPreferredWorkspaceId}
          preferredKind={preferredTaskMode === 'code' ? 'programming' : 'general'}
          disabledReason={newTaskDisabledReason}
          onClose={() => {
            setNewTaskOpen(false);
            setNewTaskResumeDraft(null);
          }}
          onSessionPersisted={persistNewTaskSession}
          onSessionReady={activateNewTaskSession}
          onRunAgentTurn={runNewTaskAgentTurn}
          onOpenRuntimeSettings={() => {
            setNewTaskOpen(false);
            setNewTaskResumeDraft(null);
            openConnectionSettings();
          }}
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
          onRuntimeStatusRefresh={refreshLocalRuntimeStatus}
          onRefreshRuntime={() => void refreshRuntime()}
          onContextChange={applySettingsContext}
          onSignOut={() => void logout()}
        />
      </div>
    </Theme>
  );
}

function unavailableWorkspaceAuthority<T>(): WorkspaceAuthorityCollection<T> {
  return { status: 'unavailable', items: [], error: null };
}

function loadingWorkspaceAuthority<T>(): WorkspaceAuthorityCollection<T> {
  return { status: 'loading', items: [], error: null };
}

function failLoadingWorkspaceAuthority<T>(
  collection: WorkspaceAuthorityCollection<T>,
  error: string,
): WorkspaceAuthorityCollection<T> {
  return collection.status === 'loading'
    ? { status: 'error', items: [], error }
    : collection;
}

async function resolveWorkspaceAuthority<T>(
  request: Promise<T[]>,
): Promise<WorkspaceAuthorityCollection<T>> {
  try {
    return { status: 'ready', items: await request, error: null };
  } catch (error) {
    return { status: 'error', items: [], error: formatError(error) };
  }
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
  if (authStatus === 'signed_in') return projects;
  const configured = projectSummaryFromConfig(config);
  return configured ? [configured] : [];
}

function WorkspaceReviewPanel({
  activeTab,
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
  currentPlan,
  taskListPlanTasks,
  canResumeTaskListReview,
  sessionCapabilities,
  sessionPlanApprovalPending,
  respondableHitlRequestIds,
  sessionDataAvailable,
  authorityNotice,
  onAuthorityAction,
  currentRunId,
  sessionViewModel,
  onRespondToHitl,
  onApprovePlan,
  onResumeTaskListReview,
  onArtifactAction,
  onStartTerminal,
  onRefreshChanges,
  onToggleChangeReference,
  onTabChange,
  sessionControls,
}: {
  activeTab: ReviewTab;
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
  currentPlan: SessionProjectionPlan | null;
  taskListPlanTasks: SessionProjectionTask[];
  canResumeTaskListReview: boolean;
  sessionCapabilities: SessionProjectionCapabilities | null;
  sessionPlanApprovalPending: boolean;
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
  onApprovePlan: (
    plan: SessionProjectionPlan,
    selection: SessionPlanApprovalSelection,
  ) => Promise<void>;
  onResumeTaskListReview: () => void;
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
  const tabId = (tab: ReviewTab) => `session-canvas-tab-${tab}`;
  const panelId = 'session-canvas-panel';

  const selectTab = (tab: ReviewTab) => {
    onTabChange(tab);
  };
  const handleTabKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    tab: ReviewTab,
  ) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const currentIndex = reviewTabs.findIndex((candidate) => candidate.tab === tab);
    if (currentIndex < 0 || reviewTabs.length < 2) return;
    event.preventDefault();
    const nextIndex =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? reviewTabs.length - 1
          : (currentIndex + (event.key === 'ArrowLeft' ? -1 : 1) + reviewTabs.length) %
            reviewTabs.length;
    const nextTab = reviewTabs[nextIndex];
    selectTab(nextTab.tab);
    sessionTabListRef.current
      ?.querySelector<HTMLButtonElement>(`#${tabId(nextTab.tab)}`)
      ?.focus();
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

  return (
    <aside className={panelClassName} aria-label={t('session.canvas')}>
      <div className="review-tabs" aria-label={t('session.canvas')}>
        <nav
          className="review-tab-scroll"
          ref={sessionTabListRef}
          role="tablist"
          aria-label={t('session.canvas')}
          aria-orientation="horizontal"
        >
          {reviewTabs.map(({ tab, label, value }) => (
            <button
              id={tabId(tab)}
              className={`review-tab ${activeTab === tab ? 'selected' : ''}`}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              aria-controls={panelId}
              tabIndex={activeTab === tab ? 0 : -1}
              aria-label={
                value
                  ? t('session.openCanvasTabWithValue', { label, value })
                  : t('session.openCanvasTab', { label })
              }
              key={tab}
              onKeyDown={(event) => handleTabKeyDown(event, tab)}
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

      <div
        className="review-content"
        id={panelId}
        role="tabpanel"
        aria-labelledby={tabId(activeTab)}
        tabIndex={0}
      >
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
                    events: socketEvents.length,
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
                      ? currentPlan || taskListPlanTasks.length > 0
                        ? t('session.planReady')
                        : t('session.noPlanShort')
                      : t('session.notAvailable')}
                  </small>
                </span>
                <ChevronRightIcon />
              </button>
              <button
                type="button"
                onClick={() =>
                  selectTab(capabilityMode === 'code' ? 'changes' : 'artifacts')
                }
              >
                {capabilityMode === 'code' ? <FileTextIcon /> : <ArchiveIcon />}
                <span>
                  <strong>
                    {capabilityMode === 'code'
                      ? t('session.canvasChanges')
                      : t('session.canvasArtifacts')}
                  </strong>
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
              <button
                type="button"
                onClick={() =>
                  selectTab(capabilityMode === 'code' ? 'checks' : 'verification')
                }
              >
                <CheckCircledIcon />
                <span>
                  <strong>
                    {capabilityMode === 'code'
                      ? t('session.canvasChecks')
                      : t('session.canvasVerification')}
                  </strong>
                  <small>
                    {sessionViewModel?.verificationCount === null ||
                    sessionViewModel?.verificationCount === undefined
                      ? t('session.notAvailable')
                      : t('session.evidence.recordCount', {
                          count: sessionViewModel.verificationCount,
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
            {currentPlan ? (
              <SessionPlanReview
                plan={currentPlan}
                capabilities={sessionCapabilities}
                capabilityMode={capabilityMode}
                pending={sessionPlanApprovalPending}
                onApprove={onApprovePlan}
              />
            ) : taskListPlanTasks.length > 0 ? (
              <SessionTaskListReview
                tasks={taskListPlanTasks}
                canResumeReview={canResumeTaskListReview}
                onResumeReview={onResumeTaskListReview}
              />
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

function chatWorkflowTargetForReviewTab(tab: ReviewTab): ChatWorkflowTarget {
  if (tab === 'pull' || tab === 'checks') return 'pull';
  if (tab === 'background' || tab === 'activity') return 'background';
  if (tab === 'artifacts') return 'artifacts';
  if (tab === 'changes') return 'changes';
  return 'plan';
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
  const { t } = useI18n();
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
        aria-label={t('commandPalette.title')}
        onKeyDown={containTabFocus}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <label className="command-search">
          <MagnifyingGlassIcon aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            aria-label={t('commandPalette.search')}
            placeholder={t('commandPalette.searchPlaceholder')}
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
        <div
          className="command-list"
          role="listbox"
          aria-label={t('commandPalette.results')}
        >
          {items.length === 0 ? (
            <div className="command-empty" role="status">
              {t('commandPalette.empty')}
            </div>
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
                <span className="command-icon" aria-hidden="true">
                  {item.icon}
                </span>
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
