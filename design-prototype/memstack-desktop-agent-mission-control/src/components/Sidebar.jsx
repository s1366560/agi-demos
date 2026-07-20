import { useEffect, useState } from 'react';
import {
  ActivityLogIcon,
  BellIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CodeIcon,
  CubeIcon,
  DashboardIcon,
  GearIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const primaryItems = [
  ['inbox', 'nav.myWork', DashboardIcon],
  ['search', 'nav.search', MagnifyingGlassIcon],
];

function ThreadRow({ thread, active, onOpen, t }) {
  const ModeIcon = thread.mode === 'code' ? CodeIcon : ActivityLogIcon;
  return (
    <button
      className={`thread-row ${active ? 'active' : ''}`}
      type="button"
      onClick={onOpen}
    >
      <i className={`thread-status ${thread.status}`} aria-hidden="true" />
      <ModeIcon className="thread-mode-icon" />
      <span>
        <b>{thread.title}</b>
        <small>{t(thread.meta)}</small>
      </span>
    </button>
  );
}

export function Sidebar({ view, activeWorkspaceId, activeThreadId, inboxCount, tenant, project, workspaces, settingsOpen, resolveThread, onNavigate, onOpenWorkspace, onOpenThread, onNewThread, onOpenSettings, onSignOut }) {
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
    <aside className="sidebar" aria-label={t('Primary navigation')}>
      <button className="brand-row brand-button" type="button" onClick={() => onNavigate('home')}>
        <img src="/memstack-icon.png" alt="MemStack" className="brand-icon" />
        <div>
          <strong>MemStack</strong>
          <span>{t('app.workspace')}</span>
        </div>
      </button>

      <button className="new-task-button" type="button" onClick={onNewThread}>
        <PlusIcon />
        {t('nav.newThread')}
      </button>

      <nav className="nav-list">
        {primaryItems.map(([id, labelKey, Icon]) => (
          <button
            className={`nav-item ${view === id ? 'active' : ''}`}
            key={id}
            type="button"
            onClick={() => onNavigate(id)}
          >
            <Icon />
            <span>{t(labelKey)}</span>
            {id === 'inbox' && inboxCount > 0 ? <small>{inboxCount}</small> : null}
          </button>
        ))}
      </nav>

      <div className="nav-section-label sidebar-tenant-label"><span>{project.name}</span><small>{t('Threads')}</small></div>
      <nav className="workspace-tree" aria-label={t('Workspace threads')}>
        {workspaces.map((workspace) => (
          <div className="workspace-tree-node" key={workspace.id}>
            <div className="workspace-tree-root">
              <button className={`workspace-tree-toggle ${expanded[workspace.id] ? 'expanded' : ''}`} type="button" aria-label={`${expanded[workspace.id] ? t('Collapse') : t('Expand')} ${workspace.name}`} onClick={() => toggleWorkspace(workspace.id)}><ChevronDownIcon /></button>
              <button className={`workspace-tree-workspace ${view === 'workspace' && activeWorkspaceId === workspace.id ? 'active' : ''}`} type="button" onClick={() => onOpenWorkspace(workspace.id)}><CubeIcon /><span><b>{workspace.name}</b><small>{workspace.sessions.length} {t('threads')}</small></span><i className={workspace.status === 'attention' ? 'attention' : ''} /></button>
            </div>
            {expanded[workspace.id] ? <div className="workspace-session-tree" role="group" aria-label={`${workspace.name} ${t('threads')}`}>
              {workspace.sessions.map((session) => (
                <ThreadRow
                  key={session.id}
                  thread={resolveThread(session)}
                  active={view === 'thread' && activeThreadId === session.id}
                  onOpen={() => onOpenThread(session, workspace.id)}
                  t={t}
                />
              ))}
            </div> : null}
          </div>
        ))}
      </nav>

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
