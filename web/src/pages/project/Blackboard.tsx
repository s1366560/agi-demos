import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceActions, useWorkspaceStore } from '@/stores/workspace';

import { unifiedEventService } from '@/services/unifiedEventService';
import { workspaceService } from '@/services/workspaceService';

import {
  clearBlackboardAutoOpenSearchParam,
  resolveRequestedWorkspaceSelection,
  syncBlackboardWorkspaceSearchParams,
} from '@/pages/project/blackboardRouteUtils';
import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';

import { WorkstationArrangementBoard } from '@/components/blackboard/WorkstationArrangementBoard';
import { useLazyMessage } from '@/components/ui/lazyAntd';

import type { Workspace } from '@/types/workspace';

const CentralBlackboardModal = lazy(() =>
  import('@/components/blackboard/CentralBlackboardModal').then((module) => ({
    default: module.CentralBlackboardModal,
  }))
);

function LoadingShell() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-full min-h-[420px] items-center justify-center rounded-3xl border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt"
    >
      <div className="flex items-center gap-3 text-sm text-text-secondary dark:text-text-muted">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-border-separator border-t-primary" />
        Loading…
      </div>
    </div>
  );
}

export function Blackboard() {
  const { tenantId, projectId } = useParams<{ tenantId: string; projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation();
  const message = useLazyMessage();
  const requestedWorkspaceId = searchParams.get('workspaceId');
  const shouldAutoOpen = searchParams.get('open') === '1';

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
    loadWorkspaceSurface,
    clearSelectedHex,
    createPost,
    loadReplies,
    createReply,
    deletePost,
    pinPost,
    unpinPost,
    deleteReply,
  } = useWorkspaceActions();

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [workspacesError, setWorkspacesError] = useState<string | null>(null);
  const [surfaceLoading, setSurfaceLoading] = useState(false);
  const [boardOpen, setBoardOpen] = useState(false);
  const workspaceListRequestIdRef = useRef(0);
  const requestedWorkspaceIdRef = useRef(requestedWorkspaceId);
  const appliedRequestedWorkspaceIdRef = useRef<string | null>(null);

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? currentWorkspace,
    [currentWorkspace, selectedWorkspaceId, workspaces]
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

  useEffect(() => {
    return () => {
      clearSelectedHex();
    };
  }, [clearSelectedHex]);

  useEffect(() => {
    setBoardOpen(false);
  }, [selectedWorkspaceId]);

  useEffect(() => {
    requestedWorkspaceIdRef.current = requestedWorkspaceId;
  }, [requestedWorkspaceId]);

  const loadWorkspaces = useCallback(async () => {
    if (!tenantId || !projectId) {
      return;
    }

    const requestId = ++workspaceListRequestIdRef.current;
    setWorkspacesLoading(true);
    setWorkspacesError(null);

    try {
      const result = await workspaceService.listByProject(tenantId, projectId);
      if (requestId !== workspaceListRequestIdRef.current) {
        return;
      }
      setWorkspaces(result);
      setSelectedWorkspaceId((current) =>
        requestedWorkspaceIdRef.current &&
          result.some((workspace) => workspace.id === requestedWorkspaceIdRef.current)
          ? requestedWorkspaceIdRef.current
          : result.some((workspace) => workspace.id === current)
            ? current
            : (result[0]?.id ?? null)
      );
    } catch (loadError: unknown) {
      if (requestId !== workspaceListRequestIdRef.current) {
        return;
      }
      setWorkspacesError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      if (requestId === workspaceListRequestIdRef.current) {
        setWorkspacesLoading(false);
      }
    }
  }, [projectId, tenantId]);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  const hydrateSurface = useCallback(async () => {
    if (!tenantId || !projectId || !selectedWorkspaceId) {
      return;
    }

    await loadWorkspaceSurface(tenantId, projectId, selectedWorkspaceId);
  }, [loadWorkspaceSurface, projectId, selectedWorkspaceId, tenantId]);

  useEffect(() => {
    let cancelled = false;

    const loadSurface = async () => {
      setSurfaceLoading(true);
      try {
        await hydrateSurface();
      } catch {
        // The workspace store exposes the load failure via state.error for this page.
      } finally {
        if (!cancelled) {
          setSurfaceLoading(false);
        }
      }
    };

    void loadSurface();

    return () => {
      cancelled = true;
    };
  }, [hydrateSurface]);

  useEffect(() => {
    if (!requestedWorkspaceId) {
      appliedRequestedWorkspaceIdRef.current = null;
      return;
    }

    const nextRequestedWorkspaceId = resolveRequestedWorkspaceSelection(
      requestedWorkspaceId,
      appliedRequestedWorkspaceIdRef.current,
      workspaces
    );
    if (!nextRequestedWorkspaceId) {
      return;
    }

    appliedRequestedWorkspaceIdRef.current = nextRequestedWorkspaceId;
    setSelectedWorkspaceId(nextRequestedWorkspaceId);
  }, [requestedWorkspaceId, workspaces]);

  useEffect(() => {
    if (workspacesLoading || workspaces.length > 0) {
      return;
    }
    if (!searchParams.has('open') && !searchParams.has('workspaceId')) {
      return;
    }

    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.delete('open');
    nextSearchParams.delete('workspaceId');
    setSearchParams(nextSearchParams, { replace: true });
  }, [searchParams, setSearchParams, workspaces, workspacesLoading]);

  useEffect(() => {
    const nextSearchParams = syncBlackboardWorkspaceSearchParams(searchParams, {
      selectedWorkspaceId,
      workspacesLoading,
    });

    if (!nextSearchParams) {
      return;
    }

    setSearchParams(nextSearchParams, { replace: true });
  }, [searchParams, selectedWorkspaceId, setSearchParams, workspacesLoading]);

  useEffect(() => {
    if (
      !shouldAutoOpen ||
      !requestedWorkspaceId ||
      requestedWorkspaceId !== selectedWorkspaceId ||
      surfaceLoading ||
      currentWorkspace?.id !== selectedWorkspaceId
    ) {
      return;
    }

    setBoardOpen(true);

    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.delete('open');
    setSearchParams(nextSearchParams, { replace: true });
  }, [
    currentWorkspace?.id,
    requestedWorkspaceId,
    searchParams,
    selectedWorkspaceId,
    setSearchParams,
    shouldAutoOpen,
    surfaceLoading,
  ]);

  const handleRetrySurface = useCallback(async () => {
    setSurfaceLoading(true);
    try {
      await hydrateSurface();
    } catch {
      // The workspace store exposes the load failure via state.error for this page.
    } finally {
      setSurfaceLoading(false);
    }
  }, [hydrateSurface]);

  useEffect(() => {
    if (!selectedWorkspaceId) {
      return;
    }

    const store = useWorkspaceStore.getState();
    const unsubscribe = unifiedEventService.subscribeWorkspace(selectedWorkspaceId, (event) => {
      const type = event.type;
      const data = event.data as Record<string, unknown>;

      if (type.startsWith('workspace.presence.')) {
        store.handlePresenceEvent({ type, data });
      } else if (type.startsWith('workspace.agent_status.')) {
        store.handleAgentStatusEvent({ type, data });
      } else if (type.startsWith('workspace_task_') || type === 'workspace_task_assigned') {
        store.handleTaskEvent({ type, data });
      } else if (type.startsWith('blackboard_')) {
        store.handleBlackboardEvent({ type, data });
      } else if (type === 'workspace_message_created') {
        store.handleChatEvent({ type, data });
      } else if (type === 'workspace_member_joined' || type === 'workspace_member_left') {
        store.handleMemberEvent({ type, data });
      } else if (type === 'workspace_updated' || type === 'workspace_deleted') {
        store.handleWorkspaceLifecycleEvent({ type, data });
      } else if (type === 'workspace_agent_bound' || type === 'workspace_agent_unbound') {
        store.handleAgentBindingEvent({ type, data });
      } else if (type === 'topology_updated' || type.startsWith('workspace.topology.')) {
        store.handleTopologyEvent({ type, data });
      }
    });

    return () => {
      unsubscribe();
    };
  }, [selectedWorkspaceId]);

  const handleCreatePost = useCallback(
    async (data: { title: string; content: string }) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await createPost(tenantId, projectId, selectedWorkspaceId, data);
        return true;
      } catch (_createError) {
        message?.error(t('blackboard.errors.createPost', 'Failed to create post'));
        return false;
      }
    },
    [createPost, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleCreateReply = useCallback(
    async (postId: string, content: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await createReply(tenantId, projectId, selectedWorkspaceId, postId, { content });
        return true;
      } catch (_createError) {
        message?.error(t('blackboard.errors.createReply', 'Failed to create reply'));
        return false;
      }
    },
    [createReply, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleLoadReplies = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await loadReplies(tenantId, projectId, selectedWorkspaceId, postId);
        return true;
      } catch (_loadError) {
        message?.error(t('blackboard.errors.loadReplies', 'Failed to load replies'));
        return false;
      }
    },
    [loadReplies, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleDeletePost = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await deletePost(tenantId, projectId, selectedWorkspaceId, postId);
        return true;
      } catch (_deleteError) {
        message?.error(t('blackboard.errors.deletePost', 'Failed to delete post'));
        return false;
      }
    },
    [deletePost, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handlePinPost = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return;
      }

      try {
        await pinPost(tenantId, projectId, selectedWorkspaceId, postId);
      } catch (_pinError) {
        message?.error(t('blackboard.errors.pinPost', 'Failed to pin post'));
        return;
      }
    },
    [message, pinPost, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleUnpinPost = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return;
      }

      try {
        await unpinPost(tenantId, projectId, selectedWorkspaceId, postId);
      } catch (_unpinError) {
        message?.error(t('blackboard.errors.unpinPost', 'Failed to unpin post'));
        return;
      }
    },
    [message, projectId, selectedWorkspaceId, t, tenantId, unpinPost]
  );

  const handleDeleteReply = useCallback(
    async (postId: string, replyId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return;
      }

      try {
        await deleteReply(tenantId, projectId, selectedWorkspaceId, postId, replyId);
      } catch (_deleteError) {
        message?.error(t('blackboard.errors.deleteReply', 'Failed to delete reply'));
        return;
      }
    },
    [deleteReply, message, projectId, selectedWorkspaceId, t, tenantId]
  );

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
        <div className="rounded-3xl border border-error/25 bg-error/10 p-6 text-sm leading-7 text-status-text-error dark:text-status-text-error-dark">
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
        <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark-alt">
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 bg-background-light p-4 dark:bg-background-dark sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl min-w-0">
          <div className="text-[11px] uppercase tracking-[0.34em] text-primary/75 dark:text-primary/80">
            {t('blackboard.pageEyebrow', 'Project operations board')}
          </div>
          <h1 className="mt-2 text-3xl font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.title', 'Blackboard')}
          </h1>
          <p className="mt-3 text-sm leading-7 text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.pageDescription',
              'A central command layer for your current workspace: shared goals, task execution, discussions, notes, and team topology in one place.'
            )}
          </p>
        </div>

        <div className="flex w-full flex-col gap-3 sm:flex-row lg:w-auto lg:items-end">
          <label className="flex w-full flex-col gap-2 text-xs uppercase tracking-[0.16em] text-text-muted dark:text-text-muted sm:min-w-[260px]">
            {t('blackboard.workspaceLabel', 'Workspace')}
            <select
              value={selectedWorkspaceId ?? ''}
              onChange={(event) => {
                setSelectedWorkspaceId(event.target.value || null);

                if (shouldAutoOpen) {
                  const nextSearchParams = clearBlackboardAutoOpenSearchParam(searchParams);
                  if (!nextSearchParams) {
                    return;
                  }

                  setSearchParams(nextSearchParams, { replace: true });
                }
              }}
              className="min-h-12 rounded-2xl border border-border-light bg-surface-light px-4 text-sm normal-case tracking-normal text-text-primary transition focus:border-primary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse"
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
          </label>

          {selectedWorkspaceId ? (
            <Link
              to={agentWorkspacePath}
              className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-border-light bg-surface-light px-5 text-sm font-medium text-text-primary transition hover:border-primary/30 hover:bg-primary/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse"
            >
              {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
            </Link>
          ) : (
            <span className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-border-light px-5 text-sm font-medium text-text-muted dark:border-border-dark dark:text-text-muted">
              {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
            </span>
          )}

          <button
            type="button"
            onClick={() => {
              setBoardOpen(true);
            }}
            disabled={
              surfaceLoading || !selectedWorkspaceId || currentWorkspace?.id !== selectedWorkspaceId
            }
            className="min-h-12 rounded-2xl bg-primary px-5 text-sm font-medium text-white transition hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('blackboard.openBoard', 'Open central blackboard')}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex flex-col gap-3 rounded-2xl border border-error/25 bg-error/10 px-4 py-3 text-sm text-status-text-error dark:text-status-text-error-dark sm:flex-row sm:items-center sm:justify-between">
          <span className="break-words">{error}</span>
          <button
            type="button"
            onClick={() => {
              void handleRetrySurface();
            }}
            disabled={surfaceLoading || !selectedWorkspaceId}
            className="min-h-10 rounded-2xl border border-error/25 bg-surface-light px-4 text-sm font-medium text-status-text-error transition hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white/5 dark:text-status-text-error-dark"
          >
            {surfaceLoading
              ? t('common.loading', 'Loading…')
              : t('common.retry', 'Retry')}
          </button>
        </div>
      )}

      <div className="flex-1 min-h-0">
        {surfaceLoading ? (
          <LoadingShell />
        ) : (
          <WorkstationArrangementBoard
            tenantId={tenantId ?? ''}
            projectId={projectId ?? ''}
            workspaceId={selectedWorkspaceId ?? currentWorkspace?.id ?? ''}
            workspaceName={selectedWorkspace?.name ?? t('blackboard.title', 'Blackboard')}
            agentWorkspacePath={agentWorkspacePath}
            agents={agents}
            nodes={topologyNodes}
            edges={topologyEdges}
            tasks={tasks}
            onOpenBlackboard={() => {
              setBoardOpen(true);
            }}
          />
        )}
      </div>

      {tenantId &&
        projectId &&
        selectedWorkspaceId &&
        !surfaceLoading &&
        currentWorkspace?.id === selectedWorkspaceId && (
        <Suspense fallback={null}>
          <CentralBlackboardModal
            open={boardOpen}
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
            onClose={() => {
              setBoardOpen(false);
            }}
            onLoadReplies={handleLoadReplies}
            onCreatePost={handleCreatePost}
            onCreateReply={handleCreateReply}
            onDeletePost={handleDeletePost}
            onPinPost={handlePinPost}
            onUnpinPost={handleUnpinPost}
            onDeleteReply={handleDeleteReply}
          />
        </Suspense>
      )}
    </div>
  );
}
