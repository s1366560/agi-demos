import { useEffect, useState } from 'react';
import {
  ActivityLogIcon,
  BellIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CodeIcon,
  CubeIcon,
  DashboardIcon,
  GearIcon,
  HomeIcon,
  LightningBoltIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const primaryItems = [
  ['Home', 'nav.home', HomeIcon],
  ['My Work', 'nav.myWork', DashboardIcon],
  ['Automations', 'nav.automations', LightningBoltIcon],
  ['Search', 'nav.search', MagnifyingGlassIcon],
];

export function Sidebar({ activeNav, activeWorkspaceId, activeSessionId, mode, taskCount, tenant, project, workspaces, settingsOpen, onModeChange, onNavigate, onOpenWorkspace, onOpenSession, onNewTask, onOpenSettings, onSignOut }) {
  const { t } = useI18n();
  const [profileOpen, setProfileOpen] = useState(false);
  const workspaceIds = workspaces.map((workspace) => workspace.id).join('|');
  const [expanded, setExpanded] = useState(() => Object.fromEntries(workspaces.map((workspace) => [workspace.id, true])));

  useEffect(() => {
    setExpanded((current) => ({ ...Object.fromEntries(workspaces.map((workspace) => [workspace.id, true])), ...current }));
  }, [workspaceIds]);

  function toggleWorkspace(workspaceId) {
    setExpanded((current) => ({ ...current, [workspaceId]: !current[workspaceId] }));
  }

  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <div className="brand-row">
        <img src="/memstack-icon.png" alt="MemStack" className="brand-icon" />
        <div>
          <strong>MemStack</strong>
          <span>{t('app.workspace')}</span>
        </div>
      </div>

      <button className="new-task-button" type="button" onClick={onNewTask}>
        <PlusIcon />
        {t('nav.newTask')}
      </button>

      <nav className="nav-list">
        {primaryItems.map(([id, labelKey, Icon]) => (
          <button
            className={`nav-item ${activeNav === id ? 'active' : ''}`}
            key={id}
            type="button"
            onClick={() => onNavigate(id)}
          >
            <Icon />
            <span>{t(labelKey)}</span>
            {id === 'My Work' && <small>{taskCount}</small>}
          </button>
        ))}
      </nav>

      <div className="nav-section-label sidebar-tenant-label"><span>{project.name}</span><small>{t('Workspaces')}</small></div>
      <nav className="workspace-tree" aria-label={t('Workspace sessions')}>
        {workspaces.map((workspace) => (
          <div className="workspace-tree-node" key={workspace.id}>
            <div className="workspace-tree-root">
              <button className={`workspace-tree-toggle ${expanded[workspace.id] ? 'expanded' : ''}`} type="button" aria-label={`${expanded[workspace.id] ? t('Collapse') : t('Expand')} ${workspace.name}`} onClick={() => toggleWorkspace(workspace.id)}><ChevronDownIcon /></button>
              <button className={`workspace-tree-workspace ${activeNav === 'Projects' && activeWorkspaceId === workspace.id ? 'active' : ''}`} type="button" onClick={() => onOpenWorkspace(workspace.id)}><CubeIcon /><span><b>{workspace.name}</b><small>{workspace.sessions.length} {t('sessions')}</small></span>{workspace.status === 'attention' ? <i className="attention" /> : <i />}</button>
            </div>
            {expanded[workspace.id] ? <div className="workspace-session-tree" role="group" aria-label={`${workspace.name} ${t('sessions')}`}>
              {workspace.sessions.map((session) => {
                const SessionIcon = session.mode === 'code' ? CodeIcon : ActivityLogIcon;
                return <button className={(activeNav === 'Conversation' || activeNav === 'My Work') && activeSessionId === session.id ? 'active' : ''} type="button" key={session.id} onClick={() => onOpenSession(session, workspace.id)}><SessionIcon /><span><b>{session.title}</b><small>{t(session.meta)}</small></span>{session.status === 'ready' ? <CheckCircledIcon className="ready" /> : <i className={session.status} />}</button>;
              })}
            </div> : null}
          </div>
        ))}
      </nav>

      <div className="mode-switcher" aria-label="Workspace mode">
        <button
          className={mode === 'work' ? 'active' : ''}
          type="button"
          onClick={() => onModeChange('work')}
        >
          <MixerHorizontalIcon /> {t('nav.work')}
        </button>
        <button
          className={mode === 'code' ? 'active' : ''}
          type="button"
          onClick={() => onModeChange('code')}
        >
          <CodeIcon /> {t('nav.code')}
        </button>
      </div>

      <div className="sidebar-footer">
        <button className="nav-item" type="button">
          <BellIcon /> <span>{t('nav.notifications')}</span><i />
        </button>
        <button className={`nav-item ${settingsOpen ? 'active' : ''}`} type="button" onClick={() => onOpenSettings('account')}>
          <GearIcon /> <span>{t('nav.settings')}</span>
        </button>
        <div className="profile-menu-wrap">
          {profileOpen ? <div className="profile-menu"><div><img src="/avatar-alex.png" alt="" /><span><b>Alex Chen</b><small>alex@northstar.ai</small></span></div><button type="button" onClick={() => { setProfileOpen(false); onOpenSettings('account'); }}><GearIcon />{t('Account settings')}</button><button type="button" onClick={() => { setProfileOpen(false); onOpenSettings('workspace'); }}><CubeIcon />{t('Switch workspace')}</button><button className="danger" type="button" onClick={onSignOut}>{t('Sign out')}</button></div> : null}
          <button className="profile-row" type="button" onClick={() => setProfileOpen((value) => !value)} aria-expanded={profileOpen}>
            <img src="/avatar-alex.png" alt="Alex Chen" />
            <div><strong>Alex Chen</strong><span>{tenant.shortName} · {project.name}</span></div><ChevronUpIcon />
          </button>
        </div>
      </div>
    </aside>
  );
}
