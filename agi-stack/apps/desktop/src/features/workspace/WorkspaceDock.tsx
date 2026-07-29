import { useEffect, useMemo, useRef, useState } from 'react';

import { ScrollArea } from '@radix-ui/themes';
import {
  ChevronDownIcon,
  ChevronRightIcon,
  DashboardIcon,
  DotsHorizontalIcon,
  Pencil1Icon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { Skeleton, SkeletonGroup } from '../../components/Skeleton';
import { treeSkeletonRows } from '../../components/skeletonModel';
import type {
  AgentConversation,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';
import {
  buildWorkspaceTree,
  conversationRecencyGroup,
  conversationTreeMetadataSummary,
  conversationTreeStatusPresentation,
  conversationTreeStatusValue,
  groupConversationsByRecency,
  isWorkspaceConversationSelected,
  isWorkspaceOverviewSelected,
  UNBOUND_CONVERSATIONS_KEY,
  workspaceTreeAvailability,
  workspaceTreeRootStatusPresentation,
  workspaceTreeSessionAvailability,
  type ConversationRecencyGroup,
  type WorkspaceTreeSelectionMode,
} from './workspaceTreeModel';
import {
  ConversationLifecycleDialogs,
  type ConversationLifecycleMode,
} from './ConversationLifecycleDialogs';
import './WorkspaceDock.css';

type ConversationLifecycleRequest = {
  mode: Exclude<ConversationLifecycleMode, null>;
  projectId: string;
  workspaceId: string;
  conversation: AgentConversation;
};

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
  onRenameConversation?: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
    title: string,
  ) => Promise<void>;
  onDeleteConversation?: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => Promise<void>;
  onCreateWorkspace?: () => void;
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
  onRenameConversation,
  onDeleteConversation,
  onCreateWorkspace,
}: WorkspaceDockProps) {
  const { t } = useI18n();
  const navigationRef = useRef<HTMLElement>(null);
  const workspaceToggleRefs = useRef(new Map<string, HTMLButtonElement>());
  const conversationActionRefs = useRef(new Map<string, HTMLElement>());
  const [unboundTasksExpanded, setUnboundTasksExpanded] = useState(true);
  const [lifecycleRequest, setLifecycleRequest] =
    useState<ConversationLifecycleRequest | null>(null);
  const projectState = nodeState.projects[currentProjectId];
  // The dock re-renders with the App on every socket flush; the tree only
  // changes with the workspace/conversation data, so rebuild it only then.
  const tree = useMemo(
    () => buildWorkspaceTree(workspaces, conversationsByWorkspace, 'project'),
    [workspaces, conversationsByWorkspace],
  );
  const availability = workspaceTreeAvailability(projectState, tree.length);
  const hasProjectScope = Boolean(currentProjectId.trim());
  const unboundConversations = conversationsByWorkspace[UNBOUND_CONVERSATIONS_KEY] ?? [];
  const unboundState = nodeState.workspaces[UNBOUND_CONVERSATIONS_KEY] ?? {
    loading: false,
    error: null,
  };
  const unboundAvailability = workspaceTreeSessionAvailability(
    unboundState,
    unboundConversations.length,
  );
  const now = new Date();
  const unboundGroups = groupConversationsByRecency(unboundConversations, now);
  const renderConversationRow = (conversation: AgentConversation, workspaceId: string) => (
    <ConversationTreeRow
      key={conversation.id}
      conversation={conversation}
      now={now}
      selected={isWorkspaceConversationSelected(
        currentConversationId,
        conversation.id,
        selectionMode,
      )}
      onSelect={() => onSelectConversation(currentProjectId, workspaceId, conversation)}
      actionRef={(element) => {
        if (element) conversationActionRefs.current.set(conversation.id, element);
        else conversationActionRefs.current.delete(conversation.id);
      }}
      onRename={
        onRenameConversation
          ? () =>
              setLifecycleRequest({
                mode: 'rename',
                projectId: currentProjectId,
                workspaceId,
                conversation,
              })
          : undefined
      }
      onDelete={
        onDeleteConversation
          ? () =>
              setLifecycleRequest({
                mode: 'delete',
                projectId: currentProjectId,
                workspaceId,
                conversation,
              })
          : undefined
      }
    />
  );
  const closeLifecycleDialog = () => {
    const conversationId = lifecycleRequest?.conversation.id ?? null;
    setLifecycleRequest(null);
    if (!conversationId || typeof window === 'undefined') return;
    window.requestAnimationFrame(() => {
      const action = conversationActionRefs.current.get(conversationId);
      if (action?.isConnected) {
        action.focus();
        return;
      }
      navigationRef.current?.focus();
    });
  };

  useEffect(() => {
    const openConversationMenu = () =>
      navigationRef.current?.querySelector<HTMLDetailsElement>(
        'details.workspace-tree-session-actions[open]',
      ) ?? null;
    const handleMenuPointerDown = (event: PointerEvent) => {
      const openMenu = openConversationMenu();
      if (!openMenu) return;
      const target = event.target;
      if (target instanceof Node && openMenu.contains(target)) return;
      openMenu.removeAttribute('open');
    };
    const handleMenuKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      const openMenu = openConversationMenu();
      if (!openMenu) return;
      event.preventDefault();
      openMenu.removeAttribute('open');
      openMenu.querySelector<HTMLElement>('summary')?.focus();
    };

    document.addEventListener('pointerdown', handleMenuPointerDown);
    document.addEventListener('keydown', handleMenuKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handleMenuPointerDown);
      document.removeEventListener('keydown', handleMenuKeyDown);
    };
  }, []);

  return (
    <>
      <nav
        ref={navigationRef}
        className="workspace-dock workspace-session-tree"
        aria-label={t('workspaceTree.navigation')}
        aria-busy={projectState?.loading || undefined}
        tabIndex={-1}
      >
        <ScrollArea className="dock-list">
          <div>
          {hasProjectScope && availability === 'refreshing' ? (
            <WorkspaceTreeState compact title={t('workspaceTree.refreshing')} />
          ) : hasProjectScope && availability === 'stale-error' ? (
            <WorkspaceTreeState
              compact
              title={t('workspaceTree.refreshFailed')}
              detail={projectState?.error ?? undefined}
              actionLabel={t('workspaceTree.retry')}
              onAction={() => {
                navigationRef.current?.focus();
                onRetryProject();
              }}
            />
          ) : null}
          {hasProjectScope &&
          availability !== 'unavailable' &&
          availability !== 'loading' &&
          availability !== 'error' ? (
            <section className="workspace-tree-root-node workspace-tree-task-group">
              <div className="workspace-tree-workspace-row">
                <button
                  type="button"
                  className="workspace-tree-toggle"
                  aria-expanded={unboundTasksExpanded}
                  aria-label={
                    unboundTasksExpanded
                      ? t('workspaceTree.collapse', { name: t('workspaceTree.tasks') })
                      : t('workspaceTree.expand', { name: t('workspaceTree.tasks') })
                  }
                  title={
                    unboundTasksExpanded
                      ? t('workspaceTree.collapse', { name: t('workspaceTree.tasks') })
                      : t('workspaceTree.expand', { name: t('workspaceTree.tasks') })
                  }
                  onClick={() => setUnboundTasksExpanded((expanded) => !expanded)}
                >
                  {unboundTasksExpanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
                </button>
                <div className="workspace-tree-workspace-action">
                  <DashboardIcon />
                  <span>
                    <strong>{t('workspaceTree.tasks')}</strong>
                    <small>
                      {t('workspaceTree.sessionCount', { count: unboundConversations.length })}
                    </small>
                  </span>
                  <i
                    data-status={
                      workspaceTreeRootStatusPresentation(null, unboundConversations).tone
                    }
                    aria-hidden="true"
                  />
                </div>
              </div>

              {unboundTasksExpanded ? (
                <div className="workspace-tree-session-children">
                  {unboundAvailability === 'refreshing' ? (
                    <WorkspaceTreeState compact title={t('workspaceTree.refreshingSessions')} />
                  ) : unboundAvailability === 'stale-error' ? (
                    <WorkspaceTreeState
                      compact
                      title={t('workspaceTree.sessionRefreshFailed')}
                      detail={unboundState.error ?? undefined}
                      actionLabel={t('workspaceTree.retry')}
                      onAction={() => onRetryWorkspace(UNBOUND_CONVERSATIONS_KEY)}
                    />
                  ) : null}
                  {unboundAvailability === 'loading' ? (
                    <WorkspaceTreeSkeleton label={t('workspaceTree.loadingTasks')} rows={2} />
                  ) : unboundAvailability === 'error' ? (
                    <WorkspaceTreeState
                      compact
                      title={t('workspaceTree.tasksUnavailable')}
                      detail={unboundState.error ?? undefined}
                      actionLabel={t('workspaceTree.retry')}
                      onAction={() => onRetryWorkspace(UNBOUND_CONVERSATIONS_KEY)}
                    />
                  ) : unboundAvailability === 'empty' ? (
                    <WorkspaceTreeState
                      compact
                      title={t('workspaceTree.noTasks')}
                      detail={t('workspaceTree.noTasksDescription')}
                    />
                  ) : (
                    unboundGroups.map((group) => (
                      <div className="workspace-tree-session-group" key={group.id}>
                        {unboundGroups.length > 1 ? (
                          <h3>{t(recencyGroupLabels[group.id])}</h3>
                        ) : null}
                        {group.conversations.map((conversation) =>
                          renderConversationRow(conversation, ''),
                        )}
                      </div>
                    ))
                  )}
                </div>
              ) : null}
            </section>
          ) : null}
          {!hasProjectScope ? (
            <WorkspaceTreeState
              title={t('settings.noProjectSelected')}
              detail={t('workspaceTree.selectProjectDescription')}
            />
          ) : availability === 'unavailable' ? (
            <WorkspaceTreeState
              title={t('workspaceTree.unavailable')}
              detail={t('workspaceTree.unavailableDescription')}
              actionLabel={t('workspaceTree.retry')}
              onAction={() => {
                navigationRef.current?.focus();
                onRetryProject();
              }}
            />
          ) : availability === 'loading' ? (
            <WorkspaceTreeSkeleton label={t('workspaceTree.loading')} rows={4} />
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
              actionLabel={onCreateWorkspace ? t('workspaceCreate.open') : undefined}
              onAction={onCreateWorkspace}
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
                      : sessionAvailability === 'refreshing'
                        ? t('workspaceTree.refreshingSessionCount', {
                            count: conversations.length,
                          })
                        : sessionAvailability === 'stale-error'
                          ? t('workspaceTree.staleSessionCount', {
                              count: conversations.length,
                            })
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
                      title={
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
                      {sessionAvailability === 'refreshing' ? (
                        <WorkspaceTreeState
                          compact
                          title={t('workspaceTree.refreshingSessions')}
                        />
                      ) : sessionAvailability === 'stale-error' ? (
                        <WorkspaceTreeState
                          compact
                          title={t('workspaceTree.sessionRefreshFailed')}
                          detail={workspaceState?.error ?? undefined}
                          actionLabel={t('workspaceTree.retry')}
                          onAction={() => {
                            workspaceToggleRefs.current.get(workspace.id)?.focus();
                            onRetryWorkspace(workspace.id);
                          }}
                        />
                      ) : null}
                      {sessionAvailability === 'deferred' ? (
                        <WorkspaceTreeState compact title={t('workspaceTree.sessionsDeferred')} />
                      ) : sessionAvailability === 'loading' ? (
                        <WorkspaceTreeSkeleton
                          label={t('workspaceTree.loadingSessions')}
                          rows={2}
                        />
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
                        conversations.map((conversation) =>
                          renderConversationRow(conversation, workspace.id),
                        )
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
      <ConversationLifecycleDialogs
        mode={lifecycleRequest?.mode ?? null}
        target={
          lifecycleRequest
            ? {
                id: lifecycleRequest.conversation.id,
                title: lifecycleRequest.conversation.title || lifecycleRequest.conversation.id,
              }
            : null
        }
        onClose={closeLifecycleDialog}
        onRename={async (title) => {
          if (!lifecycleRequest || !onRenameConversation) return;
          await onRenameConversation(
            lifecycleRequest.projectId,
            lifecycleRequest.workspaceId,
            lifecycleRequest.conversation,
            title,
          );
        }}
        onDelete={async () => {
          if (!lifecycleRequest || !onDeleteConversation) return;
          await onDeleteConversation(
            lifecycleRequest.projectId,
            lifecycleRequest.workspaceId,
            lifecycleRequest.conversation,
          );
        }}
      />
    </>
  );
}

const recencyGroupLabels: Record<ConversationRecencyGroup, string> = {
  today: 'workspaceTree.group.today',
  yesterday: 'workspaceTree.group.yesterday',
  week: 'workspaceTree.group.week',
  older: 'workspaceTree.group.older',
};

function ConversationTreeRow({
  conversation,
  now,
  selected,
  onSelect,
  actionRef,
  onRename,
  onDelete,
}: {
  conversation: AgentConversation;
  now: Date;
  selected: boolean;
  onSelect: () => void;
  actionRef: (element: HTMLElement | null) => void;
  onRename?: () => void;
  onDelete?: () => void;
}) {
  const { t, locale } = useI18n();
  const status = conversationTreeStatusValue(conversation);
  const statusPresentation = conversationTreeStatusPresentation(status);
  const statusLabel = t(statusPresentation.labelKey);
  const sessionSummary = conversationTreeMetadataSummary(conversation);
  const activityAt = conversation.updated_at ?? conversation.created_at;
  const recencyGroup = conversationRecencyGroup(activityAt, now);
  const timeLabel = recencyTimeLabel(recencyGroup, activityAt, locale, t);

  const title = conversation.title || conversation.id;
  const hasLifecycleActions = Boolean(onRename || onDelete);

  return (
    <div className={`workspace-tree-session-row-shell ${selected ? 'selected' : ''}`}>
      <button
        className={`workspace-tree-session-row ${selected ? 'selected' : ''}`}
        type="button"
        aria-current={selected ? 'page' : undefined}
        onClick={onSelect}
      >
        <i
          className="workspace-tree-session-status"
          data-status={statusPresentation.tone}
          role="img"
          aria-label={statusLabel}
          title={statusLabel}
        />
        <span>
          <strong>{title}</strong>
          {sessionSummary ? <small>{sessionSummary}</small> : null}
        </span>
        {timeLabel ? <time dateTime={activityAt}>{timeLabel}</time> : null}
      </button>
      {hasLifecycleActions ? (
        <details className="workspace-tree-session-actions">
          <summary
            ref={actionRef}
            role="button"
            aria-haspopup="menu"
            aria-label={t('workspaceTree.conversationActions', { title })}
            title={t('workspaceTree.conversationActions', { title })}
          >
            <DotsHorizontalIcon />
          </summary>
          <div role="menu" aria-label={t('workspaceTree.conversationActions', { title })}>
            {onRename ? (
              <button
                type="button"
                role="menuitem"
                onClick={(event) => {
                  event.currentTarget.closest('details')?.removeAttribute('open');
                  onRename();
                }}
              >
                <Pencil1Icon />
                {t('workspaceTree.renameConversation')}
              </button>
            ) : null}
            {onDelete ? (
              <button
                type="button"
                role="menuitem"
                className="danger"
                onClick={(event) => {
                  event.currentTarget.closest('details')?.removeAttribute('open');
                  onDelete();
                }}
              >
                <TrashIcon />
                {t('workspaceTree.deleteConversation')}
              </button>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function recencyTimeLabel(
  group: ConversationRecencyGroup,
  value: string | null | undefined,
  locale: string,
  t: (key: string) => string,
): string | null {
  const parsed = value ? Date.parse(value) : Number.NaN;
  if (!Number.isFinite(parsed)) return null;
  const date = new Date(parsed);
  if (group === 'today') {
    return new Intl.DateTimeFormat(locale, {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  }
  if (group === 'yesterday') return t('workspaceTree.group.yesterday');
  if (group === 'week') {
    return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(date);
  }
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(date);
}

function WorkspaceTreeSkeleton({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <SkeletonGroup className="skeleton-tree-rows" label={label}>
      {treeSkeletonRows(rows).map((row) => (
        <div className="skeleton-tree-row" data-depth={row.depth} key={row.id}>
          <Skeleton variant="circle" />
          <Skeleton variant="text" width={row.width} />
        </div>
      ))}
    </SkeletonGroup>
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
