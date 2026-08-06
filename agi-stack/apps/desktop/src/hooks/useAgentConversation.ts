import {
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react';

import { useAgentSocket } from './useAgentSocket';
import { createDesktopAgentAuthorityAdapter } from '../features/agent-authority/cloudAgentAuthorityClient';
import type { CloudAgentAuthorityScope } from '../features/agent-authority/agentAuthorityTypes';
import type { ConversationSessionProjection } from '../features/session/sessionProjectionTypes';
import { normalizeSessionTaskListPlan } from '../features/session/sessionPlanApprovalModel';
import { useWorkspaceAgentPolicy } from '../features/settings/useWorkspaceAgentPolicy';
import {
  DesktopApiClient,
} from '../api/client';
import {
  type PermissionPreset,
} from '../features/chat/permissionPresetModel';
import type { AgentTaskSignal } from '../features/chat/agentTaskSignalModel';
import {
  type NewTaskResumeDraft,
} from '../features/task/NewTaskFlow';
import {
  type NewTaskAgentTurnOutcome,
} from '../features/task/newTaskPlanModel';
import {
  AgentConversation,
  AuthState,
  CodeRangeReference,
  ConnectionState,
  ConversationTimelineState,
  DesktopRun,
  DesktopRunInput,
  DesktopRuntimeConfig,
  RunInputDelivery,
  RuntimeDataset,
  WorkbenchSection,
  WorkspaceSummary,
} from '../types';
import {
  type AgentConversationSession,
  type AgentTaskSignalPatch,
  type ReviewTab,
} from '../appShellTypes';
import { useConversationThreads } from './useConversationThreads';
import { useConversationMessaging } from './useConversationMessaging';

export type AgentConversationParams = {
  config: DesktopRuntimeConfig;
  auth: AuthState;
  connection: ConnectionState;
  dataset: RuntimeDataset;
  agentConversationSession: AgentConversationSession | null;
  selectedConversation: AgentConversation | null;
  currentArtifactRun: DesktopRun | null;
  sessionProjection: ConversationSessionProjection | null;
  sessionTaskListPlanRecovery: {
    tasks: NonNullable<ReturnType<typeof normalizeSessionTaskListPlan>>;
    canResume: boolean;
  } | null;
  permissionPreset: PermissionPreset;
  runInputReferences: CodeRangeReference[];
  runInputDelivery: RunInputDelivery | null;
  runInputDeliveryOptions: RunInputDelivery[];
  sessionChatDisabledReason: string | null;
  newThreadWorkspaces: WorkspaceSummary[];
  configuredNewThreadWorkspaceId: string;
  localRuntimeMode: boolean;
  canManageWorkspacePolicy: boolean;
  api: DesktopApiClient;
  socket: ReturnType<typeof useAgentSocket>;
  activityAuthorityAdapter: ReturnType<typeof createDesktopAgentAuthorityAdapter>;
  activityAuthorityScope: CloudAgentAuthorityScope | undefined;
  workspaceAgentPolicy: ReturnType<typeof useWorkspaceAgentPolicy>;
  setLoginModalOpen: Dispatch<SetStateAction<boolean>>;
  setCommandPaletteOpen: Dispatch<SetStateAction<boolean>>;
  setNewTaskOpen: Dispatch<SetStateAction<boolean>>;
  setNewTaskPreferredWorkspaceId: Dispatch<SetStateAction<string>>;
  setNewTaskResumeDraft: Dispatch<SetStateAction<NewTaskResumeDraft | null>>;
  setNewThreadScope: Dispatch<
    SetStateAction<{ projectId: string; workspaceId: string }>
  >;
  setNewThreadCreating: Dispatch<SetStateAction<boolean>>;
  setNewThreadError: Dispatch<SetStateAction<string | null>>;
  setCommandQuery: Dispatch<SetStateAction<string>>;
  setExpandedWorkspaceIds: Dispatch<SetStateAction<Set<string>>>;
  setDataset: Dispatch<SetStateAction<RuntimeDataset>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setSending: Dispatch<SetStateAction<boolean>>;
  setRunInputReferences: Dispatch<SetStateAction<CodeRangeReference[]>>;
  setRunInputs: Dispatch<SetStateAction<DesktopRunInput[]>>;
  setSectionBackStack: Dispatch<SetStateAction<WorkbenchSection[]>>;
  setSectionForwardStack: Dispatch<SetStateAction<WorkbenchSection[]>>;
  setReviewTab: Dispatch<SetStateAction<ReviewTab>>;
  setSelectedTaskId: Dispatch<SetStateAction<string>>;
  setAgentConversationSession: Dispatch<
    SetStateAction<AgentConversationSession | null>
  >;
  setConversationTimeline: Dispatch<SetStateAction<ConversationTimelineState>>;
  setAgentTaskSignals: Dispatch<SetStateAction<AgentTaskSignal[]>>;
  pendingNewTaskAgentTurnsRef: RefObject<
    Map<
      string,
      {
        conversationId: string;
        messageId: string;
        timeoutId: number;
        resolve: (outcome: NewTaskAgentTurnOutcome) => void;
        reject: (error: Error) => void;
      }
    >
  >;
  contextRevisionRef: RefObject<number>;
  configRef: RefObject<DesktopRuntimeConfig>;
  configScopeEpochRef: RefObject<number>;
  runInputRequestRef: RefObject<{
    signature: string;
    messageId: string;
    idempotencyKey: string;
  } | null>;
  commitRuntimeConfig: (nextConfig: DesktopRuntimeConfig) => void;
  invalidateSessionAuthority: () => void;
  upsertAgentTaskSignal: (patch: AgentTaskSignalPatch) => void;
  resetConversationTimeline: () => void;
  loadConversationTimeline: (
    conversation: AgentConversation,
    projectId: string,
    requestConfig?: DesktopRuntimeConfig,
  ) => Promise<void>;
  applySectionSideEffects: (section: WorkbenchSection) => void;
  switchSection: (section: WorkbenchSection) => void;
};

export function useAgentConversation(params: AgentConversationParams) {
  const {
    activateNewTaskSession,
    changeNewThreadWorkspace,
    createComposerThread,
    openNewTask,
    persistNewTaskSession,
    resumeSessionTaskListReview,
    runNewTaskAgentTurn,
    startNewSession,
  } = useConversationThreads(params);
  const { sendMessageContent } = useConversationMessaging(params);
  return {
    activateNewTaskSession,
    changeNewThreadWorkspace,
    createComposerThread,
    openNewTask,
    persistNewTaskSession,
    resumeSessionTaskListReview,
    runNewTaskAgentTurn,
    sendMessageContent,
    startNewSession,
  };
}
