import { useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal } from 'antd';

import {
  useWorkspaceActions,
  useWorkspaceGoalCandidates,
  useWorkspaceGoalCandidatesError,
  useWorkspaceGoalCandidatesLoading,
} from '@/stores/workspace';

import { WorkspaceSettingsPanel } from '@/pages/tenant/WorkspaceSettings';

import { useLazyMessage } from '@/components/ui/lazyAntd';
import { GeneList } from '@/components/workspace/genes/GeneList';
import { MemberPanel } from '@/components/workspace/MemberPanel';
import { ObjectiveCreateModal } from '@/components/workspace/objectives/ObjectiveCreateModal';


import { BlackboardTabBar, BLACKBOARD_TABS } from './BlackboardTabBar';
import { buildBlackboardNotes, buildBlackboardStats } from './blackboardUtils';
import { CollaborationOverviewTab } from './tabs/CollaborationOverviewTab';
import { DiscussionTab } from './tabs/DiscussionTab';
import { GoalsTab } from './tabs/GoalsTab';
import { NotesTab } from './tabs/NotesTab';
import { SharedFileBrowser } from './tabs/SharedFileBrowser';
import { StatusTab } from './tabs/StatusTab';
import { TopologyTab } from './tabs/TopologyTab';
import { useBlackboardModalActions } from './useBlackboardModalActions';

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

import type { BlackboardTab } from './BlackboardTabBar';

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
  const workspaceActions = useWorkspaceActions();
  const goalCandidates = useWorkspaceGoalCandidates();
  const goalCandidatesLoading = useWorkspaceGoalCandidatesLoading();
  const goalCandidatesError = useWorkspaceGoalCandidatesError();
  const tabListRef = useRef<HTMLDivElement | null>(null);

  const [activeTab, setActiveTab] = useState<BlackboardTab>('goals');

  const actions = useBlackboardModalActions({
    open,
    tenantId,
    projectId,
    workspaceId,
    posts,
    loadedReplyPostIds,
    callbacks: {
      onLoadReplies,
      onCreatePost,
      onCreateReply,
      onDeletePost,
      onPinPost,
      onUnpinPost,
      onDeleteReply,
    },
    workspaceActions,
    message,
    t,
  });

  useEffect(() => {
    if (!open || activeTab !== 'goals') {
      return;
    }
    void workspaceActions.loadGoalCandidates(workspaceId);
  }, [activeTab, open, workspaceActions, workspaceId]);

  const stats = useMemo(
    () => buildBlackboardStats(tasks, posts, agents, topologyNodes),
    [agents, posts, tasks, topologyNodes],
  );
  const notes = useMemo(
    () => buildBlackboardNotes(workspace, objectives, posts),
    [objectives, posts, workspace],
  );
  const topologyNodeTitles = useMemo(
    () =>
      new Map(
        topologyNodes.map((node) => [
          node.id,
          node.title.trim() ? node.title : t('blackboard.topologyUntitled', 'Untitled node'),
        ]),
      ),
    [t, topologyNodes],
  );

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
            backgroundColor: 'var(--color-background-dark)',
            opacity: 0.5,
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
                    'Shared goals, tasks, discussions, and topology for the active workspace.',
                  )}
              </div>
            </div>
          </div>

          <BlackboardTabBar
            activeTab={activeTab}
            onTabChange={setActiveTab}
            tabListRef={tabListRef}
          />

          {BLACKBOARD_TABS.map((tabKey) => (
            <div
              key={tabKey}
              id={`blackboard-panel-${tabKey}`}
              role="tabpanel"
              aria-labelledby={`blackboard-tab-${tabKey}`}
              aria-live="polite"
              tabIndex={activeTab === tabKey ? 0 : -1}
              hidden={activeTab !== tabKey}
              className="min-h-0 flex-1 overflow-y-auto px-4 py-4 focus-visible:outline-none sm:px-6 sm:py-5"
            >
              {activeTab === tabKey && (
                <>
            {activeTab === 'goals' && (
              <GoalsTab
                objectives={objectives}
                goalCandidates={goalCandidates}
                goalCandidatesLoading={goalCandidatesLoading}
                goalCandidatesError={goalCandidatesError}
                tasks={tasks}
                completionRatio={stats.completionRatio}
                workspaceId={workspaceId}
                tenantId={tenantId}
                projectId={projectId}
                onDeleteObjective={(objectiveId) => {
                  void actions.handleDeleteObjective(objectiveId);
                }}
                onProjectObjective={(objectiveId) => {
                  void actions.handleProjectObjective(objectiveId);
                }}
                onCreateObjective={() => {
                  actions.setShowCreateObjective(true);
                }}
                onRefreshGoalCandidates={() => {
                  void workspaceActions.loadGoalCandidates(workspaceId);
                }}
                onMaterializeGoalCandidate={(candidateId) => {
                  void workspaceActions.materializeGoalCandidate(workspaceId, candidateId);
                }}
              />
            )}

            {activeTab === 'discussion' && (
              <DiscussionTab
                posts={posts}
                selectedPostId={actions.selectedPostId}
                setSelectedPostId={actions.setSelectedPostId}
                postTitle={actions.postTitle}
                setPostTitle={actions.setPostTitle}
                postContent={actions.postContent}
                setPostContent={actions.setPostContent}
                replyDraft={actions.replyDraft}
                setReplyDraft={actions.setReplyDraft}
                creatingPost={actions.creatingPost}
                replying={actions.replying}
                deletingPostId={actions.deletingPostId}
                deletingReplyId={actions.deletingReplyId}
                togglingPostId={actions.togglingPostId}
                loadingRepliesPostId={actions.loadingRepliesPostId}
                loadedReplyPostIds={loadedReplyPostIds}
                repliesByPostId={repliesByPostId}
                handleCreatePost={actions.handleCreatePost}
                handleCreateReply={actions.handleCreateReply}
                handleTogglePin={actions.handleTogglePin}
                handleDeleteSelectedPost={actions.handleDeleteSelectedPost}
                handleDeleteSelectedReply={actions.handleDeleteSelectedReply}
                handleLoadReplies={actions.handleLoadReplies}
              />
            )}

            {activeTab === 'collaboration' && (
              <CollaborationOverviewTab
                tenantId={tenantId}
                projectId={projectId}
                workspaceId={workspaceId}
                agents={agents}
              />
            )}

            {activeTab === 'members' && (
              <div className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
                <MemberPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
              </div>
            )}

            {activeTab === 'genes' && (
              <div className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
                <GeneList
                  genes={genes}
                  onDelete={(geneId) => {
                    void actions.handleDeleteGene(geneId);
                  }}
                  onToggleActive={(geneId, isActive) => {
                    void actions.handleToggleGeneActive(geneId, isActive);
                  }}
                />
              </div>
            )}

            {activeTab === 'files' && (
              <SharedFileBrowser
                tenantId={tenantId}
                projectId={projectId}
                workspaceId={workspaceId}
              />
            )}

            {activeTab === 'status' && (
              <StatusTab
                stats={stats}
                topologyEdges={topologyEdges}
                agents={agents}
                tasks={tasks}
                tenantId={tenantId}
                projectId={projectId}
                workspaceId={workspaceId}
                statusBadgeTone={statusBadgeTone}
              />
            )}

            {activeTab === 'notes' && (
              <NotesTab notes={notes} />
            )}

            {activeTab === 'topology' && (
              <TopologyTab
                topologyNodes={topologyNodes}
                topologyEdges={topologyEdges}
                topologyNodeTitles={topologyNodeTitles}
              />
            )}

            {activeTab === 'settings' && (
              <div className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
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
        open={actions.showCreateObjective}
        onClose={() => {
          actions.setShowCreateObjective(false);
        }}
        onSubmit={(values) => {
          void actions.handleCreateObjective(values);
        }}
        parentObjectives={objectives}
        loading={actions.creatingObjective}
      />
    </>
  );
}
