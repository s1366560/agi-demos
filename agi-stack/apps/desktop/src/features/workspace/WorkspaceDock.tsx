import { Button, ScrollArea, Text } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  FileTextIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import type {
  AgentConversation,
  ProjectSummary,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';

type WorkspaceDockProps = {
  projects: ProjectSummary[];
  workspacesByProject: Record<string, WorkspaceSummary[]>;
  conversationsByWorkspace: Record<string, AgentConversation[]>;
  nodeState: RuntimeNodeLoadState;
  currentProjectId: string;
  currentWorkspaceId: string;
  currentConversationId: string | null;
  groupMode: 'project' | 'recent';
  actionDisabledReason: string | null;
  creatingWorkspace: boolean;
  creatingSessionWorkspaceId: string | null;
  expandedProjectIds: Set<string>;
  expandedWorkspaceIds: Set<string>;
  onToggleProject: (projectId: string) => void;
  onToggleWorkspace: (workspaceId: string) => void;
  onSelectProject: (projectId: string) => void;
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
  projects,
  workspacesByProject,
  conversationsByWorkspace,
  nodeState,
  currentProjectId,
  currentWorkspaceId,
  currentConversationId,
  groupMode,
  actionDisabledReason,
  creatingWorkspace,
  creatingSessionWorkspaceId,
  expandedProjectIds,
  expandedWorkspaceIds,
  onToggleProject,
  onToggleWorkspace,
  onSelectProject,
  onSelectWorkspace,
  onSelectConversation,
  onRefresh,
  onCreateWorkspace,
  onCreateSession,
}: WorkspaceDockProps) {
  const createDisabled = Boolean(actionDisabledReason) || creatingWorkspace;
  const orderedProjects = sortProjects(projects, workspacesByProject, conversationsByWorkspace, groupMode);

  return (
    <aside className="workspace-dock workspace-session-tree">
      <ScrollArea className="dock-list">
        <div>
          {orderedProjects.length === 0 ? (
            <div className="empty-state workspace-empty">
              <Text size="2" color="gray">
                No projects are available.
              </Text>
              <Text size="1" color="gray" className="action-hint">
                Connect an account or configure a project id first.
              </Text>
            </div>
          ) : (
            orderedProjects.map((project) => {
              const projectId = project.id;
              const projectState = nodeState.projects[projectId];
              const workspaces = sortWorkspaces(
                workspacesByProject[projectId] ?? [],
                conversationsByWorkspace,
                groupMode,
              );
              const expanded = expandedProjectIds.has(projectId);
              const selected = currentProjectId === projectId;
              const sessionCount = workspaces.reduce(
                (count, workspace) => count + (conversationsByWorkspace[workspace.id]?.length ?? 0),
                0,
              );

              return (
                <section className="tree-project" key={projectId} aria-label={projectLabel(project)}>
                  <div className={`dock-row project-root-row ${selected ? 'selected' : ''}`}>
                    <button
                      type="button"
                      className="dock-expander"
                      aria-label={`${expanded ? 'Collapse' : 'Expand'} project ${projectLabel(project)}`}
                      aria-expanded={expanded}
                      onClick={() => onToggleProject(projectId)}
                    >
                      {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
                    </button>
                    <button
                      type="button"
                      className="dock-main-action"
                      aria-label={`Select project ${projectLabel(project)}`}
                      onClick={() => onSelectProject(projectId)}
                    >
                      <span className="dock-leading">
                        <FileTextIcon aria-hidden />
                        <span>
                          <strong>{projectLabel(project)}</strong>
                          <Text size="1" color="gray">
                            {projectState?.loading
                              ? 'Loading workspaces...'
                              : projectState?.error
                                ? projectState.error
                                : `${workspaces.length} workspaces / ${sessionCount} sessions`}
                          </Text>
                        </span>
                      </span>
                    </button>
                    <Button
                      size="1"
                      variant="ghost"
                      aria-label={`New workspace in ${projectLabel(project)}`}
                      disabled={createDisabled}
                      title={actionDisabledReason ?? undefined}
                      onClick={() => onCreateWorkspace(projectId)}
                    >
                      <PlusIcon />
                    </Button>
                  </div>

                  {expanded ? (
                    <div className="tree-children" role="group">
                      <button
                        className="dock-row workspace-child-row new-workspace-row"
                        type="button"
                        onClick={() => onCreateWorkspace(projectId)}
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

                      {workspaces.length === 0 ? (
                        <div className="empty-state workspace-empty workspace-child-empty">
                          <Text size="2" color="gray">
                            No workspaces in this project.
                          </Text>
                        </div>
                      ) : (
                        workspaces.map((workspace) => {
                          const workspaceId = workspace.id;
                          const workspaceExpanded = expandedWorkspaceIds.has(workspaceId);
                          const workspaceSelected = currentWorkspaceId === workspaceId;
                          const conversations = sortConversations(
                            conversationsByWorkspace[workspaceId] ?? [],
                            groupMode,
                          );
                          const workspaceState = nodeState.workspaces[workspaceId];
                          const creatingSession = creatingSessionWorkspaceId === workspaceId;

                          return (
                            <section
                              className="tree-workspace"
                              key={workspaceId}
                              aria-label={workspaceLabel(workspace)}
                            >
                              <div
                                className={`dock-row workspace-row ${
                                  workspaceSelected ? 'selected' : ''
                                }`}
                              >
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
                                  onClick={() => onSelectWorkspace(projectId, workspaceId)}
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
                                  aria-label={`New session in ${workspaceLabel(workspace)}`}
                                  disabled={Boolean(actionDisabledReason) || creatingSession}
                                  title={actionDisabledReason ?? undefined}
                                  onClick={() => onCreateSession(projectId, workspaceId)}
                                >
                                  <PlusIcon />
                                </Button>
                              </div>

                              {workspaceExpanded ? (
                                <div className="tree-children session-children" role="group">
                                  <button
                                    className="dock-row session-row new-session-row"
                                    type="button"
                                    onClick={() => onCreateSession(projectId, workspaceId)}
                                    disabled={Boolean(actionDisabledReason) || creatingSession}
                                    title={actionDisabledReason ?? undefined}
                                  >
                                    <span className="dock-leading">
                                      <PlusIcon aria-hidden />
                                      <span>
                                        <strong>
                                          {creatingSession ? 'Creating session...' : 'New session'}
                                        </strong>
                                      </span>
                                    </span>
                                  </button>

                                  {conversations.length === 0 ? (
                                    <div className="empty-state workspace-empty session-child-empty">
                                      <Text size="2" color="gray">
                                        {workspaceState?.error
                                          ? 'Sessions are unavailable.'
                                          : 'No sessions in this workspace.'}
                                      </Text>
                                      {workspaceState?.error ? (
                                        <Text
                                          size="1"
                                          color="gray"
                                          className="action-hint"
                                          title={workspaceState.error}
                                        >
                                          Conversation list endpoint did not return active sessions.
                                        </Text>
                                      ) : null}
                                    </div>
                                  ) : (
                                    conversations.map((conversation) => (
                                      <button
                                        className={`dock-row session-row ${
                                          conversation.id === currentConversationId ? 'selected' : ''
                                        }`}
                                        type="button"
                                        key={conversation.id}
                                        aria-current={
                                          conversation.id === currentConversationId
                                            ? 'page'
                                            : undefined
                                        }
                                        onClick={() =>
                                          onSelectConversation(projectId, workspaceId, conversation)
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
                                          {conversationStatusLabel(conversation)}
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
          aria-label="Refresh projects, workspaces, and sessions"
          onClick={onRefresh}
          disabled={Boolean(actionDisabledReason)}
        >
          <ReloadIcon /> Refresh
        </Button>
      </div>
    </aside>
  );
}

function projectLabel(project: ProjectSummary): string {
  return project.name || project.id || 'Project';
}

function workspaceLabel(workspace: WorkspaceSummary | undefined): string {
  return workspace?.name ?? workspace?.title ?? workspace?.id ?? 'No workspace';
}

function conversationSubtitle(conversation: AgentConversation): string {
  const updated = formatDate(conversation.updated_at ?? conversation.created_at);
  const count = `${conversation.message_count} ${conversation.message_count === 1 ? 'message' : 'messages'}`;
  return updated ? `${count} / ${updated}` : count;
}

function conversationStatusLabel(conversation: AgentConversation): string {
  return conversation.status || 'active';
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '';
  return new Date(timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function sortProjects(
  projects: ProjectSummary[],
  workspacesByProject: Record<string, WorkspaceSummary[]>,
  conversationsByWorkspace: Record<string, AgentConversation[]>,
  groupMode: 'project' | 'recent',
): ProjectSummary[] {
  const copy = [...projects];
  if (groupMode === 'recent') {
    return copy.sort(
      (left, right) =>
        latestProjectTimestamp(right, workspacesByProject, conversationsByWorkspace) -
        latestProjectTimestamp(left, workspacesByProject, conversationsByWorkspace),
    );
  }
  return copy.sort((left, right) => projectLabel(left).localeCompare(projectLabel(right)));
}

function sortWorkspaces(
  workspaces: WorkspaceSummary[],
  conversationsByWorkspace: Record<string, AgentConversation[]>,
  groupMode: 'project' | 'recent',
): WorkspaceSummary[] {
  const copy = [...workspaces];
  if (groupMode === 'recent') {
    return copy.sort(
      (left, right) =>
        latestWorkspaceTimestamp(right, conversationsByWorkspace) -
        latestWorkspaceTimestamp(left, conversationsByWorkspace),
    );
  }
  return copy.sort((left, right) => workspaceLabel(left).localeCompare(workspaceLabel(right)));
}

function sortConversations(
  conversations: AgentConversation[],
  groupMode: 'project' | 'recent',
): AgentConversation[] {
  const copy = [...conversations];
  if (groupMode === 'project') {
    return copy.sort((left, right) => (left.title || left.id).localeCompare(right.title || right.id));
  }
  return copy.sort((left, right) => timestamp(right.updated_at) - timestamp(left.updated_at));
}

function latestProjectTimestamp(
  project: ProjectSummary,
  workspacesByProject: Record<string, WorkspaceSummary[]>,
  conversationsByWorkspace: Record<string, AgentConversation[]>,
): number {
  return Math.max(
    timestamp(project.updated_at),
    0,
    ...(workspacesByProject[project.id] ?? []).map((workspace) =>
      latestWorkspaceTimestamp(workspace, conversationsByWorkspace),
    ),
  );
}

function latestWorkspaceTimestamp(
  workspace: WorkspaceSummary,
  conversationsByWorkspace: Record<string, AgentConversation[]>,
): number {
  return Math.max(
    timestamp(workspace.updated_at),
    timestamp(workspace.created_at),
    0,
    ...(conversationsByWorkspace[workspace.id] ?? []).map((conversation) =>
      timestamp(conversation.updated_at ?? conversation.created_at),
    ),
  );
}

function timestamp(value: string | null | undefined): number {
  return value ? Date.parse(value) || 0 : 0;
}
