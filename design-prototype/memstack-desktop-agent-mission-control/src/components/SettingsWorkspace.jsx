import { useState } from 'react';
import {
  ArchiveIcon,
  BellIcon,
  CheckCircledIcon,
  CodeIcon,
  ComponentInstanceIcon,
  Cross2Icon,
  CubeIcon,
  FontStyleIcon,
  GearIcon,
  GlobeIcon,
  IdCardIcon,
  LockClosedIcon,
  MagicWandIcon,
  MagnifyingGlassIcon,
  PersonIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';
import { getProject, getTenant, tenantCatalog } from '../workspaceContext';
import { managementCatalog } from '../managementData';
import { ManagementWorkspace } from './ManagementWorkspace';

const resourceSections = {
  models: { label: 'Models', descriptionKey: 'settings.modelsDescription', Icon: CubeIcon },
  skills: { label: 'Skills', descriptionKey: 'settings.skillsDescription', Icon: MagicWandIcon },
  plugins: { label: 'Plugins', descriptionKey: 'settings.pluginsDescription', Icon: ComponentInstanceIcon },
  agents: { label: 'Agents', descriptionKey: 'settings.agentsDescription', Icon: PersonIcon },
};

const accountSections = {
  account: { label: 'Account', description: 'Profile and sign-in', Icon: IdCardIcon },
  workspace: { label: 'Workspace', description: 'Tenant and project context', Icon: CubeIcon },
};

const preferenceSections = {
  general: { labelKey: 'settings.general', descriptionKey: 'settings.generalDescription', Icon: GearIcon },
  appearance: { labelKey: 'settings.appearance', descriptionKey: 'settings.appearanceDescription', Icon: FontStyleIcon },
  notifications: { labelKey: 'settings.notifications', descriptionKey: 'settings.notificationsDescription', Icon: BellIcon },
};

function SettingsRow({ label, value, description }) {
  return <div className="settings-row"><div><b>{label}</b>{description ? <span>{description}</span> : null}</div><strong>{value}</strong></div>;
}

function AccountSettings({ session, tenant, onSignOut }) {
  const { t } = useI18n();
  return (
    <div className="settings-page-scroll settings-account-page">
      <header className="settings-page-header"><span>{t('ACCOUNT')}</span><h1>{t('Your account')}</h1><p>{t('Manage your identity, sign-in method, and active organization membership.')}</p></header>
      <section className="settings-panel account-profile-card">
        <div className="account-profile-hero"><img src="/avatar-alex.png" alt="Alex Chen" /><div><b>Alex Chen</b><span>{session.email}</span><em>{t('Active')}</em></div><button type="button">{t('Edit profile')}</button></div>
        <div className="settings-rows"><SettingsRow label={t('Sign-in method')} value={t('Workspace SSO + password')} /><SettingsRow label={t('Current organization')} value={tenant.name} description={`${t(tenant.role)} · ${tenant.plan}`} /><SettingsRow label={t('Session security')} value={t('Trusted device')} description={t('Last verified just now')} /></div>
      </section>
      <section className="settings-panel account-security-card"><header><div><LockClosedIcon /><span><b>{t('Security')}</b><small>{t('Your organization controls sign-in and session policies.')}</small></span></div></header><div className="settings-rows"><SettingsRow label={t('Multi-factor authentication')} value={t('Required')} /><SettingsRow label={t('Session timeout')} value={t('12 hours')} /><SettingsRow label={t('Recovery email')} value="a•••@northstar.ai" /></div></section>
      <button className="settings-signout" type="button" onClick={onSignOut}>{t('Sign out of MemStack')}</button>
    </div>
  );
}

function WorkspaceSettings({ currentTenantId, currentProjectId, onContextChange, onToast }) {
  const { t } = useI18n();
  const [tenantId, setTenantId] = useState(currentTenantId);
  const [projectId, setProjectId] = useState(currentProjectId);
  const tenant = getTenant(tenantId);
  const project = getProject(tenantId, projectId);
  const changed = tenantId !== currentTenantId || projectId !== currentProjectId;

  function chooseTenant(nextTenantId) {
    const nextTenant = getTenant(nextTenantId);
    setTenantId(nextTenantId);
    setProjectId(nextTenant.projects[0].id);
  }

  function applyContext() {
    onContextChange({ tenantId, projectId });
    onToast(`${t('Switched to')} ${tenant.name} / ${project.name}.`);
  }

  return (
    <div className="settings-page-scroll workspace-context-page">
      <header className="settings-page-header"><span>{t('WORKSPACE CONTEXT')}</span><h1>{t('Tenant and project')}</h1><p>{t('Choose the organization boundary first, then the project whose tasks, memory, and permissions should be active.')}</p></header>
      <div className="context-current-bar"><div><span>{t('CURRENT CONTEXT')}</span><b>{getTenant(currentTenantId).name} <i>/</i> {getProject(currentTenantId, currentProjectId).name}</b></div><em><LockClosedIcon /> {t('Tenant isolated')}</em></div>

      <section className="context-step">
        <header><span>1</span><div><h2>{t('Choose tenant')}</h2><p>{t('Tenants define members, billing, credentials, memory, and policy boundaries.')}</p></div></header>
        <div className="tenant-choice-list">{tenantCatalog.map((item) => <button className={tenantId === item.id ? 'selected' : ''} type="button" key={item.id} onClick={() => chooseTenant(item.id)}><span className="tenant-avatar"><CubeIcon /></span><span><b>{item.name}</b><small>{t(item.role)} · {item.domain}</small></span><em>{item.plan}</em>{tenantId === item.id ? <CheckCircledIcon /> : null}</button>)}</div>
      </section>

      <section className="context-step project-step">
        <header><span>2</span><div><h2>{t('Choose project')}</h2><p>{t('Only projects available to your role in the selected tenant are shown.')}</p></div></header>
        <div className="project-choice-grid">{tenant.projects.map((item) => {
          const Icon = item.icon === 'code' ? CodeIcon : item.icon === 'archive' ? ArchiveIcon : CubeIcon;
          return <button className={projectId === item.id ? 'selected' : ''} type="button" key={item.id} onClick={() => setProjectId(item.id)}><span className="project-choice-icon"><Icon /></span><span><b>{item.name}</b><small>{t(item.description)}</small><em>{item.activeTasks} {t('active tasks')} · {item.members} {t('members')}</em></span>{projectId === item.id ? <CheckCircledIcon /> : null}</button>;
        })}</div>
      </section>

      <footer className="context-apply-bar"><div><ReloadIcon /><span><b>{t('Context change')}</b><small>{t('Task lists, memory, agents, and permissions reload inside the selected project.')}</small></span></div><button className="primary" type="button" disabled={!changed} onClick={applyContext}>{changed ? t('Switch workspace') : t('Current workspace')}</button></footer>
    </div>
  );
}

function GeneralSettings({ onOpenResource, onToast }) {
  const { locale, setLocale, t } = useI18n();
  function changeLocale(nextLocale) { setLocale(nextLocale); onToast(t('toast.languageChanged', { language: nextLocale === 'zh-CN' ? t('settings.chinese') : t('settings.english') })); }
  return (
    <div className="settings-page-scroll">
      <header className="settings-page-header"><span>{t('settings.eyebrow')}</span><h1>{t('settings.generalTitle')}</h1><p>{t('settings.generalSubtitle')}</p></header>
      <section className="settings-panel language-panel"><header><div><GlobeIcon /><span><b>{t('settings.language')}</b><small>{t('settings.languageDescription')}</small></span></div><em>{locale === 'zh-CN' ? 'ZH-CN' : 'EN'}</em></header><div className="language-options" role="group" aria-label={t('settings.language')}><button className={locale === 'zh-CN' ? 'active' : ''} type="button" onClick={() => changeLocale('zh-CN')}><span>简</span><div><b>{t('settings.chinese')}</b><small>Chinese (Simplified)</small></div>{locale === 'zh-CN' ? <CheckCircledIcon /> : null}</button><button className={locale === 'en' ? 'active' : ''} type="button" onClick={() => changeLocale('en')}><span>EN</span><div><b>{t('settings.english')}</b><small>English (US)</small></div>{locale === 'en' ? <CheckCircledIcon /> : null}</button></div></section>
      <section className="settings-panel"><header><div><GlobeIcon /><span><b>{t('settings.region')}</b><small>{t('settings.regionDescription')}</small></span></div></header><div className="settings-rows"><SettingsRow label={t('settings.timezone')} value="Asia/Shanghai (UTC+8)" /><SettingsRow label={t('settings.dateFormat')} value={locale === 'zh-CN' ? '2026年7月11日' : 'Jul 11, 2026'} /><SettingsRow label={t('settings.numberFormat')} value="12,345.67" /></div></section>
      <section className="settings-panel resource-entry-panel"><header><div><LockClosedIcon /><span><b>{t('settings.agentResources')}</b><small>{t('settings.agentResourcesDescription')}</small></span></div></header><div className="resource-entry-grid">{Object.entries(resourceSections).map(([key, section]) => <button type="button" key={key} onClick={() => onOpenResource(key)}><section.Icon /><span><b>{t(section.label)}</b><small>{t(section.descriptionKey)}</small></span><em>{managementCatalog[key].length}</em><strong>{t('settings.open')}</strong></button>)}</div></section>
    </div>
  );
}

function PreferencePage({ section }) {
  const { t } = useI18n();
  const appearance = section === 'appearance';
  return <div className="settings-page-scroll"><header className="settings-page-header"><span>{t('settings.eyebrow')}</span><h1>{t(appearance ? 'settings.appearanceTitle' : 'settings.notificationsTitle')}</h1><p>{t(appearance ? 'settings.appearanceSubtitle' : 'settings.notificationsSubtitle')}</p></header><section className="settings-panel"><div className="settings-rows">{appearance ? <><SettingsRow label={t('settings.theme')} value={t('settings.themeValue')} /><SettingsRow label={t('settings.density')} value={t('settings.densityValue')} /><SettingsRow label={t('settings.motion')} value={t('settings.motionValue')} /></> : <><SettingsRow label={t('settings.reviewAlerts')} value="On" description={t('settings.reviewAlertsDescription')} /><SettingsRow label={t('settings.delivery')} value={t('settings.deliveryValue')} /><SettingsRow label={t('settings.quietHours')} value={t('settings.quietHoursValue')} /></>}</div></section></div>;
}

export function SettingsWorkspace({ onToast, onClose, onSignOut, session, currentTenantId, currentProjectId, onContextChange, initialSection = 'account' }) {
  const { t } = useI18n();
  const [section, setSection] = useState(initialSection);
  const isResource = Object.hasOwn(resourceSections, section);
  const tenant = getTenant(currentTenantId);
  const project = getProject(currentTenantId, currentProjectId);

  return (
    <div className="settings-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="settings-window" role="dialog" aria-modal="true" aria-label={t('settings.title')} onMouseDown={(event) => event.stopPropagation()}>
        <header className="settings-window-titlebar"><div><img src="/memstack-icon.png" alt="" /><span><b>{t('settings.title')}</b><small>{tenant.name} / {project.name}</small></span></div><label><MagnifyingGlassIcon /><input placeholder={t('Search settings')} /></label><button className="icon-button" type="button" onClick={onClose} aria-label={t('Close settings')}><Cross2Icon /></button></header>
        <main className="settings-workspace">
          <aside className="settings-rail">
            <div className="settings-section-label">{t('ACCOUNT & CONTEXT')}</div>
            <nav aria-label={t('Account and workspace')}>{Object.entries(accountSections).map(([key, value]) => <button className={section === key ? 'active' : ''} type="button" key={key} onClick={() => setSection(key)}><value.Icon /><span><b>{t(value.label)}</b><small>{t(value.description)}</small></span></button>)}</nav>
            <div className="settings-section-label">{t('PREFERENCES')}</div>
            <nav aria-label={t('Preferences')}>{Object.entries(preferenceSections).map(([key, value]) => <button className={section === key ? 'active' : ''} type="button" key={key} onClick={() => setSection(key)}><value.Icon /><span><b>{t(value.labelKey)}</b><small>{t(value.descriptionKey)}</small></span></button>)}</nav>
            <div className="settings-section-label">{t('settings.aiResources')}</div>
            <nav aria-label={t('settings.aiResources')}>{Object.entries(resourceSections).map(([key, value]) => <button className={section === key ? 'active' : ''} type="button" key={key} onClick={() => setSection(key)}><value.Icon /><span><b>{t(value.label)}</b><small>{t(value.descriptionKey)}</small></span><em>{managementCatalog[key].length}</em></button>)}</nav>
            <section className="settings-context-note"><span className="tenant-avatar small"><CubeIcon /></span><span><b>{tenant.name}</b><small>{project.name}</small></span><LockClosedIcon /></section>
          </aside>
          <section className="settings-content">
            {section === 'account' ? <AccountSettings session={session} tenant={tenant} onSignOut={onSignOut} /> : null}
            {section === 'workspace' ? <WorkspaceSettings currentTenantId={currentTenantId} currentProjectId={currentProjectId} onContextChange={onContextChange} onToast={onToast} /> : null}
            {section === 'general' ? <GeneralSettings onOpenResource={setSection} onToast={onToast} /> : null}
            {section === 'appearance' || section === 'notifications' ? <PreferencePage section={section} /> : null}
            {isResource ? <ManagementWorkspace key={section} embedded category={section} onToast={onToast} /> : null}
          </section>
        </main>
      </section>
    </div>
  );
}
