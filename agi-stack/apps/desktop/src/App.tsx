import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Theme } from '@radix-ui/themes';
import {
  DashboardIcon,
  GearIcon,
  GridIcon,
  KeyboardIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import {
  DesktopApiClient,
  DesktopApiError,
} from './api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopVaultBoundCloudRequestBroker,
} from './api/cloudRequestBroker';
import { desktopNativeCloudAuthClient } from './api/nativeCloudAuthClient';
import type {
  WorkspaceBindingAgentDefinition,
  WorkspaceCreateInput,
  WorkspaceMemberRole,
  WorkspaceUpdateInput,
} from './api/client';
import {
  clearLocalTrustedSession,
  clearNativeTrustedSession,
  hasNativeTrustedSessionBroker,
  loadLocalTrustedSession,
  saveLocalTrustedSession,
  selectPlatformPluginAuthorityV2,
} from './api/trustedSession';
import type { CloudSessionProjection } from './api/cloudSessionProjectionClient';
import { useResizablePanelWidth } from './components/ResizeHandle';
import type { RunChangeScope } from './features/agent-authority/agentAuthorityTypes';
import { desktopChangeSnapshotFromCloud } from './features/agent-authority/agentAuthorityProjection';
import {
  createDesktopAgentAuthorityProviderV2,
} from './features/agent-authority/desktopAgentAuthorityProviderV2';
import {
  findWorkspaceProject,
  isCurrentContextRevision,
  isCurrentLocalRuntimeAuthority,
  isIdentityAuthenticated,
  isSameDesktopProjectRequestScope,
  isSameDesktopRequestScope,
  isWorkspaceReady,
  workspaceContextMatchesSelection,
} from './features/auth/authContextModel';
import { ForcePasswordChangeScreen } from './features/auth/ForcePasswordChangeScreen';
import {
  completeForcedPasswordChangeOutcome,
  type PendingPasswordChangeAttempt,
} from './features/auth/forcePasswordChangeModel';
import { LoginScreen, type WorkspaceSsoPresentation } from './features/auth/LoginScreen';
import {
  createProjectCronJobsRouteBindingProviderV2,
} from './features/automations/projectCronJobsRouteBindingProviderV2';
import { initialDesktopRuntimeConfig } from './features/auth/loginRuntimeModel';
import { resolveNativeOAuthResumePath } from './features/auth/nativeOAuthSessionModel';
import type { ChatWorkflowTarget } from './features/chat/ChatWorkflowStrip';
import { isDesktopNavigationRouteEnabledV2 } from './plugins/desktopRendererAuthorityStateV2';
import type { DesktopAuthenticatedShellViewModelV2 } from './plugins/DesktopAuthenticatedShellSurfaceV2';
import type { DesktopSessionCanvasInputV2 } from './plugins/DesktopSessionCanvasSurfaceV2';
import { createDesktopRendererAppCompositionPortV2 } from './plugins/desktopRendererAppCompositionV2';
import {
  createDesktopPluginMarketplaceOperationsV2,
} from './plugins/desktopPluginMarketplaceAuthorityModulesV2';
import {
  createDesktopArtifactContentClientV2,
} from './plugins/desktopArtifactContentAuthorityModuleV2';
import { createDesktopAutomationOperationsV2 } from './plugins/desktopAutomationAuthorityModuleV2';
import { createDesktopConversationLifecycleOperationsV2 } from './plugins/desktopConversationLifecycleAuthorityModuleV2';
import { createDesktopConversationConfigOperationsV2 } from './plugins/desktopConversationConfigAuthorityModuleV2';
import { createDesktopHitlResponseOperationsV2 } from './plugins/desktopHitlResponseAuthorityModuleV2';
import { createDesktopMyWorkOperationsV2 } from './plugins/desktopMyWorkAuthorityModuleV2';
import {
  createDesktopNewTaskFlowOperationsV2,
  type DesktopNewTaskFlowClientV2,
} from './plugins/desktopNewTaskFlowAuthorityModuleV2';
import {
  createDesktopNewThreadCreationOperationsV2,
} from './plugins/desktopNewThreadCreationAuthorityModuleV2';
import {
  createDesktopProjectOverviewOperationsV2,
} from './plugins/desktopProjectOverviewAuthorityModuleV2';
import {
  createDesktopProjectAgentDashboardOperationsV2,
} from './plugins/desktopProjectAgentDashboardAuthorityModuleV2';
import {
  createDesktopProjectAgentLogsOperationsV2,
} from './plugins/desktopProjectAgentLogsAuthorityModuleV2';
import {
  createDesktopProjectAgentPatternsOperationsV2,
} from './plugins/desktopProjectAgentPatternsAuthorityModuleV2';
import {
  createDesktopProjectCommunitiesOperationsV2,
} from './plugins/desktopProjectCommunitiesAuthorityModuleV2';
import {
  createDesktopProjectEntitiesOperationsV2,
} from './plugins/desktopProjectEntitiesAuthorityModuleV2';
import {
  createDesktopProjectGraphOperationsV2,
} from './plugins/desktopProjectGraphAuthorityModuleV2';
import {
  createDesktopProjectBlackboardOperationsV2,
  createDesktopWorkspaceCollaborationClientV2,
} from './plugins/desktopProjectBlackboardAuthorityModuleV2';
import { createDesktopRuntimePoolOperationsV2 } from './plugins/desktopRuntimePoolAuthorityModuleV2';
import { createDesktopRuntimeClustersOperationsV2 } from './plugins/desktopRuntimeClustersAuthorityModuleV2';
import {
  createDesktopProjectSearchOperationsV2,
} from './plugins/desktopProjectSearchAuthorityModuleV2';
import {
  createDesktopSessionArtifactActionOperationsV2,
} from './plugins/desktopSessionArtifactActionAuthorityModuleV2';
import { createDesktopSessionProjectionOperationsV2 } from './plugins/desktopSessionProjectionAuthorityModuleV2';
import { createDesktopSessionRunControlOperationsV2 } from './plugins/desktopSessionRunControlAuthorityModuleV2';
import { createDesktopSessionRunChangesOperationsV2 } from './plugins/desktopSessionRunChangesAuthorityModuleV2';
import { createDesktopSessionRunInputOperationsV2 } from './plugins/desktopSessionRunInputAuthorityModuleV2';
import { createDesktopSessionTimelineOperationsV2 } from './plugins/desktopSessionTimelineAuthorityModuleV2';
import { createDesktopTenantAgentBindingsOperationsV2 } from './plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import { createDesktopTenantAgentDashboardOperationsV2 } from './plugins/desktopTenantAgentDashboardAuthorityModuleV2';
import { createDesktopTenantAnalyticsOperationsV2 } from './plugins/desktopTenantAnalyticsAuthorityModuleV2';
import { createDesktopTenantCatalogOperationsV2 } from './plugins/desktopTenantCatalogAuthorityModuleV2';
import { createDesktopTenantOverviewOperationsV2 } from './plugins/desktopTenantOverviewAuthorityModuleV2';
import { createDesktopTenantProjectsOperationsV2 } from './plugins/desktopTenantProjectsAuthorityModuleV2';
import { createDesktopTenantTasksOperationsV2 } from './plugins/desktopTenantTasksAuthorityModuleV2';
import {
  createDesktopWorkspaceAgentBindingOperationsV2,
} from './plugins/desktopWorkspaceAgentBindingAuthorityModuleV2';
import {
  createDesktopWorkspaceAutonomyAttentionOperationsV2,
} from './plugins/desktopWorkspaceAutonomyAttentionAuthorityModuleV2';
import {
  createDesktopWorkspaceMemberMutationOperationsV2,
} from './plugins/desktopWorkspaceMemberMutationAuthorityModuleV2';
import {
  createDesktopWorkspaceMessageCatalogOperationsV2,
} from './plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2';
import {
  createDesktopWorkspaceConversationCatalogOperationsV2,
} from './plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2';
import {
  createDesktopWorkspaceCatalogOperationsV2,
} from './plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import {
  createDesktopWorkspaceLifecycleOperationsV2,
} from './plugins/desktopWorkspaceLifecycleAuthorityModuleV2';
import {
  createDesktopWorkspaceRosterOperationsV2,
} from './plugins/desktopWorkspaceRosterAuthorityModuleV2';
import {
  createDesktopWorkspaceExecutionSnapshotOperationsV2,
} from './plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2';
import type { DesktopRendererGenerationActionsV2 } from './plugins/desktopRendererGenerationContextV2';
import {
  acquireDesktopTerminalLifecycleAuthorityV2,
  type DesktopTerminalLifecycleAuthorityV2,
} from './plugins/desktopTerminalLifecycleAuthorityModuleV2';
import { DesktopRendererAuthenticationRouterV2 } from './plugins/DesktopRendererAuthenticationRouterV2';
import { DesktopRendererAuthenticatedShellV2 } from './plugins/DesktopRendererAuthenticatedShellV2';
import {
  DesktopRendererGenerationProviderV2,
  useDesktopRendererGenerationHostV2,
} from './plugins/DesktopRendererGenerationHostV2';
import { withDesktopWorkspaceContextAuthorityOperationV2 } from './plugins/desktopWorkspaceContextAuthorityModuleV2';
import type {
  DesktopWorkbenchSurfaceViewModelV2,
  DesktopWorkbenchViewV2,
} from './plugins/DesktopWorkbenchSurfaceV2';
import { resolveSubAgentControlAuthority } from './features/chat/subagentControlAuthorityModel';
import {
  reconcileAgentTaskSignals,
  type AgentTaskSignal,
} from './features/chat/agentTaskSignalModel';
import { classifyHitlAuthorityRecovery } from './features/chat/hitlAuthorityRecovery';
import {
  applyArtifactCanvasStreamEvent,
  emptyArtifactCanvasState,
  replayArtifactCanvasEvents,
  selectArtifactCanvasTab,
  type LiveArtifactCanvasState,
} from './features/chat/artifactCanvasEventModel';
import { unboundComposerCatalogClient } from './features/chat/composerCatalogModel';
import {
  applyConversationTitleUpdate,
  readConversationTitleStreamEvent,
} from './features/chat/conversationTitleEventModel';
import { coalesceStreamingTextEvents } from './features/chat/streamingTextEventModel';
import { applyHitlResponseStreamEvent } from './features/chat/hitlResponseEventModel';
import {
  acknowledgeFullAccessWarning,
  autoApprovalSubmission,
  permissionPresetScope,
  readFullAccessWarningAcknowledged,
  readPermissionPreset,
  writePermissionPreset,
  type PermissionPreset,
} from './features/chat/permissionPresetModel';
import { applyWorkspaceLifecycleStreamEvent } from './features/chat/workspaceLifecycleEventModel';
import { applyWorkspaceMessageStreamEvent } from './features/chat/workspaceMessageEventModel';
import { applyWorkspaceRosterStreamEvent } from './features/chat/workspaceRosterEventModel';
import { applyWorkspaceTaskStreamEvent } from './features/chat/workspaceTaskEventModel';
import {
  applyMCPAppCanvasStreamEvent,
  closeMCPAppCanvasTab,
  emptyMCPAppCanvasState,
  selectMCPAppCanvasTab,
  type MCPAppCanvasState,
} from './features/chat/mcpAppCanvasEventModel';
import { useToast } from './features/feedback/ToastCenter';
import type { DesktopRightPanel } from './features/chrome/DesktopRightSidebar';
import {
  clearConversationTabs,
  closeTab,
  ensureConversationTab,
  ensureViewTab,
  isSameTab,
  isViewTabSection,
  tabKey,
  type WorkbenchTab,
} from './features/chrome/workbenchTabBarModel';
import { buildRunCompletionSummary } from './features/session/runCompletionSummaryModel';
import { deriveSessionUsage } from './features/session/sessionUsageModel';
import {
  artifactDeliveryRequest,
  artifactReviewRequest,
  artifactVersionActions,
  type ArtifactVersionAction,
} from './features/session/sessionArtifactModel';
import {
  chatWorkflowTargetForReviewTab,
  defaultSessionCanvasTab,
  shouldShowSessionCanvas,
  type SessionCanvasTabId,
} from './features/session/sessionCanvasModel';
import {
  effectiveRunInputDelivery,
  snapshotMatchesRun,
  toggleRunInputReference,
} from './features/session/sessionChangesModel';
import {
  addChangeComment,
  buildChangeCommentsMessage,
  clearChangeComments,
  commentsForConversation,
  referencesForChangeComments,
  removeChangeComment,
} from './features/session/sessionChangesReviewModel';
import type {
  ChangeReviewComment,
  ChangeReviewCommentMap,
} from './features/session/sessionChangesReviewModel';
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
  type SessionProjectionLoadState,
  type SessionProjectionPlan,
} from './features/session/sessionProjectionTypes';
import {
  terminalBindingState,
  terminalRunScopeKey,
  terminalSessionMatchesRun,
} from './features/session/sessionTerminalModel';
import {
  authoritativeRunsFromSocketEvents,
  buildSessionDetailViewModel,
  conversationWithAuthoritativeRun,
  mergeConversationListWithCurrentRunAuthority,
  respondableHitlRequestsForProjection,
  type SessionRunAction,
} from './features/session/sessionViewModel';
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
import { useActivityInbox } from './features/activity/useActivityInbox';
import { useCompletionNotifications } from './features/activity/useCompletionNotifications';
import {
  createDesktopWorkbenchCapabilityClientProviderV2,
} from './features/runtime/desktopWorkbenchCapabilityClientProviderV2';
import { desktopCapability } from './features/runtime/capabilitySnapshot';
import { useDesktopCapabilitySnapshot } from './features/runtime/useDesktopCapabilitySnapshot';
import { createProjectSearchRouteBindingProviderV2 } from './features/search/projectSearchRouteBindingProviderV2';
import {
  countMyWorkGroups,
  myWorkConversationMatchesScope,
  myWorkRefreshScopeIsCurrent,
  socketEventInvalidatesMyWork,
  type MyWorkRefreshScope,
} from './features/my-work/myWorkModel';
import { createBrowserDesktopHashLocationPort } from './features/navigation/desktopHashRouteHost';
import { DEVICE_APPROVAL_ROUTE_ID } from './features/navigation/desktopProductionRouteRegistry';
import { restoreDesktopRoute } from './features/navigation/desktopRouteRegistry';
import { createDesktopProductionRouteAuthorityProviderV2 } from './features/navigation/desktopProductionRouteAuthorityProviderV2';
import { createDesktopRouteScopeTransaction } from './features/navigation/desktopRouteScopeTransaction';
import {
  deriveDesktopNavigationDiscoveryEntries,
  filterDesktopNavigationDiscoveryEntries,
} from './features/navigation/desktopNavigationDiscoveryModel';
import {
  detectShortcutPlatform,
  shortcutById,
  shortcutChordFor,
} from './features/navigation/keyboardShortcutModel';
import {
  isCurrentLocalConversationStatusRequest,
  nextLocalConversationStatusRequest,
  type LocalConversationStatusSummary,
  type LocalConversationStatusRequest,
} from './features/project/projectOverviewLocalClient';
import {
  createAgentDefinitionsRouteBindingForRuntime,
  createMcpServersRouteBindingForRuntime,
  createPluginsRouteBindingForRuntime,
  createProvidersRouteBindingForRuntime,
  createSkillsRouteBindingForRuntime,
} from './features/settings-routes/settingsRouteRuntime';
import { terminalInteractiveCapability as resolveTerminalInteractiveCapability } from './features/sandbox/sandboxRuntimeClient';
import { useSandboxRuntimeSurface } from './features/sandbox/useSandboxRuntimeSurface';
import {
  settingsSectionForEntry,
  type SettingsEntry,
} from './features/settings/settingsEntryRouting';
import type { SettingsSection } from './features/settings/SettingsWindow';
import {
  createProfileGenerationHashLocationPort,
} from './features/settings-routes/profileAuxiliaryRoute';
import { latestAgentDefinitionEvent } from './features/settings/agentDefinitionEventModel';
import { useWorkspaceAgentPolicy } from './features/settings/useWorkspaceAgentPolicy';
import { useWorkspaceRuntimeProvider } from './features/settings/useWorkspaceRuntimeProvider';
import {
  conversationRuntimeModelSelection,
  latestConversationRuntimeModelEvent,
  projectRuntimeModelOptions,
} from './features/settings/workspaceRuntimeProviderModel';
import type { NewTaskResumeDraft } from './features/task/NewTaskFlow';
import {
  createDesktopNewThreadComposerCatalogClientProviderV2,
} from './features/task/desktopNewThreadComposerCatalogClientProviderV2';
import {
  browserLegacyPlanApprovalStorage,
  canResumeLegacyPlanApproval,
  clearLegacyPlanApprovalRecovery,
  legacyPlanApprovalRuntimeScope,
  newTaskAgentTurnResolution,
  planTaskSignature,
  readLegacyPlanApprovalRecovery,
  type NewTaskAgentTurnOutcome,
} from './features/task/newTaskPlanModel';
import { resolveNewTaskWorkspaceAuthority } from './features/task/newTaskSessionModel';
import {
  currentWorkspaceAutonomyAttentionResolveAttempt,
  discardWorkspaceAutonomyAttentionResolveAttempt,
  resolveWorkspaceAutonomyAttentionAttempt,
  retainOpenWorkspaceAutonomyAttentionResolveAttempts,
  type WorkspaceAutonomyAttentionResolveAttempt,
} from './features/workspace/autonomyAttentionResolveAttemptModel';
import { createCapabilityWorkspaceCollaborationClient } from './features/workspace/capabilityWorkspaceCollaborationClient';
import { workspaceCollaborationAuthorityEvent } from './features/workspace/workspaceCollaborationAuthorityEvent';
import type {
  WorkspaceAuthorityInvalidation,
  WorkspaceAuthorityInvalidationTrigger,
} from './features/workspace/workspaceCollaborationModel';
import {
  applyWorkspaceActivityStreamEvent,
  type WorkspaceLiveActivity,
} from './features/workspace/workspaceActivityEventModel';
import {
  WorkspaceCreateScopeChangedError,
  mergeWorkspaceIntoProjectCatalog,
  workspaceCreateScopeIsCurrent,
} from './features/workspace/workspaceCreateModel';
import type { WorkspaceCreateScope } from './features/workspace/workspaceCreateModel';
import {
  removeWorkspaceAgentBindingById,
  upsertWorkspaceAgentBinding,
} from './features/workspace/workspaceAgentBindingsModel';
import {
  removeWorkspaceMemberByUserId,
  upsertWorkspaceMember,
} from './features/workspace/workspaceMembersModel';
import {
  WorkspaceSettingsScopeChangedError,
  replaceWorkspaceInList,
  replaceWorkspaceInProjectCatalog,
  workspaceSettingsScopeIsCurrent,
} from './features/workspace/workspaceSettingsModel';
import type { WorkspaceSettingsScope } from './features/workspace/workspaceSettingsModel';
import { beginDesktopRuntimeScopeTransition } from './features/workspace/workspaceOverviewModel';
import {
  UNBOUND_CONVERSATIONS_KEY,
  beginWorkspaceConversationRequest,
  isCurrentWorkspaceConversationRequest,
  projectConversationLoadTargets,
  removeConversationFromWorkspaceRows,
  reconcileExpandedWorkspaceIds,
  reconcileWorkspaceConversationRowsAfterRefresh,
  replaceConversationInWorkspaceRows,
  resolveRuntimeWorkspaceId,
  shouldClearConversationSelectionAfterRefresh,
  shouldLoadWorkspaceConversations,
  shouldPreserveConversationSelectionDuringSidecarRecovery,
  supersedeWorkspaceConversationRequests,
  workspaceTreeRefreshFailed,
} from './features/workspace/workspaceTreeModel';
import { socketEventWindowSince, socketEventsSince, useAgentSocket } from './hooks/useAgentSocket';
import { useTerminalProxy } from './hooks/useTerminalProxy';
import { useI18n } from './i18n';
import { useThemePreference } from './theme';
import type {
  AgentConversation,
  AgentTimelineItem,
  AgentWsEvent,
  AuthState,
  ConnectionState,
  ConversationTimelineState,
  ChangeSnapshot,
  CodeRangeReference,
  ComposerContextItem,
  DesktopArtifactVersion,
  DesktopRun,
  DesktopRunInput,
  DesktopRuntimeConfig,
  HitlResponseSubmission,
  LocalRuntimeStatus,
  LlmRoutingRole,
  PlanSnapshot,
  ProjectSummary,
  ProjectWorkItem,
  RuntimeNodeLoadState,
  RuntimeDataset,
  RunSummary,
  RunInputDelivery,
  TerminalServiceResponse,
  WorkbenchSection,
  WorkspaceAgentBinding,
  WorkspaceAutonomyAttention,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
  WorkspaceSummary,
  WorkspaceTask,
} from './types';
import { mergeLocalRuntimeStatus } from './types';
import {
  desktopMCPAppSandboxProxyUrl,
  failLoadingWorkspaceAuthority,
  formatConnectionError,
  formatError,
  formatRunTime,
  loadingWorkspaceAuthority,
  projectSummaryFromConfig,
  resolveSidebarProjects,
  resolveWorkspaceAuthority,
  timestampFromIso,
  unavailableWorkspaceAuthority,
  workspaceLabel,
} from './utils/format';
import {
  agentTaskUpdateFromSocketEvent,
  mergeLiveTimelineEvent,
  mergeTimelineItems,
  timelineCursorFromFirst,
  timelineCursorFromLast,
} from './features/chat/appTimelineEventModel';
import { buildWorkspaceArtifacts } from './features/session/workspaceArtifactModel';
import {
  emptyAuthState,
  emptyDataset,
  agentConversationScopeKey,
  agentConversationScopeKeyFor,
  agentConversationSelectionIdentity,
  AUTHENTICATION_PASSTHROUGH_ROUTE_IDS,
  detectNativeDesktopShell,
  isEditableEventTarget,
  localRuntimeSidecarConfig,
  SIDEBAR_WIDTH_CONSTRAINTS,
  SIDEBAR_WIDTH_STORAGE_KEY,
  WorkspaceSsoFlowError,
  type AgentConversationSession,
  type AgentTaskSignalPatch,
  type CommandPaletteItem,
  type ReviewTab,
  type SidebarRunItem,
} from './appShellTypes';
import {
  runControlLabels,
  SESSION_RUN_ACTION_LABEL_KEY,
  runtimeHealthLabels,
  runtimeTargetComposerOptions,
  runtimeTargetLabels,
  titlebarRunLabelFromStatus,
  titlebarRunStateFromStatus,
  type RunControlState,
  type RuntimeHealthState,
  type RuntimeTarget,
} from './features/runtime/runStatusModel';
import { useDesktopAuth } from './hooks/useDesktopAuth';
import { useAgentConversation } from './hooks/useAgentConversation';

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

type ScopedWorkspaceAutonomyAttentionAuthority = {
  scopeKey: string;
  authority: WorkspaceAuthorityCollection<WorkspaceAutonomyAttention>;
};

const WORKSPACE_AUTONOMY_RETRY_ROLES = new Set(['owner', 'editor', 'admin']);

function workspaceAutonomyAttentionScopeKey(
  config: Pick<DesktopRuntimeConfig, 'tenantId' | 'projectId' | 'workspaceId'>,
): string {
  return `${config.tenantId}\u0000${config.projectId}\u0000${config.workspaceId}`;
}

export function App() {
  const runsInNativeDesktop = detectNativeDesktopShell();
  const { locale, t } = useI18n();
  const { resolved: themeAppearance } = useThemePreference();
  const { showToast } = useToast();
  const [config, setConfig] = useState<DesktopRuntimeConfig>(() =>
    initialDesktopRuntimeConfig(undefined, runsInNativeDesktop),
  );
  const [auth, setAuth] = useState<AuthState>(emptyAuthState);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [invitationSignInRequested, setInvitationSignInRequested] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [shortcutsDialogOpen, setShortcutsDialogOpen] = useState(false);
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [workspaceCreateOpen, setWorkspaceCreateOpen] = useState(false);
  const [workspaceSettingsOpen, setWorkspaceSettingsOpen] = useState(false);
  const [newTaskPreferredWorkspaceId, setNewTaskPreferredWorkspaceId] = useState('');
  const [newTaskResumeDraft, setNewTaskResumeDraft] = useState<NewTaskResumeDraft | null>(null);
  const [preferredTaskMode, setPreferredTaskMode] = useState<'work' | 'code'>('work');
  const [newThreadScope, setNewThreadScope] = useState({
    projectId: '',
    workspaceId: '',
  });
  const [newThreadCreating, setNewThreadCreating] = useState(false);
  const [newThreadError, setNewThreadError] = useState<string | null>(null);
  const [settingsWindowOpen, setSettingsWindowOpen] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] = useState<SettingsSection>('account');
  const [commandQuery, setCommandQuery] = useState('');
  const commandInputRef = useRef<HTMLInputElement>(null);
  const commandPaletteTriggerRef = useRef<HTMLElement | null>(null);
  const appShellRef = useRef<HTMLDivElement>(null);
  const loginRestoreTargetRef = useRef<HTMLElement | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // Right-panel visibility is shell-owned state from phase 1; the panel
  // itself lands in a later phase and consumes this flag.
  const [rightSidebarOpen, setRightSidebarOpen] = useState(true);
  // Workbench tabs: view tabs follow the fixed model order, conversation tabs
  // append in open order. The landing view is open from the start.
  const [openTabs, setOpenTabs] = useState<WorkbenchTab[]>([
    { kind: 'view', section: 'workspace' },
  ]);
  // Right sidebar: which panel is active, and whether the sidebar was opened
  // only to reveal the canvas (closing such a canvas closes the sidebar too).
  const [activeRightPanel, setActiveRightPanel] = useState<DesktopRightPanel>('context');
  const [rightSidebarOpenedForCanvas, setRightSidebarOpenedForCanvas] = useState(false);
  const openRightCanvasPanel = useCallback(() => {
    setRightSidebarOpen(true);
    setActiveRightPanel('canvas');
    setRightSidebarOpenedForCanvas(true);
  }, []);
  const closeRightCanvasPanel = useCallback(() => {
    setActiveRightPanel('context');
    setRightSidebarOpenedForCanvas(false);
  }, []);
  const sidebarPanelWidth = useResizablePanelWidth(
    SIDEBAR_WIDTH_STORAGE_KEY,
    SIDEBAR_WIDTH_CONSTRAINTS,
  );
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [runActionsMenuOpen, setRunActionsMenuOpen] = useState(false);
  const runActionsButtonRef = useRef<HTMLButtonElement>(null);
  const runActionsMenuRef = useRef<HTMLDivElement>(null);
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState<Set<string>>(() => new Set());
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [workspaceSso, setWorkspaceSso] = useState<WorkspaceSsoPresentation | null>(null);
  const [dataset, setDataset] = useState<RuntimeDataset>(emptyDataset);
  const [conversationStatusSummary, setConversationStatusSummary] =
    useState<LocalConversationStatusSummary | null>(null);
  const [conversationStatusRefreshRevision, setConversationStatusRefreshRevision] = useState(0);
  const [workspaceLiveActivity, setWorkspaceLiveActivity] = useState<WorkspaceLiveActivity[]>([]);
  const [workspaceAutonomyAttentionState, setWorkspaceAutonomyAttentionState] =
    useState<ScopedWorkspaceAutonomyAttentionAuthority>(() => ({
      scopeKey: '',
      authority: unavailableWorkspaceAuthority<WorkspaceAutonomyAttention>(),
    }));
  const [retryingWorkspaceAutonomyAttentionId, setRetryingWorkspaceAutonomyAttentionId] = useState<
    string | null
  >(null);
  const [resolvingWorkspaceAutonomyAttentionId, setResolvingWorkspaceAutonomyAttentionId] =
    useState<string | null>(null);
  const workspaceAutonomyAttentionResolveAttemptsRef = useRef<
    Map<string, WorkspaceAutonomyAttentionResolveAttempt>
  >(new Map());
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string>('never');
  const [localRuntimeStatus, setLocalRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [runtimeProjectionRefreshRevision, setRuntimeProjectionRefreshRevision] = useState(0);
  const [conversationModelMutation, setConversationModelMutation] = useState({
    scopeKey: '',
    switching: false,
    error: null as string | null,
    hasOverride: false,
    overrideModel: null as string | null,
    baseEventRevision: null as string | null,
  });
  const [selectedSidebarRunId, setSelectedSidebarRunId] = useState('');
  const [runStateById, setRunStateById] = useState<Record<string, RunControlState>>({});
  const [runControlState, setRunControlState] = useState<RunControlState>('running');
  const [runtimeTarget, setRuntimeTarget] = useState<RuntimeTarget>('local');
  const [runLiveMode, setRunLiveMode] = useState(true);
  const [myWorkRefreshing, setMyWorkRefreshing] = useState(false);
  const [sending, setSending] = useState(false);
  const [changeSnapshot, setChangeSnapshot] = useState<ChangeSnapshot | null>(null);
  const [changeScope, setChangeScope] = useState<RunChangeScope>('run');
  const [authoritativeRunSummary, setAuthoritativeRunSummary] = useState<RunSummary | null>(null);
  const [changeSnapshotLoading, setChangeSnapshotLoading] = useState(false);
  const [changeSnapshotError, setChangeSnapshotError] = useState<string | null>(null);
  const [runInputReferences, setRunInputReferences] = useState<CodeRangeReference[]>([]);
  // P1-4: pending inline review comments, in-memory per conversation id.
  const [changeCommentsByConversation, setChangeCommentsByConversation] =
    useState<ChangeReviewCommentMap>({});
  const [runInputDelivery, setRunInputDelivery] = useState<RunInputDelivery | null>(null);
  const [runInputs, setRunInputs] = useState<DesktopRunInput[]>([]);
  const [runInputsLoading, setRunInputsLoading] = useState(false);
  const [runInputsError, setRunInputsError] = useState<string | null>(null);
  const [promotingRunInputId, setPromotingRunInputId] = useState<string | null>(null);
  const [sessionRunActionPending, setSessionRunActionPending] = useState<SessionRunAction | null>(
    null,
  );
  const [sessionPlanApprovalPending, setSessionPlanApprovalPending] = useState(false);
  const [artifactActionPending, setArtifactActionPending] = useState<{
    versionId: string;
    action: ArtifactVersionAction;
  } | null>(null);
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('workspace');
  const activeSectionRef = useRef<WorkbenchSection>('workspace');
  const switchSectionRef = useRef<(section: WorkbenchSection) => void>(() => {});
  const [sectionBackStack, setSectionBackStack] = useState<WorkbenchSection[]>([]);
  const [sectionForwardStack, setSectionForwardStack] = useState<WorkbenchSection[]>([]);
  const [reviewTab, setReviewTab] = useState<ReviewTab>('overview');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [terminal, setTerminal] = useState<TerminalServiceResponse | null>(null);
  const [terminalLifecycle, setTerminalLifecycle] =
    useState<DesktopTerminalLifecycleAuthorityV2 | null>(null);
  const [agentConversationSession, setAgentConversationSession] =
    useState<AgentConversationSession | null>(null);
  const agentConversationSessionRef = useRef(agentConversationSession);
  const [sessionProjectionState, setSessionProjectionState] = useState<SessionProjectionLoadState>(
    emptySessionProjectionState,
  );
  const [sessionDisplayProjection, setSessionDisplayProjection] =
    useState<ConversationSessionProjection | null>(null);
  const [sessionProjectionRefreshRevision, setSessionProjectionRefreshRevision] = useState(0);
  const [conversationTimeline, setConversationTimeline] =
    useState<ConversationTimelineState>(emptyConversationTimeline);
  const [artifactCanvasState, setArtifactCanvasState] = useState<LiveArtifactCanvasState>(() =>
    emptyArtifactCanvasState(),
  );
  const [mcpAppCanvasState, setMCPAppCanvasState] = useState<MCPAppCanvasState>(() =>
    emptyMCPAppCanvasState(),
  );
  const [agentTaskSignals, setAgentTaskSignals] = useState<AgentTaskSignal[]>([]);
  const [
    workspaceCollaborationAuthorityInvalidation,
    setWorkspaceCollaborationAuthorityInvalidation,
  ] = useState<WorkspaceAuthorityInvalidation | null>(null);
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
  const sessionSocketAuthorityRef = useRef({
    connected: false,
    conversationId: '',
  });
  const conversationMetadataEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const authoritativeRunEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceActivityEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceActivityScopeRef = useRef('');
  const workspaceLifecycleEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceMessageEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceRosterEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceTaskEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceCollaborationEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const workspaceCollaborationEventsScopeRef = useRef('');
  const workspaceCollaborationSocketRef = useRef({
    connected: false,
    seenConnected: false,
    workspaceId: '',
  });
  const myWorkRequestRef = useRef(0);
  const myWorkAbortRef = useRef<AbortController | null>(null);
  const myWorkRefreshTimerRef = useRef<number | null>(null);
  const myWorkEventsHeadRef = useRef<AgentWsEvent | null>(null);
  const contextRevisionRef = useRef(0);
  const authRef = useRef(auth);
  const configRef = useRef(config);
  const datasetRef = useRef(dataset);
  const expandedWorkspaceIdsRef = useRef(expandedWorkspaceIds);
  const runtimeRefreshRequestRef = useRef(0);
  const conversationStatusRequestRef = useRef(0);
  const conversationStatusScopeRef = useRef('');
  const sidecarRecoveryRefreshGenerationRef = useRef<number | null>(null);
  const conversationModelMutationRequestRef = useRef(0);
  const conversationSummaryMutationRequestRef = useRef(0);
  const activeRuntimeConversationRequestsRef = useRef(new Map<string, number>());
  const workspaceConversationRequestGenerationsRef = useRef(new Map<string, number>());
  const configScopeEpochRef = useRef(0);
  const workspaceExpansionScopeRef = useRef('');
  const localResumeAttemptRef = useRef('');
  const authAttemptRevisionRef = useRef(0);
  const pendingPasswordChangeRef = useRef<PendingPasswordChangeAttempt | null>(null);
  const deviceAuthAttemptIdRef = useRef(0);
  const deviceAuthAttemptRef = useRef<{
    attemptId: number;
    nativeAttemptId?: string;
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
  const terminalLifecycleRef = useRef<DesktopTerminalLifecycleAuthorityV2 | null>(null);
  const currentArtifactRunRef = useRef<DesktopRun | null>(null);
  const artifactCanvasStateRef = useRef(artifactCanvasState);
  const mcpAppCanvasStateRef = useRef(mcpAppCanvasState);
  const terminalRunScopeKeyRef = useRef('');
  const workbenchRef = useRef<HTMLElement>(null);
  const settingsRouteCloseNavigationRef = useRef<(() => void) | null>(null);
  const productionRouteRefreshRef = useRef<
    ((nextConfig: DesktopRuntimeConfig, projects: ProjectSummary[]) => Promise<boolean>) | null
  >(null);
  const projectSearchRouteBindingProviderV2 = useMemo(
    () => createProjectSearchRouteBindingProviderV2(),
    [],
  );
  const projectCronJobsRouteBindingProviderV2 = useMemo(
    () => createProjectCronJobsRouteBindingProviderV2(),
    [],
  );
  const desktopWorkbenchCapabilityClientProviderV2 = useMemo(
    () => createDesktopWorkbenchCapabilityClientProviderV2(),
    [],
  );
  const desktopPluginMarketplaceGenerationActionsRefV2 =
    useRef<DesktopRendererGenerationActionsV2 | null>(null);
  const desktopProjectBlackboardOperationsV2 = useMemo(
    () =>
      createDesktopProjectBlackboardOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceCollaborationClientV2 = useMemo(
    () =>
      createDesktopWorkspaceCollaborationClientV2(
        desktopProjectBlackboardOperationsV2,
        () => configRef.current,
        'workspace-collaboration',
      ),
    [desktopProjectBlackboardOperationsV2],
  );
  const desktopArtifactClientV2 = useMemo(
    () =>
      createDesktopArtifactContentClientV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
        () => configRef.current,
      ),
    [],
  );
  const desktopAutomationApiV2 = useMemo(
    () =>
      createDesktopAutomationOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
        () => configRef.current,
      ),
    [],
  );
  const desktopPluginMarketplaceOperationsV2 = useMemo(
    () =>
      createDesktopPluginMarketplaceOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantCatalogOperationsV2 = useMemo(
    () =>
      createDesktopTenantCatalogOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantOverviewOperationsV2 = useMemo(
    () =>
      createDesktopTenantOverviewOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantAnalyticsOperationsV2 = useMemo(
    () =>
      createDesktopTenantAnalyticsOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantAgentDashboardOperationsV2 = useMemo(
    () =>
      createDesktopTenantAgentDashboardOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantAgentBindingsOperationsV2 = useMemo(
    () =>
      createDesktopTenantAgentBindingsOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantProjectsOperationsV2 = useMemo(
    () =>
      createDesktopTenantProjectsOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopTenantTasksOperationsV2 = useMemo(
    () =>
      createDesktopTenantTasksOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectOverviewOperationsV2 = useMemo(
    () =>
      createDesktopProjectOverviewOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectAgentDashboardOperationsV2 = useMemo(
    () =>
      createDesktopProjectAgentDashboardOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectAgentLogsOperationsV2 = useMemo(
    () =>
      createDesktopProjectAgentLogsOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectAgentPatternsOperationsV2 = useMemo(
    () =>
      createDesktopProjectAgentPatternsOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectCommunitiesOperationsV2 = useMemo(
    () =>
      createDesktopProjectCommunitiesOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectEntitiesOperationsV2 = useMemo(
    () =>
      createDesktopProjectEntitiesOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectGraphOperationsV2 = useMemo(
    () =>
      createDesktopProjectGraphOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopRuntimePoolOperationsV2 = useMemo(
    () =>
      createDesktopRuntimePoolOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopRuntimeClustersOperationsV2 = useMemo(
    () =>
      createDesktopRuntimeClustersOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopConversationConfigOperationsV2 = useMemo(
    () =>
      createDesktopConversationConfigOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopConversationLifecycleOperationsV2 = useMemo(
    () =>
      createDesktopConversationLifecycleOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceMessageCatalogOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceMessageCatalogOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceConversationCatalogOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceConversationCatalogOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceAgentBindingOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceAgentBindingOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceAutonomyAttentionOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceAutonomyAttentionOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceMemberMutationOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceMemberMutationOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceCatalogOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceCatalogOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceLifecycleOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceLifecycleOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopWorkspaceExecutionSnapshotOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceExecutionSnapshotOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopMyWorkOperationsV2 = useMemo(
    () =>
      createDesktopMyWorkOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopNewTaskFlowClientV2 = useMemo(
    () =>
      createDesktopNewTaskFlowOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopNewThreadCreationOperationsV2 = useMemo(
    () =>
      createDesktopNewThreadCreationOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopProjectSearchOperationsV2 = useMemo(
    () =>
      createDesktopProjectSearchOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
        () => configRef.current,
      ),
    [],
  );
  const desktopSessionArtifactActionOperationsV2 = useMemo(
    () =>
      createDesktopSessionArtifactActionOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopSessionRunControlOperationsV2 = useMemo(
    () =>
      createDesktopSessionRunControlOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopHitlResponseOperationsV2 = useMemo(
    () =>
      createDesktopHitlResponseOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopSessionProjectionOperationsV2 = useMemo(
    () =>
      createDesktopSessionProjectionOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopSessionTimelineOperationsV2 = useMemo(
    () =>
      createDesktopSessionTimelineOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopSessionRunChangesOperationsV2 = useMemo(
    () =>
      createDesktopSessionRunChangesOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopSessionRunInputOperationsV2 = useMemo(
    () =>
      createDesktopSessionRunInputOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopAgentAuthorityProviderV2 = useMemo(
    () => createDesktopAgentAuthorityProviderV2(),
    [],
  );
  const desktopProductionRouteAuthorityProviderV2 = useMemo(
    () => createDesktopProductionRouteAuthorityProviderV2(),
    [],
  );
  const desktopWorkspaceRosterOperationsV2 = useMemo(
    () =>
      createDesktopWorkspaceRosterOperationsV2(
        () => desktopPluginMarketplaceGenerationActionsRefV2.current,
      ),
    [],
  );
  const desktopNewThreadComposerCatalogClientProviderV2 = useMemo(
    () => createDesktopNewThreadComposerCatalogClientProviderV2(),
    [],
  );
  const desktopBrowserHashLocation = useMemo(() => createBrowserDesktopHashLocationPort(), []);
  const desktopProductionRouteLocation = useMemo(
    () => createProfileGenerationHashLocationPort(desktopBrowserHashLocation),
    [desktopBrowserHashLocation],
  );
  const desktopProductionRouteNavigation = useMemo(
    () =>
      Object.freeze({
        clearHash: () => {
          window.location.hash = '';
        },
        openPath: (path: string) => {
          window.location.hash = path;
        },
      }),
    [],
  );
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
      const pendingPasswordChange = pendingPasswordChangeRef.current;
      pendingPasswordChangeRef.current = null;
      if (pendingPasswordChange) {
        const nativeCloudAuth = runsInNativeDesktop
          ? desktopNativeCloudAuthClient()
          : null;
        if (nativeCloudAuth && pendingPasswordChange.runtimeConfig.mode === 'cloud') {
          void nativeCloudAuth.signOut().catch(() => undefined);
        } else {
          void new DesktopApiClient({
            ...pendingPasswordChange.runtimeConfig,
            apiKey: pendingPasswordChange.outcome.access_token,
          })
            .signOut()
            .catch(() => undefined);
        }
      }
    },
    [runsInNativeDesktop],
  );

  const updateDataset = useCallback((updater: (current: RuntimeDataset) => RuntimeDataset) => {
    setDataset((current) => {
      const nextDataset = updater(current);
      datasetRef.current = nextDataset;
      return nextDataset;
    });
  }, []);

  const commitRuntimeConfig = useCallback(
    (nextConfig: DesktopRuntimeConfig) => {
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
    },
    [updateDataset],
  );

  const identityAuthenticated = isIdentityAuthenticated(auth);
  authRef.current = auth;
  useEffect(() => {
    if (identityAuthenticated && invitationSignInRequested) {
      setInvitationSignInRequested(false);
    }
  }, [identityAuthenticated, invitationSignInRequested]);
  const showRuntimeConfig = isWorkspaceReady(auth, config);
  const scopedConversation =
    agentConversationSession?.scopeKey === agentConversationScopeKey(config)
      ? agentConversationSession.conversation
      : null;
  const scopedConversationId = scopedConversation?.id ?? '';
  // Every path that surfaces a conversation (sidebar selection, new-task
  // sessions, resumes) funnels through agentConversationSession, so a single
  // effect keeps the tab row in sync instead of hooking each call site.
  useEffect(() => {
    if (!scopedConversation) return;
    setOpenTabs((tabs) =>
      ensureConversationTab(tabs, {
        projectId: config.projectId,
        workspaceId: config.workspaceId,
        conversationId: scopedConversation.id,
        title: scopedConversation.title,
      }),
    );
  }, [scopedConversation, config.projectId, config.workspaceId]);
  const api = useMemo(() => new DesktopApiClient(config), [config]);
  const desktopRendererRouteRefsV2 = useMemo(
    () => ({
      authRef,
      configRef,
      desktopProductionRouteLocation,
      desktopProductionRouteNavigation,
      pluginMarketplaceOperationsV2: desktopPluginMarketplaceOperationsV2,
      projectBlackboardOperationsV2: desktopProjectBlackboardOperationsV2,
      projectAgentDashboardOperationsV2: desktopProjectAgentDashboardOperationsV2,
      projectAgentLogsOperationsV2: desktopProjectAgentLogsOperationsV2,
      projectAgentPatternsOperationsV2: desktopProjectAgentPatternsOperationsV2,
      projectCommunitiesOperationsV2: desktopProjectCommunitiesOperationsV2,
      projectEntitiesOperationsV2: desktopProjectEntitiesOperationsV2,
      projectGraphOperationsV2: desktopProjectGraphOperationsV2,
      projectOverviewOperationsV2: desktopProjectOverviewOperationsV2,
      runtimePoolOperationsV2: desktopRuntimePoolOperationsV2,
      runtimeClustersOperationsV2: desktopRuntimeClustersOperationsV2,
      tenantAgentBindingsOperationsV2: desktopTenantAgentBindingsOperationsV2,
      tenantAgentDashboardOperationsV2: desktopTenantAgentDashboardOperationsV2,
      tenantAnalyticsOperationsV2: desktopTenantAnalyticsOperationsV2,
      tenantCatalogOperationsV2: desktopTenantCatalogOperationsV2,
      tenantOverviewOperationsV2: desktopTenantOverviewOperationsV2,
      tenantProjectsOperationsV2: desktopTenantProjectsOperationsV2,
      tenantTasksOperationsV2: desktopTenantTasksOperationsV2,
      desktopWorkspaceCatalogOperationsV2,
      desktopWorkspaceLifecycleOperationsV2,
      projectCronJobsRouteBindingProviderV2,
      projectSearchOperationsV2: desktopProjectSearchOperationsV2,
      projectSearchRouteBindingProviderV2,
      setAuth,
      setInvitationSignInRequested,
      setSettingsInitialSection,
      setSettingsWindowOpen,
      commitRuntimeConfig,
      settingsRouteCloseNavigationRef,
    }),
    [
      desktopPluginMarketplaceOperationsV2,
      desktopProjectBlackboardOperationsV2,
      desktopProjectAgentDashboardOperationsV2,
      desktopProjectAgentLogsOperationsV2,
      desktopProjectAgentPatternsOperationsV2,
      desktopProjectCommunitiesOperationsV2,
      desktopProjectEntitiesOperationsV2,
      desktopProjectGraphOperationsV2,
      desktopProjectOverviewOperationsV2,
      desktopProjectSearchOperationsV2,
      desktopRuntimePoolOperationsV2,
      desktopRuntimeClustersOperationsV2,
      desktopTenantAgentBindingsOperationsV2,
      desktopTenantAgentDashboardOperationsV2,
      desktopTenantAnalyticsOperationsV2,
      desktopTenantCatalogOperationsV2,
      desktopTenantOverviewOperationsV2,
      desktopTenantProjectsOperationsV2,
      desktopTenantTasksOperationsV2,
      desktopWorkspaceCatalogOperationsV2,
      desktopWorkspaceLifecycleOperationsV2,
    ],
  );
  const desktopRendererCompositionV2 = useMemo(
    () => createDesktopRendererAppCompositionPortV2(desktopRendererRouteRefsV2),
    [desktopRendererRouteRefsV2],
  );
  const desktopRendererGenerationV2 = useDesktopRendererGenerationHostV2(
    config,
    identityAuthenticated,
    desktopRendererCompositionV2,
  );
  useLayoutEffect(() => {
    const actions = desktopRendererGenerationV2.actions;
    desktopPluginMarketplaceGenerationActionsRefV2.current = actions;
    return () => {
      if (desktopPluginMarketplaceGenerationActionsRefV2.current === actions) {
        desktopPluginMarketplaceGenerationActionsRefV2.current = null;
      }
    };
  }, [desktopRendererGenerationV2.actions]);
  const {
    authority: desktopRendererAuthorityV2,
    navigationRegistry: desktopCanonicalNavigationRegistry,
    routeRegistry: desktopProductionRouteRegistry,
  } = desktopRendererGenerationV2.state;
  const desktopWorkbenchCapabilityClientV2 = useMemo(
    () =>
      desktopWorkbenchCapabilityClientProviderV2.publish({
        automationApi: desktopAutomationApiV2,
        config,
        pluginMarketplaceOperationsV2: desktopPluginMarketplaceOperationsV2,
        projectBlackboardOperationsV2: desktopProjectBlackboardOperationsV2,
        projectAgentDashboardOperationsV2: desktopProjectAgentDashboardOperationsV2,
        projectAgentLogsOperationsV2: desktopProjectAgentLogsOperationsV2,
        projectAgentPatternsOperationsV2: desktopProjectAgentPatternsOperationsV2,
        projectCommunitiesOperationsV2: desktopProjectCommunitiesOperationsV2,
        projectEntitiesOperationsV2: desktopProjectEntitiesOperationsV2,
        projectGraphOperationsV2: desktopProjectGraphOperationsV2,
        projectOverviewOperationsV2: desktopProjectOverviewOperationsV2,
        runtimePoolOperationsV2: desktopRuntimePoolOperationsV2,
        runtimeClustersOperationsV2: desktopRuntimeClustersOperationsV2,
        desktopWorkspaceCatalogOperationsV2,
        desktopWorkspaceLifecycleOperationsV2,
        tenantAgentBindingsOperationsV2: desktopTenantAgentBindingsOperationsV2,
        tenantAgentDashboardOperationsV2: desktopTenantAgentDashboardOperationsV2,
        tenantAnalyticsOperationsV2: desktopTenantAnalyticsOperationsV2,
        tenantOverviewOperationsV2: desktopTenantOverviewOperationsV2,
        tenantProjectsOperationsV2: desktopTenantProjectsOperationsV2,
        tenantTasksOperationsV2: desktopTenantTasksOperationsV2,
      }),
    [
      config,
      desktopAutomationApiV2,
      desktopPluginMarketplaceOperationsV2,
      desktopProjectBlackboardOperationsV2,
      desktopProjectAgentDashboardOperationsV2,
      desktopProjectAgentLogsOperationsV2,
      desktopProjectAgentPatternsOperationsV2,
      desktopProjectCommunitiesOperationsV2,
      desktopProjectEntitiesOperationsV2,
      desktopProjectGraphOperationsV2,
      desktopProjectOverviewOperationsV2,
      desktopRuntimePoolOperationsV2,
      desktopRuntimeClustersOperationsV2,
      desktopWorkspaceCatalogOperationsV2,
      desktopWorkspaceLifecycleOperationsV2,
      desktopTenantAgentBindingsOperationsV2,
      desktopTenantAgentDashboardOperationsV2,
      desktopTenantAnalyticsOperationsV2,
      desktopTenantOverviewOperationsV2,
      desktopTenantProjectsOperationsV2,
      desktopTenantTasksOperationsV2,
      desktopWorkbenchCapabilityClientProviderV2,
    ],
  );
  const sandboxRuntime = useSandboxRuntimeSurface(
    config,
    showRuntimeConfig && connection === 'ready' && Boolean(config.projectId.trim()),
  );
  const chatComposerApi = useMemo(
    () => (config.workspaceId.trim() ? api : unboundComposerCatalogClient(api)),
    [api, config.workspaceId],
  );
  const socket = useAgentSocket(
    config,
    showRuntimeConfig && connection === 'ready',
    auth.context?.revision ?? null,
    scopedConversation?.id ?? null,
    desktopRendererGenerationV2.actions.acquireOperationLease,
  );
  const invalidateWorkspaceCollaborationAuthority = useCallback(
    (trigger: WorkspaceAuthorityInvalidationTrigger) => {
      setWorkspaceCollaborationAuthorityInvalidation((current) => ({
        sequence: (current?.sequence ?? 0) + 1,
        trigger,
      }));
    },
    [],
  );
  useEffect(() => {
    const workspaceId = config.workspaceId.trim();
    const previous = workspaceCollaborationSocketRef.current;
    if (previous.workspaceId !== workspaceId) {
      workspaceCollaborationSocketRef.current = {
        connected: socket.connected,
        seenConnected: socket.connected,
        workspaceId,
      };
      return;
    }
    const reconnect =
      Boolean(workspaceId) && socket.connected && previous.seenConnected && !previous.connected;
    workspaceCollaborationSocketRef.current = {
      connected: socket.connected,
      seenConnected: previous.seenConnected || socket.connected,
      workspaceId,
    };
    if (reconnect) invalidateWorkspaceCollaborationAuthority('reconnect');
  }, [config.workspaceId, invalidateWorkspaceCollaborationAuthority, socket.connected]);
  useEffect(() => {
    const emptyArtifactState = emptyArtifactCanvasState();
    const emptyMCPAppState = emptyMCPAppCanvasState();
    artifactCanvasStateRef.current = emptyArtifactState;
    mcpAppCanvasStateRef.current = emptyMCPAppState;
    setArtifactCanvasState(emptyArtifactState);
    setMCPAppCanvasState(emptyMCPAppState);
  }, [scopedConversationId]);
  const agentDefinitionEvent = useMemo(
    () => latestAgentDefinitionEvent(socket.events),
    [socket.events],
  );
  const modalOpen =
    loginModalOpen ||
    commandPaletteOpen ||
    newTaskOpen ||
    settingsWindowOpen ||
    shortcutsDialogOpen;
  const localRuntimeMode = config.mode === 'local' && runsInNativeDesktop;
  const desktopAgentAuthorityV2 = useMemo(
    () =>
      desktopAgentAuthorityProviderV2.publish({
        config,
        principalId: auth.user?.user_id,
      }),
    [auth.user?.user_id, config, desktopAgentAuthorityProviderV2],
  );
  const {
    adapter: activityAuthorityAdapter,
    cloudScope: activityAuthorityScope,
  } = desktopAgentAuthorityV2;
  const listMyWorkForConfig = useCallback(
    (requestConfig: DesktopRuntimeConfig, signal?: AbortSignal) =>
      desktopMyWorkOperationsV2.listMyWork({
        config: requestConfig,
        principalId: authRef.current.user?.user_id,
        signal,
      }),
    [desktopMyWorkOperationsV2],
  );
  const localRuntimeAuthorityReady = isCurrentLocalRuntimeAuthority(
    config,
    localRuntimeStatus,
    runsInNativeDesktop,
  );
  const desktopCapabilityState = useDesktopCapabilitySnapshot(
    desktopWorkbenchCapabilityClientV2.client,
    identityAuthenticated && showRuntimeConfig,
  );
  const desktopProductionRouteAuthorityV2 = useMemo(
    () =>
      desktopProductionRouteAuthorityProviderV2.publish({
        auth,
        config,
        capabilitySnapshot: desktopCapabilityState.snapshot,
        cloudRequestBroker: desktopVaultBoundCloudRequestBroker(),
        workspaceRosterOperationsV2: desktopWorkspaceRosterOperationsV2,
      }),
    [
      auth,
      config,
      desktopCapabilityState.snapshot,
      desktopProductionRouteAuthorityProviderV2,
      desktopWorkspaceRosterOperationsV2,
    ],
  );
  projectSearchRouteBindingProviderV2.publish({
    scope: Object.freeze({
      tenantId: config.tenantId,
      projectId: config.projectId,
    }),
    projects: auth.projects,
    capabilitySnapshot: desktopCapabilityState.snapshot,
    capabilityLoading: desktopCapabilityState.loading,
    onRetryCapability: desktopCapabilityState.reload,
  });
  const workspaceCollaborationClientV2 = useMemo(
    () =>
      createCapabilityWorkspaceCollaborationClient(
        desktopWorkspaceCollaborationClientV2,
        desktopCapability(desktopCapabilityState.snapshot, 'workspace_collaboration'),
        config.mode,
      ),
    [
      config.mode,
      desktopCapabilityState.snapshot,
      desktopWorkspaceCollaborationClientV2,
    ],
  );
  const runtimeModelRole: LlmRoutingRole =
    scopedConversation?.agent_config?.capability_mode === 'code' ? 'coding' : 'default';
  const {
    provider: runtimeProvider,
    modelOptions: runtimeModelOptions,
    selectedModelValue: selectedRuntimeModelValue,
    switchingModel: switchingRuntimeModel,
    modelError: runtimeModelError,
    selectModel: selectRuntimeModel,
  } = useWorkspaceRuntimeProvider(
    config,
    identityAuthenticated &&
      showRuntimeConfig &&
      connection === 'ready' &&
      (config.mode === 'cloud' || (localRuntimeMode && localRuntimeAuthorityReady)),
    runtimeProjectionRefreshRevision,
    runtimeModelRole,
  );
  const newThreadWorkspaces = dataset.workspacesByProject[config.projectId] ?? [];
  const configuredNewThreadWorkspaceId = newThreadWorkspaces.some(
    (workspace) => workspace.id === config.workspaceId,
  )
    ? config.workspaceId
    : '';
  const newThreadWorkspaceId =
    newThreadScope.projectId === config.projectId &&
    (!newThreadScope.workspaceId ||
      newThreadWorkspaces.some((workspace) => workspace.id === newThreadScope.workspaceId))
      ? newThreadScope.workspaceId
      : configuredNewThreadWorkspaceId;
  const newThreadRuntimeConfig = useMemo(
    () => ({ ...config, workspaceId: newThreadWorkspaceId }),
    [config, newThreadWorkspaceId],
  );
  const desktopNewThreadComposerCatalogClientV2 = useMemo(
    () =>
      desktopNewThreadComposerCatalogClientProviderV2.publish({
        config: newThreadRuntimeConfig,
        pluginMarketplaceOperationsV2: desktopPluginMarketplaceOperationsV2,
        workspaceRosterOperationsV2: desktopWorkspaceRosterOperationsV2,
      }),
    [
      desktopNewThreadComposerCatalogClientProviderV2,
      desktopPluginMarketplaceOperationsV2,
      desktopWorkspaceRosterOperationsV2,
      newThreadRuntimeConfig,
    ],
  );
  const workspaceAgentPolicy = useWorkspaceAgentPolicy(
    newThreadRuntimeConfig,
    identityAuthenticated && showRuntimeConfig && connection === 'ready',
    desktopWorkspaceRosterOperationsV2,
  );
  const canManageWorkspacePolicy = useMemo(() => {
    if (auth.user?.roles.some((role) => role === 'admin' || role === 'owner')) return true;
    const membership = workspaceAgentPolicy.members.find(
      (member) =>
        member.workspace_id === newThreadWorkspaceId && member.user_id === auth.user?.user_id,
    );
    return membership?.role === 'manager' || membership?.role === 'owner';
  }, [auth.user, newThreadWorkspaceId, workspaceAgentPolicy.members]);

  const syncLocalRuntimeConfig = useCallback(
    async (nextConfig: DesktopRuntimeConfig): Promise<DesktopRuntimeConfig> => {
      if (!runsInNativeDesktop || nextConfig.mode !== 'local') return nextConfig;
      const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
      if (!invoke) return nextConfig;
      const status = await invoke<LocalRuntimeStatus>('local_runtime_configure', {
        config: localRuntimeSidecarConfig(nextConfig),
      });
      setLocalRuntimeStatus(status);
      return mergeLocalRuntimeStatus(nextConfig, status);
    },
    [runsInNativeDesktop],
  );

  const refreshLocalRuntimeStatus = useCallback(async (): Promise<void> => {
    if (!runsInNativeDesktop || configRef.current.mode !== 'local') return;
    const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
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
  }, [commitRuntimeConfig, runsInNativeDesktop]);

  useEffect(() => {
    if (!localRuntimeMode) return;
    let cancelled = false;
    const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
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
    if (!scopedConversation) {
      sessionProjectionRequestRef.current += 1;
      setSessionProjectionState(emptySessionProjectionState);
      setSessionDisplayProjection(null);
      return;
    }
    const requestConfig = configRef.current;
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
    void desktopSessionProjectionOperationsV2.getConversationSession({
      config: requestConfig,
      conversation: scopedConversation,
      signal: controller.signal,
    })
      .then((payload) => {
        if (controller.signal.aborted || sessionProjectionRequestRef.current !== requestId) return;
        // A schema_version 1 snapshot_revision is the canonical digest of the payload,
        // so an unchanged revision means the already-decoded projection still holds;
        // skip the canonicalize + SHA-256 + validate pass entirely in that case.
        const scopeKey = [
          scopedConversationId,
          requestConfig.tenantId,
          requestConfig.projectId,
          requestConfig.workspaceId || '',
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
                projectId: requestConfig.projectId,
                tenantId: requestConfig.tenantId,
                workspaceId: requestConfig.workspaceId || null,
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
          error: formatConnectionError(caught, requestConfig.apiBaseUrl),
        });
      });
    return () => controller.abort();
  }, [
    desktopSessionProjectionOperationsV2,
    scopedConversation,
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
    () => respondableHitlRequestsForProjection(sessionProjection).map((request) => request.id),
    [sessionProjection],
  );
  const respondableHitlRequestIdSet = useMemo(
    () => new Set(respondableHitlRequestIds),
    [respondableHitlRequestIds],
  );
  const permissionPresetScopeKey = permissionPresetScope(config.workspaceId, scopedConversationId);
  const [permissionPreset, setPermissionPreset] = useState<PermissionPreset>('default');
  const [fullAccessWarningAcknowledged, setFullAccessWarningAcknowledged] = useState(false);
  useEffect(() => {
    setPermissionPreset(
      permissionPresetScopeKey ? readPermissionPreset(permissionPresetScopeKey) : 'default',
    );
  }, [permissionPresetScopeKey]);
  useEffect(() => {
    setFullAccessWarningAcknowledged(readFullAccessWarningAcknowledged(config.workspaceId));
  }, [config.workspaceId]);
  const handlePermissionPresetChange = useCallback(
    (preset: PermissionPreset) => {
      if (permissionPresetScopeKey) writePermissionPreset(permissionPresetScopeKey, preset);
      setPermissionPreset(preset);
    },
    [permissionPresetScopeKey],
  );
  const handleAcknowledgeFullAccessWarning = useCallback(() => {
    acknowledgeFullAccessWarning(config.workspaceId);
    setFullAccessWarningAcknowledged(true);
  }, [config.workspaceId]);
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
      plan_history: displaySessionProjection.planHistory.map((plan) => ({
        ...plan,
      })),
      run_health: displaySessionProjection.runHistory,
      pending_hitl: displaySessionProjection.pendingHitl.map((request) => ({
        ...request,
      })),
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
                workspaceId: scopedConversation.workspace_id ?? (config.workspaceId.trim() || null),
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
        shouldPreserveConversationSelectionDuringSidecarRecovery(
          sidecarRecoveryRefreshGenerationRef.current,
          runtimeRefreshRequestRef.current,
        )
      ) {
        return;
      }
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
        const response = await desktopSessionTimelineOperationsV2.getConversationMessages({
          config: {
            ...requestConfig,
            projectId,
          },
          conversation,
          limit: 50,
        });
        if (!requestIsCurrent()) return;
        const responseItems = response.timeline ?? [];
        const restoredArtifactCanvas = replayArtifactCanvasEvents(responseItems);
        artifactCanvasStateRef.current = restoredArtifactCanvas;
        setArtifactCanvasState(restoredArtifactCanvas);
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
                ? {
                    timeUs: response.first_time_us,
                    counter: response.first_counter,
                  }
                : timelineCursorFromFirst(items),
            lastCursor:
              typeof response.last_time_us === 'number' && typeof response.last_counter === 'number'
                ? {
                    timeUs: response.last_time_us,
                    counter: response.last_counter,
                  }
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
    [desktopSessionTimelineOperationsV2],
  );

  const loadEarlierTimeline = useCallback(async () => {
    const conversation = scopedConversation;
    const cursor = conversationTimeline.firstCursor;
    if (!conversation || !cursor || conversationTimeline.loadingEarlier) return;
    const requestConfig = configRef.current;
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
      const response = await desktopSessionTimelineOperationsV2.getConversationMessages({
        config: requestConfig,
        conversation,
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
              formatConnectionError(caught, requestConfig.apiBaseUrl),
            )
          : current,
      );
    }
  }, [
    conversationTimeline.firstCursor,
    conversationTimeline.loadingEarlier,
    desktopSessionTimelineOperationsV2,
    scopedConversation,
    t,
  ]);

  const respondToHitl = useCallback(
    async (submission: HitlResponseSubmission) => {
      const requestConfig = configRef.current;
      if (!scopedConversation) {
        throw new Error(t('session.authorityActionUnavailable'));
      }
      const request = sessionProjection?.pendingHitl.find(
        (candidate) => candidate.id === submission.requestId,
      );
      if (
        !request ||
        request.status !== 'pending' ||
        request.kind !== submission.hitlType ||
        request.authority_revision !== submission.expectedRevision ||
        !respondableHitlRequestIdSet.has(submission.requestId)
      ) {
        throw new Error(t('session.authorityActionUnavailable'));
      }
      setError(null);
      try {
        await desktopHitlResponseOperationsV2.respond({
          config: requestConfig,
          conversation: scopedConversation,
          submission,
        });
        invalidateSessionAuthority();
        const conversation = agentConversationSession?.conversation;
        if (conversation) {
          await loadConversationTimeline(conversation, requestConfig.projectId);
        }
      } catch (caught) {
        const recovery = classifyHitlAuthorityRecovery(caught);
        if (recovery.canonicalRefetch) {
          invalidateSessionAuthority();
          const conversation = agentConversationSession?.conversation;
          if (conversation) {
            await loadConversationTimeline(conversation, requestConfig.projectId);
          }
          if (recovery.settledByAuthority) return;
        }
        const message = formatConnectionError(caught, requestConfig.apiBaseUrl);
        setError(message);
        throw new Error(message, { cause: caught });
      }
    },
    [
      agentConversationSession?.conversation,
      desktopHitlResponseOperationsV2,
      invalidateSessionAuthority,
      loadConversationTimeline,
      respondableHitlRequestIdSet,
      scopedConversation,
      sessionProjection,
      t,
    ],
  );

  const presetAutoApprovalAttemptsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    presetAutoApprovalAttemptsRef.current.clear();
  }, [scopedConversationId]);
  useEffect(() => {
    if (!scopedConversationId || permissionPreset === 'default') return;
    const requests = respondableHitlRequestsForProjection(sessionProjection);
    for (const request of requests) {
      const submission = autoApprovalSubmission(request, permissionPreset);
      if (!submission) continue;
      const attemptKey = `${request.id}:${request.authority_revision ?? 'unversioned'}`;
      if (presetAutoApprovalAttemptsRef.current.has(attemptKey)) continue;
      presetAutoApprovalAttemptsRef.current.add(attemptKey);
      void respondToHitl(submission)
        .then(() => {
          // Truthfulness: fold the resolved-with-preset marker into the local
          // timeline immediately; the canonical refetch keeps it when the
          // runtime echoes the response data.
          setConversationTimeline((current) => ({
            ...current,
            items: applyHitlResponseStreamEvent(current.items, {
              type: 'permission_replied',
              data: {
                request_id: request.id,
                granted: true,
                auto_approved: true,
                preset: permissionPreset,
              },
            }).items,
          }));
        })
        .catch(() => undefined);
    }
  }, [permissionPreset, respondToHitl, scopedConversationId, sessionProjection]);

  useEffect(() => {
    const previous = sessionSocketAuthorityRef.current;
    sessionSocketAuthorityRef.current = {
      connected: socket.connected,
      conversationId: scopedConversationId,
    };
    if (
      !socket.connected ||
      !scopedConversationId ||
      (previous.connected && previous.conversationId === scopedConversationId)
    ) {
      return;
    }
    invalidateSessionAuthority();
    const conversation = agentConversationSessionRef.current?.conversation;
    if (conversation?.id === scopedConversationId) {
      void loadConversationTimeline(conversation, conversation.project_id);
    }
  }, [
    invalidateSessionAuthority,
    loadConversationTimeline,
    scopedConversationId,
    socket.connected,
  ]);

  useEffect(() => {
    if (!scopedConversationId) return;
    let refreshFrame: number | null = null;
    const recoverCanonicalAuthority = () => {
      if (refreshFrame !== null) return;
      refreshFrame = window.requestAnimationFrame(() => {
        refreshFrame = null;
        const conversation = agentConversationSessionRef.current?.conversation;
        if (conversation?.id !== scopedConversationId) return;
        invalidateSessionAuthority();
        void loadConversationTimeline(conversation, conversation.project_id);
      });
    };
    const recoverVisibleAuthority = () => {
      if (document.visibilityState === 'visible') recoverCanonicalAuthority();
    };
    window.addEventListener('focus', recoverCanonicalAuthority);
    document.addEventListener('visibilitychange', recoverVisibleAuthority);
    return () => {
      window.removeEventListener('focus', recoverCanonicalAuthority);
      document.removeEventListener('visibilitychange', recoverVisibleAuthority);
      if (refreshFrame !== null) window.cancelAnimationFrame(refreshFrame);
    };
  }, [invalidateSessionAuthority, loadConversationTimeline, scopedConversationId]);

  const openCommandPalette = useCallback((trigger?: HTMLElement | null) => {
    commandPaletteTriggerRef.current =
      trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setRunActionsMenuOpen(false);
    setSessionMenuOpen(false);
    setShortcutsDialogOpen(false);
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
      if (
        (event.metaKey || event.ctrlKey) &&
        event.altKey &&
        (key === 'u' || event.code === 'KeyU')
      ) {
        event.preventDefault();
        switchSectionRef.current('activity');
        return;
      }
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
        (event.metaKey || event.ctrlKey) &&
        event.key === '/' &&
        !commandPaletteOpen &&
        !loginModalOpen &&
        !newTaskOpen &&
        !settingsWindowOpen
      ) {
        event.preventDefault();
        setShortcutsDialogOpen((open) => !open);
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
      if (event.key === 'Escape' && shortcutsDialogOpen) {
        event.preventDefault();
        setShortcutsDialogOpen(false);
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
    newTaskOpen,
    openCommandPalette,
    runActionsMenuOpen,
    sessionMenuOpen,
    settingsWindowOpen,
    shortcutsDialogOpen,
  ]);

  useEffect(() => {
    const shell = appShellRef.current;
    if (!shell) return;
    const backgroundRoots = [document.getElementById('root'), shell.parentElement, shell].filter(
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
        return reconcileAgentTaskSignals(current, update);
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
    const eventWindow = socketEventWindowSince(socket.events, sessionEventsHeadRef.current);
    const events = eventWindow.events;
    sessionEventsHeadRef.current = socket.events[0] ?? null;
    if (eventWindow.cursorGap) {
      invalidateSessionAuthority();
      if (config.workspaceId.trim()) {
        invalidateWorkspaceCollaborationAuthority('cursor_gap');
      }
      const conversation = agentConversationSessionRef.current?.conversation;
      if (conversation) {
        void loadConversationTimeline(conversation, conversation.project_id);
      }
    }
    if (!events.length) return;
    const activeConversation = scopedConversation;
    if (!activeConversation) return;
    const scope = {
      conversationId: activeConversation.id,
      workspaceId: activeConversation.workspace_id ?? (config.workspaceId.trim() || null),
    };
    const timelineEvents = events.filter((event) =>
      socketEventMatchesSessionScope(event, scope, false),
    );
    if (timelineEvents.length) {
      let nextArtifactCanvas = artifactCanvasStateRef.current;
      let lastArtifactAction: 'open' | 'update' | 'close' | null = null;
      let nextMCPAppCanvas = mcpAppCanvasStateRef.current;
      let openedMCPApp = false;
      for (const event of timelineEvents) {
        const result = applyArtifactCanvasStreamEvent(nextArtifactCanvas, event);
        if (result.handled) {
          nextArtifactCanvas = result.state;
          if (result.action) lastArtifactAction = result.action;
        }
        const mcpAppResult = applyMCPAppCanvasStreamEvent(nextMCPAppCanvas, event);
        if (!mcpAppResult.handled) continue;
        nextMCPAppCanvas = mcpAppResult.state;
        if (mcpAppResult.action === 'open') openedMCPApp = true;
      }
      if (nextArtifactCanvas !== artifactCanvasStateRef.current) {
        artifactCanvasStateRef.current = nextArtifactCanvas;
        setArtifactCanvasState(nextArtifactCanvas);
      }
      if (nextMCPAppCanvas !== mcpAppCanvasStateRef.current) {
        mcpAppCanvasStateRef.current = nextMCPAppCanvas;
        setMCPAppCanvasState(nextMCPAppCanvas);
      }
      if (openedMCPApp) {
        setReviewTab('apps');
        openRightCanvasPanel();
      } else if (lastArtifactAction === 'open') {
        setReviewTab('artifacts');
        openRightCanvasPanel();
      } else if (
        lastArtifactAction === 'close' &&
        nextArtifactCanvas.tabs.length === 0 &&
        reviewTab === 'artifacts'
      ) {
        closeRightCanvasPanel();
      }
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
      events.some((event) => socketEventInvalidatesSessionProjectionForScope(event, scope)) &&
      sessionProjectionRefreshTimerRef.current === null
    ) {
      sessionProjectionRefreshTimerRef.current = window.setTimeout(() => {
        sessionProjectionRefreshTimerRef.current = null;
        invalidateSessionAuthority();
      }, 150);
    }
  }, [
    config.workspaceId,
    invalidateSessionAuthority,
    invalidateWorkspaceCollaborationAuthority,
    loadConversationTimeline,
    reviewTab,
    scopedConversation,
    socket.events,
  ]);

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
    const workspaceId = config.workspaceId.trim();
    if (workspaceCollaborationEventsScopeRef.current !== workspaceId) {
      workspaceCollaborationEventsScopeRef.current = workspaceId;
      workspaceCollaborationEventsHeadRef.current = socket.events[0] ?? null;
      return;
    }
    const events = socketEventsSince(socket.events, workspaceCollaborationEventsHeadRef.current);
    workspaceCollaborationEventsHeadRef.current = socket.events[0] ?? null;
    if (
      workspaceId &&
      events.some((event) => workspaceCollaborationAuthorityEvent(event, workspaceId))
    ) {
      invalidateWorkspaceCollaborationAuthority('delta');
    }
  }, [config.workspaceId, invalidateWorkspaceCollaborationAuthority, socket.events]);

  useEffect(() => {
    const workspaceId = config.workspaceId.trim();
    if (workspaceActivityScopeRef.current !== workspaceId) {
      workspaceActivityScopeRef.current = workspaceId;
      workspaceActivityEventsHeadRef.current = socket.events[0] ?? null;
      setWorkspaceLiveActivity([]);
      return;
    }
    const events = socketEventsSince(socket.events, workspaceActivityEventsHeadRef.current);
    workspaceActivityEventsHeadRef.current = socket.events[0] ?? null;
    if (!workspaceId || !events.length) return;
    setWorkspaceLiveActivity((current) => {
      let activities = current;
      for (const event of events) {
        activities = applyWorkspaceActivityStreamEvent(activities, event, workspaceId).activities;
      }
      return activities;
    });
  }, [config.workspaceId, socket.events]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, workspaceRosterEventsHeadRef.current);
    workspaceRosterEventsHeadRef.current = socket.events[0] ?? null;
    const workspaceId = config.workspaceId.trim();
    if (!workspaceId || !events.length) return;
    updateDataset((current) => {
      let members = current.workspaceMembers;
      let agents = current.workspaceAgents;
      for (const event of events) {
        const result = applyWorkspaceRosterStreamEvent(members, agents, event, workspaceId);
        members = result.members;
        agents = result.agents;
      }
      return members === current.workspaceMembers && agents === current.workspaceAgents
        ? current
        : { ...current, workspaceMembers: members, workspaceAgents: agents };
    });
  }, [config.workspaceId, socket.events, updateDataset]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, workspaceTaskEventsHeadRef.current);
    workspaceTaskEventsHeadRef.current = socket.events[0] ?? null;
    const workspaceId = config.workspaceId.trim();
    if (!workspaceId || !events.length) return;
    updateDataset((current) => {
      let tasks = current.tasks;
      for (const event of events) {
        tasks = applyWorkspaceTaskStreamEvent(tasks, event, workspaceId).tasks;
      }
      return tasks === current.tasks ? current : { ...current, tasks };
    });
  }, [config.workspaceId, socket.events, updateDataset]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, workspaceMessageEventsHeadRef.current);
    workspaceMessageEventsHeadRef.current = socket.events[0] ?? null;
    const workspaceId = config.workspaceId.trim();
    if (!workspaceId || !events.length) return;
    updateDataset((current) => {
      let messages = current.messages;
      for (const event of events) {
        messages = applyWorkspaceMessageStreamEvent(messages, event, workspaceId).messages;
      }
      return messages === current.messages ? current : { ...current, messages };
    });
  }, [config.workspaceId, socket.events, updateDataset]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, conversationMetadataEventsHeadRef.current);
    conversationMetadataEventsHeadRef.current = socket.events[0] ?? null;
    for (const event of events) {
      const titleEvent = readConversationTitleStreamEvent(event);
      const update = titleEvent.update;
      if (!update) continue;
      setAgentConversationSession(
        (current) => applyConversationTitleUpdate(current, {}, update).session,
      );
      updateDataset((current) => {
        const conversationsByWorkspace = applyConversationTitleUpdate(
          null,
          current.conversationsByWorkspace,
          update,
        ).conversationsByWorkspace;
        return conversationsByWorkspace === current.conversationsByWorkspace
          ? current
          : { ...current, conversationsByWorkspace };
      });
    }
  }, [socket.events, updateDataset]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, authoritativeRunEventsHeadRef.current);
    authoritativeRunEventsHeadRef.current = socket.events[0] ?? null;
    if (!authoritativeRunsFromSocketEvents(events).length) return;
    setConversationStatusRefreshRevision((revision) => revision + 1);
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
    canvasOpen: true,
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
        : !desktopApiAuthenticationAvailable(config)
          ? 'An authenticated session is required before connecting.'
          : !config.tenantId.trim() || !config.projectId.trim()
            ? 'Select an account and project before connecting.'
            : null;
  const workspaceDisabledReason = !identityAuthenticated
    ? 'Sign in or use a manual API key before loading workspaces.'
    : !showRuntimeConfig
      ? 'Select an account and project before loading workspaces.'
      : !desktopApiAuthenticationAvailable(config)
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
      : !desktopApiAuthenticationAvailable(config)
        ? t('task.disabledAuthRequired')
        : !config.tenantId.trim() || !config.projectId.trim()
          ? t('task.disabledProjectRequired')
          : null;
  const workspaceCreateDisabledReason = !identityAuthenticated
    ? t('workspaceCreate.disabledSignIn')
    : !desktopApiAuthenticationAvailable(config)
      ? t('workspaceCreate.disabledAuth')
      : !config.tenantId.trim() || !config.projectId.trim()
        ? t('workspaceCreate.disabledProject')
        : null;
  const chatDisabledReason = !identityAuthenticated
    ? 'Sign in or enter an API key before sending messages.'
    : !showRuntimeConfig
      ? 'Select an account and project before chatting.'
      : !desktopApiAuthenticationAvailable(config)
        ? 'An authenticated session is required before sending messages.'
        : !config.tenantId.trim() || !config.projectId.trim()
          ? 'Select an account and project before chatting.'
          : connection !== 'ready'
            ? t('task.liveConnectionRequired')
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
    terminalStartGenerationRef.current += 1;
    terminalLifecycleRef.current = null;
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
    setWorkspaceAutonomyAttentionState({
      scopeKey: '',
      authority: unavailableWorkspaceAuthority<WorkspaceAutonomyAttention>(),
    });
    setRetryingWorkspaceAutonomyAttentionId(null);
    setResolvingWorkspaceAutonomyAttentionId(null);
    conversationStatusRequestRef.current += 1;
    conversationStatusScopeRef.current = '';
    setConversationStatusSummary(null);
    setConnection('idle');
    setError(null);
    setLastSync('never');
    setSelectedSidebarRunId('');
    setRunStateById({});
    setRunControlState('running');
    setRunLiveMode(true);
    setSelectedTaskId('');
    setReviewTab('overview');
    closeRightCanvasPanel();
    setTerminal(null);
    setTerminalLifecycle(null);
    setAgentConversationSession(null);
    setOpenTabs((tabs) => clearConversationTabs(tabs));
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
      let localConversationStatusRequest: LocalConversationStatusRequest | null = null;
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
        if (conversationStatusScopeRef.current !== expansionScope) {
          conversationStatusRequestRef.current += 1;
          conversationStatusScopeRef.current = expansionScope;
          setConversationStatusSummary(null);
        }
        if (runtimeConfig.mode === 'local') {
          localConversationStatusRequest = nextLocalConversationStatusRequest(
            conversationStatusRequestRef.current,
            expansionScope,
          );
          conversationStatusRequestRef.current = localConversationStatusRequest.generation;
        }
        const expandSelectedWorkspace = workspaceExpansionScopeRef.current !== expansionScope;
        const projects = [resolvedProject];
        const loadingNodeState: RuntimeNodeLoadState = {
          projects: Object.fromEntries(
            projects.map((project) => [project.id, { loading: true, error: null }]),
          ),
          workspaces: {},
        };
        if (!contextIsCurrent()) return false;
        updateDataset((current) => ({
          ...current,
          nodeState: {
            projects: {
              ...current.nodeState.projects,
              ...loadingNodeState.projects,
            },
            workspaces: current.nodeState.workspaces,
          },
        }));

        const workspaceResults = await Promise.all(
          projects.map(async (project) => {
            const projectTenantId = project.tenant_id || runtimeConfig.tenantId;
            try {
              const workspaces =
                await desktopWorkspaceCatalogOperationsV2.listWorkspacesForProject({
                  config: {
                    ...runtimeConfig,
                    tenantId: projectTenantId,
                    projectId: project.id,
                    workspaceId: '',
                  },
                });
              return { project, workspaces, error: null };
            } catch (caught) {
              return {
                project,
                workspaces: [] as WorkspaceSummary[],
                error: formatError(caught),
              };
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
        const workspaceId = resolveRuntimeWorkspaceId(
          runtimeConfig.workspaceId,
          resolvedProjectId,
          projectWorkspaces,
          agentConversationSessionRef.current?.conversation ?? null,
        );
        const nextExpandedWorkspaceIds = reconcileExpandedWorkspaceIds(
          expandedWorkspaceIdsRef.current,
          projectWorkspaces.map((workspace) => workspace.id),
          workspaceId,
          expandSelectedWorkspace,
        );
        const conversationLoadTargets = projectConversationLoadTargets(
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
        if (!contextIsCurrent()) return false;
        const autonomyAttentionScopeKey = workspaceAutonomyAttentionScopeKey(resolvedConfig);
        setWorkspaceAutonomyAttentionState({
          scopeKey: autonomyAttentionScopeKey,
          authority: workspaceId
            ? loadingWorkspaceAuthority<WorkspaceAutonomyAttention>()
            : unavailableWorkspaceAuthority<WorkspaceAutonomyAttention>(),
        });
        setRetryingWorkspaceAutonomyAttentionId(null);
        setResolvingWorkspaceAutonomyAttentionId(null);
        updateDataset((current) => {
          const workspaceNodeState = { ...current.nodeState.workspaces };
          for (const targetWorkspaceId of supersededRefreshWorkspaceIds) {
            if ((current.conversationsByWorkspace[targetWorkspaceId] ?? []).length > 0) {
              workspaceNodeState[targetWorkspaceId] = {
                loading: false,
                error: null,
              };
            } else {
              delete workspaceNodeState[targetWorkspaceId];
            }
          }
          for (const targetWorkspaceId of conversationLoadTargets) {
            workspaceNodeState[targetWorkspaceId] = {
              loading: true,
              error: null,
            };
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
            const isUnboundGroup = targetWorkspaceId === UNBOUND_CONVERSATIONS_KEY;
            try {
              const response =
                await desktopWorkspaceConversationCatalogOperationsV2.listConversations({
                  config: resolvedConfig,
                  workspaceId: isUnboundGroup ? null : targetWorkspaceId,
                  unboundOnly: isUnboundGroup,
                });
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
          workspaceAutonomyAttentions,
          myWorkResult,
          conversationResults,
          localConversationStatusSummary,
        ] = await Promise.all([
          workspaceId
            ? desktopWorkspaceMessageCatalogOperationsV2.listMessages({
                config: resolvedConfig,
              })
            : Promise.resolve([]),
          workspaceId
            ? desktopWorkspaceExecutionSnapshotOperationsV2.listTasks({
                config: resolvedConfig,
              })
            : Promise.resolve([]),
          workspaceId
            ? desktopWorkspaceExecutionSnapshotOperationsV2
                .getPlanSnapshot({ config: resolvedConfig })
                .catch(() => null)
            : Promise.resolve(null),
          workspaceId
            ? resolveWorkspaceAuthority(
                desktopWorkspaceRosterOperationsV2.listWorkspaceMembers({
                  config: resolvedConfig,
                }),
              )
            : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceMemberSummary>()),
          workspaceId
            ? resolveWorkspaceAuthority(
                desktopWorkspaceRosterOperationsV2.listWorkspaceAgents({
                  config: resolvedConfig,
                }),
              )
            : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceAgentBinding>()),
          workspaceId
            ? resolveWorkspaceAuthority(
                desktopWorkspaceAutonomyAttentionOperationsV2.listWorkspaceAutonomyAttentions({
                  config: resolvedConfig,
                  workspaceId,
                }),
              )
            : Promise.resolve(unavailableWorkspaceAuthority<WorkspaceAutonomyAttention>()),
          resolvedProjectId
            ? listMyWorkForConfig(resolvedConfig)
                .then((response) => ({ items: response.items, error: null }))
                .catch((caught) => ({
                  items: [] as ProjectWorkItem[],
                  error: formatError(caught),
                }))
            : Promise.resolve({ items: [] as ProjectWorkItem[], error: null }),
          conversationResultsPromise,
          localConversationStatusRequest
            ? desktopProjectOverviewOperationsV2
                .loadProjectOverview({
                  config: resolvedConfig,
                  scope: {
                    authority: 'local',
                    tenantId: resolvedConfig.tenantId,
                    projectId: resolvedConfig.projectId,
                  },
                })
                .then((result) =>
                  result.kind === 'local-ready'
                    ? result.snapshot.conversationStatusSummary.value
                    : null,
                )
                .catch(() => null)
            : Promise.resolve(null),
        ]);
        if (!contextIsCurrent()) return false;
        const validConversationGroupIds = new Set([
          UNBOUND_CONVERSATIONS_KEY,
          ...projectWorkspaces.map((workspace) => workspace.id),
        ]);
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
        const autonomyAttentionActorId = authRef.current.user?.user_id.trim() ?? '';
        if (workspaceAutonomyAttentions.status === 'ready' && autonomyAttentionActorId) {
          retainOpenWorkspaceAutonomyAttentionResolveAttempts(
            workspaceAutonomyAttentionResolveAttemptsRef.current,
            autonomyAttentionScopeKey,
            autonomyAttentionActorId,
            workspaceAutonomyAttentions.items,
          );
        }
        setWorkspaceAutonomyAttentionState({
          scopeKey: autonomyAttentionScopeKey,
          authority: workspaceAutonomyAttentions,
        });
        commitRuntimeConfig(resolvedConfig);
        if (
          localConversationStatusRequest &&
          isCurrentLocalConversationStatusRequest(
            localConversationStatusRequest,
            conversationStatusRequestRef.current,
            conversationStatusScopeRef.current,
          )
        ) {
          setConversationStatusSummary(localConversationStatusSummary);
        }
        updateDataset((current) => {
          const conversationsByWorkspace = {
            ...Object.fromEntries(
              Object.entries(current.conversationsByWorkspace).filter(([targetWorkspaceId]) =>
                validConversationGroupIds.has(targetWorkspaceId),
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
                validConversationGroupIds.has(targetWorkspaceId),
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
            nodeState: {
              projects: projectNodeState,
              workspaces: workspaceNodeState,
            },
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
            agentConversationScopeKeyFor(
              resolvedProjectId,
              result.workspaceId === UNBOUND_CONVERSATIONS_KEY ? '' : result.workspaceId,
            ),
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
        setLastSync(
          new Date().toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        );
        return true;
      } catch (caught) {
        if (!contextIsCurrent()) return false;
        if (
          !localConversationStatusRequest ||
          isCurrentLocalConversationStatusRequest(
            localConversationStatusRequest,
            conversationStatusRequestRef.current,
            conversationStatusScopeRef.current,
          )
        ) {
          conversationStatusRequestRef.current += 1;
          setConversationStatusSummary(null);
        }
        const connectionError = formatConnectionError(caught, nextConfig.apiBaseUrl);
        setWorkspaceAutonomyAttentionState((current) =>
          current.authority.status === 'loading'
            ? {
                ...current,
                authority: failLoadingWorkspaceAuthority(
                  current.authority,
                  connectionError,
                ),
              }
            : current,
        );
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
              ...workspaceTreeRefreshFailed(current.nodeState, refreshProjectId, connectionError),
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
      desktopProjectOverviewOperationsV2,
      desktopWorkspaceAutonomyAttentionOperationsV2,
      desktopWorkspaceCatalogOperationsV2,
      desktopWorkspaceConversationCatalogOperationsV2,
      desktopWorkspaceExecutionSnapshotOperationsV2,
      desktopWorkspaceMessageCatalogOperationsV2,
      desktopWorkspaceRosterOperationsV2,
      listMyWorkForConfig,
      syncLocalRuntimeConfig,
      t,
      updateDataset,
    ],
  );
  useEffect(() => {
    if (
      auth.status !== 'signed_in' ||
      config.mode !== 'local' ||
      connection !== 'ready' ||
      !config.tenantId.trim() ||
      !config.projectId.trim()
    ) {
      conversationStatusRequestRef.current += 1;
      conversationStatusScopeRef.current = '';
      setConversationStatusSummary(null);
      return undefined;
    }
    const effectScope = `${config.tenantId}\u0000${config.projectId}`;
    if (conversationStatusScopeRef.current !== effectScope) {
      conversationStatusRequestRef.current += 1;
      conversationStatusScopeRef.current = effectScope;
      setConversationStatusSummary(null);
    }
    let active = true;
    let timer: number | null = null;
    const refreshSummary = () => {
      const runtimeConfig = configRef.current;
      const requestScope = `${runtimeConfig.tenantId}\u0000${runtimeConfig.projectId}`;
      const statusRequest = nextLocalConversationStatusRequest(
        conversationStatusRequestRef.current,
        requestScope,
      );
      conversationStatusRequestRef.current = statusRequest.generation;
      let request: ReturnType<
        typeof desktopProjectOverviewOperationsV2.loadProjectOverview
      >;
      try {
        request = desktopProjectOverviewOperationsV2.loadProjectOverview({
          config: runtimeConfig,
          scope: {
            authority: 'local',
            tenantId: runtimeConfig.tenantId,
            projectId: runtimeConfig.projectId,
          },
        });
      } catch {
        if (
          active &&
          isCurrentLocalConversationStatusRequest(
            statusRequest,
            conversationStatusRequestRef.current,
            conversationStatusScopeRef.current,
          )
        ) {
          setConversationStatusSummary(null);
        }
        return;
      }
      void request
        .then((result) => {
          if (result.kind !== 'local-ready') return;
          const snapshot = result.snapshot;
          if (
            active &&
            isCurrentLocalConversationStatusRequest(
              statusRequest,
              conversationStatusRequestRef.current,
              conversationStatusScopeRef.current,
            ) &&
            configRef.current.tenantId === snapshot.scope.tenantId &&
            configRef.current.projectId === snapshot.scope.projectId &&
            conversationStatusScopeRef.current === requestScope
          ) {
            setConversationStatusSummary(snapshot.conversationStatusSummary.value);
          }
        })
        .catch(() => {
          if (
            active &&
            conversationStatusScopeRef.current === requestScope &&
            isCurrentLocalConversationStatusRequest(
              statusRequest,
              conversationStatusRequestRef.current,
              conversationStatusScopeRef.current,
            )
          ) {
            setConversationStatusSummary(null);
          }
        });
    };
    const refreshVisibleSummary = () => {
      if (document.visibilityState === 'visible') refreshSummary();
    };
    refreshSummary();
    timer = window.setInterval(refreshSummary, 15_000);
    window.addEventListener('focus', refreshSummary);
    document.addEventListener('visibilitychange', refreshVisibleSummary);
    return () => {
      active = false;
      if (timer !== null) window.clearInterval(timer);
      window.removeEventListener('focus', refreshSummary);
      document.removeEventListener('visibilitychange', refreshVisibleSummary);
    };
  }, [
    auth.status,
    config.mode,
    config.projectId,
    config.tenantId,
    connection,
    conversationStatusRefreshRevision,
    desktopProjectOverviewOperationsV2,
  ]);
  productionRouteRefreshRef.current = (nextConfig, projects) =>
    refreshRuntime(nextConfig, projects);
  const productionRouteScopeTransaction = useMemo(
    () =>
      createDesktopRouteScopeTransaction({
        getCurrent: () => ({
          config: configRef.current,
          authRevision: authAttemptRevisionRef.current,
        }),
        createAuthority: (authorityConfig, operation) =>
          withDesktopWorkspaceContextAuthorityOperationV2(
            desktopRendererGenerationV2.actions,
            authorityConfig,
            operation,
          ),
        commit: ({ config: nextConfig, context, projects }) => {
          contextRevisionRef.current = context.revision;
          commitRuntimeConfig(nextConfig);
          setAuth((current) => ({
            ...current,
            context,
            projects: [...projects],
          }));
        },
        refresh: async ({ config: nextConfig, projects }, signal) => {
          if (signal.aborted) {
            throw signal.reason ?? new DOMException('Aborted', 'AbortError');
          }
          await productionRouteRefreshRef.current?.(nextConfig, [...projects]);
          if (signal.aborted) {
            throw signal.reason ?? new DOMException('Aborted', 'AbortError');
          }
        },
      }),
    [commitRuntimeConfig, desktopRendererGenerationV2.actions],
  );
  const switchProductionRouteScope = useCallback(
    async (
      context: Parameters<typeof productionRouteScopeTransaction.switchScope>[0],
      signal: AbortSignal,
    ): Promise<void> => {
      await productionRouteScopeTransaction.switchScope(context, signal);
    },
    [productionRouteScopeTransaction],
  );

  useEffect(() => {
    if (!localRuntimeMode) return;
    const onSidecarRecovered = window.__MEMSTACK_DESKTOP__?.events?.onSidecarRecovered;
    if (!onSidecarRecovered) return;
    return onSidecarRecovered(() => {
      const recoveryRefreshGeneration = runtimeRefreshRequestRef.current + 1;
      sidecarRecoveryRefreshGenerationRef.current = recoveryRefreshGeneration;
      void refreshRuntime(configRef.current).finally(() => {
        if (sidecarRecoveryRefreshGenerationRef.current === recoveryRefreshGeneration) {
          sidecarRecoveryRefreshGenerationRef.current = null;
        }
      });
    });
  }, [localRuntimeMode, refreshRuntime]);

  useEffect(() => {
    const events = socketEventsSince(socket.events, workspaceLifecycleEventsHeadRef.current);
    workspaceLifecycleEventsHeadRef.current = socket.events[0] ?? null;
    const runtimeConfig = configRef.current;
    const scope = {
      tenantId: runtimeConfig.tenantId.trim(),
      projectId: runtimeConfig.projectId.trim(),
      workspaceId: runtimeConfig.workspaceId.trim(),
    };
    if (!scope.tenantId || !scope.projectId || !events.length) return;

    const initialDataset = datasetRef.current;
    let nextDataset = initialDataset;
    let activeWorkspaceDeleted = false;
    let nextWorkspaceId = scope.workspaceId;
    for (const event of events) {
      const result = applyWorkspaceLifecycleStreamEvent(nextDataset, event, scope);
      nextDataset = result.dataset;
      if (result.activeWorkspaceDeleted) {
        activeWorkspaceDeleted = true;
        nextWorkspaceId = result.nextWorkspaceId;
      }
    }
    if (nextDataset === initialDataset) return;
    updateDataset(() => nextDataset);
    if (!activeWorkspaceDeleted) return;

    const nextConfig = { ...runtimeConfig, workspaceId: nextWorkspaceId };
    commitRuntimeConfig(nextConfig);
    agentConversationSessionRef.current = null;
    setAgentConversationSession(null);
    resetConversationTimeline();
    setAgentTaskSignals([]);
    setReviewTab('overview');
    setExpandedWorkspaceIds((current) => {
      const next = new Set(current);
      next.delete(scope.workspaceId);
      if (nextWorkspaceId) next.add(nextWorkspaceId);
      expandedWorkspaceIdsRef.current = next;
      return next;
    });
    if (activeSectionRef.current === 'chat') {
      activeSectionRef.current = 'workspace';
      setActiveSection('workspace');
      workbenchRef.current?.focus();
    }
    void refreshRuntime(nextConfig);
  }, [
    commitRuntimeConfig,
    refreshRuntime,
    resetConversationTimeline,
    socket.events,
    updateDataset,
  ]);

  const loadWorkspaceConversations = useCallback(
    async (workspaceId: string) => {
      const requestConfig = configRef.current;
      const projectId = requestConfig.projectId.trim();
      const tenantId = requestConfig.tenantId.trim();
      const currentDataset = datasetRef.current;
      const isUnboundGroup = workspaceId === UNBOUND_CONVERSATIONS_KEY;
      const workspaceExists =
        isUnboundGroup ||
        (currentDataset.workspacesByProject[projectId] ?? []).some(
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
        const response =
          await desktopWorkspaceConversationCatalogOperationsV2.listConversations({
            config: requestConfig,
            workspaceId: isUnboundGroup ? null : workspaceId,
            unboundOnly: isUnboundGroup,
          });
        const refreshedConversations = response.items;
        if (!requestIsCurrent()) return;
        updateDataset((current) => {
          if (
            !requestIsCurrent() ||
            (!isUnboundGroup &&
              !(current.workspacesByProject[projectId] ?? []).some(
                (workspace) => workspace.id === workspaceId,
              ))
          ) {
            return current;
          }
          const nextDataset: RuntimeDataset = {
            ...current,
            conversationsByWorkspace: {
              ...current.conversationsByWorkspace,
              [workspaceId]: mergeConversationListWithCurrentRunAuthority(
                refreshedConversations,
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
          agentConversationScopeKeyFor(projectId, isUnboundGroup ? '' : workspaceId),
          refreshedConversations,
        );
      } catch (caught) {
        if (!requestIsCurrent()) return;
        updateDataset((current) => {
          if (
            !requestIsCurrent() ||
            (!isUnboundGroup &&
              !(current.workspacesByProject[projectId] ?? []).some(
                (workspace) => workspace.id === workspaceId,
              ))
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
    },
    [
      clearMissingConversationSelection,
      desktopWorkspaceConversationCatalogOperationsV2,
      updateDataset,
    ],
  );

  const refreshMyWork = useCallback(
    async (scheduledScope?: MyWorkRefreshScope) => {
      const requestConfig = configRef.current;
      const projectId = requestConfig.projectId.trim();
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
        const response = await listMyWorkForConfig(requestConfig, controller.signal);
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
    },
    [listMyWorkForConfig],
  );

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
    desktopProductionRouteNavigation.clearHash();
    applySectionSideEffects('workspace');
    void refreshRuntime(nextConfig);
  };

  const createWorkspaceFromDialog = async (
    input: WorkspaceCreateInput,
    submittedScope: WorkspaceCreateScope,
    signal: AbortSignal,
  ) => {
    const currentScope = {
      tenantId: configRef.current.tenantId,
      projectId: configRef.current.projectId,
      epoch: configScopeEpochRef.current,
      contextRevision: contextRevisionRef.current,
    };
    if (!workspaceCreateScopeIsCurrent(submittedScope, currentScope)) {
      throw new WorkspaceCreateScopeChangedError();
    }
    const created = await desktopWorkspaceLifecycleOperationsV2.createWorkspace({
      config: {
        ...configRef.current,
        tenantId: submittedScope.tenantId,
        projectId: submittedScope.projectId,
        workspaceId: '',
      },
      input,
      signal,
    });
    const committedScope = {
      tenantId: configRef.current.tenantId,
      projectId: configRef.current.projectId,
      epoch: configScopeEpochRef.current,
      contextRevision: contextRevisionRef.current,
    };
    if (!workspaceCreateScopeIsCurrent(submittedScope, committedScope)) {
      throw new WorkspaceCreateScopeChangedError();
    }
    updateDataset((current) => ({
      ...current,
      workspaces: [
        created,
        ...current.workspaces.filter((candidate) => candidate.id !== created.id),
      ],
      workspacesByProject: mergeWorkspaceIntoProjectCatalog(current.workspacesByProject, created),
    }));
    setExpandedWorkspaceIds((current) => new Set([...current, created.id]));
    selectWorkspace(created.id, submittedScope.projectId);
  };

  const updateWorkspaceFromDialog = async (
    input: WorkspaceUpdateInput,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceSummary> => {
    const currentScope = {
      tenantId: configRef.current.tenantId,
      projectId: configRef.current.projectId,
      workspaceId: configRef.current.workspaceId,
      epoch: configScopeEpochRef.current,
      contextRevision: contextRevisionRef.current,
    };
    const scopedWorkspace = datasetRef.current.workspaces.find(
      (workspace) =>
        workspace.id === submittedScope.workspaceId &&
        workspace.tenant_id === submittedScope.tenantId &&
        workspace.project_id === submittedScope.projectId,
    );
    if (!scopedWorkspace || !workspaceSettingsScopeIsCurrent(submittedScope, currentScope)) {
      throw new WorkspaceSettingsScopeChangedError();
    }
    const updated = await desktopWorkspaceLifecycleOperationsV2.updateWorkspace({
      config: {
        ...configRef.current,
        tenantId: submittedScope.tenantId,
        projectId: submittedScope.projectId,
        workspaceId: submittedScope.workspaceId,
      },
      workspaceId: submittedScope.workspaceId,
      input,
      signal,
    });
    const committedScope = {
      tenantId: configRef.current.tenantId,
      projectId: configRef.current.projectId,
      workspaceId: configRef.current.workspaceId,
      epoch: configScopeEpochRef.current,
      contextRevision: contextRevisionRef.current,
    };
    if (!workspaceSettingsScopeIsCurrent(submittedScope, committedScope)) {
      throw new WorkspaceSettingsScopeChangedError();
    }
    updateDataset((current) => ({
      ...current,
      workspaces: replaceWorkspaceInList(current.workspaces, updated),
      workspacesByProject: replaceWorkspaceInProjectCatalog(current.workspacesByProject, updated),
    }));
    return updated;
  };

  const assertWorkspaceMemberMutationScope = (submittedScope: WorkspaceSettingsScope) => {
    const currentScope = {
      tenantId: configRef.current.tenantId,
      projectId: configRef.current.projectId,
      workspaceId: configRef.current.workspaceId,
      epoch: configScopeEpochRef.current,
      contextRevision: contextRevisionRef.current,
    };
    const scopedWorkspace = datasetRef.current.workspaces.find(
      (workspace) =>
        workspace.id === submittedScope.workspaceId &&
        workspace.tenant_id === submittedScope.tenantId &&
        workspace.project_id === submittedScope.projectId,
    );
    if (!scopedWorkspace || !workspaceSettingsScopeIsCurrent(submittedScope, currentScope)) {
      throw new WorkspaceSettingsScopeChangedError();
    }
  };

  const addWorkspaceMemberFromDialog = async (
    userId: string,
    role: WorkspaceMemberRole,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceMemberSummary> => {
    assertWorkspaceMemberMutationScope(submittedScope);
    const member = await desktopWorkspaceMemberMutationOperationsV2.addWorkspaceMember({
      config: {
        ...configRef.current,
        tenantId: submittedScope.tenantId,
        projectId: submittedScope.projectId,
        workspaceId: submittedScope.workspaceId,
      },
      workspaceId: submittedScope.workspaceId,
      userId,
      role,
      signal,
    });
    assertWorkspaceMemberMutationScope(submittedScope);
    updateDataset((current) => ({
      ...current,
      workspaceMembers: {
        status: 'ready',
        items: upsertWorkspaceMember(current.workspaceMembers.items, member),
        error: null,
      },
    }));
    return member;
  };

  const updateWorkspaceMemberRoleFromDialog = async (
    userId: string,
    role: WorkspaceMemberRole,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceMemberSummary> => {
    assertWorkspaceMemberMutationScope(submittedScope);
    const member = await desktopWorkspaceMemberMutationOperationsV2.updateWorkspaceMemberRole({
      config: {
        ...configRef.current,
        tenantId: submittedScope.tenantId,
        projectId: submittedScope.projectId,
        workspaceId: submittedScope.workspaceId,
      },
      workspaceId: submittedScope.workspaceId,
      userId,
      role,
      signal,
    });
    assertWorkspaceMemberMutationScope(submittedScope);
    updateDataset((current) => ({
      ...current,
      workspaceMembers: {
        status: 'ready',
        items: upsertWorkspaceMember(current.workspaceMembers.items, member),
        error: null,
      },
    }));
    return member;
  };

  const removeWorkspaceMemberFromDialog = async (
    userId: string,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<void> => {
    assertWorkspaceMemberMutationScope(submittedScope);
    await desktopWorkspaceMemberMutationOperationsV2.removeWorkspaceMember({
      config: {
        ...configRef.current,
        tenantId: submittedScope.tenantId,
        projectId: submittedScope.projectId,
        workspaceId: submittedScope.workspaceId,
      },
      workspaceId: submittedScope.workspaceId,
      userId,
      signal,
    });
    assertWorkspaceMemberMutationScope(submittedScope);
    updateDataset((current) => ({
      ...current,
      workspaceMembers: {
        status: 'ready',
        items: removeWorkspaceMemberByUserId(current.workspaceMembers.items, userId),
        error: null,
      },
    }));
  };

  const assertWorkspaceAgentBindingScope = (submittedScope: WorkspaceSettingsScope) => {
    const currentScope = {
      tenantId: configRef.current.tenantId,
      projectId: configRef.current.projectId,
      workspaceId: configRef.current.workspaceId,
      epoch: configScopeEpochRef.current,
      contextRevision: contextRevisionRef.current,
    };
    const scopedWorkspace = datasetRef.current.workspaces.find(
      (workspace) =>
        workspace.id === submittedScope.workspaceId &&
        workspace.tenant_id === submittedScope.tenantId &&
        workspace.project_id === submittedScope.projectId,
    );
    if (!scopedWorkspace || !workspaceSettingsScopeIsCurrent(submittedScope, currentScope)) {
      throw new WorkspaceSettingsScopeChangedError();
    }
  };

  const workspaceAgentBindingOperationScope = (
    scope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ) => ({
    config: {
      ...configRef.current,
      tenantId: scope.tenantId,
      projectId: scope.projectId,
      workspaceId: scope.workspaceId,
    },
    workspaceId: scope.workspaceId,
    signal,
  });

  const loadWorkspaceAgentDefinitionsFromDialog = async (
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceBindingAgentDefinition[]> => {
    assertWorkspaceAgentBindingScope(submittedScope);
    const definitions =
      await desktopWorkspaceAgentBindingOperationsV2.listWorkspaceBindingAgentDefinitions(
        workspaceAgentBindingOperationScope(submittedScope, signal),
      );
    assertWorkspaceAgentBindingScope(submittedScope);
    return definitions;
  };

  const bindWorkspaceAgentFromDialog = async (
    agentId: string,
    displayName: string,
    description: string,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceAgentBinding> => {
    assertWorkspaceAgentBindingScope(submittedScope);
    const binding = await desktopWorkspaceAgentBindingOperationsV2.bindWorkspaceAgent({
      ...workspaceAgentBindingOperationScope(submittedScope, signal),
      input: { agentId, displayName, description },
    });
    assertWorkspaceAgentBindingScope(submittedScope);
    updateDataset((current) => ({
      ...current,
      workspaceAgents: {
        status: 'ready',
        items: upsertWorkspaceAgentBinding(current.workspaceAgents.items, binding),
        error: null,
      },
    }));
    return binding;
  };

  const unbindWorkspaceAgentFromDialog = async (
    bindingId: string,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<void> => {
    assertWorkspaceAgentBindingScope(submittedScope);
    await desktopWorkspaceAgentBindingOperationsV2.unbindWorkspaceAgent({
      ...workspaceAgentBindingOperationScope(submittedScope, signal),
      bindingId,
    });
    assertWorkspaceAgentBindingScope(submittedScope);
    updateDataset((current) => ({
      ...current,
      workspaceAgents: {
        status: 'ready',
        items: removeWorkspaceAgentBindingById(current.workspaceAgents.items, bindingId),
        error: null,
      },
    }));
  };

  const renameConversation = async (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
    title: string,
  ) => {
    try {
      const requestConfig = configRef.current;
      const expectedScopeEpoch = configScopeEpochRef.current;
      const expectedContextRevision = contextRevisionRef.current;
      const normalizedWorkspaceId = workspaceId.trim();
      if (
        conversation.tenant_id !== requestConfig.tenantId ||
        conversation.project_id !== projectId ||
        projectId !== requestConfig.projectId ||
        (conversation.workspace_id?.trim() ?? '') !== normalizedWorkspaceId
      ) {
        throw new Error('Invalid conversation lifecycle scope');
      }
      const mutationScopeIsCurrent = () =>
        expectedScopeEpoch === configScopeEpochRef.current &&
        expectedContextRevision === contextRevisionRef.current &&
        isSameDesktopProjectRequestScope(requestConfig, configRef.current);
      const updated =
        await desktopConversationLifecycleOperationsV2.updateAgentConversationTitle({
          config: requestConfig,
          conversation,
          title,
        });
      if (!mutationScopeIsCurrent()) return;
      updateDataset((current) => {
        const conversationsByWorkspace = replaceConversationInWorkspaceRows(
          current.conversationsByWorkspace,
          updated,
        );
        return conversationsByWorkspace === current.conversationsByWorkspace
          ? current
          : { ...current, conversationsByWorkspace };
      });
      showToast('success', t('toast.conversationRenameSuccess'));
      const currentSession = agentConversationSessionRef.current;
      if (
        currentSession?.scopeKey !==
          agentConversationScopeKeyFor(projectId, normalizedWorkspaceId) ||
        currentSession.conversation.id !== updated.id
      ) {
        return;
      }
      const nextSession = { ...currentSession, conversation: updated };
      agentConversationSessionRef.current = nextSession;
      setAgentConversationSession(nextSession);
    } catch (caught) {
      showToast('error', t('toast.conversationRenameError', { detail: formatError(caught) }));
      throw caught;
    }
  };

  const regenerateConversationSummary = async (conversationId: string) => {
    const requestConfig = configRef.current;
    const currentSession = agentConversationSessionRef.current;
    const requiredConversationId = conversationId.trim();
    const normalizedWorkspaceId = requestConfig.workspaceId.trim();
    const expectedScopeEpoch = configScopeEpochRef.current;
    const expectedContextRevision = contextRevisionRef.current;
    const expectedScopeKey = agentConversationScopeKey(requestConfig);
    const requestGeneration = conversationSummaryMutationRequestRef.current + 1;
    conversationSummaryMutationRequestRef.current = requestGeneration;
    if (
      requestConfig.mode !== 'cloud' ||
      !requiredConversationId ||
      !requestConfig.tenantId ||
      !requestConfig.projectId ||
      currentSession?.scopeKey !== expectedScopeKey ||
      currentSession.conversation.id !== requiredConversationId ||
      currentSession.conversation.tenant_id !== requestConfig.tenantId ||
      currentSession.conversation.project_id !== requestConfig.projectId ||
      (currentSession.conversation.workspace_id?.trim() ?? '') !== normalizedWorkspaceId
    ) {
      throw new Error('Invalid conversation summary scope');
    }
    const updated =
      await desktopConversationLifecycleOperationsV2.generateAgentConversationSummary({
        config: requestConfig,
        conversation: currentSession.conversation,
      });
    const latestSession = agentConversationSessionRef.current;
    if (
      conversationSummaryMutationRequestRef.current !== requestGeneration ||
      expectedScopeEpoch !== configScopeEpochRef.current ||
      expectedContextRevision !== contextRevisionRef.current ||
      !isSameDesktopProjectRequestScope(requestConfig, configRef.current) ||
      latestSession?.scopeKey !== expectedScopeKey ||
      latestSession.conversation.id !== requiredConversationId
    ) {
      return;
    }
    updateDataset((current) => {
      const conversationsByWorkspace = replaceConversationInWorkspaceRows(
        current.conversationsByWorkspace,
        updated,
      );
      return conversationsByWorkspace === current.conversationsByWorkspace
        ? current
        : { ...current, conversationsByWorkspace };
    });
    const nextSession = { ...latestSession, conversation: updated };
    agentConversationSessionRef.current = nextSession;
    setAgentConversationSession(nextSession);
  };

  const deleteConversation = async (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => {
    try {
      const requestConfig = configRef.current;
      const expectedScopeEpoch = configScopeEpochRef.current;
      const expectedContextRevision = contextRevisionRef.current;
      const normalizedWorkspaceId = workspaceId.trim();
      if (
        conversation.tenant_id !== requestConfig.tenantId ||
        conversation.project_id !== projectId ||
        projectId !== requestConfig.projectId ||
        (conversation.workspace_id?.trim() ?? '') !== normalizedWorkspaceId
      ) {
        throw new Error('Invalid conversation lifecycle scope');
      }
      const mutationScopeIsCurrent = () =>
        expectedScopeEpoch === configScopeEpochRef.current &&
        expectedContextRevision === contextRevisionRef.current &&
        isSameDesktopProjectRequestScope(requestConfig, configRef.current);
      await desktopConversationLifecycleOperationsV2.deleteAgentConversation({
        config: requestConfig,
        conversation,
      });
      if (!mutationScopeIsCurrent()) return;
      updateDataset((current) => {
        const conversationsByWorkspace = removeConversationFromWorkspaceRows(
          current.conversationsByWorkspace,
          conversation.id,
        );
        return conversationsByWorkspace === current.conversationsByWorkspace
          ? current
          : { ...current, conversationsByWorkspace };
      });
      showToast('success', t('toast.conversationDeleteSuccess'));
      if (
        agentConversationSessionRef.current?.scopeKey ===
          agentConversationScopeKeyFor(projectId, normalizedWorkspaceId) &&
        agentConversationSessionRef.current.conversation.id === conversation.id
      ) {
        agentConversationSessionRef.current = null;
        selectWorkspace(normalizedWorkspaceId, projectId);
      }
    } catch (caught) {
      showToast('error', t('toast.conversationDeleteError', { detail: formatError(caught) }));
      throw caught;
    }
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
    const isUnboundConversation = !workspaceId.trim();
    const requiresRuntimeRefresh =
      !isUnboundConversation &&
      sessionSelectionRequiresRuntimeRefresh(configRef.current, nextConfig);
    commitRuntimeConfig(nextConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(projectId, workspaceId),
      conversation,
    });
    setAgentTaskSignals([]);
    setReviewTab('overview');
    if (workspaceId) {
      setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
    }
    desktopProductionRouteNavigation.clearHash();
    applySectionSideEffects(targetSection);
    void loadConversationTimeline(conversation, projectId, nextConfig);
    if (requiresRuntimeRefresh) void refreshRuntime(nextConfig);
  };

  const sendChatMessage = useCallback(
    (
      content: string,
      contextItems: ComposerContextItem[],
      onWorkspaceMessageSaved?: () => void,
      referencesOverride?: CodeRangeReference[],
    ) => {
      void sendMessageContentRef.current(
        content,
        contextItems,
        onWorkspaceMessageSaved,
        referencesOverride,
      );
    },
    [],
  );

  // Permission deny feedback is part of the canonical HITL response. The
  // backend persists and restores it atomically into the resumed Agent context.
  const respondToHitlWithSteering = useCallback(
    async (submission: HitlResponseSubmission) => {
      await respondToHitl(submission);
    },
    [respondToHitl],
  );

  const startTerminal = async () => {
    await runSandboxAction(async () => {
      const sourceRun = currentArtifactRunRef.current;
      if (!sourceRun) {
        throw new Error(t('session.terminalRequiresActiveRun'));
      }
      if (!sourceRun.environment) {
        throw new Error(t('session.terminalCanonicalRunAuthorityUnavailable'));
      }
      const terminalRunAuthority = {
        id: sourceRun.id,
        conversation_id: sourceRun.conversation_id,
        project_id: sourceRun.project_id,
        revision: sourceRun.revision,
        environment: {
          id: sourceRun.environment.id,
          workspace_path: sourceRun.environment.workspace_path,
        },
      };
      const requestGeneration = terminalStartGenerationRef.current + 1;
      terminalStartGenerationRef.current = requestGeneration;
      terminalProxy.close();
      const previousLifecycle = terminalLifecycleRef.current;
      terminalLifecycleRef.current = null;
      setTerminalLifecycle(null);
      setTerminal(null);
      if (previousLifecycle !== null) await previousLifecycle.release();

      const lifecycle = await acquireDesktopTerminalLifecycleAuthorityV2(
        desktopPluginMarketplaceGenerationActionsRefV2.current,
        {
          config,
          run: terminalRunAuthority,
          capabilities: sandboxRuntime.capabilities,
        },
      );
      let retained = false;
      let primaryError: unknown;
      try {
        const started = await lifecycle.start();
        if (terminalStartGenerationRef.current !== requestGeneration) return;
        if (!terminalSessionMatchesRun(started.terminal, currentArtifactRunRef.current)) {
          throw new Error(t('session.terminalAuthorityMismatch'));
        }
        terminalLifecycleRef.current = lifecycle;
        setTerminalLifecycle(lifecycle);
        setTerminal(started.terminal);
        retained = true;
      } catch (caught) {
        primaryError = caught;
        throw caught;
      } finally {
        if (!retained) {
          try {
            await lifecycle.release();
          } catch (releaseError) {
            if (primaryError === undefined) throw releaseError;
          }
        }
      }
      terminalProxy.clear();
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

  const paneStageClassName =
    activeSection === 'board'
      ? 'pane-stage single-stage my-work-stage'
      : activeSection === 'home'
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
  const workspaceAutonomyAttentionScope = workspaceAutonomyAttentionScopeKey(config);
  const workspaceAutonomyAttentions =
    config.workspaceId.trim() &&
    workspaceAutonomyAttentionState.scopeKey === workspaceAutonomyAttentionScope
      ? workspaceAutonomyAttentionState.authority
      : unavailableWorkspaceAuthority<WorkspaceAutonomyAttention>();
  const selectedWorkspaceMembershipRole = useMemo(
    () =>
      dataset.workspaceMembers.items.find(
        (member) =>
          member.workspace_id === config.workspaceId &&
          member.user_id === auth.user?.user_id,
      )?.role ?? null,
    [auth.user?.user_id, config.workspaceId, dataset.workspaceMembers.items],
  );
  const canRetryWorkspaceAutonomyAttention = Boolean(
    auth.user?.is_superuser ||
      (selectedWorkspaceMembershipRole !== null &&
        WORKSPACE_AUTONOMY_RETRY_ROLES.has(selectedWorkspaceMembershipRole)),
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
  const activityInbox = useActivityInbox({
    items: dataset.myWork,
    scopeKey: `${config.tenantId}:${config.projectId}`,
    authorityAdapter: activityAuthorityAdapter,
    authorityScope: activityAuthorityScope,
  });
  // OS 通知点击后经由 ref 跳转,避免 hook 依赖后文才定义的 openMyWorkSession。
  const openMyWorkSessionRef = useRef<(item: ProjectWorkItem) => void>(() => {});
  useCompletionNotifications({
    entries: activityInbox.entries,
    scopeKey: `${config.tenantId}:${config.projectId}`,
    hydrated: connection !== 'loading',
    onOpenEntry: (entry) => openMyWorkSessionRef.current(entry.item),
  });
  const selectedConversationId = selectedConversation?.id ?? null;
  // 打开会话即视为已读该会话的收件箱条目(硬验收:每个未读信号都可在应用内消除)。
  useEffect(() => {
    if (selectedConversationId) {
      activityInbox.markConversationRead(selectedConversationId);
    }
  }, [selectedConversationId, activityInbox.markConversationRead]);
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
  const subAgentControlAuthority = useMemo(
    () =>
      resolveSubAgentControlAuthority(
        config.mode,
        selectedConversation ?? null,
        currentArtifactRun,
      ),
    [config.mode, currentArtifactRun, selectedConversation],
  );
  useEffect(() => {
    let active = true;
    if (
      config.mode !== 'cloud' ||
      !activityAuthorityAdapter.client ||
      !activityAuthorityScope ||
      !currentArtifactRun
    ) {
      setAuthoritativeRunSummary(null);
      return () => {
        active = false;
      };
    }
    setAuthoritativeRunSummary(null);
    void activityAuthorityAdapter.client
      .getRunSummary(activityAuthorityScope, currentArtifactRun.id)
      .then((summary) => {
        if (active) setAuthoritativeRunSummary(summary);
      })
      .catch(() => {
        if (active) setAuthoritativeRunSummary(null);
      });
    return () => {
      active = false;
    };
  }, [activityAuthorityAdapter, activityAuthorityScope, config.mode, currentArtifactRun]);
  const sessionUsageSummary = useMemo(
    () => deriveSessionUsage(conversationTimeline.items),
    [conversationTimeline],
  );
  const runCompletionSummary = useMemo(
    () =>
      sessionDetailViewModel && (config.mode !== 'cloud' || authoritativeRunSummary)
        ? buildRunCompletionSummary({
            status: sessionDetailViewModel.status,
            capabilityMode: sessionDetailViewModel.capabilityMode,
            error: sessionDetailViewModel.error,
            runStartedAt: currentArtifactRun?.started_at ?? null,
            runCompletedAt: currentArtifactRun?.completed_at ?? null,
            usage: config.mode === 'cloud' ? null : sessionUsageSummary,
            changeSnapshot,
            artifactVersions: displaySessionProjection?.artifactVersions ?? [],
            authoritySummary: authoritativeRunSummary,
          })
        : null,
    [
      sessionDetailViewModel,
      authoritativeRunSummary,
      config.mode,
      currentArtifactRun,
      sessionUsageSummary,
      changeSnapshot,
      displaySessionProjection,
    ],
  );
  const openSessionCanvasTab = useCallback(
    (tab: SessionCanvasTabId) => {
      setReviewTab(tab);
      openRightCanvasPanel();
    },
    [openRightCanvasPanel],
  );
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
  useEffect(() => {
    if (terminalRunScopeKeyRef.current === currentTerminalRunScopeKey) return;
    terminalRunScopeKeyRef.current = currentTerminalRunScopeKey;
    terminalStartGenerationRef.current += 1;
    terminalLifecycleRef.current = null;
    setTerminal(null);
    setTerminalLifecycle(null);
  }, [currentTerminalRunScopeKey]);
  const terminalMatchesCurrentRun = terminalSessionMatchesRun(terminal, currentArtifactRun);
  const terminalProxy = useTerminalProxy(terminalLifecycle, invalidateSessionAuthority);
  const terminalBinding = useMemo(
    () => terminalBindingState(terminal, currentArtifactRun, terminalProxy.status),
    [currentArtifactRun, terminal, terminalProxy.status],
  );
  const terminalInteractiveCapability = useMemo(
    () =>
      resolveTerminalInteractiveCapability(terminalMatchesCurrentRun && terminalProxy.connected),
    [terminalMatchesCurrentRun, terminalProxy.connected],
  );
  const runInputDeliveryOptions = useMemo(() => {
    if (!currentArtifactRun) return [];
    const options: RunInputDelivery[] = [];
    if (config.mode === 'local' && !localRuntimeMode) return options;
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
  }, [
    config.mode,
    currentArtifactRun,
    localRuntimeMode,
    sessionProjection?.capabilities,
  ]);
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
    if (sessionProjectionState.status === 'idle' || sessionProjectionState.status === 'loading') {
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
  const loadRunChanges = useCallback(async (signal = new AbortController().signal) => {
    const requestConfig = configRef.current;
    if (!currentArtifactRun) {
      setChangeSnapshot(null);
      setChangeSnapshotError(null);
      setChangeSnapshotLoading(false);
      return;
    }
    setChangeSnapshotLoading(true);
    setChangeSnapshotError(null);
    try {
      const snapshot =
        requestConfig.mode === 'cloud'
          ? activityAuthorityAdapter.client && activityAuthorityScope
            ? desktopChangeSnapshotFromCloud(
                await activityAuthorityAdapter.client.getRunChanges(
                  activityAuthorityScope,
                  currentArtifactRun.id,
                  {
                    scope: changeScope,
                    expected_revision: currentArtifactRun.revision,
                    ...(changeScope === 'turn' ? { turn_id: currentArtifactRun.message_id } : {}),
                  },
                ),
              )
            : (() => {
                throw new Error('cloud_run_changes_authority_scope_unavailable');
              })()
          : changeScope === 'run' && scopedConversation
            ? await desktopSessionRunChangesOperationsV2.getRunChanges({
                config: requestConfig,
                conversation: scopedConversation,
                runId: currentArtifactRun.id,
                expectedRevision: currentArtifactRun.revision,
                signal,
              })
            : (() => {
                throw new Error('local_run_changes_scope_unavailable');
              })();
      setChangeSnapshot(snapshot);
      setRunInputReferences((current) =>
        current.filter(
          (reference) =>
            reference.snapshot_id === snapshot.id &&
            reference.environment_id === snapshot.environment_id,
        ),
      );
    } catch (caught) {
      setChangeSnapshotError(formatConnectionError(caught, requestConfig.apiBaseUrl));
    } finally {
      setChangeSnapshotLoading(false);
    }
  }, [
    activityAuthorityAdapter,
    activityAuthorityScope,
    changeScope,
    currentArtifactRun,
    desktopSessionRunChangesOperationsV2,
    scopedConversation,
  ]);
  const availableChangeScopes = useMemo<readonly RunChangeScope[]>(
    () =>
      config.mode === 'cloud'
        ? currentArtifactRun?.message_id
          ? ['turn', 'run', 'session']
          : ['run', 'session']
        : ['run'],
    [config.mode, currentArtifactRun?.message_id],
  );
  useEffect(() => {
    if (!availableChangeScopes.includes(changeScope)) setChangeScope('run');
  }, [availableChangeScopes, changeScope]);
  useEffect(() => {
    const controller = new AbortController();
    void loadRunChanges(controller.signal);
    return () => controller.abort();
  }, [loadRunChanges]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const requestConfig = configRef.current;
    if (
      !currentArtifactRun ||
      !scopedConversation ||
      (requestConfig.mode === 'local' && !localRuntimeMode)
    ) {
      setRunInputs([]);
      setRunInputsLoading(false);
      setRunInputsError(null);
      return () => {
        active = false;
        controller.abort();
      };
    }
    setRunInputsLoading(true);
    setRunInputsError(null);
    const requestRunInputs = async (): Promise<DesktopRunInput[]> => {
      const response = await desktopSessionRunInputOperationsV2.listRunInputs({
        config: requestConfig,
        conversation: scopedConversation,
        runId: currentArtifactRun.id,
        signal: controller.signal,
      });
      return response.inputs;
    };
    void requestRunInputs()
      .then((inputs) => {
        if (active) setRunInputs(inputs);
      })
      .catch((caught) => {
        if (active) {
          setRunInputsError(formatConnectionError(caught, requestConfig.apiBaseUrl));
        }
      })
      .finally(() => {
        if (active) setRunInputsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [
    config.apiBaseUrl,
    config.mode,
    currentArtifactRun,
    desktopSessionRunInputOperationsV2,
    localRuntimeMode,
    scopedConversation,
  ]);
  useEffect(() => {
    setRunInputDelivery((current) =>
      current && runInputDeliveryOptions.includes(current)
        ? current
        : (runInputDeliveryOptions[0] ?? null),
    );
  }, [runInputDeliveryOptions]);
  useEffect(() => {
    if (snapshotMatchesRun(changeSnapshot, currentArtifactRun?.id, currentArtifactRun?.revision)) {
      return;
    }
    setRunInputReferences([]);
    runInputRequestRef.current = null;
  }, [changeSnapshot, currentArtifactRun?.id, currentArtifactRun?.revision]);
  const promoteQueuedRunInput = useCallback(
    async (input: DesktopRunInput) => {
      const requestConfig = configRef.current;
      if (
        !currentArtifactRun ||
        currentArtifactRun.id !== input.run_id ||
        !selectedConversation
      ) {
        setError(t('session.queueSourceRunUnavailable'));
        return;
      }
      setPromotingRunInputId(input.id);
      setError(null);
      try {
        const outcome = await desktopSessionRunInputOperationsV2.promoteRunInput({
          config: requestConfig,
          conversation: selectedConversation,
          runId: currentArtifactRun.id,
          inputId: input.id,
          expectedSourceRunRevision: currentArtifactRun.revision,
          idempotencyKey: `desktop-run-input-promotion:${input.id}`,
        });
        const promotedConversation = {
          ...selectedConversation,
          ...outcome.conversation,
        };
        invalidateSessionAuthority();
        setRunInputs((current) =>
          current.map((candidate) =>
            candidate.id === outcome.input.id ? outcome.input : candidate,
          ),
        );
        setAgentConversationSession((current) =>
          current?.conversation.id === outcome.conversation.id
            ? {
                ...current,
                conversation: { ...current.conversation, ...outcome.conversation },
              }
            : current,
        );
        setDataset((current) => ({
          ...current,
          conversationsByWorkspace: Object.fromEntries(
            Object.entries(current.conversationsByWorkspace).map(([workspaceId, conversations]) => [
              workspaceId,
              conversations.map((conversation) =>
                conversation.id === outcome.conversation.id
                  ? { ...conversation, ...outcome.conversation }
                  : conversation,
              ),
            ]),
          ),
        }));
        setReviewTab('plan');
        await loadConversationTimeline(promotedConversation, requestConfig.projectId);
      } catch (caught) {
        setError(formatConnectionError(caught, requestConfig.apiBaseUrl));
      } finally {
        setPromotingRunInputId(null);
      }
    },
    [
      currentArtifactRun,
      desktopSessionRunInputOperationsV2,
      invalidateSessionAuthority,
      loadConversationTimeline,
      selectedConversation,
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
      const requestConfig = configRef.current;
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
        const { approvePlanAndStart } =
          desktopNewTaskFlowClientV2.bindOperation(requestConfig);
        const client: Pick<DesktopNewTaskFlowClientV2, 'approvePlanAndStart'> = Object.freeze({
          approvePlanAndStart,
        });
        const outcome = await client.approvePlanAndStart(
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
        const workspaceId = nextConversation.workspace_id ?? requestConfig.workspaceId.trim();
        if (workspaceId) {
          selectConversation(nextConversation.project_id, workspaceId, nextConversation, 'chat');
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
        setError(formatConnectionError(caught, requestConfig.apiBaseUrl));
      } finally {
        setSessionPlanApprovalPending(false);
      }
    },
    [
      applyAuthoritativeRun,
      desktopNewTaskFlowClientV2,
      invalidateSessionAuthority,
      sessionProjection,
      t,
    ],
  );
  const handleSessionRunAction = useCallback(
    async (action: SessionRunAction, feedback?: string) => {
      const authoritativeRun = sessionProjection?.currentRun;
      const runId = sessionDetailViewModel?.runId;
      const revision = sessionDetailViewModel?.runRevision;
      if (
        !runId ||
        revision === null ||
        revision === undefined ||
        !authoritativeRun ||
        authoritativeRun.id !== runId ||
        authoritativeRun.revision !== revision
      ) {
        setError(t('session.runControlUnavailable'));
        return;
      }
      if (!sessionDetailViewModel.runActions.includes(action)) {
        setError(t('session.authorityActionUnavailable'));
        return;
      }
      const requestConfig = configRef.current;
      setSessionRunActionPending(action);
      setError(null);
      try {
        const client = desktopSessionRunControlOperationsV2.bindOperation(
          requestConfig,
          authoritativeRun.conversation_id,
        );
        const outcome =
          action === 'pause'
            ? await client.pauseRun(runId, revision)
            : action === 'resume' || action === 'reconnect'
              ? await client.resumeRun(runId, revision)
              : action === 'fork'
                ? await client.forkRecoveryRun(
                    runId,
                    revision,
                    `desktop-recovery-fork:${runId}:${revision}`,
                  )
                : action === 'cancel'
                  ? await client.cancelRun(runId, revision)
                  : await client.reviewRun(runId, {
                      action: action === 'approve' ? 'approve' : 'request_changes',
                      expectedRevision: revision,
                      ...(feedback ? { feedback } : {}),
                    });
        applyAuthoritativeRun(outcome.run);
        invalidateSessionAuthority();
        showToast(
          'success',
          t('toast.sessionRunActionSuccess', {
            action: t(SESSION_RUN_ACTION_LABEL_KEY[action]),
          }),
        );
      } catch (caught) {
        setError(formatError(caught));
      } finally {
        setSessionRunActionPending(null);
      }
    },
    [
      applyAuthoritativeRun,
      desktopSessionRunControlOperationsV2,
      invalidateSessionAuthority,
      sessionProjection,
      sessionDetailViewModel,
      showToast,
      t,
    ],
  );
  const handleArtifactAction = useCallback(
    async (version: DesktopArtifactVersion, action: ArtifactVersionAction, feedback?: string) => {
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
      const requestConfig = configRef.current;
      setArtifactActionPending({ versionId: authoritativeVersion.id, action });
      setError(null);
      try {
        const client = desktopSessionArtifactActionOperationsV2.bindOperation(
          requestConfig,
          authoritativeVersion.conversation_id,
        );
        if (action === 'deliver') {
          const outcome = await client.deliverArtifactVersion(
            authoritativeVersion.id,
            artifactDeliveryRequest(authoritativeVersion),
          );
          if (!outcome.accepted) throw new Error(t('session.authorityActionUnavailable'));
        } else {
          const outcome = await client.reviewArtifactVersion(
            authoritativeVersion.id,
            artifactReviewRequest(authoritativeVersion, action, currentArtifactRun, feedback),
          );
          if (outcome.run) applyAuthoritativeRun(outcome.run);
        }
        invalidateSessionAuthority();
      } catch (caught) {
        setError(formatConnectionError(caught, requestConfig.apiBaseUrl));
      } finally {
        setArtifactActionPending(null);
      }
    },
    [
      applyAuthoritativeRun,
      currentArtifactRun,
      desktopSessionArtifactActionOperationsV2,
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
      ? (auth.user?.email ?? 'signed in')
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
  const localRuntimeModelLabel = runtimeProvider?.model.trim() || t('providers.notAvailable');
  const chatRuntimeModelLabel = runtimeProvider?.model.trim() || t('chat.modelNotConfigured');
  const conversationModelEvent = useMemo(
    () =>
      conversationTimeline.conversationId === scopedConversationId
        ? latestConversationRuntimeModelEvent(conversationTimeline.items)
        : null,
    [conversationTimeline.conversationId, conversationTimeline.items, scopedConversationId],
  );
  const chatModelScopeKey = scopedConversation
    ? `${agentConversationScopeKey(config)}\u0000${scopedConversation.id}`
    : '';
  const currentConversationModelMutation =
    conversationModelMutation.scopeKey === chatModelScopeKey &&
    conversationModelMutation.hasOverride &&
    conversationModelMutation.baseEventRevision === (conversationModelEvent?.revision ?? null)
      ? conversationModelMutation
      : null;
  const chatRuntimeModelSelection = conversationRuntimeModelSelection(
    scopedConversation?.agent_config,
    runtimeModelOptions,
    selectedRuntimeModelValue,
    chatRuntimeModelLabel,
    currentConversationModelMutation
      ? currentConversationModelMutation.overrideModel
      : conversationModelEvent?.overrideModel,
  );
  const persistChatRuntimeModelOverride = useCallback(
    async (
      overrideModel: string | null,
      routeOverride?: { provider_id: string; model_id: string } | null,
    ): Promise<void> => {
      const conversation = scopedConversation;
      if (!conversation || !chatModelScopeKey) {
        throw new Error(t('chat.selectedModelUnavailable'));
      }
      const requestConfig = configRef.current;
      const requestId = conversationModelMutationRequestRef.current + 1;
      conversationModelMutationRequestRef.current = requestId;
      const baseEventRevision = conversationModelEvent?.revision ?? null;
      setConversationModelMutation((current) => ({
        scopeKey: chatModelScopeKey,
        switching: true,
        error: null,
        hasOverride:
          current.scopeKey === chatModelScopeKey &&
          current.baseEventRevision === baseEventRevision &&
          current.hasOverride,
        overrideModel:
          current.scopeKey === chatModelScopeKey && current.baseEventRevision === baseEventRevision
            ? current.overrideModel
            : null,
        baseEventRevision,
      }));
      try {
        const updated = await desktopConversationConfigOperationsV2.updateModelOverride({
          config: requestConfig,
          conversation,
          llmModelOverride: overrideModel,
          llmRouteOverride: routeOverride ?? null,
        });
        const activeSession = agentConversationSessionRef.current;
        if (
          conversationModelMutationRequestRef.current !== requestId ||
          activeSession?.scopeKey !== agentConversationScopeKey(configRef.current) ||
          activeSession.conversation.id !== conversation.id
        ) {
          return;
        }
        setAgentConversationSession((current) => {
          if (
            current?.scopeKey !== activeSession.scopeKey ||
            current.conversation.id !== conversation.id
          ) {
            return current;
          }
          const next = { ...current, conversation: updated };
          agentConversationSessionRef.current = next;
          return next;
        });
        updateDataset((current) => {
          const workspaceId = updated.workspace_id?.trim() || requestConfig.workspaceId.trim();
          const conversations = current.conversationsByWorkspace[workspaceId];
          if (!conversations?.some((candidate) => candidate.id === updated.id)) return current;
          return {
            ...current,
            conversationsByWorkspace: {
              ...current.conversationsByWorkspace,
              [workspaceId]: conversations.map((candidate) =>
                candidate.id === updated.id ? updated : candidate,
              ),
            },
          };
        });
        setConversationModelMutation({
          scopeKey: chatModelScopeKey,
          switching: false,
          error: null,
          hasOverride: true,
          overrideModel,
          baseEventRevision,
        });
      } catch (caught) {
        const message = formatConnectionError(caught, requestConfig.apiBaseUrl);
        if (conversationModelMutationRequestRef.current === requestId) {
          setConversationModelMutation({
            scopeKey: chatModelScopeKey,
            switching: false,
            error: message,
            hasOverride: false,
            overrideModel: null,
            baseEventRevision,
          });
        }
        throw caught instanceof Error ? caught : new Error(message);
      }
    },
    [
      chatModelScopeKey,
      conversationModelEvent?.revision,
      desktopConversationConfigOperationsV2,
      scopedConversation,
      t,
      updateDataset,
    ],
  );
  const selectChatRuntimeModel = useCallback(
    async (value: string): Promise<void> => {
      if (!scopedConversation) return selectRuntimeModel(value);
      const option = runtimeModelOptions.find((candidate) => candidate.value === value);
      if (!option) throw new Error(t('chat.selectedModelUnavailable'));
      return persistChatRuntimeModelOverride(
        option.modelId,
        config.mode === 'local'
          ? { provider_id: option.providerId, model_id: option.modelId }
          : null,
      );
    },
    [
      persistChatRuntimeModelOverride,
      runtimeModelOptions,
      scopedConversation,
      selectRuntimeModel,
      t,
    ],
  );
  const resetChatRuntimeModel = useCallback((): Promise<void> => {
    return persistChatRuntimeModelOverride(null, null);
  }, [persistChatRuntimeModelOverride]);
  const chatRuntimeModelMutationIsCurrent =
    conversationModelMutation.scopeKey === chatModelScopeKey;
  const chatRuntimeModelSwitching = scopedConversation
    ? chatRuntimeModelMutationIsCurrent && conversationModelMutation.switching
    : switchingRuntimeModel;
  const chatRuntimeModelError = scopedConversation
    ? chatRuntimeModelMutationIsCurrent
      ? conversationModelMutation.error
      : null
    : runtimeModelError;
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
      : (sidebarRunItems[0]?.id ?? '');
  const activeSidebarRun = sidebarRunItems.find((item) => item.id === activeSidebarRunId) ?? null;
  const titlebarPrimaryLabel =
    showRuntimeConfig && activeSection === 'board'
      ? t('myWork.title')
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

    switchSection('board');
  };

  const applySectionSideEffects = (section: WorkbenchSection) => {
    activeSectionRef.current = section;
    setActiveSection(section);
    if (isViewTabSection(section)) {
      setOpenTabs((tabs) => ensureViewTab(tabs, section));
    }
    if (section === 'board') {
      setReviewTab('changes');
      closeRightCanvasPanel();
    }
  };

  const nativeOAuthResumeRoute = useCallback(() => {
    const restored = restoreDesktopRoute(
      desktopProductionRouteRegistry,
      desktopProductionRouteLocation.readHash(),
    );
    return restored.status === 'matched' ? restored.match.canonicalPath : '/';
  }, [desktopProductionRouteLocation, desktopProductionRouteRegistry]);

  const handleNativeOAuthAuthenticated = useCallback(
    (resumeRoute: string, projection: CloudSessionProjection) => {
      const canonicalPath = resolveNativeOAuthResumePath(
        desktopProductionRouteRegistry,
        resumeRoute,
        projection,
      );
      if (canonicalPath) desktopProductionRouteNavigation.openPath(canonicalPath);
      else desktopProductionRouteNavigation.clearHash();
    },
    [desktopProductionRouteNavigation, desktopProductionRouteRegistry],
  );

  const {
    beginNativeOAuth,
    cancelForcedPasswordChange,
    cancelWorkspaceSso,
    changeLoginMode,
    handleConfigChange,
    hydrateCloudSession,
    hydrateProjectedCloudSession,
    hydrateLocalSession,
    login,
    loginLocalSession,
    loginWithWorkspaceSso,
    nativeOAuthPendingProvider,
    nativeOAuthProviders,
    logout,
    openCurrentWorkspaceSso,
    submitForcedPasswordChange,
    useApiKeyManually,
  } = useDesktopAuth({
    activeSectionRef,
    api,
    applySectionSideEffects,
    auth,
    authAttemptRevisionRef,
    commitRuntimeConfig,
    nativeOAuthResumeRoute,
    onNativeOAuthAuthenticated: handleNativeOAuthAuthenticated,
    config,
    configRef,
    contextRevisionRef,
    deviceAuthAttemptIdRef,
    deviceAuthAttemptRef,
    error,
    localResumeAttemptRef,
    localRuntimeAuthorityReady,
    loginEmail,
    loginPassword,
    pendingPasswordChangeRef,
    refreshRuntime,
    resetConversationTimeline,
    resetProjectScopedState,
    runsInNativeDesktop,
    selectedProject,
    setActiveSection,
    setAgentConversationSession,
    setAgentTaskSignals,
    setAuth,
    setConnection,
    setDataset,
    setError,
    setLastSync,
    setLoginEmail,
    setLoginModalOpen,
    setLoginPassword,
    setSectionBackStack,
    setSectionForwardStack,
    setSettingsInitialSection,
    setSettingsWindowOpen,
    setWorkspaceSso,
    workspaceSso,
  });

  useEffect(() => {
    if (!runsInNativeDesktop || auth.status !== 'signed_out' || !hasNativeTrustedSessionBroker()) {
      return;
    }
    const attemptKey = `${config.mode}|${config.apiBaseUrl}|${config.localApiToken}`;
    if (localResumeAttemptRef.current === attemptKey) return;
    localResumeAttemptRef.current = attemptKey;
    const authAttemptRevision = ++authAttemptRevisionRef.current;

    void (async () => {
      try {
        setAuth((current) => ({
          ...current,
          status: 'signing_in',
          error: null,
        }));
        setConnection('loading');
        setError(null);

        await selectPlatformPluginAuthorityV2(config.mode);
        if (config.mode === 'cloud') {
          const projection = await hydrateProjectedCloudSession(authAttemptRevision);
          if (
            localResumeAttemptRef.current !== attemptKey ||
            authAttemptRevisionRef.current !== authAttemptRevision
          ) {
            return;
          }
          if (!projection) {
            setAuth(emptyAuthState);
            setConnection('idle');
          }
          return;
        }

        const trustedSession = await loadLocalTrustedSession();
        if (!trustedSession) {
          setAuth(emptyAuthState);
          setConnection('idle');
          return;
        }
        if (
          localResumeAttemptRef.current !== attemptKey ||
          authAttemptRevisionRef.current !== authAttemptRevision
        ) {
          return;
        }

        if (trustedSession.runtime_mode !== 'local' || !localRuntimeAuthorityReady) {
          localResumeAttemptRef.current = '';
          setAuth(emptyAuthState);
          setConnection('idle');
          return;
        }

        // The native local runtime uses an ephemeral port after each launch. Bind recovery to the
        // exact live endpoint and launch capability reported by the sidecar, then rotate the record.
        const bootstrapClient = new DesktopApiClient({ ...config, apiKey: '' });
        const outcome = await bootstrapClient.resumeLocalSession(trustedSession.credential);
        if (
          localResumeAttemptRef.current !== attemptKey ||
          authAttemptRevisionRef.current !== authAttemptRevision
        ) {
          return;
        }
        if (!outcome?.session?.session_id) {
          await clearLocalTrustedSession();
          if (authAttemptRevisionRef.current !== authAttemptRevision) return;
          setAuth(emptyAuthState);
          setConnection('idle');
          return;
        }
        await saveLocalTrustedSession({
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
          if (config.mode === 'local') {
            await clearLocalTrustedSession();
          } else {
            await clearNativeTrustedSession();
          }
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
    runsInNativeDesktop,
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

  // The active tab mirrors the workbench state: the scoped conversation when
  // chatting, otherwise the current view section.
  const activeWorkbenchTab: WorkbenchTab =
    activeSection === 'chat' && scopedConversation
      ? {
          kind: 'conversation',
          projectId: config.projectId,
          workspaceId: config.workspaceId,
          conversationId: scopedConversation.id,
          title: scopedConversation.title,
        }
      : {
          kind: 'view',
          section: isViewTabSection(activeSection) ? activeSection : 'workspace',
        };
  const activeWorkbenchTabKey = tabKey(activeWorkbenchTab);

  const findOpenConversation = (conversationId: string): AgentConversation | null =>
    Object.values(dataset.conversationsByWorkspace)
      .flat()
      .find((conversation) => conversation.id === conversationId) ?? null;

  const activateWorkbenchTab = (tab: WorkbenchTab) => {
    if (tab.kind === 'view') {
      switchSection(tab.section);
      return;
    }
    const conversation = findOpenConversation(tab.conversationId);
    if (!conversation) {
      // The conversation was deleted or never hydrated; drop the dead tab.
      setOpenTabs((tabs) => tabs.filter((candidate) => !isSameTab(candidate, tab)));
      return;
    }
    selectConversation(tab.projectId, tab.workspaceId, conversation);
  };

  const closeWorkbenchTab = (tab: WorkbenchTab) => {
    const { tabs: nextTabs, fallback } = closeTab(openTabs, tab, activeWorkbenchTabKey);
    setOpenTabs(nextTabs);
    if (!fallback) return;
    if (fallback.kind === 'view') {
      switchSection(fallback.section);
      return;
    }
    const conversation = findOpenConversation(fallback.conversationId);
    if (conversation) {
      selectConversation(fallback.projectId, fallback.workspaceId, conversation);
      return;
    }
    setOpenTabs((tabs) => tabs.filter((candidate) => !isSameTab(candidate, fallback)));
    switchSection('workspace');
  };

  // The right sidebar hosts the session context rail, the review canvas, and
  // the in-app browser panel. The browser panel is not session-scoped, so the
  // sidebar stays available in the chat section even without a session.
  const rightSidebarAvailable = activeSection === 'chat';

  const handleOpenCanvas = (tab?: SessionCanvasTabId) => {
    setReviewTab(
      tab ??
        (sessionDetailViewModel
          ? defaultSessionCanvasTab(
              sessionDetailViewModel.status,
              sessionDetailViewModel.capabilityMode,
            )
          : 'overview'),
    );
    openRightCanvasPanel();
  };

  const handleCloseCanvas = () => {
    // A canvas the user never asked for takes the whole sidebar down with it.
    if (rightSidebarOpenedForCanvas) setRightSidebarOpen(false);
    closeRightCanvasPanel();
  };

  const handleSelectRightPanel = (panel: DesktopRightPanel) => {
    setActiveRightPanel(panel);
    setRightSidebarOpenedForCanvas(false);
    if (panel === 'canvas') setRightSidebarOpen(true);
  };

  const {
    activateNewTaskSession,
    changeNewThreadWorkspace,
    createComposerThread,
    openNewTask,
    persistNewTaskSession,
    resumeSessionTaskListReview,
    runNewTaskAgentTurn,
    sendMessageContent,
    startNewSession,
  } = useAgentConversation({
    agentConversationSession,
    api,
    applySectionSideEffects,
    auth,
    canManageWorkspacePolicy,
    commitRuntimeConfig,
    config,
    configRef,
    configScopeEpochRef,
    configuredNewThreadWorkspaceId,
    connection,
    contextRevisionRef,
    currentArtifactRun,
    dataset,
    invalidateSessionAuthority,
    loadConversationTimeline,
    localRuntimeMode,
    newThreadWorkspaces,
    newThreadCreationClientV2: desktopNewThreadCreationOperationsV2,
    sessionRunInputOperationsV2: desktopSessionRunInputOperationsV2,
    pendingNewTaskAgentTurnsRef,
    permissionPreset,
    resetConversationTimeline,
    runInputDelivery,
    runInputDeliveryOptions,
    runInputReferences,
    runInputRequestRef,
    selectedConversation,
    sessionChatDisabledReason,
    sessionProjection,
    sessionTaskListPlanRecovery,
    setAgentConversationSession,
    setAgentTaskSignals,
    setCommandPaletteOpen,
    setCommandQuery,
    setConversationTimeline,
    setDataset,
    setError,
    setExpandedWorkspaceIds,
    setLoginModalOpen,
    setNewTaskOpen,
    setNewTaskPreferredWorkspaceId,
    setNewTaskResumeDraft,
    setNewThreadCreating,
    setNewThreadError,
    setNewThreadScope,
    setReviewTab,
    setRunInputReferences,
    setRunInputs,
    setSectionBackStack,
    setSectionForwardStack,
    setSelectedTaskId,
    setSending,
    socket,
    switchSection,
    upsertAgentTaskSignal,
    workspaceAgentPolicy,
  });

  const sendMessageContentRef = useRef(sendMessageContent);
  sendMessageContentRef.current = sendMessageContent;
  switchSectionRef.current = switchSection;

  const openSettingsEntry = (entry: SettingsEntry) => {
    setSettingsInitialSection(settingsSectionForEntry(entry));
    setSettingsWindowOpen(true);
  };

  const openSidebarSettings = () => openSettingsEntry('sidebar');
  const openWorkspaceSettings = () => {
    if (selectedWorkspace && config.tenantId && config.projectId) {
      setWorkspaceSettingsOpen(true);
      return;
    }
    openSettingsEntry('workspace_overview');
  };
  const retryWorkspaceAutonomyAttention = useCallback(async (attentionId: string) => {
    const requestConfig = configRef.current;
    const requestScopeKey = workspaceAutonomyAttentionScopeKey(requestConfig);
    if (!requestConfig.workspaceId.trim()) return;
    const requestIsCurrent = () =>
      isSameDesktopRequestScope(requestConfig, configRef.current) &&
      requestScopeKey === workspaceAutonomyAttentionScopeKey(configRef.current);
    setRetryingWorkspaceAutonomyAttentionId(attentionId);
    setWorkspaceAutonomyAttentionState((current) =>
      current.scopeKey === requestScopeKey
        ? { ...current, authority: { ...current.authority, error: null } }
        : current,
    );
    try {
      const attentions =
        await desktopWorkspaceAutonomyAttentionOperationsV2.withRetryWorkspaceAutonomyAttention(
          {
            config: requestConfig,
            workspaceId: requestConfig.workspaceId,
            attentionId,
          },
          async (client) => {
            await client.retryWorkspaceAutonomyAttention(attentionId);
            return client.listWorkspaceAutonomyAttentions();
          },
        );
      if (!requestIsCurrent()) return;
      setWorkspaceAutonomyAttentionState({
        scopeKey: requestScopeKey,
        authority: { status: 'ready', items: attentions, error: null },
      });
    } catch (caught) {
      if (!requestIsCurrent()) return;
      const retryError = formatConnectionError(caught, requestConfig.apiBaseUrl);
      setWorkspaceAutonomyAttentionState((current) =>
        current.scopeKey === requestScopeKey
          ? {
              ...current,
              authority: { ...current.authority, status: 'error', error: retryError },
            }
          : current,
      );
    } finally {
      if (requestIsCurrent()) {
        setRetryingWorkspaceAutonomyAttentionId((current) =>
          current === attentionId ? null : current,
        );
      }
    }
  }, [desktopWorkspaceAutonomyAttentionOperationsV2]);
  const resolveWorkspaceAutonomyAttention = useCallback(async (attentionId: string) => {
    const requestConfig = configRef.current;
    const requestScopeKey = workspaceAutonomyAttentionScopeKey(requestConfig);
    const requestActorId = authRef.current.user?.user_id.trim() ?? '';
    if (!requestConfig.workspaceId.trim() || !requestActorId) return;
    const requestIsCurrent = () =>
      isSameDesktopRequestScope(requestConfig, configRef.current) &&
      requestScopeKey === workspaceAutonomyAttentionScopeKey(configRef.current) &&
      (authRef.current.user?.user_id.trim() ?? '') === requestActorId;
    const applyCanonicalAttentions = (
      attentions: readonly WorkspaceAutonomyAttention[],
      authorityError: string | null,
    ): boolean => {
      retainOpenWorkspaceAutonomyAttentionResolveAttempts(
        workspaceAutonomyAttentionResolveAttemptsRef.current,
        requestScopeKey,
        requestActorId,
        attentions,
      );
      const attentionRemainsOpen = attentions.some(
        (attention) => attention.attention_id === attentionId,
      );
      setWorkspaceAutonomyAttentionState({
        scopeKey: requestScopeKey,
        authority: {
          status: authorityError ? 'error' : 'ready',
          items: [...attentions],
          error: authorityError,
        },
      });
      return attentionRemainsOpen;
    };
    const persistedAttempt = currentWorkspaceAutonomyAttentionResolveAttempt(
      workspaceAutonomyAttentionResolveAttemptsRef.current,
      requestScopeKey,
      requestActorId,
      attentionId,
    );
    const operationIdempotencyKey =
      persistedAttempt?.idempotencyKey ??
      `desktop-autonomy-attention-resolve:${globalThis.crypto.randomUUID()}`;
    setResolvingWorkspaceAutonomyAttentionId(attentionId);
    setWorkspaceAutonomyAttentionState((current) =>
      current.scopeKey === requestScopeKey
        ? { ...current, authority: { ...current.authority, error: null } }
        : current,
    );
    let operationErrorHandled = false;
    try {
      await desktopWorkspaceAutonomyAttentionOperationsV2.withResolveWorkspaceAutonomyAttention(
        {
          config: requestConfig,
          workspaceId: requestConfig.workspaceId,
          actorId: requestActorId,
          attentionId,
          expectedRevision: persistedAttempt?.expectedRevision ?? null,
          idempotencyKey: operationIdempotencyKey,
        },
        async (client, prepared) => {
          try {
            let attempt = persistedAttempt;
            if (!attempt) {
              const expectedRevision = await client.getWorkspaceAuthorityRevision();
              if (!requestIsCurrent()) return;
              attempt = resolveWorkspaceAutonomyAttentionAttempt(
                workspaceAutonomyAttentionResolveAttemptsRef.current,
                {
                  scopeKey: requestScopeKey,
                  actorId: requestActorId,
                  attentionId,
                  expectedRevision,
                  idempotencyKey: prepared.idempotencyKey,
                },
              );
            }
            await client.resolveWorkspaceAutonomyAttention(
              attentionId,
              attempt.expectedRevision,
              attempt.idempotencyKey,
            );
            const attentions = await client.listWorkspaceAutonomyAttentions();
            if (!requestIsCurrent()) return;
            applyCanonicalAttentions(attentions, null);
          } catch (caught) {
            if (!requestIsCurrent()) throw caught;
            const resolveError = formatConnectionError(caught, requestConfig.apiBaseUrl);
            try {
              const attentions = await client.listWorkspaceAutonomyAttentions();
              if (!requestIsCurrent()) throw caught;
              const attentionRemainsOpen = attentions.some(
                (attention) => attention.attention_id === attentionId,
              );
              if (!attentionRemainsOpen) {
                applyCanonicalAttentions(attentions, null);
              } else {
                if (caught instanceof DesktopApiError && caught.status === 409) {
                  discardWorkspaceAutonomyAttentionResolveAttempt(
                    workspaceAutonomyAttentionResolveAttemptsRef.current,
                    requestScopeKey,
                    requestActorId,
                    attentionId,
                  );
                }
                applyCanonicalAttentions(attentions, resolveError);
              }
            } catch {
              if (!requestIsCurrent()) throw caught;
              setWorkspaceAutonomyAttentionState((current) =>
                current.scopeKey === requestScopeKey
                  ? {
                      ...current,
                      authority: {
                        ...current.authority,
                        status: 'error',
                        error: resolveError,
                      },
                    }
                  : current,
              );
            }
            operationErrorHandled = true;
            throw caught;
          }
        },
      );
    } catch (caught) {
      if (!requestIsCurrent() || operationErrorHandled) return;
      const resolveError = formatConnectionError(caught, requestConfig.apiBaseUrl);
      setWorkspaceAutonomyAttentionState((current) =>
        current.scopeKey === requestScopeKey
          ? {
              ...current,
              authority: { ...current.authority, status: 'error', error: resolveError },
            }
          : current,
      );
    } finally {
      if (requestIsCurrent()) {
        setResolvingWorkspaceAutonomyAttentionId((current) =>
          current === attentionId ? null : current,
        );
      }
    }
  }, [desktopWorkspaceAutonomyAttentionOperationsV2]);
  const openProfileWorkspaceSettings = () => openSettingsEntry('profile_workspace_switch');

  const openConnectionSettings = () => {
    if (!identityAuthenticated) {
      useApiKeyManually();
    }
    openSettingsEntry('runtime_connection');
  };
  projectCronJobsRouteBindingProviderV2.publish({
    api: desktopAutomationApiV2,
    scope: Object.freeze({
      tenantId: config.tenantId,
      projectId: config.projectId,
    }),
    projects: auth.projects,
    capabilitySnapshot: desktopCapabilityState.snapshot,
    onOpenProjectSettings: openWorkspaceSettings,
    onOpenConnection: openConnectionSettings,
  });

  const applySettingsContext = async (tenantId: string, projectId: string) => {
    const requestConfig = Object.freeze({ ...configRef.current });
    const authAttemptRevision = authAttemptRevisionRef.current;
    const requestIsCurrent = () =>
      authAttemptRevisionRef.current === authAttemptRevision &&
      isSameDesktopRequestScope(requestConfig, configRef.current);
    if (!auth.tenants.some((tenant) => tenant.id === tenantId)) {
      throw new Error(t('settings.selectedTenantUnavailable'));
    }
    const authorityConfig = Object.freeze({
      ...requestConfig,
      tenantId,
      projectId: '',
      workspaceId: '',
    });
    const signal = new AbortController().signal;
    await withDesktopWorkspaceContextAuthorityOperationV2(
      desktopRendererGenerationV2.actions,
      authorityConfig,
      async (contextClient) => {
        const listedProjects = await contextClient.listProjects(tenantId, signal);
        if (!requestIsCurrent()) return;
        const scopedProjects = listedProjects.filter(
          (project) => project.tenant_id === tenantId,
        );
        const selectedProject = findWorkspaceProject(scopedProjects, tenantId, projectId);
        if (!selectedProject) {
          throw new Error(t('settings.selectedProjectUnavailable'));
        }

        let currentContext = auth.context;
        if (!currentContext) {
          const currentContextResponse = await contextClient.getWorkspaceContext(signal);
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
            signal,
          );
          if (!requestIsCurrent()) return;
          nextContext = nextContextResponse.context;
        }
        if (!workspaceContextMatchesSelection(nextContext, tenantId, projectId)) {
          throw new Error(t('settings.contextResponseMismatch'));
        }
        if (!requestIsCurrent()) return;
        const nextConfig = {
          ...requestConfig,
          tenantId,
          projectId,
          workspaceId: '',
        };
        contextRevisionRef.current = nextContext.revision;
        resetProjectScopedState();
        commitRuntimeConfig(nextConfig);
        setAuth((current) => ({
          ...current,
          context: nextContext,
          projects: scopedProjects,
        }));
        applySectionSideEffects('workspace');
        await refreshRuntime(nextConfig, [selectedProject]);
      },
    );
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

  const selectChatWorkflowTarget = useCallback(
    (target: ChatWorkflowTarget) => {
      openRightCanvasPanel();
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
    },
    [openRightCanvasPanel],
  );

  const openMCPAppResult = useCallback(
    (item: AgentTimelineItem) => {
      const result = applyMCPAppCanvasStreamEvent(mcpAppCanvasStateRef.current, item);
      if (!result.handled || result.action !== 'open') return;
      mcpAppCanvasStateRef.current = result.state;
      setMCPAppCanvasState(result.state);
      setReviewTab('apps');
      openRightCanvasPanel();
    },
    [openRightCanvasPanel],
  );

  const handleChatRemoveReference = useCallback((reference: CodeRangeReference) => {
    setRunInputReferences((current) => toggleRunInputReference(current, reference));
  }, []);

  const handleAddChangeComment = useCallback(
    (comment: ChangeReviewComment) => {
      const conversationId = changeSnapshot?.conversation_id;
      if (!conversationId) return;
      setChangeCommentsByConversation((current) =>
        addChangeComment(current, conversationId, comment),
      );
    },
    [changeSnapshot?.conversation_id],
  );

  const handleRemoveChangeComment = useCallback(
    (commentId: string) => {
      const conversationId = changeSnapshot?.conversation_id;
      if (!conversationId) return;
      setChangeCommentsByConversation((current) =>
        removeChangeComment(current, conversationId, commentId),
      );
    },
    [changeSnapshot?.conversation_id],
  );

  // P1-4: batch every pending inline comment into one agent-bound message.
  // The text carries quoted anchors (path#L12 / path#L-9) so the agent can
  // resolve each commented location even where structured references are not
  // carried on the wire; the deduplicated code-range references ride the
  // run-input payload exactly like composer's toggled references.
  const handleSendChangeComments = useCallback(
    (comments: ChangeReviewComment[]) => {
      const conversationId = changeSnapshot?.conversation_id;
      if (!conversationId || comments.length === 0) return;
      sendChatMessage(
        buildChangeCommentsMessage(comments),
        [],
        undefined,
        referencesForChangeComments(comments),
      );
      setChangeCommentsByConversation((current) => clearChangeComments(current, conversationId));
    },
    [changeSnapshot?.conversation_id, sendChatMessage],
  );

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

  const showShortcutsDefinition = shortcutById('show-shortcuts');
  const showShortcutsChord = showShortcutsDefinition
    ? shortcutChordFor(
        showShortcutsDefinition,
        detectShortcutPlatform(navigator.userAgent, navigator.platform),
      )
    : undefined;
  const routeDiscoveryEntries =
    desktopRendererAuthorityV2.status === 'ready' &&
    desktopCanonicalNavigationRegistry.definitions.length > 0 &&
    desktopCanonicalNavigationRegistry.definitions.length ===
      desktopRendererAuthorityV2.navigationDiscoveryRouteIds.length
      ? deriveDesktopNavigationDiscoveryEntries({
          registry: desktopCanonicalNavigationRegistry,
          authenticated: identityAuthenticated,
          context: {
            tenantId: config.tenantId,
            projectId: config.projectId,
            workspaceId: config.workspaceId,
          },
          translate: t,
        })
      : [];
  const routeCommandItems: CommandPaletteItem[] = routeDiscoveryEntries.map((entry) => ({
    id: `route:${entry.routeId}`,
    kind: 'route',
    groupId: entry.groupId,
    groupLabel: entry.groupLabel,
    routeId: entry.routeId,
    label: entry.label,
    description: entry.description,
    icon: <GridIcon />,
    disabled: Boolean(entry.disabledReason),
    disabledReason: entry.disabledReason
      ? t(`featureDirectory.disabled.${entry.disabledReason.code}`, {
          scope: entry.disabledReason.scope
            ? t(`featureDirectory.scope.${entry.disabledReason.scope}`)
            : '',
        })
      : undefined,
    searchText: entry.searchText,
    onSelect: () => {
      if (entry.destinationPath) {
        desktopProductionRouteNavigation.openPath(entry.destinationPath);
      }
    },
  }));
  const shellCommandGroup = t('featureDirectory.group.desktopShell');
  const commandItems: CommandPaletteItem[] = [
    ...routeCommandItems,
    {
      id: 'home',
      kind: 'action',
      groupId: 'desktop-shell',
      groupLabel: shellCommandGroup,
      label: t('nav.home'),
      description: t('commandPalette.homeDescription'),
      icon: <DashboardIcon />,
      searchText: `${t('nav.home')} ${t('commandPalette.homeDescription')}`,
      onSelect: () => switchSection('home'),
    },
    {
      id: 'my-work',
      kind: 'action',
      groupId: 'desktop-shell',
      groupLabel: shellCommandGroup,
      label: t('myWork.title'),
      description: t('myWork.commandDescription'),
      icon: <GridIcon />,
      searchText: `${t('myWork.title')} ${t('myWork.commandDescription')}`,
      onSelect: () => switchSection('board'),
    },
    {
      id: 'settings',
      kind: 'settings',
      groupId: 'desktop-shell',
      groupLabel: shellCommandGroup,
      label: identityAuthenticated ? t('settings.title') : t('commandPalette.useApiKey'),
      description: identityAuthenticated
        ? t('commandPalette.settingsDescription')
        : t('commandPalette.apiKeyDescription'),
      icon: <GearIcon />,
      searchText: `${t('settings.title')} ${t('commandPalette.settingsDescription')} ${t('commandPalette.useApiKey')} ${t('commandPalette.apiKeyDescription')}`,
      onSelect: identityAuthenticated ? openSidebarSettings : openConnectionSettings,
    },
    {
      id: 'browser-integration-settings',
      kind: 'settings',
      groupId: 'desktop-auxiliary',
      groupLabel: t('featureDirectory.group.auxiliary'),
      label: t('settings.browser'),
      description: t('settings.browserDescription'),
      icon: <GearIcon />,
      searchText: `${t('settings.browser')} ${t('settings.browserDescription')}`,
      onSelect: () => openSettingsEntry('browser_integration'),
    },
    {
      id: 'sign-in',
      kind: 'settings',
      groupId: 'desktop-shell',
      groupLabel: shellCommandGroup,
      label: auth.status === 'signed_in' ? t('settings.account') : t('login.signInTitle'),
      description:
        auth.status === 'signed_in'
          ? (auth.user?.email ?? t('commandPalette.accountDescription'))
          : t('commandPalette.signInDescription'),
      icon: <RocketIcon />,
      searchText: `${t('settings.account')} ${t('login.signInTitle')} ${auth.user?.email ?? ''}`,
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
      kind: 'action',
      groupId: 'desktop-shell',
      groupLabel: shellCommandGroup,
      label: t('commandPalette.refreshWorkspace'),
      description: runtimeDisabledReason ?? t('commandPalette.refreshDescription'),
      icon: <RocketIcon />,
      disabled: Boolean(runtimeDisabledReason) || connection === 'loading',
      disabledReason: runtimeDisabledReason ?? undefined,
      searchText: `${t('commandPalette.refreshWorkspace')} ${runtimeDisabledReason ?? t('commandPalette.refreshDescription')}`,
      onSelect: () => void refreshRuntime(),
    },
    {
      id: 'keyboard-shortcuts',
      kind: 'action',
      groupId: 'desktop-shell',
      groupLabel: shellCommandGroup,
      label: t('commandPalette.showShortcuts'),
      description: t('shortcuts.description'),
      icon: <KeyboardIcon />,
      shortcut: showShortcutsChord,
      searchText: `${t('commandPalette.showShortcuts')} ${t('shortcuts.description')}`,
      onSelect: () => setShortcutsDialogOpen(true),
    },
  ];
  const matchingRouteIds = new Set(
    filterDesktopNavigationDiscoveryEntries(routeDiscoveryEntries, commandQuery, locale).map(
      ({ routeId }) => routeId,
    ),
  );
  const authorizedCommandItems = commandItems.filter(
    (item) =>
      item.kind !== 'route' ||
      (item.routeId !== undefined &&
        isDesktopNavigationRouteEnabledV2(desktopRendererAuthorityV2, item.routeId)),
  );
  const normalizedCommandQuery = commandQuery.trim().toLocaleLowerCase(locale);
  const filteredCommandItems = normalizedCommandQuery
    ? authorizedCommandItems.filter((item) =>
        item.kind === 'route' && item.id.startsWith('route:') && item.routeId
          ? matchingRouteIds.has(item.routeId as (typeof routeDiscoveryEntries)[number]['routeId'])
          : item.searchText.toLocaleLowerCase(locale).includes(normalizedCommandQuery),
      )
    : authorizedCommandItems;

  const createChatWorkbenchViewV2 = (): DesktopWorkbenchViewV2 => ({
    kind: 'chat',
    chatPanel: {
      api: chatComposerApi,
      conversations: dataset.conversationsByWorkspace[config.workspaceId] ?? [],
      selectedConversationId: selectedConversation?.id ?? null,
      messages: dataset.messages,
      timelineState: selectedConversation ? sessionTimeline : null,
      agentTaskSignals,
      workflowCounts: chatWorkflowCounts,
      sessionTitle: selectedConversation?.title ?? workspaceLabel(selectedWorkspace ?? undefined),
      scopeLabel: selectedConversation
        ? `Agent session / ${workspaceLabel(selectedWorkspace ?? undefined)}`
        : 'Workspace conversation',
      turnCollapseRuntime: {
        mode: config.mode,
        apiBaseUrl: config.apiBaseUrl,
        tenantId: config.tenantId,
        projectId: config.projectId,
      },
      voiceTranscriptionConfig: config,
      composerVariant: selectedConversation ? 'session' : 'workspace',
      composerResetKey: selectedConversation?.id ?? config.workspaceId,
      activityPresence: sessionActivityState,
      activityStructuredEvidence: sessionActivityStructuredEvidence,
      sending,
      disabledReason: sessionChatDisabledReason,
      agentControlEvents: socket.events,
      activeWorkflowTarget: chatWorkflowTargetForReviewTab(reviewTab),
      modelLabel: chatRuntimeModelSelection.displayLabel,
      modelOptions: runtimeModelOptions,
      selectedModelValue: chatRuntimeModelSelection.selectedValue,
      modelSwitching: chatRuntimeModelSwitching,
      modelError: chatRuntimeModelError,
      runtimeTargetLabel: runtimeTargetLabels[runtimeTarget],
      runtimeTargetOptions: runtimeTargetComposerOptions,
      composeAheadFallbackAllowed: false,
      canonicalRunStatus: currentArtifactRun?.status ?? null,
      runInputDelivery: effectiveRunInputDeliveryValue,
      runInputDeliveryOptions,
      runInputs,
      runInputsLoading,
      runInputsError,
      promotingRunInputId,
      runInputAuthorityRunId: currentArtifactRun?.id ?? null,
      references: runInputReferences,
      onRunInputDeliveryChange: setRunInputDelivery,
      onPromoteRunInput: promoteQueuedRunInput,
      onRemoveReference: handleChatRemoveReference,
      onSend: sendChatMessage,
      onRegenerateConversationSummary: regenerateConversationSummary,
      onStopResponse: socket.stopAgentResponse,
      onSteerResponse: (request) =>
        socket.sendSteerMessage({
          conversationId: request.conversationId,
          projectId: config.projectId,
          message: request.text,
          messageId: request.messageId,
        }),
      subAgentControlAuthority,
      onSubAgentControl: socket.sendSubAgentControl,
      onRefresh: handleChatRefresh,
      onLoadEarlier: loadEarlierTimeline,
      onRespondToHitl: respondToHitlWithSteering,
      respondableHitlRequestIds,
      permissionPreset: selectedConversation ? permissionPreset : undefined,
      permissionPresetFullAccessAcknowledged: fullAccessWarningAcknowledged,
      onPermissionPresetChange: selectedConversation ? handlePermissionPresetChange : undefined,
      onAcknowledgeFullAccessWarning: selectedConversation
        ? handleAcknowledgeFullAccessWarning
        : undefined,
      authorityNotice: sessionAuthorityNotice,
      onAuthorityAction:
        sessionProjectionState.status === 'error' ? invalidateSessionAuthority : undefined,
      onWorkflowSelect: selectChatWorkflowTarget,
      onModelChange: selectChatRuntimeModel,
      onModelReset:
        scopedConversation && chatRuntimeModelSelection.canReset
          ? resetChatRuntimeModel
          : undefined,
      onRuntimeTargetChange: handleChatRuntimeTargetChange,
      onOpenMCPAppResult: openMCPAppResult,
      onOpenCommands: openCommandPalette,
      runCompletionSummary: selectedConversation ? runCompletionSummary : null,
      onOpenSessionCanvasTab: openSessionCanvasTab,
    },
  });

  const createWorkspaceWorkbenchViewV2 = (): DesktopWorkbenchViewV2 => ({
    kind: 'workspace',
    overview: {
      workspace: selectedWorkspace,
      project: selectedProject,
      tenantName:
        auth.tenants.find((tenant) => tenant.id === config.tenantId)?.name ||
        config.tenantId ||
        t('settings.noTenantSelected'),
      workspaceAuthority: newTaskWorkspaceAuthority,
      conversations: dataset.conversationsByWorkspace[config.workspaceId] ?? [],
      members: dataset.workspaceMembers,
      agents: dataset.workspaceAgents,
      plan: activeDataset.plan,
      sandboxStatus: dataset.sandbox?.status ?? null,
      liveActivity: workspaceLiveActivity,
      autonomyAttentions: workspaceAutonomyAttentions,
      canRetryAutonomyAttention: canRetryWorkspaceAutonomyAttention,
      canResolveAutonomyAttention: canRetryWorkspaceAutonomyAttention,
      retryingAutonomyAttentionId: retryingWorkspaceAutonomyAttentionId,
      resolvingAutonomyAttentionId: resolvingWorkspaceAutonomyAttentionId,
      newTaskDisabledReason,
      onNewTask: () => openNewTask(config.workspaceId),
      onRetryWorkspaces: () => void refreshRuntime(),
      onRetryAutonomyAttention: (attentionId) => void retryWorkspaceAutonomyAttention(attentionId),
      onResolveAutonomyAttention: (attentionId) =>
        void resolveWorkspaceAutonomyAttention(attentionId),
      onOpenConversation: (conversationId) => {
        const conversation = (dataset.conversationsByWorkspace[config.workspaceId] ?? []).find(
          (item) => item.id === conversationId,
        );
            if (!conversation) {
              setError(t('myWork.sessionUnavailable'));
          return;
        }
        selectConversation(config.projectId, config.workspaceId, conversation, 'chat');
      },
      onOpenSettings: openWorkspaceSettings,
    },
    collaboration:
      selectedWorkspace && config.workspaceId.trim()
        ? {
            workspaceId: config.workspaceId,
            client: workspaceCollaborationClientV2,
            authorityInvalidation: workspaceCollaborationAuthorityInvalidation,
          }
        : null,
  });

  const openMyWorkSession = async (item: ProjectWorkItem) => {
    const workspaceId = item.workspace_id ?? '';
    const conversationGroupKey = workspaceId || UNBOUND_CONVERSATIONS_KEY;
    const expectedContextRevision = contextRevisionRef.current;
    const expectedScopeEpoch = configScopeEpochRef.current;
    let conversation = (dataset.conversationsByWorkspace[conversationGroupKey] ?? []).find(
      (candidate) => candidate.id === item.conversation_id,
    );
    if (item.project_id !== config.projectId) {
      setError(t('myWork.sessionUnavailable'));
      return;
    }
    if (!conversation) {
      try {
        const response =
          await desktopWorkspaceConversationCatalogOperationsV2.listConversations({
            config: {
              ...config,
              projectId: item.project_id,
              workspaceId,
            },
            workspaceId: workspaceId || null,
            unboundOnly: !workspaceId,
          });
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
  openMyWorkSessionRef.current = (item) => void openMyWorkSession(item);

  const openAgentSession = async (conversationId: string) => {
    const projectId = config.projectId;
    const workspaceId = config.workspaceId;
    const expectedContextRevision = contextRevisionRef.current;
    const expectedScopeEpoch = configScopeEpochRef.current;
    if (!conversationId || !projectId || !workspaceId) {
      setError(t('myWork.sessionUnavailable'));
      return;
    }
    let conversation = (dataset.conversationsByWorkspace[workspaceId] ?? []).find(
      (candidate) => candidate.id === conversationId,
    );
    if (!conversation) {
      try {
        const response =
          await desktopWorkspaceConversationCatalogOperationsV2.listConversations({
            config: {
              ...config,
              projectId,
              workspaceId,
            },
            workspaceId,
            unboundOnly: false,
          });
        conversation = response.items.find((candidate) => candidate.id === conversationId);
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
      conversation.project_id !== projectId ||
      conversation.tenant_id !== config.tenantId ||
      conversation.workspace_id !== workspaceId
    ) {
      setError(t('myWork.sessionUnavailable'));
      return;
    }
    selectConversation(projectId, workspaceId, conversation, 'chat');
  };

  const createBoardWorkbenchViewV2 = (): DesktopWorkbenchViewV2 => ({
    kind: 'board',
    myWorkQueue: {
      items: dataset.myWork,
      error: dataset.myWorkError,
      loading: connection === 'loading' || myWorkRefreshing,
      mode: preferredTaskMode,
      projectName: selectedProject?.name ?? selectedProject?.id ?? t('overview.none'),
      workspaceLabels: myWorkWorkspaceLabels,
      onRefresh: () => void refreshMyWork(),
      onOpenSession: (item) => void openMyWorkSession(item),
    },
  });

  const createActivityWorkbenchViewV2 = (): DesktopWorkbenchViewV2 => ({
    kind: 'activity',
    activityInbox: {
      groups: activityInbox.groups,
      isEntryRead: activityInbox.isEntryRead,
      unreadCount: activityInbox.unreadCount,
      error: dataset.myWorkError,
      loading: connection === 'loading' || myWorkRefreshing,
      projectName: selectedProject?.name ?? selectedProject?.id ?? t('overview.none'),
      workspaceLabels: myWorkWorkspaceLabels,
      onRefresh: () => void refreshMyWork(),
      onOpen: (entry) => {
        activityInbox.markRead(entry.id);
        void openMyWorkSession(entry.item);
      },
      onMarkRead: activityInbox.markRead,
      onMarkAllRead: activityInbox.markAllRead,
    },
  });

  const createHomeWorkbenchViewV2 = (): DesktopWorkbenchViewV2 => {
    const newThreadComposerScopeKey = [
      config.mode,
      config.apiBaseUrl,
      config.tenantId,
      config.projectId,
      auth.user?.user_id ?? '',
    ].join('\u0000');
    const workspace = newThreadWorkspaces.find((item) => item.id === newThreadWorkspaceId) ?? null;
    const workspaceModelOptions =
      preferredTaskMode === 'code'
        ? workspaceAgentPolicy.codeModelOptions
        : workspaceAgentPolicy.workModelOptions;
    const modelOptions = newThreadWorkspaceId
      ? workspaceModelOptions
      : projectRuntimeModelOptions(workspaceAgentPolicy.providers, config.mode);
    const policyUnavailable = Boolean(newThreadWorkspaceId && workspaceAgentPolicy.error);
    const modelUnavailable = Boolean(
      newThreadWorkspaceId && workspaceAgentPolicy.policy && workspaceModelOptions.length === 0,
    );
    const unboundTransportUnavailable =
      !newThreadWorkspaceId && config.mode === 'cloud' && connection !== 'ready';
    return {
      kind: 'home',
      newThreadComposer: {
        scopeKey: newThreadComposerScopeKey,
        composer: {
          api: desktopNewThreadComposerCatalogClientV2.client,
          workspaceId: newThreadWorkspaceId,
          workspace,
          workspaces: newThreadWorkspaces,
          conversations:
            dataset.conversationsByWorkspace[newThreadWorkspaceId || UNBOUND_CONVERSATIONS_KEY] ??
            [],
          mode: preferredTaskMode,
          policy: workspaceAgentPolicy.policy,
          modelOptions,
          canManagePolicy: canManageWorkspacePolicy && !workspaceAgentPolicy.compatibilityMode,
          loadingPolicy: workspaceAgentPolicy.loading,
          compatibilityMode: Boolean(newThreadWorkspaceId) && workspaceAgentPolicy.compatibilityMode,
          disabledReason:
            newTaskDisabledReason ??
            (unboundTransportUnavailable
              ? t('task.liveConnectionRequired')
              : policyUnavailable
                ? t('task.policyUnavailable')
                : modelUnavailable
                  ? t('task.noModelsAvailable')
                  : null),
          creating: newThreadCreating,
          error: newThreadError,
          onModeChange: setPreferredTaskMode,
          onWorkspaceChange: changeNewThreadWorkspace,
          onCreate: (input) => void createComposerThread(input),
          onOpenThread: (conversation) =>
            selectConversation(config.projectId, newThreadWorkspaceId, conversation, 'chat'),
          onManageModels: () => {
            setSettingsInitialSection('models');
            setSettingsWindowOpen(true);
          },
        },
      },
    };
  };

  const desktopSessionCanvasInputV2: DesktopSessionCanvasInputV2 = {
    actions: {
      onAddChangeComment: handleAddChangeComment,
      onApprovePlan: approveSessionPlan,
      onArtifactAction: handleArtifactAction,
      onAuthorityAction:
        sessionProjectionState.status === 'error' ? invalidateSessionAuthority : undefined,
      onChangeScope: setChangeScope,
      onCloseMCPAppCanvasTab: (tabId) => {
        setMCPAppCanvasState((current) => {
          const next = closeMCPAppCanvasTab(current, tabId);
          mcpAppCanvasStateRef.current = next;
          return next;
        });
      },
      onOpenAgentSession: (conversationId) => void openAgentSession(conversationId),
      onRefreshChanges: () => void loadRunChanges(),
      onRemoveChangeComment: handleRemoveChangeComment,
      onRespondToHitl: respondToHitlWithSteering,
      onResumeTaskListReview: resumeSessionTaskListReview,
      onSelectArtifactCanvasTab: (artifactId) => {
        setArtifactCanvasState((current) => {
          const next = selectArtifactCanvasTab(current, artifactId);
          artifactCanvasStateRef.current = next;
          return next;
        });
      },
      onSelectMCPAppCanvasTab: (tabId) => {
        setMCPAppCanvasState((current) => {
          const next = selectMCPAppCanvasTab(current, tabId);
          mcpAppCanvasStateRef.current = next;
          return next;
        });
      },
      onSendChangeComments: handleSendChangeComments,
      onSendMCPAppMessage: (message) => sendChatMessage(message, []),
      onStartTerminal: () => void startTerminal(),
      onTabChange: setReviewTab,
      onTerminalInput: terminalProxy.sendInput,
      onTerminalResize: terminalProxy.resize,
      onToggleChangeReference: (reference) =>
        setRunInputReferences((current) => toggleRunInputReference(current, reference)),
    },
    meta: {
      artifactClient: desktopArtifactClientV2,
      mcpAppApi: api,
      mcpAppProjectId: config.projectId,
      mcpAppSandboxProxyUrl: desktopMCPAppSandboxProxyUrl(config.apiBaseUrl),
      sandboxRuntime,
      terminalInteractiveCapability,
    },
    state: {
      activeTab: reviewTab,
      approvalRequests: displaySessionProjection?.pendingHitl ?? [],
      artifactActionPending,
      artifactCanvas: artifactCanvasState,
      artifactDeliveries: displaySessionProjection?.artifactDeliveries ?? [],
      artifacts: workspaceArtifacts,
      artifactVersions: displaySessionProjection?.artifactVersions ?? [],
      authorityNotice: sessionAuthorityNotice,
      availableChangeScopes,
      canResumeTaskListReview:
        displaySessionProjection?.planAuthority.kind === 'agent_task_list' &&
        sessionTaskListPlanRecovery?.canResume === true,
      capabilityMode: sessionDetailViewModel?.capabilityMode ?? 'unavailable',
      changeComments: commentsForConversation(
        changeCommentsByConversation,
        changeSnapshot?.conversation_id,
      ),
      changeReferences: runInputReferences,
      changeScope,
      changeSnapshot,
      changeSnapshotError,
      changeSnapshotLoading,
      currentPlan: displaySessionProjection?.currentPlan ?? null,
      currentRun: currentArtifactRun,
      currentRunId: sessionDetailViewModel?.runId ?? null,
      mcpAppCanvas: mcpAppCanvasState,
      respondableHitlRequestIds,
      sessionCapabilities: sessionProjection?.capabilities ?? null,
      sessionDataAvailable: displaySessionProjection !== null,
      sessionPlanApprovalPending,
      sessionViewModel: sessionDetailViewModel,
      socketEvents: workspaceEventInputs,
      taskListPlanTasks:
        displaySessionProjection?.planAuthority.kind === 'agent_task_list'
          ? displaySessionProjection.tasks
          : [],
      terminal,
      terminalBinding,
      terminalBusy: sandboxBusy,
      terminalError: terminalProxy.error,
      terminalLines: terminalProxy.lines,
      timelineItems: conversationTimeline.items,
      toolInvocations: displaySessionProjection?.toolInvocations ?? [],
    },
  };

  const selectDesktopWorkbenchViewV2 = (): DesktopWorkbenchViewV2 => {
    if (!showRuntimeConfig) return createWorkspaceWorkbenchViewV2();
    if (activeSection === 'workspace') return createWorkspaceWorkbenchViewV2();
    if (activeSection === 'chat') return createChatWorkbenchViewV2();
    if (activeSection === 'board') return createBoardWorkbenchViewV2();
    if (activeSection === 'activity') return createActivityWorkbenchViewV2();
    if (activeSection === 'home') return createHomeWorkbenchViewV2();
    return createWorkspaceWorkbenchViewV2();
  };

  if (auth.status === 'password_change_required' || auth.status === 'changing_password') {
    return (
      <Theme
        appearance={themeAppearance}
        accentColor="cyan"
        grayColor="slate"
        radius="medium"
        scaling="95%"
      >
        <ForcePasswordChangeScreen
          busy={auth.status === 'changing_password'}
          error={auth.error}
          onSubmit={(currentPassword, newPassword) =>
            void submitForcedPasswordChange(currentPassword, newPassword)
          }
          onSignOut={cancelForcedPasswordChange}
        />
      </Theme>
    );
  }

  if (!identityAuthenticated) {
    const authenticationPassthroughRouteIds = invitationSignInRequested
      ? new Set([DEVICE_APPROVAL_ROUTE_ID])
      : AUTHENTICATION_PASSTHROUGH_ROUTE_IDS;
    return (
      <DesktopRendererGenerationProviderV2 value={desktopRendererGenerationV2}>
        <Theme
          appearance={themeAppearance}
          accentColor="cyan"
          grayColor="slate"
          radius="medium"
          scaling="95%"
        >
          <DesktopRendererAuthenticationRouterV2
            authenticationPassthroughRouteIds={authenticationPassthroughRouteIds}
            forceLegacyChildren={invitationSignInRequested}
            location={desktopProductionRouteLocation}
            mode={desktopProductionRouteAuthorityV2.mode}
            navigation={desktopProductionRouteNavigation}
            permissions={desktopProductionRouteAuthorityV2.permissions}
            resolveCapability={desktopProductionRouteAuthorityV2.resolveCapability}
            resolvePermissionSnapshot={
              desktopProductionRouteAuthorityV2.resolvePermissionSnapshot
            }
            switchScope={switchProductionRouteScope}
          >
            <LoginScreen
              auth={auth}
              mode={config.mode}
              localReady={localRuntimeAuthorityReady}
              localModeAvailable={runsInNativeDesktop}
              email={loginEmail}
              password={loginPassword}
              onModeChange={changeLoginMode}
              onEmailChange={setLoginEmail}
              onPasswordChange={setLoginPassword}
              onEmailLogin={(trustedDevice) => void login(trustedDevice)}
              onLocalSession={(trustedDevice) => void loginLocalSession(trustedDevice)}
              onWorkspaceSso={(trustedDevice) => void loginWithWorkspaceSso(trustedDevice)}
              nativeOAuthProviders={nativeOAuthProviders}
              nativeOAuthPendingProvider={nativeOAuthPendingProvider}
              onNativeOAuth={beginNativeOAuth}
              workspaceSso={workspaceSso}
              onOpenWorkspaceSso={openCurrentWorkspaceSso}
              onCancelWorkspaceSso={cancelWorkspaceSso}
            />
          </DesktopRendererAuthenticationRouterV2>
        </Theme>
      </DesktopRendererGenerationProviderV2>
    );
  }

  const desktopWorkbenchSurfaceViewModelV2: DesktopWorkbenchSurfaceViewModelV2 = {
    error: error
      ? {
          message: error,
          onRetry:
            connection === 'error' && showRuntimeConfig
              ? () => {
                  workbenchRef.current?.focus();
                  void refreshRuntime();
                }
              : null,
        }
      : null,
    paneStageClassName,
    session:
      activeSection === 'chat' && sessionDetailViewModel
        ? {
            viewModel: sessionDetailViewModel,
            onOpenCanvas: handleOpenCanvas,
            runActionPending: sessionRunActionPending,
            liveConnected: socket.connected,
            liveError: socket.error,
            onRunAction: (action, feedback) => void handleSessionRunAction(action, feedback),
            onOpenTask: sessionDetailViewModel.linkedTaskId
              ? () => {
                  setSelectedTaskId(sessionDetailViewModel.linkedTaskId!);
                  switchSection('board');
                }
              : undefined,
            onRenameConversation: scopedConversation
              ? (title) =>
                  renameConversation(
                    config.projectId,
                    config.workspaceId,
                    scopedConversation,
                    title,
                  )
              : undefined,
            onDeleteConversation: scopedConversation
              ? () => deleteConversation(config.projectId, config.workspaceId, scopedConversation)
              : undefined,
          }
        : null,
    view: selectDesktopWorkbenchViewV2(),
  };

  const activeTenantName =
    auth.tenants.find((tenant) => tenant.id === config.tenantId)?.name ||
    config.tenantId ||
    t('settings.noTenantSelected');
  const activeProjectName =
    selectedProject?.name ?? selectedProject?.id ?? t('settings.noProjectSelected');
  const desktopAuthenticatedShellViewModelV2: DesktopAuthenticatedShellViewModelV2 = {
    meta: {
      appearance: themeAppearance,
      appShellRef,
      generation: desktopRendererGenerationV2.meta,
      workbenchRef,
    },
    state: {
      layoutMode: activeSection === 'board' ? 'my-work' : 'default',
      sidebarCollapsed,
      sidebarPreferredWidth: sidebarPanelWidth.width,
      windowMode: runsInNativeDesktop ? 'native' : 'browser',
    },
    surfaces: {
      titlebar: runsInNativeDesktop
        ? {
            kind: 'visible',
            props: {
              contextTitle: `${activeTenantName} · ${activeProjectName}`,
              sidebarCollapsed,
              rightSidebarOpen,
              rightSidebarAvailable,
              onToggleSidebar: () => setSidebarCollapsed((collapsed) => !collapsed),
              onToggleRightSidebar: () => {
                if (!rightSidebarAvailable) return;
                setRightSidebarOpen((open) => !open);
              },
            },
          }
        : { kind: 'hidden' },
      sidebar: {
        props: {
          activeSection:
            activeSection === 'board'
              ? 'my-work'
              : activeSection === 'home' || activeSection === 'activity'
                ? activeSection
                : null,
          taskCount: dataset.myWork.length,
          activityUnreadCount: activityInbox.unreadCount,
          conversationStatusSummary,
          tenantName: activeTenantName,
          projectName: activeProjectName,
          user: auth.user,
          workspaces: dataset.workspacesByProject[config.projectId] ?? [],
          conversationsByWorkspace: dataset.conversationsByWorkspace,
          nodeState: dataset.nodeState,
          currentProjectId: config.projectId,
          currentWorkspaceId: config.workspaceId,
          currentConversationId: selectedConversation?.id ?? null,
          workspaceTreeSelectionMode:
            activeSection === 'workspace'
              ? 'overview'
              : activeSection === 'chat'
                ? 'conversation'
                : activeSection === 'board'
                  ? 'my-work'
                  : 'none',
          expandedWorkspaceIds,
          newTaskDisabledReason,
          onNavigate: (section) => {
            if (section === 'home') switchSection('home');
            if (section === 'my-work') switchSection('board');
            if (section === 'activity') switchSection('activity');
          },
          onOpenFeatureDirectory: (trigger) => openCommandPalette(trigger),
          onToggleWorkspace: toggleWorkspace,
          onRetryProject: () => void refreshRuntime(),
          onRetryWorkspace: (workspaceId) => void loadWorkspaceConversations(workspaceId),
          onSelectWorkspace: (projectId, workspaceId) =>
            selectWorkspace(workspaceId, projectId),
          onSelectConversation: selectConversation,
          onRenameConversation: renameConversation,
          onDeleteConversation: deleteConversation,
          workspaceCreateDisabledReason,
          onCreateWorkspace: () => setWorkspaceCreateOpen(true),
          onNewTask: startNewSession,
          onOpenAccountSettings: openSidebarSettings,
          onSwitchWorkspace: openProfileWorkspaceSettings,
          onSignOut: () => void logout(),
        },
        resizeHandle: sidebarCollapsed
          ? { kind: 'hidden' }
          : {
              kind: 'visible',
              props: {
                side: 'trailing',
                width: sidebarPanelWidth.width,
                constraints: SIDEBAR_WIDTH_CONSTRAINTS,
                label: t('layout.resizeSidebar'),
                onResize: sidebarPanelWidth.resize,
                onReset: sidebarPanelWidth.reset,
              },
            },
      },
      tabBar: {
        tabs: openTabs,
        activeTabKey: activeWorkbenchTabKey,
        onActivate: activateWorkbenchTab,
        onClose: closeWorkbenchTab,
      },
      router: {
        authenticationPassthroughRouteIds: AUTHENTICATION_PASSTHROUGH_ROUTE_IDS,
        location: desktopProductionRouteLocation,
        mode: desktopProductionRouteAuthorityV2.mode,
        navigation: desktopProductionRouteNavigation,
        permissions: desktopProductionRouteAuthorityV2.permissions,
        resolveCapability: desktopProductionRouteAuthorityV2.resolveCapability,
        resolvePermissionSnapshot:
          desktopProductionRouteAuthorityV2.resolvePermissionSnapshot,
        switchScope: switchProductionRouteScope,
        viewModel: desktopWorkbenchSurfaceViewModelV2,
      },
      rightSidebar:
        rightSidebarAvailable && rightSidebarOpen
          ? {
              kind: 'visible',
              props: {
                activePanel: activeRightPanel,
                canvas: showReviewPanel
                  ? { kind: 'available', input: desktopSessionCanvasInputV2 }
                  : { kind: 'unavailable' },
                viewModel: sessionDetailViewModel,
                runActionPending: sessionRunActionPending,
                onRunAction: (action, feedback) =>
                  void handleSessionRunAction(action, feedback),
                onOpenCanvas: handleOpenCanvas,
                onSelectPanel: handleSelectRightPanel,
                onCloseCanvas: handleCloseCanvas,
                onClose: () => setRightSidebarOpen(false),
              },
            }
          : { kind: 'hidden' },
      statusBar: {
        connection,
        liveConnected: socket.connected,
        liveError: socket.error,
        tenantName: activeTenantName,
        projectName: activeProjectName,
      },
      commandPalette: commandPaletteOpen
        ? {
            kind: 'visible',
            props: {
              inputRef: commandInputRef,
              query: commandQuery,
              items: filteredCommandItems,
              onQueryChange: setCommandQuery,
              onClose: closeCommandPalette,
            },
          }
        : { kind: 'hidden' },
      keyboardShortcuts: {
        open: shortcutsDialogOpen,
        onClose: () => setShortcutsDialogOpen(false),
      },
      newTask: {
        open: newTaskOpen,
        config,
        actorId: auth.user?.user_id,
        newTaskFlowClientV2: desktopNewTaskFlowClientV2,
        workspaceAuthority: newTaskWorkspaceAuthority,
        resumeDraft: newTaskResumeDraft,
        preferredWorkspaceId: newTaskPreferredWorkspaceId,
        preferredKind: preferredTaskMode === 'code' ? 'programming' : 'general',
        disabledReason: newTaskDisabledReason,
        onClose: () => {
          setNewTaskOpen(false);
          setNewTaskResumeDraft(null);
        },
        onSessionPersisted: persistNewTaskSession,
        onSessionReady: activateNewTaskSession,
        onRunAgentTurn: runNewTaskAgentTurn,
        onOpenRuntimeSettings: () => {
          setNewTaskOpen(false);
          setNewTaskResumeDraft(null);
          openConnectionSettings();
        },
        onError: setError,
      },
      workspaceCreate: {
        open: workspaceCreateOpen,
        projectName:
          selectedProject?.name ?? selectedProject?.id ?? t('settings.noProjectSelected'),
        scope: {
          tenantId: config.tenantId,
          projectId: config.projectId,
          epoch: configScopeEpochRef.current,
          contextRevision: contextRevisionRef.current,
        },
        onOpenChange: setWorkspaceCreateOpen,
        onCreate: createWorkspaceFromDialog,
      },
      workspaceSettings: {
        open: workspaceSettingsOpen,
        workspace: selectedWorkspace,
        agents: dataset.workspaceAgents,
        members: dataset.workspaceMembers,
        actorUserId: auth.user?.user_id ?? '',
        scope: {
          tenantId: config.tenantId,
          projectId: config.projectId,
          workspaceId: config.workspaceId,
          epoch: configScopeEpochRef.current,
          contextRevision: contextRevisionRef.current,
        },
        onOpenChange: setWorkspaceSettingsOpen,
        onSave: updateWorkspaceFromDialog,
        onAddMember: addWorkspaceMemberFromDialog,
        onUpdateMemberRole: updateWorkspaceMemberRoleFromDialog,
        onRemoveMember: removeWorkspaceMemberFromDialog,
        onLoadAgentDefinitions: loadWorkspaceAgentDefinitionsFromDialog,
        onBindAgent: bindWorkspaceAgentFromDialog,
        onUnbindAgent: unbindWorkspaceAgentFromDialog,
      },
      settings: {
        open: settingsWindowOpen,
        initialSection: settingsInitialSection,
        auth,
        config,
        connection,
        wsConnected: socket.connected,
        wsError: socket.error,
        runtimeDisabledReason,
        agentDefinitionEvent,
        rendererRouteRegistry: desktopProductionRouteRegistry,
        pluginMarketplaceOperationsV2: desktopPluginMarketplaceOperationsV2,
        onClose: () => {
          const closeRoute = settingsRouteCloseNavigationRef.current;
          settingsRouteCloseNavigationRef.current = null;
          setSettingsWindowOpen(false);
          closeRoute?.();
        },
        onConfigChange: handleConfigChange,
        onRuntimeStatusRefresh: refreshLocalRuntimeStatus,
        onRefreshRuntime: () => void refreshRuntime(),
        onContextChange: applySettingsContext,
        onSignOut: () => void logout(),
      },
    },
  };

  return (
    <DesktopRendererGenerationProviderV2 value={desktopRendererGenerationV2}>
      <DesktopRendererAuthenticatedShellV2
        viewModel={desktopAuthenticatedShellViewModelV2}
      />
    </DesktopRendererGenerationProviderV2>
  );
}
