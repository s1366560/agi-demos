import { useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceStore } from '@/stores/workspace';

import { useBlackboardPageActions } from '@/hooks/useBlackboardActions';
import { useBlackboardLifecycle } from '@/hooks/useBlackboardLifecycle';
import { useBlackboardSSE } from '@/hooks/useBlackboardSSE';

import {
  resolveBlackboardTab,
  syncBlackboardTabSearchParam,
} from '@/pages/project/blackboardRouteUtils';
import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';

import { BlackboardErrorBoundary } from '@/components/blackboard/BlackboardErrorBoundary';
import { NON_AUTHORITATIVE } from '@/components/blackboard/blackboardSurfaceContract';
import type { BlackboardTab } from '@/components/blackboard/BlackboardTabBar';
import { CentralBlackboardContent } from '@/components/blackboard/CentralBlackboardContent';
import { SensingSurfaceBadge } from '@/components/blackboard/SensingSurfaceBadge';

function LoadingShell() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-full min-h-[420px] items-center justify-center rounded-lg border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt"
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
  const planRefreshToken = useWorkspaceStore((state) =>
    selectedWorkspaceId ? (state.planRefreshCounters[selectedWorkspaceId] ?? 0) : 0
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

  const {
    handleCreatePost,
    handleCreateReply,
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
      <div className="flex h-full min-h-0 flex-col bg-background-light p-4 dark:bg-background-dark sm:p-6">
        <LoadingShell />
      </div>
    );
  }

  if (workspacesError) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-background-light p-4 dark:bg-background-dark sm:p-6">
        <div className="rounded-2xl border border-error/25 bg-error/10 p-6 text-sm leading-7 text-status-text-error dark:text-status-text-error-dark">
          <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('common.error', 'Error')}
          </div>
          <p className="mt-2 break-words text-status-text-error dark:text-status-text-error-dark">
            {workspacesError}
          </p>
        </div>
      </div>
    );
  }

  if (workspaces.length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col justify-center bg-background-light p-4 dark:bg-background-dark sm:p-6">
        <div className="rounded-2xl border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark-alt">
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
      <div className="flex h-full min-h-0 flex-col gap-4 bg-background-light p-4 dark:bg-background-dark sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 sm:flex-nowrap">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-semibold text-text-primary dark:text-text-inverse sm:text-xl">
              {t('blackboard.title', 'Blackboard')}
            </h1>
            <div className="mt-1 truncate text-sm text-text-secondary dark:text-text-muted">
              {selectedWorkspace?.name ??
                t(
                  'blackboard.modalSubtitle',
                  'Shared goals, tasks, discussions, and topology for the active workspace.'
                )}
            </div>
            <div className="mt-1 text-xs text-text-muted dark:text-text-muted">
              {t(
                'blackboard.shellHint',
                'Blackboard hosts collaboration and projected workspace views; execution authority remains on tasks, attempts, and runtime.'
              )}
            </div>
            <div className="mt-2">
              <SensingSurfaceBadge
                labelKey="blackboard.shellSensingHint"
                fallbackLabel="workspace shell sync"
              />
            </div>
          </div>

          <div className="flex w-full items-center sm:w-auto sm:min-w-[260px]">
            <label htmlFor="workspace-select" className="sr-only">
              {t('blackboard.workspaceLabel', 'Workspace')}
            </label>
            <select
              id="workspace-select"
              value={selectedWorkspaceId ?? ''}
              onChange={(event) => {
                setSelectedWorkspaceId(event.target.value || null);
              }}
              className="min-h-11 w-full rounded-md border border-border-light bg-surface-light px-4 text-sm normal-case tracking-normal text-text-primary transition focus:border-primary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse"
            >
              {workspaces.map((workspace) => (
                <option
                  key={workspace.id}
                  value={workspace.id}
                  className="bg-surface-light text-text-primary dark:bg-surface-dark dark:text-text-inverse"
                >
                  {workspace.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex w-full flex-wrap items-center gap-3 sm:w-auto sm:flex-nowrap">
            {selectedWorkspaceId ? (
              <Link
                to={agentWorkspacePath}
                className="inline-flex min-h-11 flex-1 items-center justify-center whitespace-nowrap rounded-md border border-border-light bg-surface-light px-5 text-sm font-medium text-text-primary transition motion-reduce:transition-none hover:border-primary/30 hover:bg-primary/5 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse sm:flex-none"
              >
                {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
              </Link>
            ) : (
              <span className="inline-flex min-h-11 flex-1 items-center justify-center whitespace-nowrap rounded-md border border-border-light px-5 text-sm font-medium text-text-muted dark:border-border-dark dark:text-text-muted sm:flex-none">
                {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
              </span>
            )}
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="flex flex-col gap-3 rounded-2xl border border-error/25 bg-error/10 px-4 py-3 text-sm text-status-text-error dark:text-status-text-error-dark sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="break-words">{error}</span>
            <button
              type="button"
              onClick={() => {
                void handleRetrySurface();
              }}
              disabled={surfaceLoading || !selectedWorkspaceId}
              className="min-h-10 rounded-md border border-error/25 bg-surface-light px-4 text-sm font-medium text-status-text-error transition motion-reduce:transition-none hover:bg-error/15 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white/5 dark:text-status-text-error-dark"
            >
              {surfaceLoading ? t('common.loading', 'Loading…') : t('common.retry', 'Retry')}
            </button>
          </div>
        )}

        <div
          className="flex min-h-0 flex-1 flex-col"
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
              planRefreshToken={planRefreshToken}
              agentWorkspacePath={agentWorkspacePath}
              onLoadReplies={handleLoadReplies}
              onCreatePost={handleCreatePost}
              onCreateReply={handleCreateReply}
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
