import { useRef } from 'react';

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
  conversationTreeMetadataSummary,
  conversationTreeStatusPresentation,
  conversationTreeStatusValue,
  isWorkspaceConversationSelected,
  isWorkspaceOverviewSelected,
  workspaceTreeAvailability,
  workspaceTreeRootStatusPresentation,
  workspaceTreeSessionAvailability,
  type WorkspaceTreeStatusTone,
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
  onRetryProject: () => void;
  onRetryWorkspace: (workspaceId: string) => void;
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
  onRetryProject,
  onRetryWorkspace,
  onSelectWorkspace,
  onSelectConversation,
}: WorkspaceDockProps) {
  const { t } = useI18n();
  const navigationRef = useRef<HTMLElement>(null);
  const workspaceToggleRefs = useRef(new Map<string, HTMLButtonElement>());
  const projectState = nodeState.projects[currentProjectId];
  const tree = buildWorkspaceTree(workspaces, conversationsByWorkspace, 'project');
  const availability = workspaceTreeAvailability(projectState, tree.length);

  return (
    <nav
      ref={navigationRef}
      className="workspace-dock workspace-session-tree"
      aria-label={t('workspaceTree.navigation')}
      aria-busy={projectState?.loading || undefined}
      tabIndex={-1}
    >
      <ScrollArea className="dock-list">
        <div>
          {availability === 'loading' ? (
            <WorkspaceTreeState
              title={t('workspaceTree.loading')}
              detail={t('workspaceTree.loadingDescription')}
            />
          ) : availability === 'error' ? (
            <WorkspaceTreeState
              title={t('workspaceTree.unavailable')}
              detail={projectState?.error ?? undefined}
              actionLabel={t('workspaceTree.retry')}
              onAction={() => {
                navigationRef.current?.focus();
                onRetryProject();
              }}
            />
          ) : availability === 'empty' ? (
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
              const sessionAvailability = workspaceTreeSessionAvailability(
                workspaceState,
                conversations.length,
              );
              const rootStatus = workspaceTreeRootStatusPresentation(
                workspace.office_status,
                conversations,
              );
              const rootStatusLabel = t(rootStatus.labelKey);
              const sessionSummary =
                sessionAvailability === 'deferred'
                  ? t('workspaceTree.sessionsDeferred')
                  : sessionAvailability === 'loading'
                    ? t('workspaceTree.loadingSessions')
                    : sessionAvailability === 'error'
                      ? t('workspaceTree.sessionsUnavailable')
                      : t('workspaceTree.sessionCount', { count: conversations.length });

              return (
                <section
                  className="workspace-tree-root-node"
                  key={workspace.id}
                >
                  <div
                    className={
                      `workspace-tree-workspace-row ${workspaceSelected ? 'selected' : ''}`
                    }
                  >
                    <button
                      type="button"
                      className="workspace-tree-toggle"
                      ref={(element) => {
                        if (element) workspaceToggleRefs.current.set(workspace.id, element);
                        else workspaceToggleRefs.current.delete(workspace.id);
                      }}
                      aria-expanded={workspaceExpanded}
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
                        <small>{sessionSummary}</small>
                      </span>
                      <i
                        data-status={rootStatus.tone}
                        role="img"
                        aria-label={rootStatusLabel}
                        title={rootStatusLabel}
                      />
                    </button>
                  </div>

                  {workspaceExpanded ? (
                    <div className="workspace-tree-session-children">
                      {sessionAvailability === 'deferred' ? (
                        <WorkspaceTreeState compact title={t('workspaceTree.sessionsDeferred')} />
                      ) : sessionAvailability === 'loading' ? (
                        <WorkspaceTreeState compact title={t('workspaceTree.loadingSessions')} />
                      ) : sessionAvailability === 'error' ? (
                        <WorkspaceTreeState
                          compact
                          title={t('workspaceTree.sessionsUnavailable')}
                          detail={workspaceState?.error ?? undefined}
                          actionLabel={t('workspaceTree.retry')}
                          onAction={() => {
                            workspaceToggleRefs.current.get(workspace.id)?.focus();
                            onRetryWorkspace(workspace.id);
                          }}
                        />
                      ) : sessionAvailability === 'empty' ? (
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
                          const status = conversationTreeStatusValue(conversation);
                          const statusPresentation = conversationTreeStatusPresentation(status);
                          const statusLabel = t(statusPresentation.labelKey);
                          const sessionSummary =
                            conversationTreeMetadataSummary(conversation) ?? statusLabel;
                          const StatusIcon = conversationStatusIcon(statusPresentation.tone);

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
                                <small>{sessionSummary}</small>
                              </span>
                              <StatusIcon
                                data-status={statusPresentation.tone}
                                aria-label={statusLabel}
                              />
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
    </nav>
  );
}

function WorkspaceTreeState({
  title,
  detail,
  compact = false,
  actionLabel,
  onAction,
}: {
  title: string;
  detail?: string;
  compact?: boolean;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div
      className={`workspace-tree-state ${compact ? 'compact' : ''}`}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <strong>{title}</strong>
      {detail ? <small>{detail}</small> : null}
      {actionLabel && onAction ? (
        <button type="button" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function workspaceLabel(workspace: WorkspaceSummary) {
  return workspace.name ?? workspace.title ?? workspace.id;
}

function conversationIcon(conversation: AgentConversation) {
  return conversation.agent_config?.capability_mode === 'code' ? CodeIcon : ActivityLogIcon;
}

function conversationStatusIcon(tone: WorkspaceTreeStatusTone) {
  if (tone === 'attention' || tone === 'danger') return ExclamationTriangleIcon;
  if (tone === 'ready' || tone === 'completed') return CheckCircledIcon;
  return ActivityLogIcon;
}
