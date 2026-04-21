import { useEffect, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';

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
import {
  buildBlackboardNotes,
  buildBlackboardStats,
  statusBadgeTone,
} from './blackboardUtils';
import { CollaborationOverviewTab } from './tabs/CollaborationOverviewTab';
import { DiscussionTab } from './tabs/DiscussionTab';
import { GoalsTab } from './tabs/GoalsTab';
import { NotesTab } from './tabs/NotesTab';
import { SharedFileBrowser } from './tabs/SharedFileBrowser';
import { StatusTab } from './tabs/StatusTab';
import { TopologyTab } from './tabs/TopologyTab';
import { useBlackboardActions } from './useBlackboardActions';
import { WorkstationArrangementBoard } from './WorkstationArrangementBoard';

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

export interface CentralBlackboardContentProps {
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
  activeTab: BlackboardTab;
  onActiveTabChange: (nextTab: BlackboardTab) => void;
  agentWorkspacePath: string;
  onLoadReplies: (postId: string) => Promise<boolean>;
  onCreatePost: (data: { title: string; content: string }) => Promise<boolean>;
  onCreateReply: (postId: string, content: string) => Promise<boolean>;
  onDeletePost: (postId: string) => Promise<boolean>;
  onPinPost: (postId: string) => Promise<void>;
  onUnpinPost: (postId: string) => Promise<void>;
  onDeleteReply: (postId: string, replyId: string) => Promise<void>;
}

export function CentralBlackboardContent({
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
  activeTab,
  onActiveTabChange,
  agentWorkspacePath,
  onLoadReplies,
  onCreatePost,
  onCreateReply,
  onDeletePost,
  onPinPost,
  onUnpinPost,
  onDeleteReply,
}: CentralBlackboardContentProps) {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const workspaceActions = useWorkspaceActions();
  const goalCandidates = useWorkspaceGoalCandidates();
  const goalCandidatesLoading = useWorkspaceGoalCandidatesLoading();
  const goalCandidatesError = useWorkspaceGoalCandidatesError();
  const tabListRef = useRef<HTMLDivElement | null>(null);

  const actions = useBlackboardActions({
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
    if (activeTab !== 'goals') {
      return;
    }
    void workspaceActions.loadGoalCandidates(workspaceId);
  }, [activeTab, workspaceActions, workspaceId]);

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
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark">
        <BlackboardTabBar
          activeTab={activeTab}
          onTabChange={onActiveTabChange}
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

                {activeTab === 'notes' && <NotesTab notes={notes} />}

                {activeTab === 'topology' && (
                  <div className="flex min-h-0 flex-col gap-4">
                    <WorkstationArrangementBoard
                      tenantId={tenantId}
                      projectId={projectId}
                      workspaceId={workspaceId}
                      workspaceName={workspace?.name ?? t('blackboard.title', 'Blackboard')}
                      agentWorkspacePath={agentWorkspacePath}
                      agents={agents}
                      nodes={topologyNodes}
                      edges={topologyEdges}
                      tasks={tasks}
                      onOpenBlackboard={() => onActiveTabChange('goals')}
                    />
                    <TopologyTab
                      topologyNodes={topologyNodes}
                      topologyEdges={topologyEdges}
                      topologyNodeTitles={topologyNodeTitles}
                    />
                  </div>
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
