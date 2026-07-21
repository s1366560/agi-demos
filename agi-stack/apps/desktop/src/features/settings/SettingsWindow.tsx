import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Theme } from '@radix-ui/themes';
import {
  BellIcon,
  ComponentInstanceIcon,
  Cross2Icon,
  CubeIcon,
  FontStyleIcon,
  GearIcon,
  IdCardIcon,
  LockClosedIcon,
  MagicWandIcon,
  MagnifyingGlassIcon,
  PersonIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AuthState,
  ConnectionState,
  DesktopRuntimeConfig,
  ManagedAgentDefinition,
  ManagedPlugin,
  ManagedSkill,
  ManagedSubAgent,
} from '../../types';
import { RuntimeConfigPanel } from '../runtime/RuntimeConfigPanel';
import { AgentDefinitionEditorDialog } from './AgentDefinitionEditorDialog';
import {
  ManagedResourceWorkspace,
  type ManagedResource,
  type ResourceSection,
} from './ManagedResourceViews';
import {
  filterManagedResources,
  managedResourceAction,
  managedResourceManagementAllowed,
  managedResourceSnapshotIsCurrent,
  resourceIsImmutable,
  resolveManagedResourceSelection,
  type ManagedResourceListFilter,
} from './managedResourceModel';
import { ModelProviderWorkspace } from './ModelProviderWorkspace';
import { PluginConfigDialog, PluginInstallDialog } from './PluginManagementDialogs';
import { SkillManagementDialogs } from './SkillManagementDialogs';
import { providerManagementAllowed } from './providerManagementModel';
import {
  AccountSettingsPage,
  GeneralSettingsPage,
  PreferenceSummaryPage,
  SettingsPage,
  WorkspaceSettingsPage,
  type SettingsResourceCounts,
} from './SettingsCorePages';
import {
  filterSettingsSections,
  SETTINGS_GROUPS,
  type SettingsSearchCopy,
  type SettingsSection,
} from './settingsNavigationModel';
import { useModalDialog } from './useModalDialog';
import { useAgentDefinitionManagement } from './useAgentDefinitionManagement';
import { usePluginManagement } from './usePluginManagement';
import { useSkillManagement } from './useSkillManagement';
import { useSkillPackageManagement } from './useSkillPackageManagement';
import './SettingsWindow.css';

export type { SettingsSection } from './settingsNavigationModel';

type SettingsWindowProps = {
  open: boolean;
  initialSection?: SettingsSection;
  auth: AuthState;
  config: DesktopRuntimeConfig;
  connection: ConnectionState;
  wsConnected: boolean;
  wsError: string | null;
  runtimeDisabledReason: string | null;
  onClose: () => void;
  onConfigChange: (config: DesktopRuntimeConfig) => void;
  onRuntimeStatusRefresh: () => Promise<void>;
  onRefreshRuntime: () => void;
  onContextChange: (tenantId: string, projectId: string) => Promise<void>;
  onSignOut: () => void | Promise<void>;
};

const sectionMeta = {
  account: {
    label: 'settings.account',
    description: 'settings.accountDescription',
    Icon: IdCardIcon,
  },
  workspace: {
    label: 'settings.workspace',
    description: 'settings.workspaceDescription',
    Icon: CubeIcon,
  },
  general: {
    label: 'settings.general',
    description: 'settings.generalDescription',
    Icon: GearIcon,
  },
  connection: {
    label: 'settings.connectionRecovery',
    description: 'settings.connectionRecoveryDescription',
    Icon: GearIcon,
  },
  appearance: {
    label: 'settings.appearance',
    description: 'settings.appearanceDescription',
    Icon: FontStyleIcon,
  },
  notifications: {
    label: 'settings.notifications',
    description: 'settings.notificationsDescription',
    Icon: BellIcon,
  },
  models: {
    label: 'settings.models',
    description: 'settings.modelsDescription',
    Icon: CubeIcon,
  },
  skills: {
    label: 'settings.skills',
    description: 'settings.skillsDescription',
    Icon: MagicWandIcon,
  },
  plugins: {
    label: 'settings.plugins',
    description: 'settings.pluginsDescription',
    Icon: ComponentInstanceIcon,
  },
  agents: {
    label: 'settings.agents',
    description: 'settings.agentsDescription',
    Icon: PersonIcon,
  },
  subagents: {
    label: 'settings.subagents',
    description: 'settings.subagentsDescription',
    Icon: PersonIcon,
  },
} satisfies Record<SettingsSection, { label: string; description: string; Icon: typeof GearIcon }>;

export function SettingsWindow({
  open,
  initialSection = 'account',
  auth,
  config,
  connection,
  wsConnected,
  wsError,
  runtimeDisabledReason,
  onClose,
  onConfigChange,
  onRuntimeStatusRefresh,
  onRefreshRuntime,
  onContextChange,
  onSignOut,
}: SettingsWindowProps) {
  const { t } = useI18n();
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [query, setQuery] = useState('');
  const [resourceQuery, setResourceQuery] = useState('');
  const [resourceItems, setResourceItems] = useState<ManagedResource[]>([]);
  const [loadedResourceSection, setLoadedResourceSection] = useState<ResourceSection | null>(null);
  const [loadedResourceContextKey, setLoadedResourceContextKey] = useState<string | null>(null);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceError, setResourceError] = useState<string | null>(null);
  const [resourceActionError, setResourceActionError] = useState<string | null>(null);
  const [resourceFilter, setResourceFilter] = useState<ManagedResourceListFilter>('all');
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(null);
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const resourceRequestId = useRef(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const activeSectionRef = useRef(section);
  const resourceContextKey = `${config.mode}:${config.tenantId}:${config.projectId}`;
  const resourceContextKeyRef = useRef(resourceContextKey);
  activeSectionRef.current = section;
  resourceContextKeyRef.current = resourceContextKey;
  const [resourceCounts, setResourceCounts] = useState<SettingsResourceCounts>({
    models: null,
    skills: null,
    plugins: null,
    agents: null,
    subagents: null,
  });

  const selectedTenant = auth.tenants.find((tenant) => tenant.id === config.tenantId) ?? null;
  const selectedProject = auth.projects.find((project) => project.id === config.projectId) ?? null;
  const isResourceSection = isResource(section);
  const canManageProviders = providerManagementAllowed(config.mode, auth.user?.roles ?? []);
  const normalizedRoles = new Set(
    (auth.user?.roles ?? []).map((role) => role.trim().toLowerCase())
  );
  const canManageAgentDefinitions = normalizedRoles.has('admin') || normalizedRoles.has('owner');
  const canCreateSkills =
    canManageAgentDefinitions ||
    (config.mode === 'cloud' && normalizedRoles.has('member') && Boolean(config.projectId));
  const canManagePluginControlPlane = canManageAgentDefinitions;
  const settingsDialogRef = useModalDialog({
    active: open,
    initialFocusRef: searchInputRef,
    onClose,
  });

  useEffect(() => {
    if (!open) return;
    setSection(initialSection);
    setQuery('');
    setResourceQuery('');
    setResourceFilter('all');
    setLoadedResourceSection(null);
    setLoadedResourceContextKey(null);
    setResourceItems([]);
    setSelectedResourceId(null);
    setResourceCounts({
      models: null,
      skills: null,
      plugins: null,
      agents: null,
      subagents: null,
    });
  }, [initialSection, open]);

  useEffect(() => {
    if (!open) return;
    setResourceCounts({
      models: null,
      skills: null,
      plugins: null,
      agents: null,
      subagents: null,
    });
  }, [config.projectId, config.tenantId, open]);

  const loadResources = useCallback(
    async (resourceSection: ResourceSection, signal?: AbortSignal) => {
      const requestId = resourceRequestId.current + 1;
      resourceRequestId.current = requestId;
      setResourceLoading(true);
      setResourceError(null);
      try {
        const client = new DesktopApiClient(config);
        const items =
          resourceSection === 'skills'
            ? await client.listManagedSkills(signal)
            : resourceSection === 'plugins'
              ? await client.listManagedPlugins(signal)
              : resourceSection === 'agents'
                ? await client.listManagedAgents(signal)
                : await client.listManagedSubAgents(signal);
        if (requestId !== resourceRequestId.current) return;
        setResourceItems(items);
        setLoadedResourceSection(resourceSection);
        setLoadedResourceContextKey(resourceContextKey);
        setResourceCounts((current) => ({
          ...current,
          [resourceSection]: items.length < 100 ? items.length : null,
        }));
        setSelectedResourceId((current) =>
          current && items.some((item) => item.id === current) ? current : (items[0]?.id ?? null)
        );
      } catch (error) {
        if (requestId !== resourceRequestId.current || signal?.aborted) return;
        setResourceItems([]);
        setLoadedResourceSection(null);
        setLoadedResourceContextKey(null);
        setResourceError(error instanceof Error ? error.message : String(error));
      } finally {
        if (requestId === resourceRequestId.current) setResourceLoading(false);
      }
    },
    [config, resourceContextKey]
  );
  const reloadPluginResources = useCallback(() => loadResources('plugins'), [loadResources]);
  const reloadSkillResources = useCallback(() => loadResources('skills'), [loadResources]);
  const reloadAgentResources = useCallback(() => loadResources('agents'), [loadResources]);
  const clearPluginSelection = useCallback(() => setSelectedResourceId(null), []);
  const clearResourceSelection = useCallback(() => setSelectedResourceId(null), []);
  const selectSavedResource = useCallback((id: string) => setSelectedResourceId(id), []);
  const pluginManagement = usePluginManagement({
    active: open,
    config,
    contextKey: resourceContextKey,
    canManage: canManagePluginControlPlane,
    onReload: reloadPluginResources,
    onUninstalled: clearPluginSelection,
  });
  const skillManagement = useSkillManagement({
    active: open,
    config,
    contextKey: resourceContextKey,
    canCreate: canCreateSkills,
    onReload: reloadSkillResources,
    onSaved: selectSavedResource,
    onDeleted: clearResourceSelection,
  });
  const skillPackageManagement = useSkillPackageManagement({
    active: open,
    config,
    contextKey: resourceContextKey,
    canImport: canCreateSkills,
    onReload: reloadSkillResources,
    onSelected: selectSavedResource,
  });
  const agentManagement = useAgentDefinitionManagement({
    active: open,
    config,
    contextKey: resourceContextKey,
    canManage: canManageAgentDefinitions,
    onReload: reloadAgentResources,
    onSaved: selectSavedResource,
    onDeleted: clearResourceSelection,
  });

  useEffect(() => {
    if (!open || !isResourceSection) return;
    const controller = new AbortController();
    setResourceQuery('');
    setResourceFilter('all');
    setResourceActionError(null);
    setLoadedResourceSection(null);
    setLoadedResourceContextKey(null);
    setResourceItems([]);
    setSelectedResourceId(null);
    void loadResources(section, controller.signal);
    return () => {
      controller.abort();
      resourceRequestId.current += 1;
    };
  }, [isResourceSection, loadResources, open, section]);

  const filteredItems = useMemo(() => {
    if (
      !isResourceSection ||
      !managedResourceSnapshotIsCurrent(
        section,
        resourceContextKey,
        loadedResourceSection,
        loadedResourceContextKey
      )
    ) {
      return [];
    }
    return filterManagedResources(section, resourceItems, resourceQuery, resourceFilter);
  }, [
    isResourceSection,
    loadedResourceContextKey,
    loadedResourceSection,
    resourceFilter,
    resourceItems,
    resourceQuery,
    resourceContextKey,
    section,
  ]);
  const selectedResource = useMemo(
    () =>
      resourceLoading ||
      !isResourceSection ||
      !managedResourceSnapshotIsCurrent(
        section,
        resourceContextKey,
        loadedResourceSection,
        loadedResourceContextKey
      )
        ? null
        : resolveManagedResourceSelection(filteredItems, selectedResourceId),
    [
      filteredItems,
      isResourceSection,
      loadedResourceContextKey,
      loadedResourceSection,
      resourceContextKey,
      resourceLoading,
      section,
      selectedResourceId,
    ]
  );

  useEffect(() => {
    const nextId = selectedResource?.id ?? null;
    if (nextId !== selectedResourceId) setSelectedResourceId(nextId);
  }, [selectedResource, selectedResourceId]);
  const settingsSearchCopy = useMemo(
    (): SettingsSearchCopy => ({
      account: [t(sectionMeta.account.label), t(sectionMeta.account.description)],
      workspace: [t(sectionMeta.workspace.label), t(sectionMeta.workspace.description)],
      general: [t(sectionMeta.general.label), t(sectionMeta.general.description)],
      appearance: [t(sectionMeta.appearance.label), t(sectionMeta.appearance.description)],
      notifications: [t(sectionMeta.notifications.label), t(sectionMeta.notifications.description)],
      models: [t(sectionMeta.models.label), t(sectionMeta.models.description)],
      skills: [t(sectionMeta.skills.label), t(sectionMeta.skills.description)],
      plugins: [t(sectionMeta.plugins.label), t(sectionMeta.plugins.description)],
      agents: [t(sectionMeta.agents.label), t(sectionMeta.agents.description)],
      subagents: [t(sectionMeta.subagents.label), t(sectionMeta.subagents.description)],
    }),
    [t]
  );
  const filteredSettingSections = useMemo(
    () => filterSettingsSections(query, settingsSearchCopy),
    [query, settingsSearchCopy]
  );
  const visibleSections = useMemo(
    () => new Set(filteredSettingSections),
    [filteredSettingSections]
  );
  const updateModelCount = useCallback((count: number | null) => {
    setResourceCounts((current) => ({ ...current, models: count }));
  }, []);

  useEffect(() => {
    if (
      !query.trim() ||
      (section !== 'connection' && visibleSections.has(section)) ||
      filteredSettingSections.length === 0
    ) {
      return;
    }
    setSection(filteredSettingSections[0]);
  }, [filteredSettingSections, query, section, visibleSections]);

  if (!open) return null;

  const toggleResource = async (item: ManagedResource) => {
    if (!isResourceSection) return;
    const mutationSection = section;
    const mutationContextKey = resourceContextKey;
    const canManageResource = managedResourceManagementAllowed(
      config.mode,
      auth.user?.roles ?? [],
      section,
      item
    );
    const action = managedResourceAction(section, item, canManageResource, config.mode);
    if (!action) return;
    setActionBusyId(item.id);
    setResourceActionError(null);
    try {
      const client = new DesktopApiClient(config);
      if (action.kind === 'set_skill_status') {
        const skill = item as ManagedSkill;
        await client.setManagedSkillStatus(skill.id, action.nextActive ? 'active' : 'disabled');
      } else if (action.kind === 'set_plugin_enabled') {
        const plugin = item as ManagedPlugin;
        await client.setManagedPluginEnabled(plugin.id, action.nextActive);
      } else if (action.kind === 'set_subagent_enabled') {
        const subagent = item as ManagedSubAgent;
        await client.setManagedSubAgentEnabled(subagent.id, action.nextActive);
      } else {
        const agent = item as ManagedAgentDefinition;
        await client.setManagedAgentEnabled(agent.id, action.nextActive);
      }
      if (
        activeSectionRef.current === mutationSection &&
        resourceContextKeyRef.current === mutationContextKey
      ) {
        await loadResources(mutationSection);
      }
    } catch (error) {
      if (
        activeSectionRef.current === mutationSection &&
        resourceContextKeyRef.current === mutationContextKey
      ) {
        setResourceActionError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setActionBusyId(null);
    }
  };

  const windowContent = (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="settings-window-backdrop" onMouseDown={onClose}>
        <section
          ref={settingsDialogRef}
          className="settings-window-dialog"
          role="dialog"
          aria-modal="true"
          aria-label={t('settings.title')}
          tabIndex={-1}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <header className="settings-window-titlebar">
            <div className="settings-window-brand">
              <img src="/icon-192.png" alt="" />
              <div>
                <strong>{t('settings.title')}</strong>
                <small>
                  {selectedTenant?.name || config.tenantId || t('settings.noTenantSelected')} /{' '}
                  {selectedProject?.name || config.projectId || t('settings.noProjectSelected')}
                </small>
              </div>
            </div>
            <label className="settings-window-search">
              <MagnifyingGlassIcon />
              <input
                ref={searchInputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('settings.search')}
              />
            </label>
            <button type="button" aria-label={t('settings.close')} onClick={onClose}>
              <Cross2Icon />
            </button>
          </header>

          <div className="settings-window-body">
            <aside className="settings-window-rail">
              {filteredSettingSections.length > 0
                ? SETTINGS_GROUPS.map((group) => (
                    <SettingsGroup
                      key={group.id}
                      label={t(
                        group.id === 'account_context'
                          ? 'settings.accountContext'
                          : group.id === 'preferences'
                            ? 'settings.preferences'
                            : 'settings.aiResources'
                      )}
                      sections={group.sections.filter((candidate) =>
                        visibleSections.has(candidate)
                      )}
                      active={section}
                      counts={resourceCounts}
                      onSelect={setSection}
                    />
                  ))
                : null}
              {query.trim() && filteredSettingSections.length === 0 ? (
                <div className="settings-search-empty">
                  <MagnifyingGlassIcon />
                  <span>{t('settings.noSearchResults')}</span>
                </div>
              ) : null}
              <div className="settings-window-scope">
                <LockClosedIcon />
                <span>
                  <strong>
                    {selectedTenant?.name || config.tenantId || t('settings.noTenantSelected')}
                  </strong>
                  <small>
                    {selectedProject?.name || config.projectId || t('settings.noProjectSelected')}
                  </small>
                </span>
              </div>
            </aside>

            <main
              className={`settings-window-content ${
                section === 'models' ? 'provider-mode' : isResourceSection ? 'managed-mode' : ''
              }`}
            >
              {section === 'account' ? (
                <AccountSettingsPage
                  auth={auth}
                  tenant={selectedTenant}
                  config={config}
                  onSignOut={onSignOut}
                />
              ) : null}

              {section === 'workspace' ? (
                <WorkspaceSettingsPage
                  auth={auth}
                  config={config}
                  onContextChange={onContextChange}
                  onApplied={onClose}
                />
              ) : null}
              {section === 'general' ? (
                <GeneralSettingsPage counts={resourceCounts} onOpenResource={setSection} />
              ) : null}
              {section === 'appearance' || section === 'notifications' ? (
                <PreferenceSummaryPage section={section} />
              ) : null}

              {section === 'connection' ? (
                <SettingsPage
                  eyebrow={t('settings.connectionRecoveryEyebrow')}
                  title={t('settings.connectionRecovery')}
                  description={t('settings.connectionRecoveryDescription')}
                >
                  <RuntimeConfigPanel
                    config={config}
                    connection={connection}
                    wsConnected={wsConnected}
                    wsError={wsError}
                    disabledReason={runtimeDisabledReason}
                    onChange={onConfigChange}
                    onRefresh={onRefreshRuntime}
                  />
                </SettingsPage>
              ) : null}
              {section === 'models' ? (
                <ModelProviderWorkspace
                  key={`${config.mode}|${config.apiBaseUrl}|${config.tenantId}|${config.projectId}|${config.workspaceId}`}
                  config={config}
                  canManage={canManageProviders}
                  onRuntimeStatusRefresh={onRuntimeStatusRefresh}
                  onCountChange={updateModelCount}
                />
              ) : null}
              {isResourceSection ? (
                <ManagedResourceWorkspace
                  section={section}
                  items={filteredItems}
                  selected={selectedResource}
                  query={resourceQuery}
                  filter={resourceFilter}
                  loading={resourceLoading}
                  error={resourceError}
                  actionError={
                    resourceActionError ?? pluginManagement.reloadError ??
                    skillPackageManagement.packageActionError
                  }
                  busy={
                    actionBusyId !== null ||
                    pluginManagement.reloadBusy ||
                    skillPackageManagement.importBusy ||
                    skillPackageManagement.exportBusyId !== null ||
                    (skillPackageManagement.versionsDialog?.rollbackVersion ?? null) !== null
                  }
                  mode={config.mode}
                  canCreate={
                    section === 'skills'
                      ? canCreateSkills
                      : section === 'plugins'
                        ? canManagePluginControlPlane
                        : section === 'agents'
                          ? canManageAgentDefinitions
                          : false
                  }
                  canManage={
                    selectedResource
                      ? managedResourceManagementAllowed(
                          config.mode,
                          auth.user?.roles ?? [],
                          section,
                          selectedResource
                        )
                      : false
                  }
                  onQueryChange={setResourceQuery}
                  onFilterChange={setResourceFilter}
                  onSelect={(id) => {
                    setSelectedResourceId(id);
                    setResourceActionError(null);
                  }}
                  onRetry={() => void loadResources(section)}
                  onAction={(item) => void toggleResource(item)}
                  onCreate={() => {
                    if (section === 'skills') void skillManagement.open(null);
                    if (section === 'plugins') pluginManagement.openInstall();
                    if (section === 'agents') agentManagement.open(null);
                  }}
                  onImport={skillPackageManagement.openImport}
                  onEdit={(item) => {
                    if (section === 'skills') void skillManagement.open(item as ManagedSkill);
                    if (section === 'plugins') {
                      void pluginManagement.openConfig(item as ManagedPlugin);
                    }
                    if (section === 'agents') agentManagement.open(item as ManagedAgentDefinition);
                  }}
                  onVersions={(item) => {
                    if (section !== 'skills') return;
                    const skill = item as ManagedSkill;
                    const canRollback =
                      managedResourceManagementAllowed(
                        config.mode,
                        auth.user?.roles ?? [],
                        section,
                        skill
                      ) && !resourceIsImmutable(section, skill, config.mode);
                    skillPackageManagement.openVersions(skill, canRollback);
                  }}
                  onExport={(item) =>
                    void skillPackageManagement.exportPackage(item as ManagedSkill)
                  }
                  onEvolution={(item, canManage) =>
                    skillPackageManagement.openEvolution(item as ManagedSkill, canManage)
                  }
                  onReload={() => void pluginManagement.reload()}
                  onRemove={(item) => {
                    if (section === 'plugins') {
                      void pluginManagement.openConfig(item as ManagedPlugin, true);
                    }
                  }}
                />
              ) : null}
            </main>
          </div>
        </section>
        {agentManagement.dialog ? (
          <AgentDefinitionEditorDialog
            key={agentManagement.dialog.key}
            definition={agentManagement.dialog.definition}
            projects={auth.projects.filter((project) => project.tenant_id === config.tenantId)}
            initialProjectId={config.projectId || null}
            busy={agentManagement.busy}
            error={agentManagement.error}
            onClose={agentManagement.close}
            onSave={(input) => void agentManagement.save(input)}
            onDelete={
              agentManagement.dialog.definition ? () => void agentManagement.remove() : null
            }
          />
        ) : null}
        <SkillManagementDialogs
          projects={auth.projects.filter((project) => project.tenant_id === config.tenantId)}
          initialProjectId={config.projectId || null}
          allowTenantScope={canManageAgentDefinitions}
          management={skillManagement}
          packages={skillPackageManagement}
        />
        {pluginManagement.dialog?.kind === 'install' ? (
          <PluginInstallDialog
            key={pluginManagement.dialog.key}
            busy={pluginManagement.dialogBusy}
            error={pluginManagement.dialogError}
            onClose={pluginManagement.closeDialog}
            onInstall={(requirement) => void pluginManagement.install(requirement)}
          />
        ) : null}
        {pluginManagement.dialog?.kind === 'config' ? (
          <PluginConfigDialog
            key={pluginManagement.dialog.key}
            plugin={pluginManagement.dialog.plugin}
            schema={pluginManagement.dialog.schema}
            record={pluginManagement.dialog.record}
            loading={pluginManagement.dialog.loading}
            busy={pluginManagement.dialogBusy}
            error={pluginManagement.dialogError}
            initialConfirmUninstall={pluginManagement.dialog.confirmUninstall}
            onClose={pluginManagement.closeDialog}
            onSave={(input) => void pluginManagement.saveConfig(input)}
            onUninstall={() => void pluginManagement.uninstall()}
          />
        ) : null}
      </div>
    </Theme>
  );

  return createPortal(windowContent, document.body);
}

function SettingsGroup({
  label,
  sections,
  active,
  counts,
  onSelect,
}: {
  label: string;
  sections: SettingsSection[];
  active: SettingsSection;
  counts: SettingsResourceCounts;
  onSelect: (section: SettingsSection) => void;
}) {
  const { t } = useI18n();
  if (sections.length === 0) return null;
  return (
    <section className="settings-rail-group">
      <span>{label}</span>
      {sections.map((section) => {
        const meta = sectionMeta[section];
        return (
          <button
            type="button"
            key={section}
            className={active === section ? 'active' : ''}
            onClick={() => onSelect(section)}
          >
            <meta.Icon />
            <span>
              <strong>{t(meta.label)}</strong>
              <small>{t(meta.description)}</small>
            </span>
            {isCountedSection(section) && counts[section] !== null ? (
              <em>{counts[section]}</em>
            ) : null}
          </button>
        );
      })}
    </section>
  );
}

function isResource(section: SettingsSection): section is ResourceSection {
  return (
    section === 'skills' || section === 'plugins' || section === 'agents' || section === 'subagents'
  );
}

function isCountedSection(section: SettingsSection): section is keyof SettingsResourceCounts {
  return section === 'models' || isResource(section);
}
