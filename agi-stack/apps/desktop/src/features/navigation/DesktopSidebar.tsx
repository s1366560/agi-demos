import { useState } from 'react';

import {
  BellIcon,
  ChevronUpIcon,
  CodeIcon,
  CubeIcon,
  DashboardIcon,
  GearIcon,
  HomeIcon,
  LightningBoltIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PersonIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  CurrentUser,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';
import { WorkspaceDock } from '../workspace/WorkspaceDock';
import type { WorkspaceTreeSelectionMode } from '../workspace/workspaceTreeModel';
import './DesktopSidebar.css';

type DesktopSidebarSection = 'home' | 'my-work' | 'automations' | 'search' | 'notifications';

type DesktopSidebarProps = {
  activeSection: DesktopSidebarSection | null;
  mode: 'work' | 'code';
  taskCount: number;
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
  onModeChange: (mode: 'work' | 'code') => void;
  onNavigate: (section: DesktopSidebarSection) => void;
  onToggleWorkspace: (workspaceId: string) => void;
  onRetryProject: () => void;
  onRetryWorkspace: (workspaceId: string) => void;
  onSelectWorkspace: (projectId: string, workspaceId: string) => void;
  onSelectConversation: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => void;
  onNewTask: () => void;
  onOpenAccountSettings: () => void;
  onSwitchWorkspace: () => void;
  onSignOut: () => void;
};

const primaryItems = [
  { id: 'home', labelKey: 'nav.home', icon: HomeIcon },
  { id: 'my-work', labelKey: 'nav.myWork', icon: DashboardIcon },
  { id: 'automations', labelKey: 'nav.automations', icon: LightningBoltIcon },
  { id: 'search', labelKey: 'nav.search', icon: MagnifyingGlassIcon },
] as const;

export function DesktopSidebar({
  activeSection,
  mode,
  taskCount,
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
  onModeChange,
  onNavigate,
  onToggleWorkspace,
  onRetryProject,
  onRetryWorkspace,
  onSelectWorkspace,
  onSelectConversation,
  onNewTask,
  onOpenAccountSettings,
  onSwitchWorkspace,
  onSignOut,
}: DesktopSidebarProps) {
  const { t } = useI18n();
  const [profileOpen, setProfileOpen] = useState(false);

  return (
    <aside className="desktop-design-sidebar" aria-label={t('sidebar.primaryNavigation')}>
      <div className="desktop-design-brand">
        <img src="/icon-192.png" alt="" />
        <div>
          <strong>MemStack</strong>
          <span>{t('sidebar.agentWorkspace')}</span>
        </div>
      </div>

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
          </button>
        ))}
      </nav>

      <section className="desktop-design-workspaces">
        <header>
          <strong>{projectName}</strong>
          <span>{t('workspaceTree.workspaces')}</span>
        </header>
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
        />
      </section>

      <div className="desktop-design-sidebar-bottom">
        <div className="desktop-design-mode-switcher" aria-label={t('sidebar.defaultTaskMode')}>
          <button
            className={mode === 'work' ? 'active' : ''}
            type="button"
            onClick={() => onModeChange('work')}
          >
            <MixerHorizontalIcon /> {t('sidebar.workMode')}
          </button>
          <button
            className={mode === 'code' ? 'active' : ''}
            type="button"
            onClick={() => onModeChange('code')}
          >
            <CodeIcon /> {t('sidebar.codeMode')}
          </button>
        </div>

        <nav className="desktop-design-footer-nav">
          <button
            className={activeSection === 'notifications' ? 'active' : ''}
            type="button"
            onClick={() => onNavigate('notifications')}
          >
            <BellIcon /> <span>{t('sidebar.notifications')}</span><i />
          </button>
          <button type="button" onClick={onOpenAccountSettings}>
            <GearIcon /> <span>{t('settings.title')}</span>
          </button>
        </nav>

        <div className="desktop-design-profile-wrap">
          {profileOpen ? (
            <div className="desktop-design-profile-menu">
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
                onClick={() => {
                  setProfileOpen(false);
                  onOpenAccountSettings();
                }}
              >
                <GearIcon /> {t('sidebar.accountSettings')}
              </button>
              <button
                type="button"
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
            className="desktop-design-profile"
            type="button"
            aria-expanded={profileOpen}
            onClick={() => setProfileOpen((open) => !open)}
          >
            <span className="desktop-design-profile-avatar">
              <PersonIcon />
            </span>
            <span>
              <strong>{user?.name || user?.email || t('sidebar.account')}</strong>
              <small>{tenantName} · {projectName}</small>
            </span>
            <ChevronUpIcon />
          </button>
        </div>
      </div>
    </aside>
  );
}
