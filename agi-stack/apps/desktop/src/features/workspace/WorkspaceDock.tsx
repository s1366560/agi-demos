import { ScrollArea } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  CubeIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';
import {
  buildWorkspaceTree,
  isWorkspaceConversationSelected,
  isWorkspaceOverviewSelected,
  type WorkspaceTreeSelectionMode,
} from './workspaceTreeModel';
import './WorkspaceDock.css';

type WorkspaceDockProps = {
  workspaces: WorkspaceSummary[];
  conversationsByWorkspace: Record<string, AgentConversation[]>;
  nodeState: RuntimeNodeLoadState;
  currentProjectId: string;
  currentWorkspaceId: string;
  currentConversationId: string | null;
  selectionMode: WorkspaceTreeSelectionMode;
  expandedWorkspaceIds: Set<string>;
  onToggleWorkspace: (workspaceId: string) => void;
  onSelectWorkspace: (projectId: string, workspaceId: string) => void;
  onSelectConversation: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => void;
};

export function WorkspaceDock({
  workspaces,
  conversationsByWorkspace,
  nodeState,
  currentProjectId,
  currentWorkspaceId,
  currentConversationId,
  selectionMode,
  expandedWorkspaceIds,
  onToggleWorkspace,
  onSelectWorkspace,
  onSelectConversation,
}: WorkspaceDockProps) {
  const { t } = useI18n();
  const projectState = nodeState.projects[currentProjectId];
  const tree = buildWorkspaceTree(workspaces, conversationsByWorkspace, 'project');

  return (
    <div className="workspace-dock workspace-session-tree" role="tree">
      <ScrollArea className="dock-list">
        <div>
          {projectState?.loading ? (
            <WorkspaceTreeState
              title={t('workspaceTree.loading')}
              detail={t('workspaceTree.loadingDescription')}
            />
          ) : projectState?.error ? (
            <WorkspaceTreeState
              title={t('workspaceTree.unavailable')}
              detail={projectState.error}
            />
          ) : tree.length === 0 ? (
            <WorkspaceTreeState
              title={t('workspaceTree.empty')}
              detail={t('workspaceTree.emptyDescription')}
            />
          ) : (
            tree.map(({ workspace, conversations }) => {
              const workspaceExpanded = expandedWorkspaceIds.has(workspace.id);
              const workspaceSelected = isWorkspaceOverviewSelected(
                currentWorkspaceId,
                workspace.id,
                selectionMode,
              );
              const workspaceState = nodeState.workspaces[workspace.id];

              return (
                <section
                  className="workspace-tree-root-node"
                  key={workspace.id}
                  role="treeitem"
                  aria-expanded={workspaceExpanded}
                  aria-label={workspaceLabel(workspace)}
                >
                  <div
                    className={
                      `workspace-tree-workspace-row ${workspaceSelected ? 'selected' : ''}`
                    }
                  >
                    <button
                      type="button"
                      className="workspace-tree-toggle"
                      aria-label={
                        workspaceExpanded
                          ? t('workspaceTree.collapse', { name: workspaceLabel(workspace) })
                          : t('workspaceTree.expand', { name: workspaceLabel(workspace) })
                      }
                      onClick={() => onToggleWorkspace(workspace.id)}
                    >
                      {workspaceExpanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
                    </button>
                    <button
                      type="button"
                      className="workspace-tree-workspace-action"
                      aria-current={workspaceSelected ? 'page' : undefined}
                      onClick={() => onSelectWorkspace(currentProjectId, workspace.id)}
                    >
                      <CubeIcon />
                      <span>
                        <strong>{workspaceLabel(workspace)}</strong>
                        <small>
                          {t('workspaceTree.sessionCount', { count: conversations.length })}
                        </small>
                      </span>
                      <i data-status={workspace.office_status ?? 'unknown'} />
                    </button>
                  </div>

                  {workspaceExpanded ? (
                    <div
                      className="workspace-tree-session-children"
                      role="group"
                      aria-label={t('workspaceTree.sessionsFor', {
                        name: workspaceLabel(workspace),
                      })}
                    >
                      {workspaceState?.loading ? (
                        <WorkspaceTreeState compact title={t('workspaceTree.loadingSessions')} />
                      ) : workspaceState?.error ? (
                        <WorkspaceTreeState
                          compact
                          title={t('workspaceTree.sessionsUnavailable')}
                          detail={workspaceState.error}
                        />
                      ) : conversations.length === 0 ? (
                        <WorkspaceTreeState
                          compact
                          title={t('workspaceTree.noSessions')}
                          detail={t('workspaceTree.noSessionsDescription')}
                        />
                      ) : (
                        conversations.map((conversation) => {
                          const selected = isWorkspaceConversationSelected(
                            currentConversationId,
                            conversation.id,
                            selectionMode,
                          );
                          const CapabilityIcon = conversationIcon(conversation);
                          const status = conversationRunStatus(conversation) ?? conversation.status;
                          const StatusIcon = conversationStatusIcon(status);

                          return (
                            <button
                              className={`workspace-tree-session-row ${selected ? 'selected' : ''}`}
                              type="button"
                              key={conversation.id}
                              aria-current={selected ? 'page' : undefined}
                              onClick={() =>
                                onSelectConversation(currentProjectId, workspace.id, conversation)
                              }
                            >
                              <CapabilityIcon />
                              <span>
                                <strong>{conversation.title || conversation.id}</strong>
                                <small>{conversationStatusLabel(status, t)}</small>
                              </span>
                              <StatusIcon data-status={status} />
                            </button>
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
    </div>
  );
}

function WorkspaceTreeState({
  title,
  detail,
  compact = false,
}: {
  title: string;
  detail?: string;
  compact?: boolean;
}) {
  return (
    <div className={`workspace-tree-state ${compact ? 'compact' : ''}`}>
      <strong>{title}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function workspaceLabel(workspace: WorkspaceSummary) {
  return workspace.name ?? workspace.title ?? workspace.id;
}

function conversationIcon(conversation: AgentConversation) {
  return conversation.agent_config?.capability_mode === 'code' ? CodeIcon : ActivityLogIcon;
}

function conversationRunStatus(conversation: AgentConversation) {
  const run = conversation.metadata?.run;
  if (!run || typeof run !== 'object' || Array.isArray(run)) return null;
  const status = (run as Record<string, unknown>).status;
  return typeof status === 'string' && status.trim() ? status : null;
}

function conversationStatusIcon(status: string) {
  if (status === 'needs_input' || status === 'needs_approval') return ExclamationTriangleIcon;
  if (status === 'ready_review' || status === 'completed') return CheckCircledIcon;
  return ActivityLogIcon;
}

function conversationStatusLabel(
  status: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (status === 'running') return t('workspaceTree.running');
  if (status === 'needs_input' || status === 'needs_approval') return t('workspaceTree.needsInput');
  if (status === 'ready_review') return t('workspaceTree.readyReview');
  if (status === 'completed') return t('workspaceTree.completed');
  return status;
}
