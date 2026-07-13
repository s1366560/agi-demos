import { useState } from 'react';
import {
  ArchiveIcon,
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
  PlusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const primaryItems = [
  ['Home', 'nav.home', HomeIcon],
  ['My Work', 'nav.myWork', DashboardIcon],
  ['Automations', 'nav.automations', LightningBoltIcon],
  ['Search', 'nav.search', MagnifyingGlassIcon],
];

export function Sidebar({ activeNav, mode, taskCount, tenant, project, settingsOpen, onModeChange, onNavigate, onNewTask, onOpenSettings, onSignOut }) {
  const { t } = useI18n();
  const [profileOpen, setProfileOpen] = useState(false);
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

      <div className="nav-section-label sidebar-tenant-label"><span>{tenant.shortName}</span><small>{t('nav.projects')}</small></div>
      <nav className="nav-list project-list">
        {tenant.projects.slice(0, 3).map((item) => {
          const Icon = item.icon === 'code' ? CodeIcon : item.icon === 'archive' ? ArchiveIcon : CubeIcon;
          return <button className={`nav-item ${activeNav === 'Projects' && project.id === item.id ? 'active' : ''}`} type="button" key={item.id} onClick={() => onNavigate('Projects')}><Icon /><span>{item.name}</span>{project.id === item.id ? <small>{t('Current')}</small> : null}</button>;
        })}
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
