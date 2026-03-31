import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal } from 'antd';

import { useWorkspaceActions } from '@/stores/workspace';

import { WorkspaceSettingsPanel } from '@/pages/tenant/WorkspaceSettings';

import { useLazyMessage } from '@/components/ui/lazyAntd';
import { ChatPanel } from '@/components/workspace/chat/ChatPanel';
import { GeneList } from '@/components/workspace/genes/GeneList';
import { MemberPanel } from '@/components/workspace/MemberPanel';
import {
  ObjectiveCreateModal,
  type ObjectiveFormValues,
} from '@/components/workspace/objectives/ObjectiveCreateModal';
import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { TaskBoard } from '@/components/workspace/TaskBoard';

import { buildBlackboardNotes, buildBlackboardStats } from './blackboardUtils';
import { StatBadge } from './StatBadge';
import { DiscussionTab } from './tabs/DiscussionTab';
import { StatusTab } from './tabs/StatusTab';
import { TopologyTab } from './tabs/TopologyTab';

import type {
  BlackboardPost,
  BlackboardReply,
  CyberGene,
  CyberObjective,
  TopologyEdge,
  TopologyNode,
  Workspace,
  WorkspaceAgent,
  WorkspaceTask,
} from '@/types/workspace';

export interface CentralBlackboardModalProps {
  open: boolean;
  tenantId: string;
  projectId: string;
  workspaceId: string;
  workspace: Workspace | null;
  posts: BlackboardPost[];
  repliesByPostId: Record<string, BlackboardReply[]>;
  loadedReplyPostIds: Record<string, boolean>;
  tasks: WorkspaceTask[];
  objectives: CyberObjective[];
  genes: CyberGene[];
  agents: WorkspaceAgent[];
  topologyNodes: TopologyNode[];
  topologyEdges: TopologyEdge[];
  onClose: () => void;
  onLoadReplies: (postId: string) => Promise<boolean>;
  onCreatePost: (data: { title: string; content: string }) => Promise<boolean>;
  onCreateReply: (postId: string, content: string) => Promise<boolean>;
  onDeletePost: (postId: string) => Promise<boolean>;
  onPinPost: (postId: string) => Promise<void>;
  onUnpinPost: (postId: string) => Promise<void>;
  onDeleteReply: (postId: string, replyId: string) => Promise<void>;
}

type BlackboardTab =
  | 'goals'
  | 'discussion'
  | 'collaboration'
  | 'members'
  | 'genes'
  | 'files'
  | 'status'
  | 'notes'
  | 'topology'
  | 'settings';

function statusBadgeTone(status: string | undefined): string {
  if (status === 'busy' || status === 'running') return 'bg-success';
  if (status === 'error') return 'bg-error';
  if (status === 'idle') return 'bg-text-muted dark:bg-text-muted';
  return 'bg-warning';
}

export function CentralBlackboardModal({
  open,
  tenantId,
  projectId,
  workspaceId,
  workspace,
  posts,
  repliesByPostId,
  loadedReplyPostIds,
  tasks,
  objectives,
  genes,
  agents,
  topologyNodes,
  topologyEdges,
  onClose,
  onLoadReplies,
  onCreatePost,
  onCreateReply,
  onDeletePost,
  onPinPost,
  onUnpinPost,
  onDeleteReply,
}: CentralBlackboardModalProps) {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const { createObjective, deleteObjective, deleteGene, updateGene } = useWorkspaceActions();
  const tabListRef = useRef<HTMLDivElement | null>(null);

  const [activeTab, setActiveTab] = useState<BlackboardTab>('goals');
  const [selectedPostId, setSelectedPostId] = useState<string | null>(null);
  const [postTitle, setPostTitle] = useState('');
  const [postContent, setPostContent] = useState('');
  const [replyDraft, setReplyDraft] = useState('');
  const [autoReplyRetryBlockedByPostId, setAutoReplyRetryBlockedByPostId] = useState<
    Record<string, boolean>
  >({});
  const [creatingPost, setCreatingPost] = useState(false);
  const [replying, setReplying] = useState(false);
  const [loadingRepliesPostId, setLoadingRepliesPostId] = useState<string | null>(null);
  const [togglingPostId, setTogglingPostId] = useState<string | null>(null);
  const [deletingPostId, setDeletingPostId] = useState<string | null>(null);
  const [deletingReplyId, setDeletingReplyId] = useState<string | null>(null);
  const [showCreateObjective, setShowCreateObjective] = useState(false);
  const [creatingObjective, setCreatingObjective] = useState(false);

  const stats = useMemo(
    () => buildBlackboardStats(tasks, posts, agents, topologyNodes),
    [agents, posts, tasks, topologyNodes]
  );
  const notes = useMemo(
    () => buildBlackboardNotes(workspace, objectives, posts),
    [objectives, posts, workspace]
  );
  const topologyNodeTitles = useMemo(
    () =>
      new Map(
        topologyNodes.map((node) => [
          node.id,
          node.title.trim() ? node.title : t('blackboard.topologyUntitled', 'Untitled node'),
        ])
      ),
    [t, topologyNodes]
  );

  useEffect(() => {
    const fallbackPostId = posts.find((post) => post.is_pinned)?.id ?? posts[0]?.id ?? null;
    const hasSelectedPost = posts.some((post) => post.id === selectedPostId);

    if (!hasSelectedPost && fallbackPostId !== selectedPostId) {
      setSelectedPostId(fallbackPostId);
    }
  }, [posts, selectedPostId]);

  useEffect(() => {
    setReplyDraft('');
  }, [selectedPostId]);

  useEffect(() => {
    if (!open) {
      setAutoReplyRetryBlockedByPostId({});
    }
  }, [open]);

  const handleLoadReplies = useCallback(
    async (postId: string, options?: { manual?: boolean }) => {
      setLoadingRepliesPostId(postId);
      try {
        const loaded = await onLoadReplies(postId);

        if (loaded) {
          setAutoReplyRetryBlockedByPostId((current) => {
            if (!(postId in current)) {
              return current;
            }

            return { ...current, [postId]: false };
          });
          return;
        }

        if (!options?.manual) {
          setAutoReplyRetryBlockedByPostId((current) => ({ ...current, [postId]: true }));
        }
      } finally {
        setLoadingRepliesPostId((current) => (current === postId ? null : current));
      }
    },
    [onLoadReplies]
  );

  useEffect(() => {
    if (
      !open ||
      !selectedPostId ||
      loadedReplyPostIds[selectedPostId] ||
      autoReplyRetryBlockedByPostId[selectedPostId] === true ||
      loadingRepliesPostId === selectedPostId
    ) {
      return;
    }

    void handleLoadReplies(selectedPostId);
  }, [
    autoReplyRetryBlockedByPostId,
    handleLoadReplies,
    loadedReplyPostIds,
    loadingRepliesPostId,
    open,
    selectedPostId,
  ]);

  const selectedPost = posts.find((post) => post.id === selectedPostId) ?? null;

  const tabs = useMemo(
    () =>
      [
        { key: 'goals', label: t('blackboard.tabs.goals', 'Goals / Tasks') },
        { key: 'discussion', label: t('blackboard.tabs.discussion', 'Discussion') },
        { key: 'collaboration', label: t('blackboard.tabs.collaboration', 'Collaboration') },
        { key: 'members', label: t('blackboard.tabs.members', 'Members') },
        { key: 'genes', label: t('blackboard.tabs.genes', 'Genes') },
        { key: 'files', label: t('blackboard.tabs.files', 'Files') },
        { key: 'status', label: t('blackboard.tabs.status', 'Status') },
        { key: 'notes', label: t('blackboard.tabs.notes', 'Notes') },
        { key: 'topology', label: t('blackboard.tabs.topology', 'Topology') },
        { key: 'settings', label: t('blackboard.tabs.settings', 'Settings') },
      ] as const,
    [t]
  );

  const moveTabFocus = useCallback((nextIndex: number) => {
    const nextTab = tabs[nextIndex];
    if (!nextTab) {
      return;
    }

    setActiveTab(nextTab.key);

    requestAnimationFrame(() => {
      const nextButton = tabListRef.current?.querySelector<HTMLButtonElement>(
        `#blackboard-tab-${nextTab.key}`
      );
      nextButton?.focus();
    });
  }, [tabs]);

  const handleTabKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
      const lastIndex = tabs.length - 1;

      if (event.key === 'ArrowRight') {
        event.preventDefault();
        moveTabFocus(index === lastIndex ? 0 : index + 1);
        return;
      }

      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        moveTabFocus(index === 0 ? lastIndex : index - 1);
        return;
      }

      if (event.key === 'Home') {
        event.preventDefault();
        moveTabFocus(0);
        return;
      }

      if (event.key === 'End') {
        event.preventDefault();
        moveTabFocus(lastIndex);
      }
    },
    [moveTabFocus, tabs.length]
  );

  const handleCreatePost = async () => {
    const title = postTitle.trim();
    const content = postContent.trim();
    if (!title || !content) {
      return;
    }

    setCreatingPost(true);
    try {
      const created = await onCreatePost({ title, content });
      if (created) {
        setPostTitle('');
        setPostContent('');
      }
    } finally {
      setCreatingPost(false);
    }
  };

  const handleCreateReply = async () => {
    if (!selectedPost) {
      return;
    }

    const nextContent = replyDraft.trim();
    if (!nextContent) {
      return;
    }

    setReplying(true);
    try {
      const created = await onCreateReply(selectedPost.id, nextContent);
      if (created) {
        setReplyDraft('');
      }
    } finally {
      setReplying(false);
    }
  };

  const handleTogglePin = async () => {
    if (!selectedPost) {
      return;
    }

    setTogglingPostId(selectedPost.id);
    try {
      if (selectedPost.is_pinned) {
        await onUnpinPost(selectedPost.id);
      } else {
        await onPinPost(selectedPost.id);
      }
    } finally {
      setTogglingPostId(null);
    }
  };

  const handleDeleteSelectedPost = async () => {
    if (!selectedPost) {
      return;
    }

    setDeletingPostId(selectedPost.id);
    try {
      const deleted = await onDeletePost(selectedPost.id);
      if (deleted) {
        setSelectedPostId((current) => (current === selectedPost.id ? null : current));
      }
    } finally {
      setDeletingPostId(null);
    }
  };

  const handleDeleteSelectedReply = async (replyId: string) => {
    if (!selectedPost) {
      return;
    }

    setDeletingReplyId(replyId);
    try {
      await onDeleteReply(selectedPost.id, replyId);
    } finally {
      setDeletingReplyId(null);
    }
  };

  const handleCreateObjective = async (values: ObjectiveFormValues) => {
    setCreatingObjective(true);
    try {
      const payload: Parameters<typeof createObjective>[3] = {
        title: values.title,
        obj_type: values.obj_type,
      };

      if (values.description) {
        payload.description = values.description;
      }
      if (values.parent_id) {
        payload.parent_id = values.parent_id;
      }

      await createObjective(tenantId, projectId, workspaceId, payload);
      setShowCreateObjective(false);
    } catch {
      message?.error(t('blackboard.errors.createObjective', 'Failed to create objective'));
    } finally {
      setCreatingObjective(false);
    }
  };

  const handleDeleteObjective = async (objectiveId: string) => {
    try {
      await deleteObjective(tenantId, projectId, workspaceId, objectiveId);
    } catch {
      message?.error(t('blackboard.errors.deleteObjective', 'Failed to delete objective'));
    }
  };

  const handleDeleteGene = async (geneId: string) => {
    try {
      await deleteGene(tenantId, projectId, workspaceId, geneId);
    } catch {
      message?.error(t('blackboard.errors.deleteGene', 'Failed to delete gene'));
    }
  };

  const handleToggleGeneActive = async (geneId: string, isActive: boolean) => {
    try {
      await updateGene(tenantId, projectId, workspaceId, geneId, { is_active: isActive });
    } catch {
      message?.error(t('blackboard.errors.updateGene', 'Failed to update gene'));
    }
  };

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        centered
        destroyOnHidden
        width="min(1440px, calc(100vw - 24px))"
        className="[&_.ant-modal-close]:text-text-muted dark:[&_.ant-modal-close]:text-text-muted [&_.ant-modal-close:hover]:text-text-primary dark:[&_.ant-modal-close:hover]:text-text-inverse [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!border [&_.ant-modal-content]:!border-border-light dark:[&_.ant-modal-content]:!border-border-dark [&_.ant-modal-content]:!bg-surface-light dark:[&_.ant-modal-content]:!bg-surface-dark [&_.ant-modal-content]:!p-0 [&_.ant-modal-content]:shadow-2xl"
        styles={{
          mask: {
            backgroundColor: 'rgba(15, 23, 42, 0.5)',
            backdropFilter: 'blur(8px)',
          },
        }}
      >
        <div className="flex max-h-[calc(100dvh-24px)] min-h-[min(620px,calc(100dvh-24px))] flex-col overflow-hidden bg-surface-light dark:bg-surface-dark">
          <div className="border-b border-border-light px-4 py-4 dark:border-border-dark sm:px-6">
            <div className="pr-10">
              <div className="text-xl font-semibold text-text-primary dark:text-text-inverse">
                {t('blackboard.title', 'Blackboard')}
              </div>
              <div className="mt-1 text-sm text-text-secondary dark:text-text-muted">
                {workspace?.name ??
                  t(
                    'blackboard.modalSubtitle',
                    'Shared goals, tasks, discussions, and topology for the active workspace.'
                  )}
              </div>
            </div>
          </div>

          <div
            ref={tabListRef}
            role="tablist"
            aria-label={t('blackboard.tabs.ariaLabel', 'Blackboard sections')}
            className="flex gap-1 overflow-x-auto border-b border-border-light px-4 py-3 dark:border-border-dark sm:px-6"
          >
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                id={`blackboard-tab-${tab.key}`}
                aria-selected={activeTab === tab.key}
                aria-controls={`blackboard-panel-${tab.key}`}
                tabIndex={activeTab === tab.key ? 0 : -1}
                onKeyDown={(event) => {
                  handleTabKeyDown(event, tabs.findIndex((item) => item.key === tab.key));
                }}
                onClick={() => {
                  setActiveTab(tab.key);
                }}
                className={`rounded-full px-4 py-2 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                  activeTab === tab.key
                    ? 'bg-primary/10 text-primary'
                    : 'text-text-secondary hover:bg-surface-muted hover:text-text-primary dark:text-text-muted dark:hover:bg-surface-elevated dark:hover:text-text-inverse'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {tabs.map((tab) => (
            <div
              key={tab.key}
              id={`blackboard-panel-${tab.key}`}
              role="tabpanel"
              aria-labelledby={`blackboard-tab-${tab.key}`}
              aria-live="polite"
              tabIndex={activeTab === tab.key ? 0 : -1}
              hidden={activeTab !== tab.key}
              className="min-h-0 flex-1 overflow-y-auto px-4 py-4 focus-visible:outline-none sm:px-6 sm:py-5"
            >
              {activeTab === tab.key && (
                <>
            {activeTab === 'goals' && (
              <div className="space-y-5">
                <section className="rounded-2xl border border-border-light bg-surface-muted px-4 py-4 dark:border-border-dark dark:bg-background-dark/35">
                  <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                    <div className="max-w-2xl">
                      <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
                        {t('blackboard.goalsOverviewTitle', 'Goals and delivery')}
                      </h3>
                      <p className="mt-1 text-sm leading-7 text-text-secondary dark:text-text-muted">
                        {t(
                          'blackboard.goalsOverviewBody',
                          'Review shared outcomes and the delivery queue together so the blackboard stays connected to execution.'
                        )}
                      </p>
                    </div>
                    <dl className="flex flex-wrap gap-2">
                      {[
                        {
                          key: 'completion',
                          label: t('blackboard.metrics.completion', 'Task completion'),
                          value: `${String(stats.completionRatio)}%`,
                        },
                        {
                          key: 'objectives',
                          label: t('blackboard.objectivesTitle', 'Goals'),
                          value: String(objectives.length),
                        },
                        {
                          key: 'tasks',
                          label: t('blackboard.metrics.tasks', 'Tasks'),
                          value: String(tasks.length),
                        },
                      ].map((metric) => (
                        <StatBadge key={metric.key} label={metric.label} value={metric.value} />
                      ))}
                    </dl>
                  </div>
                </section>

                <ObjectiveList
                  objectives={objectives}
                  onDelete={(objectiveId) => {
                    void handleDeleteObjective(objectiveId);
                  }}
                  onCreate={() => {
                    setShowCreateObjective(true);
                  }}
                />

                <TaskBoard workspaceId={workspaceId} />
              </div>
            )}

            {activeTab === 'discussion' && (
              <DiscussionTab
                posts={posts}
                selectedPostId={selectedPostId}
                setSelectedPostId={setSelectedPostId}
                postTitle={postTitle}
                setPostTitle={setPostTitle}
                postContent={postContent}
                setPostContent={setPostContent}
                replyDraft={replyDraft}
                setReplyDraft={setReplyDraft}
                creatingPost={creatingPost}
                replying={replying}
                deletingPostId={deletingPostId}
                deletingReplyId={deletingReplyId}
                togglingPostId={togglingPostId}
                loadingRepliesPostId={loadingRepliesPostId}
                loadedReplyPostIds={loadedReplyPostIds}
                repliesByPostId={repliesByPostId}
                handleCreatePost={handleCreatePost}
                handleCreateReply={handleCreateReply}
                handleTogglePin={handleTogglePin}
                handleDeleteSelectedPost={handleDeleteSelectedPost}
                handleDeleteSelectedReply={handleDeleteSelectedReply}
                handleLoadReplies={handleLoadReplies}
              />
            )}

            {activeTab === 'collaboration' && (
              <div className="rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
                <div className="mb-4">
                  <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
                    {t('blackboard.tabs.collaboration', 'Collaboration')}
                  </div>
                  <p className="mt-1 text-sm text-text-secondary dark:text-text-muted">
                    {t(
                      'blackboard.collaborationHint',
                      'Keep the workspace-wide collaboration stream inside the central blackboard so execution and discussion stay in one place.'
                    )}
                  </p>
                </div>
                <div className="min-h-[560px]">
                  <ChatPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
                </div>
              </div>
            )}

            {activeTab === 'members' && (
              <div className="rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
                <MemberPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
              </div>
            )}

            {activeTab === 'genes' && (
              <div className="rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
                <GeneList
                  genes={genes}
                  onDelete={(geneId) => {
                    void handleDeleteGene(geneId);
                  }}
                  onToggleActive={(geneId, isActive) => {
                    void handleToggleGeneActive(geneId, isActive);
                  }}
                />
              </div>
            )}

            {activeTab === 'files' && (
              <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark">
                <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
                  {t('blackboard.filesUnavailableTitle', 'Shared files are not wired here yet')}
                </div>
                <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-text-secondary dark:text-text-muted">
                  {t(
                    'blackboard.filesUnavailableBody',
                    'The central blackboard already combines discussion, goals, and execution. File operations can be added later when a workspace-scoped file endpoint is available.'
                  )}
                </p>
              </div>
            )}

            {activeTab === 'status' && (
              <StatusTab
                stats={stats}
                topologyEdges={topologyEdges}
                agents={agents}
                workspaceId={workspaceId}
                statusBadgeTone={statusBadgeTone}
              />
            )}

            {activeTab === 'notes' && (
              <div className="space-y-4">
                {notes.map((note) => (
                  <article
                    key={note.id}
                    className="rounded-3xl border border-border-light bg-surface-muted p-5 dark:border-border-dark dark:bg-surface-dark-alt"
                  >
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="rounded-full border border-border-light bg-surface-light px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                        {t(`blackboard.noteKinds.${note.kind}`, note.kind)}
                      </span>
                    </div>
                    <h3 className="mt-4 break-words text-lg font-semibold text-text-primary dark:text-text-inverse">
                      {note.title}
                    </h3>
                    <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-text-secondary dark:text-text-muted">
                      {note.summary}
                    </p>
                  </article>
                ))}

                {notes.length === 0 && (
                  <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-8 text-center text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                    {t(
                      'blackboard.noNotes',
                      'No shared notes yet. Add workspace description, objectives, or pinned discussions to make this tab more useful.'
                    )}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'topology' && (
              <TopologyTab
                topologyNodes={topologyNodes}
                topologyEdges={topologyEdges}
                topologyNodeTitles={topologyNodeTitles}
              />
            )}

            {activeTab === 'settings' && (
              <div className="rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
                <WorkspaceSettingsPanel
                  tenantId={tenantId}
                  projectId={projectId}
                  workspaceId={workspaceId}
                />
              </div>
            )}
                </>
              )}
            </div>
          ))}
        </div>
      </Modal>

      <ObjectiveCreateModal
        open={showCreateObjective}
        onClose={() => {
          setShowCreateObjective(false);
        }}
        onSubmit={(values) => {
          void handleCreateObjective(values);
        }}
        parentObjectives={objectives}
        loading={creatingObjective}
      />
    </>
  );
}
