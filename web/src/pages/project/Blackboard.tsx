import { useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';

import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceStore } from '@/stores/workspace';

import { unifiedEventService } from '@/services/unifiedEventService';
import { workspacePlanService } from '@/services/workspaceService';

import { useBlackboardPageActions } from '@/hooks/useBlackboardActions';
import { useBlackboardLifecycle } from '@/hooks/useBlackboardLifecycle';
import { useBlackboardSSE } from '@/hooks/useBlackboardSSE';

import {
  resolveBlackboardTab,
  syncBlackboardTabSearchParam,
} from '@/pages/project/blackboardRouteUtils';
import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import { logger } from '@/utils/logger';

import { BlackboardDashboardHeader } from '@/components/blackboard/BlackboardDashboardHeader';
import { BlackboardErrorBoundary } from '@/components/blackboard/BlackboardErrorBoundary';
import { NON_AUTHORITATIVE } from '@/components/blackboard/blackboardSurfaceContract';
import type { BlackboardTab } from '@/components/blackboard/BlackboardTabBar';
import { buildBlackboardStats } from '@/components/blackboard/blackboardUtils';
import { CentralBlackboardContent } from '@/components/blackboard/CentralBlackboardContent';

import type {
  Workspace,
  WorkspaceCollaborationMode,
  WorkspacePlan,
  WorkspacePlanRootGoal,
  WorkspaceUseCase,
} from '@/types/workspace';

const DEFAULT_WORKSPACE_USE_CASE: WorkspaceUseCase = 'general';
const DEFAULT_COLLABORATION_MODE: WorkspaceCollaborationMode = 'multi_agent_shared';

function isWorkspaceUseCase(value: unknown): value is WorkspaceUseCase {
  return (
    value === 'programming' ||
    value === 'conversation' ||
    value === 'research' ||
    value === 'operations' ||
    value === 'general'
  );
}

function isWorkspaceCollaborationMode(value: unknown): value is WorkspaceCollaborationMode {
  return (
    value === 'single_agent' ||
    value === 'multi_agent_shared' ||
    value === 'multi_agent_isolated' ||
    value === 'autonomous'
  );
}

function getWorkspaceUseCase(workspace: Workspace | null | undefined): WorkspaceUseCase {
  const direct = workspace?.metadata?.workspace_use_case;
  if (isWorkspaceUseCase(direct)) {
    return direct;
  }
  const type = workspace?.metadata?.workspace_type;
  if (type === 'software_development') {
    return 'programming';
  }
  if (type === 'research' || type === 'operations' || type === 'general') {
    return type;
  }
  return DEFAULT_WORKSPACE_USE_CASE;
}

function getWorkspaceCollaborationMode(
  workspace: Workspace | null | undefined
): WorkspaceCollaborationMode {
  const direct = workspace?.metadata?.collaboration_mode;
  if (isWorkspaceCollaborationMode(direct)) {
    return direct;
  }
  const legacy = workspace?.metadata?.agent_conversation_mode;
  if (isWorkspaceCollaborationMode(legacy)) {
    return legacy;
  }
  return DEFAULT_COLLABORATION_MODE;
}

function LoadingShell() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-full min-h-[420px] items-center justify-center rounded-md border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt"
    >
      <div className="flex items-center gap-3 text-sm text-text-secondary dark:text-text-muted">
        <span
          aria-hidden="true"
          className="h-3 w-3 animate-spin rounded-full border-2 border-border-separator border-t-primary motion-reduce:animate-none"
        />
        {t('common.loading', 'Loading…')}
      </div>
    </div>
  );
}

export function Blackboard() {
  const { tenantId, projectId } = useParams<{ tenantId: string; projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation();
  const requestedWorkspaceId = searchParams.get('workspaceId');
  const activeTab = resolveBlackboardTab(searchParams);

  const {
    currentWorkspace,
    posts,
    repliesByPostId,
    loadedReplyPostIds,
    tasks,
    objectives,
    genes,
    agents,
    topologyNodes,
    topologyEdges,
    error,
  } = useWorkspaceStore(
    useShallow((state) => ({
      currentWorkspace: state.currentWorkspace,
      posts: state.posts,
      repliesByPostId: state.repliesByPostId,
      loadedReplyPostIds: state.loadedReplyPostIds,
      tasks: state.tasks,
      objectives: state.objectives,
      genes: state.genes,
      agents: state.agents,
      topologyNodes: state.topologyNodes,
      topologyEdges: state.topologyEdges,
      error: state.error,
    }))
  );

  const {
    workspaces,
    selectedWorkspaceId,
    setSelectedWorkspaceId,
    workspacesLoading,
    workspacesError,
    surfaceLoading,
    handleRetrySurface,
    handleRetryWorkspaces,
  } = useBlackboardLifecycle({
    tenantId,
    projectId,
    requestedWorkspaceId,
    searchParams,
    setSearchParams,
    currentWorkspaceId: currentWorkspace?.id,
  });

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? currentWorkspace,
    [currentWorkspace, selectedWorkspaceId, workspaces]
  );
  const workspaceUseCaseLabels = useMemo(
    () =>
      ({
        general: t('tenant.workspaceList.typeGeneral', 'General'),
        programming: t('tenant.workspaceList.typeProgramming', 'Programming'),
        conversation: t('tenant.workspaceList.typeConversation', 'Conversation'),
        research: t('tenant.workspaceList.typeResearch', 'Research'),
        operations: t('tenant.workspaceList.typeOperations', 'Operations'),
      }) satisfies Record<WorkspaceUseCase, string>,
    [t]
  );
  const collaborationModeLabels = useMemo(
    () =>
      ({
        single_agent: t('tenant.workspaceList.modeSingle', 'Single'),
        multi_agent_shared: t('tenant.workspaceList.modeShared', 'Shared team'),
        multi_agent_isolated: t('tenant.workspaceList.modeIsolated', 'Isolated'),
        autonomous: t('tenant.workspaceList.modeAutonomous', 'Autonomous'),
      }) satisfies Record<WorkspaceCollaborationMode, string>,
    [t]
  );
  const workspaceUseCase = getWorkspaceUseCase(selectedWorkspace);
  const collaborationMode = getWorkspaceCollaborationMode(selectedWorkspace);
  const planRefreshToken = useWorkspaceStore((state) =>
    selectedWorkspaceId ? (state.planRefreshCounters[selectedWorkspaceId] ?? 0) : 0
  );
  const [loadedStatsPlan, setLoadedStatsPlan] = useState<{
    workspaceId: string;
    plan: WorkspacePlan | null;
    rootGoal: WorkspacePlanRootGoal | null;
  } | null>(null);

  useEffect(() => {
    if (!selectedWorkspaceId) {
      return;
    }

    let cancelled = false;
    workspacePlanService
      .getSnapshot(selectedWorkspaceId, {
        outboxLimit: 0,
        eventLimit: 0,
        includeDetails: false,
        recoverStaleAttempts: false,
      })
      .then((snapshot) => {
        if (!cancelled) {
          setLoadedStatsPlan({
            workspaceId: selectedWorkspaceId,
            plan: snapshot.plan ?? null,
            rootGoal: snapshot.root_goal ?? null,
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadedStatsPlan({ workspaceId: selectedWorkspaceId, plan: null, rootGoal: null });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedWorkspaceId, planRefreshToken]);

  const statsPlan =
    loadedStatsPlan?.workspaceId === selectedWorkspaceId ? loadedStatsPlan.plan : null;
  const statsRootGoal =
    loadedStatsPlan?.workspaceId === selectedWorkspaceId ? loadedStatsPlan.rootGoal : null;
  const shellStats = useMemo(
    () => buildBlackboardStats(tasks, posts, agents, topologyNodes, statsPlan, statsRootGoal),
    [agents, posts, statsPlan, statsRootGoal, tasks, topologyNodes]
  );
  const agentWorkspacePath = useMemo(
    () =>
      buildAgentWorkspacePath({
        tenantId,
        projectId,
        workspaceId: selectedWorkspaceId,
      }),
    [projectId, selectedWorkspaceId, tenantId]
  );

  useBlackboardSSE(selectedWorkspaceId);

  const hasSeenWorkspaceSocketConnectedRef = useRef(false);
  const shouldRefreshWorkspaceOnReconnectRef = useRef(false);
  const reconnectRefreshInFlightRef = useRef(false);

  useEffect(() => {
    if (!selectedWorkspaceId) {
      return;
    }

    hasSeenWorkspaceSocketConnectedRef.current = false;
    shouldRefreshWorkspaceOnReconnectRef.current = false;
    reconnectRefreshInFlightRef.current = false;
    let cancelled = false;

    const refreshCanonicalWorkspaceSurface = () => {
      if (reconnectRefreshInFlightRef.current) {
        return;
      }
      reconnectRefreshInFlightRef.current = true;
      logger.debug('[Blackboard] Refetching workspace surface after websocket reconnect', {
        workspaceId: selectedWorkspaceId,
      });
      void handleRetrySurface()
        .catch((error: unknown) => {
          logger.warn('[Blackboard] Reconnect workspace refetch failed', {
            workspaceId: selectedWorkspaceId,
            error,
          });
        })
        .finally(() => {
          if (!cancelled) {
            reconnectRefreshInFlightRef.current = false;
          }
        });
    };

    const unsubscribeStatus = unifiedEventService.onStatusChange((status) => {
      if (status === 'connected') {
        if (shouldRefreshWorkspaceOnReconnectRef.current) {
          shouldRefreshWorkspaceOnReconnectRef.current = false;
          refreshCanonicalWorkspaceSurface();
        }
        hasSeenWorkspaceSocketConnectedRef.current = true;
        return;
      }

      if (
        hasSeenWorkspaceSocketConnectedRef.current &&
        (status === 'disconnected' || status === 'error')
      ) {
        shouldRefreshWorkspaceOnReconnectRef.current = true;
      }
    });

    return () => {
      cancelled = true;
      unsubscribeStatus();
    };
  }, [handleRetrySurface, selectedWorkspaceId]);

  const {
    handleCreatePost,
    handleCreateReply,
    handleUpdatePost,
    handleUpdateReply,
    handleLoadReplies,
    handleDeletePost,
    handlePinPost,
    handleUnpinPost,
    handleDeleteReply,
  } = useBlackboardPageActions({ tenantId, projectId, selectedWorkspaceId });

  const handleTabChange = (nextTab: BlackboardTab) => {
    const next = syncBlackboardTabSearchParam(searchParams, nextTab);
    if (!next) {
      return;
    }
    setSearchParams(next, { replace: true });
  };

  if (workspacesLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-background-light p-3 dark:bg-background-dark sm:p-4">
        <LoadingShell />
      </div>
    );
  }

  if (workspacesError) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-background-light p-3 dark:bg-background-dark sm:p-4">
        <div
          role="alert"
          className="rounded-md border border-error/25 bg-error/10 p-6 text-sm leading-7 text-status-text-error dark:text-status-text-error-dark"
        >
          <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('common.error', 'Error')}
          </div>
          <p className="mt-2 break-words text-status-text-error dark:text-status-text-error-dark">
            {workspacesError}
          </p>
          <button
            type="button"
            onClick={() => {
              void handleRetryWorkspaces();
            }}
            className="mt-4 min-h-10 rounded-md border border-error/25 bg-surface-light px-4 text-sm font-medium text-status-text-error transition-colors duration-150 hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:bg-white/5 dark:text-status-text-error-dark"
          >
            {t('common.retry', 'Retry')}
          </button>
        </div>
      </div>
    );
  }

  if (workspaces.length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col justify-center bg-background-light p-3 dark:bg-background-dark sm:p-4">
        <div className="rounded-md border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="text-xl font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.noWorkspaces', 'No workspaces found')}
          </div>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.noWorkspacesDescription',
              'Create or attach a workspace first, then the central blackboard will aggregate its tasks, discussions, and topology.'
            )}
          </p>
        </div>
      </div>
    );
  }

  const canRenderBoard =
    !!tenantId &&
    !!projectId &&
    !!selectedWorkspaceId &&
    !surfaceLoading &&
    currentWorkspace?.id === selectedWorkspaceId;

  return (
    <BlackboardErrorBoundary
      fallbackLabel={t('blackboard.errorBoundary.title', 'Something went wrong')}
      retryLabel={t('blackboard.errorBoundary.retry', 'Try again')}
    >
      <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-background-light dark:bg-background-dark md:overflow-hidden">
        <BlackboardDashboardHeader
          selectedWorkspace={selectedWorkspace}
          workspaces={workspaces}
          selectedWorkspaceId={selectedWorkspaceId}
          workspaceUseCaseLabel={workspaceUseCaseLabels[workspaceUseCase]}
          collaborationModeLabel={collaborationModeLabels[collaborationMode]}
          stats={shellStats}
          agentWorkspacePath={agentWorkspacePath}
          onWorkspaceChange={setSelectedWorkspaceId}
        />

        {error && (
          <div
            role="alert"
            className="mx-3 mt-3 flex flex-col gap-3 rounded-md border border-error/25 bg-error/10 px-4 py-3 text-sm text-status-text-error dark:text-status-text-error-dark sm:mx-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="break-words">{error}</span>
            <button
              type="button"
              onClick={() => {
                void handleRetrySurface();
              }}
              disabled={surfaceLoading || !selectedWorkspaceId}
              className="min-h-10 rounded-md border border-error/25 bg-surface-light px-4 text-sm font-medium text-status-text-error transition-colors duration-150 hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white/5 dark:text-status-text-error-dark"
            >
              {surfaceLoading ? t('common.loading', 'Loading…') : t('common.retry', 'Retry')}
            </button>
          </div>
        )}

        <div
          className="flex flex-col px-3 py-3 sm:px-4 md:min-h-0 md:flex-1"
          data-blackboard-surface="shell"
          data-blackboard-authority={NON_AUTHORITATIVE}
        >
          {surfaceLoading || !canRenderBoard ? (
            <LoadingShell />
          ) : (
            <CentralBlackboardContent
              tenantId={tenantId}
              projectId={projectId}
              workspaceId={selectedWorkspaceId}
              workspace={selectedWorkspace}
              posts={posts}
              repliesByPostId={repliesByPostId}
              loadedReplyPostIds={loadedReplyPostIds}
              tasks={tasks}
              objectives={objectives}
              genes={genes}
              agents={agents}
              topologyNodes={topologyNodes}
              topologyEdges={topologyEdges}
              activeTab={activeTab}
              onActiveTabChange={handleTabChange}
              statsPlan={statsPlan}
              statsRootGoal={statsRootGoal}
              planRefreshToken={planRefreshToken}
              agentWorkspacePath={agentWorkspacePath}
              onLoadReplies={handleLoadReplies}
              onCreatePost={handleCreatePost}
              onCreateReply={handleCreateReply}
              onUpdatePost={handleUpdatePost}
              onUpdateReply={handleUpdateReply}
              onDeletePost={handleDeletePost}
              onPinPost={handlePinPost}
              onUnpinPost={handleUnpinPost}
              onDeleteReply={handleDeleteReply}
            />
          )}
        </div>
      </div>
    </BlackboardErrorBoundary>
  );
}
