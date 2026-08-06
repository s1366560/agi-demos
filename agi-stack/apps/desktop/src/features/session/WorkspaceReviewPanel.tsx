import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Badge,
  Button,
  Heading,
  IconButton,
  Text,
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
  EnterFullScreenIcon,
  FileTextIcon,
  MixerHorizontalIcon,
  ReloadIcon,
  RocketIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';
import {
  DesktopApiClient,
} from '../../api/client';
import {
  RunChangeScope,
} from '../agent-authority/agentAuthorityTypes';
import {
  type ChatWorkflowTarget,
} from '../chat/ChatPanel';
import {
  DesktopMCPAppCanvas,
} from '../chat/DesktopMCPAppCanvas';
import {
  LiveArtifactCanvas,
} from '../chat/LiveArtifactCanvas';
import {
  type DesktopArtifactClient,
} from '../chat/desktopArtifactClient';
import {
  type LiveArtifactCanvasState,
} from '../chat/artifactCanvasEventModel';
import {
  resolveA2UISurfaceAuthority,
} from '../chat/a2uiSurfaceAuthorityModel';
import {
  type MCPAppCanvasState,
} from '../chat/mcpAppCanvasEventModel';
import {
  SessionEvidenceCanvas,
} from './SessionEvidenceCanvas';
import {
  SessionAgentsCanvas,
} from './SessionAgentsCanvas';
import {
  SessionChangesCanvas,
} from './SessionChangesCanvas';
import {
  SessionContextWindowCanvas,
} from './SessionContextWindowCanvas';
import {
  SessionExecutionGraphCanvas,
} from './SessionExecutionGraphCanvas';
import {
  SessionExecutionInsightsCanvas,
} from './SessionExecutionInsightsCanvas';
import {
  SessionInvocationActivity,
} from './SessionInvocationLedger';
import {
  SessionRuntimeInfrastructureCanvas,
} from './SessionRuntimeInfrastructureCanvas';
import {
  SessionPlanReview,
  SessionTaskListReview,
} from './SessionPlanReview';
import {
  SessionTerminalCanvas,
} from './SessionTerminalCanvas';
import {
  artifactVersionActions,
  currentArtifactVersions,
  deliveryForArtifactVersion,
  type ArtifactVersionAction,
} from './sessionArtifactModel';
import {
  sessionCanvasTabs,
  type SessionCanvasTabId,
} from './sessionCanvasModel';
import {
  ChangeReviewComment,
} from './sessionChangesReviewModel';
import {
  approvalResponseSubmission,
  latestPendingApproval,
  validateApprovalRequest,
} from './sessionDecisionModel';
import {
  artifactEvidenceForCurrentVersions,
} from './sessionEvidenceModel';
import {
  buildSessionInvocationLedger,
  sessionInvocationLedgerSummary,
} from './sessionInvocationLedgerModel';
import {
  buildSessionAgentTree,
} from './sessionAgentTreeModel';
import {
  buildSessionContextWindow,
} from './sessionContextWindowModel';
import {
  buildSessionExecutionGraph,
} from './sessionExecutionGraphModel';
import {
  buildSessionExecutionInsights,
} from './sessionExecutionInsightsModel';
import {
  buildSessionRuntimeInfrastructure,
} from './sessionRuntimeInfrastructureModel';
import {
  type SessionPlanApprovalSelection,
} from './sessionPlanApprovalModel';
import {
  type SessionProjectionCapabilities,
  type SessionProjectionPlan,
  type SessionProjectionTask,
} from './sessionProjectionTypes';
import {
  type TerminalBindingState,
} from './sessionTerminalModel';
import {
  type SessionCapabilityMode,
  type SessionDetailViewModel,
} from './sessionViewModel';
import {
  workspaceReviewPanelChrome,
  type SessionCanvasControls,
} from './workspaceReviewPanelModel';
import {
  type SandboxRuntimeCapability,
} from '../sandbox/sandboxRuntimeClient';
import {
  type SessionSandboxRuntimeSurface,
} from '../sandbox/useSandboxRuntimeSurface';
import {
  useI18n,
} from '../../i18n';
import {
  AgentTimelineItem,
  ChangeSnapshot,
  CodeRangeReference,
  DesktopApprovalRequest,
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
  DesktopToolInvocation,
  HitlResponseSubmission,
  TerminalServiceResponse,
} from '../../types';
import {
  asRecordValue,
  compactArtifactValue,
  formatBytes,
  readStringField,
} from '../../utils/format';
import {
  buildReviewDecisionSummary,
} from './workspaceArtifactModel';
import {
  type ReviewDecisionSummary,
  type ReviewTab,
  type WorkspaceArtifact,
} from '../../appShellTypes';

export function WorkspaceReviewPanel({
  activeTab,
  socketEvents,
  timelineItems,
  artifacts,
  artifactVersions,
  artifactCanvas,
  artifactClient,
  mcpAppCanvas,
  mcpAppApi,
  mcpAppProjectId,
  mcpAppSandboxProxyUrl,
  onSendMCPAppMessage,
  artifactDeliveries,
  toolInvocations,
  currentRun,
  changeSnapshot,
  changeSnapshotLoading,
  changeSnapshotError,
  changeScope,
  availableChangeScopes,
  changeReferences,
  changeComments,
  onAddChangeComment,
  onRemoveChangeComment,
  onSendChangeComments,
  artifactActionPending,
  terminal,
  terminalBinding,
  terminalError,
  terminalLines,
  terminalBusy,
  terminalInteractiveCapability,
  sandboxRuntime,
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
  onSelectArtifactCanvasTab,
  onSelectMCPAppCanvasTab,
  onCloseMCPAppCanvasTab,
  onStartTerminal,
  onTerminalInput,
  onTerminalResize,
  onRefreshChanges,
  onChangeScope,
  onToggleChangeReference,
  onOpenAgentSession,
  onTabChange,
  sessionControls,
}: {
  activeTab: ReviewTab;
  socketEvents: unknown[];
  timelineItems: AgentTimelineItem[];
  artifacts: WorkspaceArtifact[];
  artifactVersions: DesktopArtifactVersion[];
  artifactCanvas: LiveArtifactCanvasState;
  artifactClient: DesktopArtifactClient;
  mcpAppCanvas: MCPAppCanvasState;
  mcpAppApi: DesktopApiClient;
  mcpAppProjectId: string;
  mcpAppSandboxProxyUrl: string;
  onSendMCPAppMessage: (message: string) => void;
  artifactDeliveries: DesktopArtifactDelivery[];
  toolInvocations: DesktopToolInvocation[];
  currentRun: DesktopRun | null;
  changeSnapshot: ChangeSnapshot | null;
  changeSnapshotLoading: boolean;
  changeSnapshotError: string | null;
  changeScope: RunChangeScope;
  availableChangeScopes: readonly RunChangeScope[];
  changeReferences: CodeRangeReference[];
  changeComments: ChangeReviewComment[];
  onAddChangeComment: (comment: ChangeReviewComment) => void;
  onRemoveChangeComment: (commentId: string) => void;
  onSendChangeComments: (comments: ChangeReviewComment[]) => void;
  artifactActionPending: {
    versionId: string;
    action: ArtifactVersionAction;
  } | null;
  terminal: TerminalServiceResponse | null;
  terminalBinding: TerminalBindingState;
  terminalError: string | null;
  terminalLines: string[];
  terminalBusy: boolean;
  terminalInteractiveCapability: SandboxRuntimeCapability;
  sandboxRuntime: SessionSandboxRuntimeSurface;
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
  onSelectArtifactCanvasTab: (artifactId: string) => void;
  onSelectMCPAppCanvasTab: (tabId: string) => void;
  onCloseMCPAppCanvasTab: (tabId: string) => void;
  onStartTerminal: () => void;
  onTerminalInput: (data: string) => boolean | void;
  onTerminalResize: (cols: number, rows: number) => void;
  onRefreshChanges: () => void;
  onChangeScope: (scope: RunChangeScope) => void;
  onToggleChangeReference: (reference: CodeRangeReference) => void;
  onOpenAgentSession: (conversationId: string) => void;
  onTabChange: (tab: ReviewTab) => void;
  sessionControls?: SessionCanvasControls;
}) {
  const { t } = useI18n();
  const [focusedArtifactVersionId, setFocusedArtifactVersionId] = useState<
    string | null
  >(null);
  const sessionTabListRef = useRef<HTMLElement>(null);
  const invocationLedger = useMemo(
    () =>
      buildSessionInvocationLedger(
        timelineItems,
        {
          runId: sessionViewModel?.runId,
          revision: sessionViewModel?.runRevision,
        },
        toolInvocations,
      ),
    [
      sessionViewModel?.runId,
      sessionViewModel?.runRevision,
      timelineItems,
      toolInvocations,
    ],
  );
  const invocationSummary = useMemo(
    () => sessionInvocationLedgerSummary(invocationLedger),
    [invocationLedger],
  );
  const sessionAgentTree = useMemo(
    () => buildSessionAgentTree(timelineItems),
    [timelineItems],
  );
  const sessionExecutionGraph = useMemo(
    () => buildSessionExecutionGraph(timelineItems),
    [timelineItems],
  );
  const sessionExecutionInsights = useMemo(
    () => buildSessionExecutionInsights(timelineItems),
    [timelineItems],
  );
  const sessionContextWindow = useMemo(
    () => buildSessionContextWindow(timelineItems),
    [timelineItems],
  );
  const sessionRuntimeInfrastructure = useMemo(
    () => buildSessionRuntimeInfrastructure(timelineItems),
    [timelineItems],
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
  const a2uiAuthorities = useMemo(
    () =>
      Object.fromEntries(
        artifactCanvas.tabs.flatMap((tab) => {
          if (tab.contentType !== 'a2ui_surface') return [];
          const authority = resolveA2UISurfaceAuthority(
            tab.id,
            timelineItems,
            respondableHitlRequestIds,
          );
          return authority ? [[tab.id, authority] as const] : [];
        }),
      ),
    [artifactCanvas.tabs, respondableHitlRequestIds, timelineItems],
  );
  const reviewDecision = useMemo(
    () => buildReviewDecisionSummary(approvalRequest),
    [approvalRequest],
  );
  const configuredCanvasTabs = useMemo(
    () => sessionCanvasTabs(capabilityMode),
    [capabilityMode],
  );
  const chrome = workspaceReviewPanelChrome(Boolean(sessionControls));
  const tabValue = (tab: ReviewTab): string | undefined => {
    if (tab === 'changes' && changeSnapshot?.status === 'ready') {
      return `+${changeSnapshot.additions} / −${changeSnapshot.deletions}`;
    }
    if (tab === 'activity' && invocationSummary.total)
      return `${invocationSummary.total}`;
    if (tab === 'checks' || tab === 'verification') {
      const failed = checkEvidence.rows.filter((row) => {
        const status = row.status?.toLowerCase();
        return status === 'failed' || status === 'error';
      }).length;
      if (failed) return `${failed} ${t('session.failedShort')}`;
      if (checkEvidence.rows.length) return `${checkEvidence.rows.length}`;
      return checkEvidence.missing.length
        ? t('session.evidence.missing')
        : undefined;
    }
    if (tab === 'artifacts') {
      const artifactIds = new Set([
        ...currentArtifactVersions(artifactVersions).map(
          (version) => version.artifact_id,
        ),
        ...artifactCanvas.tabs.map((tab) => tab.id),
      ]);
      if (artifactIds.size) return `${artifactIds.size}`;
    }
    if (tab === 'apps' && mcpAppCanvas.tabs.length)
      return `${mcpAppCanvas.tabs.length}`;
    if (tab === 'agents' && sessionAgentTree.summary.total) {
      return `${sessionAgentTree.summary.total}`;
    }
    if (tab === 'graph' && sessionExecutionGraph.summary.nodes) {
      return `${sessionExecutionGraph.summary.nodes}`;
    }
    if (tab === 'insights' && sessionExecutionInsights.summary.entries) {
      return `${sessionExecutionInsights.summary.entries}`;
    }
    if (tab === 'context' && sessionContextWindow.current) {
      return `${sessionContextWindow.current.occupancyPct.toFixed(1)}%`;
    }
    if (tab === 'runtime' && sessionRuntimeInfrastructure.summary.resources) {
      return `${sessionRuntimeInfrastructure.summary.resources}`;
    }
    if (tab === 'sources') {
      if (sourceEvidence.rows.length) return `${sourceEvidence.rows.length}`;
      return sourceEvidence.missing.length
        ? t('session.evidence.missing')
        : undefined;
    }
    return undefined;
  };
  const reviewTabs: Array<{
    tab: ReviewTab;
    label: string;
    value?: string;
  }> = [
    ...configuredCanvasTabs.primary.map((tab) => ({
      tab: tab.id,
      label: t(tab.labelKey),
      value: tabValue(tab.id),
    })),
    ...(sessionContextWindow.current
      ? [
          {
            tab: 'context' as const,
            label: t('session.canvasContext'),
            value: `${sessionContextWindow.current.occupancyPct.toFixed(1)}%`,
          },
        ]
      : []),
    ...(sessionRuntimeInfrastructure.events.length
      ? [
          {
            tab: 'runtime' as const,
            label: t('session.canvasRuntime'),
            value: `${sessionRuntimeInfrastructure.summary.resources}`,
          },
        ]
      : []),
    ...(sessionExecutionGraph.activeRun
      ? [
          {
            tab: 'graph' as const,
            label: t('session.canvasGraph'),
            value: `${sessionExecutionGraph.summary.nodes}`,
          },
        ]
      : []),
    ...(sessionExecutionInsights.activeTrace
      ? [
          {
            tab: 'insights' as const,
            label: t('session.canvasInsights'),
            value: `${sessionExecutionInsights.summary.entries}`,
          },
        ]
      : []),
    ...(sessionAgentTree.summary.total
      ? [
          {
            tab: 'agents' as const,
            label: t('session.canvasAgents'),
            value: `${sessionAgentTree.summary.total}`,
          },
        ]
      : []),
    ...(mcpAppCanvas.tabs.length
      ? [
          {
            tab: 'apps' as const,
            label: t('session.canvasApps'),
            value: `${mcpAppCanvas.tabs.length}`,
          },
        ]
      : []),
  ];
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
    const currentIndex = reviewTabs.findIndex(
      (candidate) => candidate.tab === tab,
    );
    if (currentIndex < 0 || reviewTabs.length < 2) return;
    event.preventDefault();
    const nextIndex =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? reviewTabs.length - 1
          : (currentIndex +
              (event.key === 'ArrowLeft' ? -1 : 1) +
              reviewTabs.length) %
            reviewTabs.length;
    const nextTab = reviewTabs[nextIndex];
    selectTab(nextTab.tab);
    sessionTabListRef.current
      ?.querySelector<HTMLButtonElement>(`#${tabId(nextTab.tab)}`)
      ?.focus();
  };
  useEffect(() => {
    const availableTabs = new Set<ReviewTab>(
      [...configuredCanvasTabs.primary, ...configuredCanvasTabs.secondary].map(
        (tab) => tab.id,
      ),
    );
    if (mcpAppCanvas.tabs.length) availableTabs.add('apps');
    if (sessionExecutionGraph.activeRun) availableTabs.add('graph');
    if (sessionExecutionInsights.activeTrace) availableTabs.add('insights');
    if (sessionContextWindow.current) availableTabs.add('context');
    if (sessionRuntimeInfrastructure.events.length)
      availableTabs.add('runtime');
    if (sessionAgentTree.summary.total) availableTabs.add('agents');
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
  }, [
    activeTab,
    configuredCanvasTabs,
    mcpAppCanvas.tabs.length,
    onTabChange,
    sessionAgentTree.summary.total,
    sessionExecutionGraph.activeRun,
    sessionExecutionInsights.activeTrace,
    sessionContextWindow.current,
    sessionRuntimeInfrastructure.events.length,
  ]);

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
                {sessionControls.layout === 'focus' ? (
                  <ColumnsIcon />
                ) : (
                  <EnterFullScreenIcon />
                )}
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
              <Button
                type="button"
                size="1"
                variant="soft"
                onClick={onAuthorityAction}
              >
                {authorityNotice.actionLabel}
              </Button>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'overview' ? (
          <section
            className="session-overview-canvas"
            aria-label={t('session.canvasOverview')}
          >
            <header>
              <span>{t('session.overviewKicker')}</span>
              <h2>
                {sessionViewModel?.title ?? t('session.workspaceOverview')}
              </h2>
              <p>{t('session.overviewDescription')}</p>
            </header>
            <div className="session-overview-metrics">
              <article>
                <span>{t('session.overviewStatus')}</span>
                <strong>
                  {sessionViewModel?.status ?? t('session.notAvailable')}
                </strong>
                <small>
                  {sessionViewModel?.executionMode ?? t('session.notAvailable')}
                </small>
              </article>
              <article>
                <span>{t('session.overviewStage')}</span>
                <strong>
                  {sessionViewModel?.stage ?? t('session.notAvailable')}
                </strong>
                <small>
                  {sessionViewModel?.elapsedLabel ?? t('session.notAvailable')}
                </small>
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
                <small>
                  {sessionViewModel?.usageLabel ?? t('session.notAvailable')}
                </small>
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
                  selectTab(
                    capabilityMode === 'code' ? 'checks' : 'verification',
                  )
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
                <dd>
                  {sessionViewModel?.environmentLabel ??
                    t('session.notAvailable')}
                </dd>
              </div>
              <div>
                <dt>{t('session.overviewModel')}</dt>
                <dd>
                  {sessionViewModel?.modelLabel ?? t('session.notAvailable')}
                </dd>
              </div>
              <div>
                <dt>{t('session.overviewPermission')}</dt>
                <dd>
                  {sessionViewModel?.permissionLabel ??
                    t('session.notAvailable')}
                </dd>
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
            comments={changeComments}
            onRefresh={onRefreshChanges}
            scope={changeScope}
            availableScopes={availableChangeScopes}
            onScopeChange={onChangeScope}
            onToggleReference={onToggleChangeReference}
            onAddComment={onAddChangeComment}
            onRemoveComment={onRemoveChangeComment}
            onSendComments={onSendChangeComments}
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
                  sessionDataAvailable
                    ? t('session.noPlan')
                    : t('session.notAvailable')
                }
                body={
                  sessionDataAvailable
                    ? t('session.noPlanDescription')
                    : (authorityNotice?.description ??
                      t('session.authorityErrorDescription'))
                }
              />
            )}
          </div>
        ) : null}

        {activeTab === 'activity' || activeTab === 'background' ? (
          <SessionInvocationActivity entries={invocationLedger} />
        ) : null}

        {activeTab === 'agents' ? (
          <SessionAgentsCanvas
            model={sessionAgentTree}
            onOpenSession={onOpenAgentSession}
          />
        ) : null}

        {activeTab === 'graph' ? (
          <SessionExecutionGraphCanvas
            model={sessionExecutionGraph}
            onOpenSession={onOpenAgentSession}
          />
        ) : null}

        {activeTab === 'insights' ? (
          <SessionExecutionInsightsCanvas model={sessionExecutionInsights} />
        ) : null}

        {activeTab === 'context' ? (
          <SessionContextWindowCanvas model={sessionContextWindow} />
        ) : null}

        {activeTab === 'runtime' ? (
          <SessionRuntimeInfrastructureCanvas
            model={sessionRuntimeInfrastructure}
          />
        ) : null}

        {activeTab === 'apps' ? (
          <DesktopMCPAppCanvas
            state={mcpAppCanvas}
            api={mcpAppApi}
            projectId={mcpAppProjectId}
            sandboxProxyUrl={mcpAppSandboxProxyUrl}
            onSendMessage={onSendMCPAppMessage}
            onSelect={onSelectMCPAppCanvasTab}
            onClose={onCloseMCPAppCanvasTab}
          />
        ) : null}

        {activeTab === 'artifacts' ? (
          <>
            <LiveArtifactCanvas
              state={artifactCanvas}
              onSelect={onSelectArtifactCanvasTab}
              artifactClient={artifactClient}
              a2uiAuthorities={a2uiAuthorities}
              onRespondToA2UI={onRespondToHitl}
            />
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
          </>
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
            interactiveCapability={terminalInteractiveCapability}
            sandboxRuntime={sandboxRuntime}
            onTerminalInput={onTerminalInput}
            onTerminalResize={onTerminalResize}
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

export function ArtifactLifecyclePanel({
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
  const currentVersions = useMemo(
    () => currentArtifactVersions(versions),
    [versions],
  );
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(
    null,
  );
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  );
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedback, setFeedback] = useState('');

  useEffect(() => {
    if (!focusVersionId) return;
    const focusedVersion = versions.find(
      (version) => version.id === focusVersionId,
    );
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
    if (
      !selectedArtifactId ||
      !currentVersions.some((item) => item.artifact_id === selectedArtifactId)
    ) {
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
  const isPending = Boolean(
    selectedVersion && pending?.versionId === selectedVersion.id,
  );

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
      <section
        className="artifact-lifecycle artifact-lifecycle-empty"
        aria-label={t('artifact.title')}
      >
        <ReviewEmpty
          icon={<ArchiveIcon />}
          title={t('artifact.emptyTitle')}
          body={t('artifact.emptyDescription')}
        />
        {unversionedEvidenceCount ? (
          <p>
            {t('artifact.unversionedEvidence', {
              count: unversionedEvidenceCount,
            })}
          </p>
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
        <nav
          className="artifact-lifecycle-list"
          aria-label={t('artifact.currentVersions')}
        >
          {currentVersions.map((version) => (
            <button
              type="button"
              className={
                version.artifact_id === selectedArtifactId ? 'selected' : ''
              }
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
                      v{version.version} ·{' '}
                      {t(`artifact.status.${version.status}`)}
                    </option>
                  ))}
                </select>
              </label>
            </header>

            <div
              className="artifact-status-track"
              aria-label={t('artifact.lifecycle')}
            >
              {(['ready', 'approved', 'delivered'] as const).map(
                (status, index) => {
                  const reached = artifactStatusReached(
                    selectedVersion.status,
                    status,
                  );
                  return (
                    <span className={reached ? 'reached' : ''} key={status}>
                      {reached ? <CheckCircledIcon /> : <ClockIcon />}
                      <small>0{index + 1}</small>
                      <strong>{t(`artifact.status.${status}`)}</strong>
                    </span>
                  );
                },
              )}
            </div>

            <dl className="artifact-version-facts">
              <div>
                <dt>{t('artifact.location')}</dt>
                <dd title={selectedVersion.path}>
                  {selectedVersion.relative_path}
                </dd>
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
                  void onAction(
                    selectedVersion,
                    'request_changes',
                    feedback.trim(),
                  ).then(() => {
                    setFeedbackOpen(false);
                    setFeedback('');
                  });
                }}
              >
                <label htmlFor="artifact-review-feedback">
                  {t('artifact.feedbackLabel')}
                </label>
                <textarea
                  id="artifact-review-feedback"
                  value={feedback}
                  placeholder={t('artifact.feedbackPlaceholder')}
                  onChange={(event) => setFeedback(event.target.value)}
                />
                <div>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setFeedbackOpen(false)}
                  >
                    {t('session.cancelAction')}
                  </Button>
                  <Button
                    type="submit"
                    disabled={!feedback.trim() || isPending}
                  >
                    {isPending
                      ? t('artifact.submitting')
                      : t('artifact.sendChanges')}
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
          {t('artifact.unversionedEvidence', {
            count: unversionedEvidenceCount,
          })}
        </p>
      ) : null}
    </section>
  );
}

export function artifactDeliveryReceiptPath(receipt: unknown): string {
  if (receipt === null || typeof receipt !== 'object' || Array.isArray(receipt))
    return '';
  const value = receipt as Record<string, unknown>;
  const path = value.relative_path ?? value.path;
  return typeof path === 'string' ? path : '';
}

export function ArtifactEvidenceSection({
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
              ? (readStringField(record, 'label') ??
                readStringField(record, 'id') ??
                readStringField(record, 'kind') ??
                compactArtifactValue(record))
              : compactArtifactValue(item);
            const status = record
              ? readStringField(record, 'status')
              : undefined;
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

export function artifactStatusReached(
  current: DesktopArtifactVersion['status'],
  target: 'ready' | 'approved' | 'delivered',
): boolean {
  const order = {
    draft: 0,
    ready: 1,
    approved: 2,
    delivered: 3,
    superseded: 0,
  };
  return order[current] >= order[target];
}

export function artifactStatusColor(
  status: DesktopArtifactVersion['status'],
): 'gray' | 'cyan' | 'green' | 'amber' {
  if (status === 'delivered') return 'green';
  if (status === 'approved') return 'cyan';
  if (status === 'ready') return 'amber';
  return 'gray';
}

export function ReviewDecisionPanel({
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
  const [submitting, setSubmitting] = useState<
    'approve' | 'request_changes' | null
  >(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const validation = validateApprovalRequest(request);
  const decision = request.decision;
  const statusColor =
    summary.risk === 'High'
      ? 'red'
      : summary.risk === 'Medium'
        ? 'amber'
        : 'gray';

  const submit = async (action: 'approve' | 'request_changes') => {
    if (!canRespond || submitting) return;
    if (action === 'approve' && !validation.canApprove) return;
    if (action === 'request_changes' && !feedback.trim()) return;
    setSubmitting(action);
    setSubmissionError(null);
    try {
      await onRespond(approvalResponseSubmission(request, action, feedback));
    } catch (caught) {
      setSubmissionError(
        caught instanceof Error ? caught.message : t('approval.submitFailed'),
      );
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

        <div
          className="decision-risk-strip"
          aria-label={t('approval.reviewSummary')}
        >
          <div>
            <ActivityLogIcon />
            <span>{t('approval.action')}</span>
            <strong>
              {decision?.action.name ?? t('approval.notProvided')}
            </strong>
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
            <strong className={`risk-${summary.risk.toLowerCase()}`}>
              {summary.risk}
            </strong>
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
          <div
            className="decision-context-grid"
            aria-label={t('approval.riskScope')}
          >
            <div>
              <span>{t('approval.riskRationale')}</span>
              <strong>
                {decision?.risk.rationale ?? t('approval.notProvided')}
              </strong>
            </div>
            <div>
              <span>{t('approval.reversibility')}</span>
              <strong>
                {decision?.reversibility.mode ?? t('approval.notProvided')}
              </strong>
            </div>
            <div>
              <span>{t('approval.recovery')}</span>
              <strong>
                {decision?.reversibility.recovery ?? t('approval.notProvided')}
              </strong>
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
              {t('approval.incomplete', {
                fields: validation.missing.join(', '),
              })}
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
          disabled={
            !canRespond || !validation.canApprove || Boolean(submitting)
          }
          onClick={() => void submit('approve')}
        >
          <CheckCircledIcon />
          <span>
            <strong>
              {submitting === 'approve'
                ? t('approval.submitting')
                : t('approval.approve')}
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
        {submissionError ? (
          <p className="decision-submit-error">{submissionError}</p>
        ) : null}
        <small>{t('approval.authoritativeNotice')}</small>
      </section>
    </div>
  );
}

export function ReviewEmpty({
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

export function chatWorkflowTargetForReviewTab(tab: ReviewTab): ChatWorkflowTarget {
  if (tab === 'pull' || tab === 'checks') return 'pull';
  if (tab === 'background' || tab === 'activity') return 'background';
  if (tab === 'artifacts' || tab === 'apps') return 'artifacts';
  if (tab === 'changes') return 'changes';
  return 'plan';
}
