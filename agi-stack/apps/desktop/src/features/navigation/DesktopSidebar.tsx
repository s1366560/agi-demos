import { useEffect, useRef, useState, type ReactNode } from 'react';

import {
  BellIcon,
  ChevronUpIcon,
  CubeIcon,
  DashboardIcon,
  GearIcon,
  GridIcon,
  MagnifyingGlassIcon,
  PersonIcon,
  PlusIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { LocalConversationStatusSummary } from '../project/projectOverviewLocalClient';
import type {
  AgentConversation,
  CurrentUser,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';
import { WorkspaceDock } from '../workspace/WorkspaceDock';
import type { WorkspaceTreeSelectionMode } from '../workspace/workspaceTreeModel';
import './DesktopSidebar.css';

type DesktopSidebarSection = 'home' | 'my-work' | 'automations' | 'search' | 'activity';

type DesktopSidebarProps = {
  activeSection: DesktopSidebarSection | null;
  mode?: 'work' | 'code';
  taskCount: number;
  activityUnreadCount: number;
  conversationStatusSummary?: LocalConversationStatusSummary | null;
  tenantName: string;
  projectName: string;
  user: CurrentUser | null;
  workspaces: WorkspaceSummary[];
  conversationsByWorkspace: Record<string, AgentConversation[]>;
  nodeState: RuntimeNodeLoadState;
  currentProjectId: string;
  currentWorkspaceId: string;
  currentConversationId: string | null;
  workspaceTreeSelectionMode: WorkspaceTreeSelectionMode;
  expandedWorkspaceIds: Set<string>;
  newTaskDisabledReason: string | null;
  onModeChange?: (mode: 'work' | 'code') => void;
  onNavigate: (section: DesktopSidebarSection) => void;
  onOpenFeatureDirectory?: (trigger: HTMLButtonElement) => void;
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
  workspaceCreateDisabledReason?: string | null;
  onCreateWorkspace?: () => void;
  onNewTask: () => void;
  onOpenAccountSettings: () => void;
  onSwitchWorkspace: () => void;
  onSignOut: () => void;
  resizeHandle?: ReactNode;
};

const primaryItems = [
  { id: 'my-work', labelKey: 'nav.myWork', icon: DashboardIcon },
  { id: 'automations', labelKey: 'nav.automations', icon: RocketIcon },
  { id: 'search', labelKey: 'nav.search', icon: MagnifyingGlassIcon },
  { id: 'activity', labelKey: 'sidebar.activity', icon: BellIcon },
] as const;

export function DesktopSidebar({
  activeSection,
  taskCount,
  activityUnreadCount,
  conversationStatusSummary = null,
  tenantName,
  projectName,
  user,
  workspaces,
  conversationsByWorkspace,
  nodeState,
  currentProjectId,
  currentWorkspaceId,
  currentConversationId,
  workspaceTreeSelectionMode,
  expandedWorkspaceIds,
  newTaskDisabledReason,
  onNavigate,
  onOpenFeatureDirectory,
  onToggleWorkspace,
  onRetryProject,
  onRetryWorkspace,
  onSelectWorkspace,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  workspaceCreateDisabledReason,
  onCreateWorkspace,
  onNewTask,
  onOpenAccountSettings,
  onSwitchWorkspace,
  onSignOut,
  resizeHandle,
}: DesktopSidebarProps) {
  const { t } = useI18n();
  const [profileOpen, setProfileOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const profileTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!profileOpen) return undefined;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && profileMenuRef.current?.contains(target)) return;
      setProfileOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setProfileOpen(false);
      profileTriggerRef.current?.focus();
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [profileOpen]);

  return (
    <aside className="desktop-design-sidebar" aria-label={t('sidebar.primaryNavigation')}>
      {/* Brand: one compact row. */}
      <div className="desktop-design-brand">
        <img src="/icon-192.png" alt="" />
        <strong>MemStack</strong>
      </div>

      {/* View navigation: every workbench section in one column. */}
      <nav className="desktop-design-primary-nav">
        {primaryItems.map(({ id, labelKey, icon: Icon }) => (
          <button
            className={activeSection === id ? 'active' : ''}
            type="button"
            key={id}
            onClick={() => onNavigate(id)}
          >
            <Icon />
            <span>{t(labelKey)}</span>
            {id === 'my-work' && taskCount > 0 ? <small>{taskCount}</small> : null}
            {id === 'activity' && activityUnreadCount > 0 ? (
              <small>{activityUnreadCount}</small>
            ) : null}
          </button>
        ))}
        {onOpenFeatureDirectory ? (
          <button
            className="desktop-design-feature-directory"
            type="button"
            aria-haspopup="dialog"
            onClick={(event) => onOpenFeatureDirectory(event.currentTarget)}
          >
            <GridIcon aria-hidden="true" />
            <span>{t('featureDirectory.open')}</span>
          </button>
        ) : null}
      </nav>

      {/* Header: the primary create action and the project/workspace heading. */}
      <div className="desktop-design-header">
        <button
          className="desktop-design-new-task"
          type="button"
          disabled={Boolean(newTaskDisabledReason)}
          title={newTaskDisabledReason ?? undefined}
          onClick={onNewTask}
        >
          <PlusIcon /> {t('overview.newTask')}
        </button>
        <header className="desktop-design-header-row">
          <strong>{projectName}</strong>
          <div className="desktop-workspace-heading-actions">
            <span>{t('workspaceTree.workspaces')}</span>
            {onCreateWorkspace ? (
              <button
                type="button"
                aria-label={t('workspaceCreate.open')}
                title={workspaceCreateDisabledReason ?? t('workspaceCreate.open')}
                disabled={Boolean(workspaceCreateDisabledReason)}
                onClick={onCreateWorkspace}
              >
                <PlusIcon aria-hidden="true" />
              </button>
            ) : null}
          </div>
        </header>
        {conversationStatusSummary ? (
          <div
            className="desktop-conversation-status-summary"
            role="group"
            aria-label={`${t('overview.conversations')} ${conversationStatusSummary.total}`}
          >
            <ConversationStatusChip
              label={t('workspaceTree.running')}
              count={conversationStatusSummary.running}
              tone="running"
            />
            <ConversationStatusChip
              label={t('workspaceTree.queued')}
              count={conversationStatusSummary.queued}
              tone="queued"
            />
            <ConversationStatusChip
              label={t('settings.attention')}
              count={conversationStatusSummary.attention}
              tone="attention"
            />
            <ConversationStatusChip
              label={t('workspaceTree.failed')}
              count={conversationStatusSummary.failed}
              tone="failed"
            />
            <ConversationStatusChip
              label={t('workspaceTree.completed')}
              count={conversationStatusSummary.completed}
              tone="completed"
            />
            <ConversationStatusChip
              label={t('overview.idle')}
              count={conversationStatusSummary.idle}
              tone="idle"
            />
            <ConversationStatusChip
              label={t('workspaceTree.cancelled')}
              count={conversationStatusSummary.cancelled}
              tone="cancelled"
            />
          </div>
        ) : null}
      </div>

      {/* Core list: the workspace tree owns the remaining scrollable space. */}
      <section className="desktop-design-workspaces">
        <WorkspaceDock
          workspaces={workspaces}
          conversationsByWorkspace={conversationsByWorkspace}
          nodeState={nodeState}
          currentProjectId={currentProjectId}
          currentWorkspaceId={currentWorkspaceId}
          currentConversationId={currentConversationId}
          selectionMode={workspaceTreeSelectionMode}
          expandedWorkspaceIds={expandedWorkspaceIds}
          onToggleWorkspace={onToggleWorkspace}
          onRetryProject={onRetryProject}
          onRetryWorkspace={onRetryWorkspace}
          onSelectWorkspace={onSelectWorkspace}
          onSelectConversation={onSelectConversation}
          onRenameConversation={onRenameConversation}
          onDeleteConversation={onDeleteConversation}
          onCreateWorkspace={workspaceCreateDisabledReason ? undefined : onCreateWorkspace}
        />
      </section>

      {/* Bottom toolbar: settings entry plus the profile menu trigger. */}
      <div className="desktop-design-toolbar">
        <button
          className="desktop-design-toolbar-button"
          type="button"
          aria-label={t('settings.title')}
          title={t('settings.title')}
          onClick={onOpenAccountSettings}
        >
          <GearIcon />
        </button>
        <div ref={profileMenuRef} className="desktop-design-profile-wrap">
          {profileOpen ? (
            <div
              id="desktop-profile-menu"
              className="desktop-design-profile-menu"
              role="menu"
              aria-label={t('sidebar.account')}
            >
              <div className="desktop-design-profile-menu-identity">
                <span className="desktop-design-profile-avatar">
                  <PersonIcon />
                </span>
                <span>
                  <strong>{user?.name || user?.email || t('sidebar.account')}</strong>
                  <small>{user?.email ?? t('overview.none')}</small>
                </span>
              </div>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setProfileOpen(false);
                  onOpenAccountSettings();
                }}
              >
                <GearIcon /> {t('sidebar.accountSettings')}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setProfileOpen(false);
                  onSwitchWorkspace();
                }}
              >
                <CubeIcon /> {t('settings.switchWorkspace')}
              </button>
              <button
                className="danger"
                type="button"
                role="menuitem"
                onClick={() => {
                  setProfileOpen(false);
                  onSignOut();
                }}
              >
                {t('settings.signOut')}
              </button>
            </div>
          ) : null}
          <button
            ref={profileTriggerRef}
            className="desktop-design-profile"
            type="button"
            aria-haspopup="menu"
            aria-expanded={profileOpen}
            aria-controls={profileOpen ? 'desktop-profile-menu' : undefined}
            onClick={() => setProfileOpen((open) => !open)}
          >
            <span className="desktop-design-profile-avatar">
              <PersonIcon />
            </span>
            <span>
              <strong>{user?.name || user?.email || t('sidebar.account')}</strong>
              <small>
                {tenantName} · {projectName}
              </small>
            </span>
            <ChevronUpIcon />
          </button>
        </div>
      </div>
      {resizeHandle}
    </aside>
  );
}

function ConversationStatusChip({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: string;
}) {
  if (count === 0) return null;
  return (
    <span className={tone} title={`${label}: ${count}`}>
      <i aria-hidden="true" />
      {label}
      <strong>{count}</strong>
    </span>
  );
}
