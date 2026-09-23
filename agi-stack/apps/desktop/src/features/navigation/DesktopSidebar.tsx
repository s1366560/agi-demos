import { useEffect, useRef, useState, type ReactNode } from 'react';

import {
  ChevronUpIcon,
  CubeIcon,
  GearIcon,
  GridIcon,
  MagnifyingGlassIcon,
  PersonIcon,
  PlusIcon,
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

type DesktopSidebarSection = 'home' | 'my-work' | 'activity';

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
  onOpenSearch?: () => void;
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

export function DesktopSidebar({
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
  onOpenSearch,
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
      {/* Brand: one compact row; navigates home like the prototype brand button. */}
      <button className="desktop-design-brand" type="button" onClick={() => onNavigate('home')}>
        <img src="/icon-192.png" alt="" />
        <span className="desktop-design-brand-text">
          <strong>MemStack</strong>
        </span>
      </button>

      {/* Primary create action: prototype "New thread" anatomy, above the nav. */}
      <button
        className="desktop-design-new-task"
        type="button"
        disabled={Boolean(newTaskDisabledReason)}
        title={newTaskDisabledReason ?? undefined}
        onClick={onNewTask}
      >
        <PlusIcon /> {t('overview.newTask')}
      </button>

      <nav className="desktop-design-primary-nav">
        {onOpenSearch ? (
          <button type="button" onClick={onOpenSearch}>
            <MagnifyingGlassIcon />
            <span>{t('nav.search')}</span>
          </button>
        ) : null}
      </nav>

      {/* Header: the project/workspace heading and conversation status chips. */}
      <div className="desktop-design-header">
        <header className="desktop-design-header-row">
          <strong>{projectName}</strong>
          <div className="desktop-workspace-heading-actions">
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

      {/* Bottom toolbar: feature directory, settings entry, profile menu. */}
      <div className="desktop-design-toolbar">
        {onOpenFeatureDirectory ? (
          <button
            className="desktop-design-toolbar-button desktop-design-feature-button"
            type="button"
            aria-label={t('featureDirectory.open')}
            aria-haspopup="dialog"
            onClick={(event) => onOpenFeatureDirectory(event.currentTarget)}
          >
            <GridIcon aria-hidden="true" />
            <span>{t('featureDirectory.open')}</span>
          </button>
        ) : null}
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
                  profileTriggerRef.current?.focus();
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
                  profileTriggerRef.current?.focus();
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
