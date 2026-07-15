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
} from '../../types';
import { RuntimeConfigPanel } from '../runtime/RuntimeConfigPanel';
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
  resolveManagedResourceSelection,
  type ManagedResourceListFilter,
} from './managedResourceModel';
import { ModelProviderWorkspace } from './ModelProviderWorkspace';
import { providerManagementAllowed } from './providerManagementModel';
import {
  AccountSettingsPage,
  GeneralSettingsPage,
  PreferenceUnavailablePage,
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
  models: { label: 'settings.models', description: 'settings.modelsDescription', Icon: CubeIcon },
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
  agents: { label: 'settings.agents', description: 'settings.agentsDescription', Icon: PersonIcon },
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
  });

  const selectedTenant = auth.tenants.find((tenant) => tenant.id === config.tenantId) ?? null;
  const selectedProject = auth.projects.find((project) => project.id === config.projectId) ?? null;
  const isResourceSection = isResource(section);
  const canManageProviders = providerManagementAllowed(config.mode, auth.user?.roles ?? []);
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
    setResourceCounts({ models: null, skills: null, plugins: null, agents: null });
  }, [initialSection, open]);

  useEffect(() => {
    if (!open) return;
    setResourceCounts({ models: null, skills: null, plugins: null, agents: null });
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
              : await client.listManagedAgents(signal);
        if (requestId !== resourceRequestId.current) return;
        setResourceItems(items);
        setLoadedResourceSection(resourceSection);
        setLoadedResourceContextKey(resourceContextKey);
        setResourceCounts((current) => ({
          ...current,
          [resourceSection]: items.length < 100 ? items.length : null,
        }));
        setSelectedResourceId((current) =>
          current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null,
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
    [config, resourceContextKey],
  );

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
        loadedResourceContextKey,
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
        loadedResourceContextKey,
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
    ],
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
      notifications: [
        t(sectionMeta.notifications.label),
        t(sectionMeta.notifications.description),
      ],
      models: [t(sectionMeta.models.label), t(sectionMeta.models.description)],
      skills: [t(sectionMeta.skills.label), t(sectionMeta.skills.description)],
      plugins: [t(sectionMeta.plugins.label), t(sectionMeta.plugins.description)],
      agents: [t(sectionMeta.agents.label), t(sectionMeta.agents.description)],
    }),
    [t],
  );
  const filteredSettingSections = useMemo(
    () => filterSettingsSections(query, settingsSearchCopy),
    [query, settingsSearchCopy],
  );
  const visibleSections = useMemo(
    () => new Set(filteredSettingSections),
    [filteredSettingSections],
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
      item,
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
                  {selectedTenant?.name || config.tenantId || t('settings.signedOut')} /{' '}
                  {selectedProject?.name || config.projectId || t('settings.project')}
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
                            : 'settings.aiResources',
                      )}
                      sections={group.sections.filter((candidate) =>
                        visibleSections.has(candidate),
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
                    {selectedTenant?.name || config.tenantId || t('settings.signedOut')}
                  </strong>
                  <small>
                    {selectedProject?.name || config.projectId || t('settings.project')}
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
                <PreferenceUnavailablePage section={section} />
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
                  config={config}
                  canManage={canManageProviders}
                  onConfigChange={onConfigChange}
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
                  actionError={resourceActionError}
                  busy={actionBusyId !== null}
                  mode={config.mode}
                  canManage={
                    selectedResource
                      ? managedResourceManagementAllowed(
                          config.mode,
                          auth.user?.roles ?? [],
                          section,
                          selectedResource,
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
                />
              ) : null}
            </main>
          </div>
        </section>
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
  return section === 'skills' || section === 'plugins' || section === 'agents';
}

function isCountedSection(
  section: SettingsSection,
): section is keyof SettingsResourceCounts {
  return section === 'models' || isResource(section);
}
