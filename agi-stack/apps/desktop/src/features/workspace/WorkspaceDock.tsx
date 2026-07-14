import { Button, ScrollArea, Text } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  FileTextIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';
import { buildWorkspaceTree } from './workspaceTreeModel';

type WorkspaceDockProps = {
  workspaces: WorkspaceSummary[];
  conversationsByWorkspace: Record<string, AgentConversation[]>;
  nodeState: RuntimeNodeLoadState;
  currentProjectId: string;
  currentWorkspaceId: string;
  currentConversationId: string | null;
  groupMode: 'project' | 'recent';
  actionDisabledReason: string | null;
  creatingWorkspace: boolean;
  creatingSessionWorkspaceId: string | null;
  expandedWorkspaceIds: Set<string>;
  onToggleWorkspace: (workspaceId: string) => void;
  onSelectWorkspace: (projectId: string, workspaceId: string) => void;
  onSelectConversation: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => void;
  onRefresh: () => void;
  onCreateWorkspace: (projectId: string) => void;
  onCreateSession: (projectId: string, workspaceId: string) => void;
};

export function WorkspaceDock({
  workspaces,
  conversationsByWorkspace,
  nodeState,
  currentProjectId,
  currentWorkspaceId,
  currentConversationId,
  groupMode,
  actionDisabledReason,
  creatingWorkspace,
  creatingSessionWorkspaceId,
  expandedWorkspaceIds,
  onToggleWorkspace,
  onSelectWorkspace,
  onSelectConversation,
  onRefresh,
  onCreateWorkspace,
  onCreateSession,
}: WorkspaceDockProps) {
  const { t } = useI18n();
  const createDisabled = Boolean(actionDisabledReason) || creatingWorkspace;
  const projectState = nodeState.projects[currentProjectId];
  const tree = buildWorkspaceTree(workspaces, conversationsByWorkspace, groupMode);

  return (
    <aside className="workspace-dock workspace-session-tree">
      <ScrollArea className="dock-list">
        <div>
          <button
            className="dock-row workspace-child-row new-workspace-row workspace-tree-create-root"
            type="button"
            onClick={() => onCreateWorkspace(currentProjectId)}
            disabled={createDisabled}
            title={actionDisabledReason ?? undefined}
          >
            <span className="dock-leading">
              <PlusIcon aria-hidden />
              <span>
                <strong>{creatingWorkspace ? 'Creating workspace...' : 'New workspace'}</strong>
              </span>
            </span>
          </button>

          {projectState?.loading ? (
            <WorkspaceTreeState title="Loading workspaces..." detail="Reading the current project scope." />
          ) : projectState?.error ? (
            <WorkspaceTreeState title="Workspaces are unavailable." detail={projectState.error} />
          ) : tree.length === 0 ? (
            <WorkspaceTreeState
              title="No workspaces in this project."
              detail="Create a workspace to start an isolated conversation tree."
            />
          ) : (
            tree.map(({ workspace, conversations }) => {
              const workspaceId = workspace.id;
              const workspaceExpanded = expandedWorkspaceIds.has(workspaceId);
              const workspaceSelected = currentWorkspaceId === workspaceId;
              const workspaceState = nodeState.workspaces[workspaceId];
              const creatingSession = creatingSessionWorkspaceId === workspaceId;

              return (
                <section
                  className="tree-workspace workspace-tree-root-node"
                  key={workspaceId}
                  aria-label={workspaceLabel(workspace)}
                >
                  <div className={`dock-row workspace-row ${workspaceSelected ? 'selected' : ''}`}>
                    <button
                      type="button"
                      className="dock-expander"
                      aria-label={`${workspaceExpanded ? 'Collapse' : 'Expand'} workspace ${workspaceLabel(workspace)}`}
                      aria-expanded={workspaceExpanded}
                      onClick={() => onToggleWorkspace(workspaceId)}
                    >
                      {workspaceExpanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
                    </button>
                    <button
                      type="button"
                      className="dock-main-action"
                      aria-label={`Select workspace ${workspaceLabel(workspace)}`}
                      onClick={() => onSelectWorkspace(currentProjectId, workspaceId)}
                    >
                      <span className="dock-leading">
                        <ChatBubbleIcon aria-hidden />
                        <span>
                          <strong>{workspaceLabel(workspace)}</strong>
                          <Text size="1" color="gray">
                            {workspaceState?.loading
                              ? 'Loading sessions...'
                              : workspaceState?.error
                                ? workspaceState.error
                                : `${conversations.length} sessions`}
                          </Text>
                        </span>
                      </span>
                    </button>
                    <Button
                      size="1"
                      variant="ghost"
                      aria-label={`New task in ${workspaceLabel(workspace)}`}
                      disabled={Boolean(actionDisabledReason) || creatingSession}
                      title={actionDisabledReason ?? undefined}
                      onClick={() => onCreateSession(currentProjectId, workspaceId)}
                    >
                      <PlusIcon />
                    </Button>
                  </div>

                  {workspaceExpanded ? (
                    <div
                      className="tree-children session-children"
                      role="group"
                      aria-label={`${workspaceLabel(workspace)} sessions`}
                    >
                      <button
                        className="dock-row session-row new-session-row"
                        type="button"
                        onClick={() => onCreateSession(currentProjectId, workspaceId)}
                        disabled={Boolean(actionDisabledReason) || creatingSession}
                        title={actionDisabledReason ?? undefined}
                      >
                        <span className="dock-leading">
                          <PlusIcon aria-hidden />
                          <span>
                            <strong>
                              {creatingSession ? 'Creating task...' : 'New task'}
                            </strong>
                          </span>
                        </span>
                      </button>

                      {conversations.length === 0 ? (
                        <WorkspaceTreeState
                          compact
                          title={
                            workspaceState?.error
                              ? 'Sessions are unavailable.'
                              : 'No sessions in this workspace.'
                          }
                          detail={workspaceState?.error ?? 'Start a session from this workspace.'}
                        />
                      ) : (
                        conversations.map((conversation) => (
                          <button
                            className={`dock-row session-row ${
                              conversation.id === currentConversationId ? 'selected' : ''
                            }`}
                            type="button"
                            key={conversation.id}
                            aria-current={
                              conversation.id === currentConversationId ? 'page' : undefined
                            }
                            onClick={() =>
                              onSelectConversation(currentProjectId, workspaceId, conversation)
                            }
                          >
                            <span className="dock-leading">
                              <FileTextIcon aria-hidden />
                              <span>
                                <strong>{conversation.title || conversation.id}</strong>
                                <Text size="1" color="gray">
                                  {conversationSubtitle(conversation)}
                                </Text>
                              </span>
                            </span>
                            <span className="tree-meta">
                              {conversationStatusLabel(conversation.status, t)}
                            </span>
                          </button>
                        ))
                      )}
                    </div>
                  ) : null}
                </section>
              );
            })
          )}
        </div>
      </ScrollArea>
      <div className="tree-footer">
        <Button
          size="1"
          variant="ghost"
          aria-label="Refresh workspaces and sessions"
          onClick={onRefresh}
          disabled={Boolean(actionDisabledReason)}
        >
          <ReloadIcon /> Refresh
        </Button>
      </div>
    </aside>
  );
}

function conversationStatusLabel(
  status: string | undefined,
  translate: (key: string) => string,
): string {
  const normalized = status?.trim().toLowerCase() || 'active';
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
  return labels[normalized] ? translate(labels[normalized]) : status || 'active';
}

function WorkspaceTreeState({
  title,
  detail,
  compact = false,
}: {
  title: string;
  detail: string;
  compact?: boolean;
}) {
  return (
    <div
      className={`empty-state workspace-empty ${compact ? 'session-child-empty' : ''}`}
      role="status"
    >
      <Text size="2" color="gray">
        {title}
      </Text>
      <Text size="1" color="gray" className="action-hint" title={detail}>
        {detail}
      </Text>
    </div>
  );
}

function workspaceLabel(workspace: WorkspaceSummary | undefined): string {
  return workspace?.name ?? workspace?.title ?? workspace?.id ?? 'No workspace';
}

function conversationSubtitle(conversation: AgentConversation): string {
  const updated = formatDate(conversation.updated_at ?? conversation.created_at);
  const count = `${conversation.message_count} ${conversation.message_count === 1 ? 'message' : 'messages'}`;
  return updated ? `${count} / ${updated}` : count;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '';
  return new Date(timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' });
}
