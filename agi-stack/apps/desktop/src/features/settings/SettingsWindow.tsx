import { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Badge, Button, Text, Theme } from '@radix-ui/themes';
import {
  CheckCircledIcon,
  ComponentInstanceIcon,
  Cross2Icon,
  CubeIcon,
  GearIcon,
  GlobeIcon,
  IdCardIcon,
  LockClosedIcon,
  MagicWandIcon,
  MagnifyingGlassIcon,
  PersonIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AuthState,
  ConnectionState,
  DesktopRuntimeConfig,
  LlmProviderMutationInput,
  LlmProviderValidationOutcome,
  ManagedAgentDefinition,
  ManagedLlmProvider,
  ManagedPlugin,
  ManagedSkill,
} from '../../types';
import { RuntimeConfigPanel } from '../runtime/RuntimeConfigPanel';
import { ProviderDetailEditor } from './ProviderDetailEditor';
import { providerManagementAllowed } from './providerManagementModel';
import './SettingsWindow.css';

export type SettingsSection =
  | 'account'
  | 'workspace'
  | 'general'
  | 'connection'
  | 'models'
  | 'skills'
  | 'plugins'
  | 'agents';

type ResourceSection = Extract<SettingsSection, 'models' | 'skills' | 'plugins' | 'agents'>;
type ManagedResource = ManagedLlmProvider | ManagedSkill | ManagedPlugin | ManagedAgentDefinition;

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
  account: { label: 'settings.account', description: 'settings.accountDescription', Icon: IdCardIcon },
  workspace: {
    label: 'settings.workspace',
    description: 'settings.workspaceDescription',
    Icon: CubeIcon,
  },
  general: { label: 'settings.general', description: 'settings.generalDescription', Icon: GlobeIcon },
  connection: {
    label: 'settings.connection',
    description: 'settings.connectionDescription',
    Icon: GearIcon,
  },
  models: { label: 'settings.models', description: 'settings.modelsDescription', Icon: CubeIcon },
  skills: { label: 'settings.skills', description: 'settings.skillsDescription', Icon: MagicWandIcon },
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
  const { locale, setLocale, t } = useI18n();
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [query, setQuery] = useState('');
  const [resourceItems, setResourceItems] = useState<ManagedResource[]>([]);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceError, setResourceError] = useState<string | null>(null);
  const [resourceFilter, setResourceFilter] = useState<'all' | 'active' | 'disabled'>('all');
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(null);
  const [selectedTenantId, setSelectedTenantId] = useState(config.tenantId);
  const [selectedProjectId, setSelectedProjectId] = useState(config.projectId);
  const [contextProjects, setContextProjects] = useState(auth.projects);
  const [contextProjectsLoading, setContextProjectsLoading] = useState(false);
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [contextApplying, setContextApplying] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  const selectedTenant = auth.tenants.find((tenant) => tenant.id === selectedTenantId) ?? null;
  const availableProjects = contextProjects.filter(
    (project) => !selectedTenantId || project.tenant_id === selectedTenantId,
  );
  const isResourceSection = isResource(section);
  const canManageProviders = providerManagementAllowed(config.mode, auth.user?.roles ?? []);

  const signOut = async () => {
    setSigningOut(true);
    try {
      await onSignOut();
    } finally {
      setSigningOut(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setSection(initialSection);
    setQuery('');
    setSelectedTenantId(config.tenantId);
    setSelectedProjectId(config.projectId);
    setContextProjects(auth.projects);
    setResourceFilter('all');
    setSelectedResourceId(null);
  }, [auth.projects, config.projectId, config.tenantId, initialSection, open]);

  useEffect(() => {
    if (!open || section !== 'workspace' || !selectedTenantId) return;
    const controller = new AbortController();
    setContextProjectsLoading(true);
    setContextError(null);
    const client = new DesktopApiClient({
      ...config,
      tenantId: selectedTenantId,
      projectId: '',
      workspaceId: '',
    });
    void client
      .listProjects(selectedTenantId, controller.signal)
      .then((projects) => {
        setContextProjects(projects);
        setSelectedProjectId((current) =>
          projects.some((project) => project.id === current) ? current : projects[0]?.id ?? '',
        );
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setContextProjects([]);
        setSelectedProjectId('');
        setContextError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setContextProjectsLoading(false);
      });
    return () => controller.abort();
  }, [config, open, section, selectedTenantId]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, open]);

  const loadResources = useCallback(
    async (resourceSection: ResourceSection, signal?: AbortSignal) => {
      setResourceLoading(true);
      setResourceError(null);
      try {
        const client = new DesktopApiClient(config);
        const items =
          resourceSection === 'models'
            ? await client.listLlmProviders(signal)
            : resourceSection === 'skills'
              ? await client.listManagedSkills(signal)
              : resourceSection === 'plugins'
                ? await client.listManagedPlugins(signal)
                : await client.listManagedAgents(signal);
        setResourceItems(items);
        setSelectedResourceId((current) =>
          current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null,
        );
      } catch (error) {
        setResourceItems([]);
        setResourceError(error instanceof Error ? error.message : String(error));
      } finally {
        setResourceLoading(false);
      }
    },
    [config],
  );

  useEffect(() => {
    if (!open || !isResourceSection) return;
    const controller = new AbortController();
    void loadResources(section, controller.signal);
    return () => controller.abort();
  }, [isResourceSection, loadResources, open, section]);

  const filteredItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return resourceItems.filter((item) => {
      const matchesQuery =
        !normalizedQuery || JSON.stringify(item).toLowerCase().includes(normalizedQuery);
      const active = resourceView(isResourceSection ? section : 'models', item).active;
      const matchesFilter =
        resourceFilter === 'all' ||
        (resourceFilter === 'active' ? active : !active);
      return matchesQuery && matchesFilter;
    });
  }, [isResourceSection, query, resourceFilter, resourceItems, section]);
  const selectedResource = useMemo(
    () =>
      filteredItems.find((item) => item.id === selectedResourceId) ?? filteredItems[0] ?? null,
    [filteredItems, selectedResourceId],
  );

  if (!open) return null;

  const chooseTenant = (tenantId: string) => {
    setSelectedTenantId(tenantId);
    setSelectedProjectId('');
  };

  const applyContext = async () => {
    if (!selectedTenantId || !selectedProjectId) return;
    setContextApplying(true);
    setContextError(null);
    try {
      await onContextChange(selectedTenantId, selectedProjectId);
      onClose();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      setContextApplying(false);
    }
  };

  const toggleResource = async (item: ManagedResource) => {
    if (!isResourceSection || section === 'models') return;
    setActionBusyId(item.id);
    setResourceError(null);
    try {
      const client = new DesktopApiClient(config);
      if (section === 'skills') {
        const skill = item as ManagedSkill;
        await client.setManagedSkillStatus(skill.id, skill.status === 'active' ? 'disabled' : 'active');
      } else if (section === 'plugins') {
        const plugin = item as ManagedPlugin;
        await client.setManagedPluginEnabled(plugin.name, !plugin.enabled);
      } else {
        const agent = item as ManagedAgentDefinition;
        await client.setManagedAgentEnabled(agent.id, agent.enabled === false);
      }
      await loadResources(section);
    } catch (error) {
      setResourceError(error instanceof Error ? error.message : String(error));
    } finally {
      setActionBusyId(null);
    }
  };

  const saveProvider = async (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ): Promise<ManagedLlmProvider> => {
    const client = new DesktopApiClient(config);
    const updated = await client.updateLlmProvider(provider.id, mutation);
    setResourceItems((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
    setSelectedResourceId(updated.id);
    if (config.mode === 'local') {
      onConfigChange({
        ...config,
        llmProvider: updated.is_active === false ? 'unconfigured' : updated.provider_type,
        llmBaseUrl: updated.base_url ?? '',
        llmModel: updated.is_active === false ? '' : updated.llm_model ?? '',
        llmApiKey: '',
      });
    }
    return updated;
  };

  const validateProvider = async (providerId: string): Promise<LlmProviderValidationOutcome> => {
    const outcome = await new DesktopApiClient(config).checkLlmProvider(providerId);
    if (outcome.provider) {
      setResourceItems((current) =>
        current.map((item) => (item.id === outcome.provider?.id ? outcome.provider : item)),
      );
    }
    return outcome;
  };

  const windowContent = (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="settings-window-backdrop" onMouseDown={onClose}>
        <section
          className="settings-window-dialog"
          role="dialog"
          aria-modal="true"
          aria-label={t('settings.title')}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <header className="settings-window-titlebar">
            <div className="settings-window-brand">
              <span><GearIcon /></span>
              <div>
                <strong>{t('settings.title')}</strong>
                <small>{t('settings.subtitle')}</small>
              </div>
            </div>
            <label className="settings-window-search">
              <MagnifyingGlassIcon />
              <input
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
              <SettingsGroup
                label={t('settings.accountContext')}
                sections={['account', 'workspace']}
                active={section}
                onSelect={setSection}
              />
              <SettingsGroup
                label={t('settings.preferences')}
                sections={['general', 'connection']}
                active={section}
                onSelect={setSection}
              />
              <SettingsGroup
                label={t('settings.aiResources')}
                sections={['models', 'skills', 'plugins', 'agents']}
                active={section}
                onSelect={setSection}
              />
              <div className="settings-window-scope">
                <LockClosedIcon />
                <span>
                  <strong>{selectedTenant?.name || config.tenantId || t('settings.signedOut')}</strong>
                  <small>{config.projectId || t('settings.project')}</small>
                </span>
              </div>
            </aside>

            <main className="settings-window-content">
              {section === 'account' ? (
                <SettingsPage
                  eyebrow={t('settings.account')}
                  title={t('settings.accountTitle')}
                  description={auth.user?.email || t('settings.signedOut')}
                >
                  <section className="settings-profile-card">
                    <span className="settings-profile-avatar"><PersonIcon /></span>
                    <div>
                      <strong>{auth.user?.name || auth.user?.email || t('settings.signedOut')}</strong>
                      <small>{auth.user?.email || config.apiBaseUrl}</small>
                    </div>
                    <Badge color={auth.status === 'signed_in' ? 'green' : 'gray'} variant="soft">
                      {auth.status}
                    </Badge>
                  </section>
                  {auth.session ? (
                    <section className="settings-session-card">
                      <header>
                        <div>
                          <strong>{t('settings.currentDeviceSession')}</strong>
                          <small>{auth.session.session_id}</small>
                        </div>
                        <Badge color={auth.session.trusted_device ? 'cyan' : 'gray'} variant="soft">
                          {t(
                            auth.session.trusted_device
                              ? 'settings.trustedDevice'
                              : 'settings.temporarySession',
                          )}
                        </Badge>
                      </header>
                      <dl>
                        <div>
                          <dt>{t('settings.authMethod')}</dt>
                          <dd>{auth.session.auth_method}</dd>
                        </div>
                        <div>
                          <dt>{t('settings.sessionExpires')}</dt>
                          <dd>
                            {auth.session.expires_at
                              ? new Date(auth.session.expires_at).toLocaleString(locale)
                              : t('settings.notAvailable')}
                          </dd>
                        </div>
                      </dl>
                    </section>
                  ) : null}
                  {auth.status === 'signed_in' ? (
                    <Button
                      color="red"
                      variant="soft"
                      loading={signingOut}
                      disabled={signingOut}
                      onClick={() => void signOut()}
                    >
                      {t('settings.signOut')}
                    </Button>
                  ) : null}
                </SettingsPage>
              ) : null}

              {section === 'workspace' ? (
                <SettingsPage
                  eyebrow={t('settings.currentContext')}
                  title={t('settings.tenantProject')}
                  description={t('settings.tenantProjectDescription')}
                >
                  <ContextPicker
                    title={t('settings.chooseTenant')}
                    items={auth.tenants.map((tenant) => ({ id: tenant.id, label: tenant.name }))}
                    selectedId={selectedTenantId}
                    onSelect={chooseTenant}
                  />
                  <ContextPicker
                    title={t('settings.chooseProject')}
                    items={availableProjects.map((project) => ({ id: project.id, label: project.name }))}
                    selectedId={selectedProjectId}
                    onSelect={setSelectedProjectId}
                  />
                  {contextProjectsLoading ? <SettingsState text={t('settings.loading')} /> : null}
                  <div className="settings-context-footer">
                    <span>
                      {selectedTenant?.name || '-'} /{' '}
                      {availableProjects.find((project) => project.id === selectedProjectId)?.name || '-'}
                    </span>
                    <Button
                      disabled={
                        !selectedTenantId ||
                        !selectedProjectId ||
                        contextProjectsLoading ||
                        (selectedTenantId === config.tenantId && selectedProjectId === config.projectId)
                      }
                      loading={contextApplying}
                      onClick={() => void applyContext()}
                    >
                      {t('settings.applyContext')}
                    </Button>
                  </div>
                  {contextError ? <SettingsState error text={contextError} /> : null}
                </SettingsPage>
              ) : null}

              {section === 'general' ? (
                <SettingsPage
                  eyebrow={t('settings.preferences')}
                  title={t('settings.general')}
                  description={t('settings.languageDescription')}
                >
                  <section className="settings-language-card">
                    <GlobeIcon />
                    <button
                      type="button"
                      className={locale === 'zh-CN' ? 'active' : ''}
                      onClick={() => setLocale('zh-CN')}
                    >
                      <span>简</span>
                      <strong>{t('settings.chinese')}</strong>
                      {locale === 'zh-CN' ? <CheckCircledIcon /> : null}
                    </button>
                    <button
                      type="button"
                      className={locale === 'en' ? 'active' : ''}
                      onClick={() => setLocale('en')}
                    >
                      <span>EN</span>
                      <strong>{t('settings.english')}</strong>
                      {locale === 'en' ? <CheckCircledIcon /> : null}
                    </button>
                  </section>
                </SettingsPage>
              ) : null}

              {section === 'connection' ? (
                <SettingsPage
                  eyebrow={t('runtime.connection')}
                  title={t('settings.connection')}
                  description={`${t('settings.server')}: ${config.apiBaseUrl}`}
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

              {isResourceSection ? (
                <SettingsPage
                  eyebrow={t(sectionMeta[section].label)}
                  title={t('settings.resourceTitle', { resource: t(sectionMeta[section].label) })}
                  description={t('settings.resourceDescription')}
                  action={
                    <div className="settings-resource-actions">
                      <div role="group" aria-label={t('settings.status')}>
                        {(['all', 'active', 'disabled'] as const).map((filter) => (
                          <button
                            type="button"
                            key={filter}
                            className={resourceFilter === filter ? 'active' : ''}
                            onClick={() => setResourceFilter(filter)}
                          >
                            {filter === 'all'
                              ? t('settings.all')
                              : filter === 'active'
                                ? t('settings.active')
                                : t('settings.disabled')}
                          </button>
                        ))}
                      </div>
                      <Button variant="soft" onClick={() => void loadResources(section)}>
                        <ReloadIcon /> {t('settings.refresh')}
                      </Button>
                    </div>
                  }
                >
                  {section === 'models' && config.mode === 'local' ? (
                    <div className="settings-resource-callout">
                      <CubeIcon />
                      <span>
                        <strong>{t('settings.localProvider')}</strong>
                        <small>{t('settings.localProviderDescription')}</small>
                      </span>
                    </div>
                  ) : null}
                  {resourceLoading ? <SettingsState text={t('settings.loading')} /> : null}
                  {!resourceLoading && resourceError ? (
                    <SettingsState error text={t('settings.unavailable')} detail={resourceError} />
                  ) : null}
                  {!resourceLoading && !resourceError && filteredItems.length === 0 ? (
                    <SettingsState text={t('settings.empty')} />
                  ) : null}
                  {!resourceLoading && filteredItems.length > 0 ? (
                    <div className="settings-resource-workspace">
                      <div className="settings-resource-list">
                        {filteredItems.map((item) => (
                          <ResourceRow
                            key={item.id}
                            section={section}
                            item={item}
                            selected={selectedResource?.id === item.id}
                            busy={actionBusyId === item.id}
                            onSelect={() => setSelectedResourceId(item.id)}
                            onAction={() => void toggleResource(item)}
                          />
                        ))}
                      </div>
                      {selectedResource ? (
                        <ResourceDetail
                          section={section}
                          item={selectedResource}
                          mode={config.mode}
                          canManageProviders={canManageProviders}
                          onSaveProvider={saveProvider}
                          onValidateProvider={validateProvider}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </SettingsPage>
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
  onSelect,
}: {
  label: string;
  sections: SettingsSection[];
  active: SettingsSection;
  onSelect: (section: SettingsSection) => void;
}) {
  const { t } = useI18n();
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
          </button>
        );
      })}
    </section>
  );
}

function SettingsPage({
  eyebrow,
  title,
  description,
  action,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="settings-page">
      <header className="settings-page-heading">
        <div>
          <Text size="1" color="gray">{eyebrow.toUpperCase()}</Text>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {action}
      </header>
      {children}
    </div>
  );
}

function ContextPicker({
  title,
  items,
  selectedId,
  onSelect,
}: {
  title: string;
  items: Array<{ id: string; label: string }>;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="settings-context-picker">
      <h2>{title}</h2>
      <div>
        {items.map((item) => (
          <button
            type="button"
            key={item.id}
            className={selectedId === item.id ? 'active' : ''}
            onClick={() => onSelect(item.id)}
          >
            <CubeIcon />
            <strong>{item.label}</strong>
            {selectedId === item.id ? <CheckCircledIcon /> : null}
          </button>
        ))}
      </div>
    </section>
  );
}

function ResourceRow({
  section,
  item,
  selected,
  busy,
  onSelect,
  onAction,
}: {
  section: ResourceSection;
  item: ManagedResource;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onAction: () => void;
}) {
  const { t } = useI18n();
  const view = resourceView(section, item);
  const canAct = section !== 'models';
  return (
    <article className={`settings-resource-row ${selected ? 'selected' : ''}`}>
      <button type="button" className="settings-resource-main" onClick={onSelect}>
        <span className="settings-resource-icon"><view.Icon /></span>
        <div>
          <strong>{view.name}</strong>
          <p>{view.description}</p>
          <div className="settings-resource-meta">
            {view.meta.map((value) => <span key={value}>{value}</span>)}
          </div>
        </div>
      </button>
      <aside>
        <Badge color={view.active ? 'green' : 'gray'} variant="soft">{view.status}</Badge>
        {canAct ? (
          <Button size="1" variant="soft" loading={busy} onClick={onAction}>
            {view.active ? t('settings.disable') : t('settings.enable')}
          </Button>
        ) : null}
      </aside>
    </article>
  );
}

function ResourceDetail({
  section,
  item,
  mode,
  canManageProviders,
  onSaveProvider,
  onValidateProvider,
}: {
  section: ResourceSection;
  item: ManagedResource;
  mode: DesktopRuntimeConfig['mode'];
  canManageProviders: boolean;
  onSaveProvider: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
  onValidateProvider: (providerId: string) => Promise<LlmProviderValidationOutcome>;
}) {
  const { t } = useI18n();
  if (section === 'models') {
    return (
      <ProviderDetailEditor
        provider={item as ManagedLlmProvider}
        mode={mode}
        canManage={canManageProviders}
        onSave={onSaveProvider}
        onValidate={onValidateProvider}
      />
    );
  }
  const view = resourceView(section, item);
  const facts = resourceFacts(section, item, t);
  const capabilities = resourceCapabilities(section, item);
  return (
    <aside className="settings-resource-detail">
      <header>
        <span className="settings-resource-icon"><view.Icon /></span>
        <div>
          <Text size="1" color="gray">{t(sectionMeta[section].label).toUpperCase()}</Text>
          <h2>{view.name}</h2>
          <p>{view.description}</p>
        </div>
        <Badge color={view.active ? 'green' : 'gray'} variant="soft">{view.status}</Badge>
      </header>
      <dl>
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <section>
        <Text size="1" color="gray">{t('settings.capabilitiesRelationships').toUpperCase()}</Text>
        {capabilities.length > 0 ? (
          <div className="settings-detail-chips">
            {capabilities.map((capability, index) => (
              <span key={`${capability}-${index}`}>{capability}</span>
            ))}
          </div>
        ) : (
          <p className="settings-detail-empty">{t('settings.noCapabilities')}</p>
        )}
      </section>
    </aside>
  );
}

function resourceFacts(
  section: ResourceSection,
  item: ManagedResource,
  t: (key: string) => string,
): Array<[string, string]> {
  if (section === 'models') {
    const provider = item as ManagedLlmProvider;
    return [
      [t('settings.providerType'), provider.provider_type],
      [t('settings.model'), provider.llm_model || t('settings.notConfigured')],
      [t('settings.endpoint'), provider.base_url || t('settings.providerDefault')],
      [t('settings.health'), provider.health_status || t('settings.notChecked')],
    ];
  }
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return [
      [t('settings.scope'), skill.scope],
      [t('settings.version'), `v${skill.current_version ?? 0}`],
      [t('settings.status'), skill.status],
      [t('settings.source'), skill.is_system_skill ? t('settings.system') : t('settings.managed')],
    ];
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return [
      [t('settings.source'), plugin.source],
      [t('settings.package'), plugin.package || t('settings.builtIn')],
      [t('settings.version'), plugin.version || t('settings.unversioned')],
      [
        t('settings.discovery'),
        plugin.discovered ? t('settings.discovered') : t('settings.unavailable'),
      ],
    ];
  }
  const agent = item as ManagedAgentDefinition;
  return [
    [t('settings.model'), agent.model_name || t('settings.tenantDefault')],
    [
      t('settings.status'),
      agent.enabled === false ? t('settings.disabled') : agent.status || t('settings.active'),
    ],
    [t('settings.tools'), String(agent.allowed_tools?.length ?? 0)],
    [t('settings.skills'), String(agent.allowed_skills?.length ?? 0)],
  ];
}

function resourceCapabilities(section: ResourceSection, item: ManagedResource): string[] {
  if (section === 'models') {
    const provider = item as ManagedLlmProvider;
    return [...(provider.allowed_models ?? []), ...(provider.secondary_models ?? [])].slice(0, 20);
  }
  if (section === 'skills') return (item as ManagedSkill).tools.slice(0, 20);
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return [
      ...(plugin.providers ?? []),
      ...(plugin.skills ?? []),
      ...(plugin.channel_types ?? []),
      ...(plugin.tool_definitions ?? []).map((tool) => String(tool.name ?? 'tool')),
    ].slice(0, 20);
  }
  const agent = item as ManagedAgentDefinition;
  return [
    ...(agent.allowed_tools ?? []),
    ...(agent.allowed_skills ?? []),
    ...(agent.allowed_mcp_servers ?? []),
  ].slice(0, 20);
}

function resourceView(section: ResourceSection, item: ManagedResource) {
  if (section === 'models') {
    const provider = item as ManagedLlmProvider;
    return {
      name: provider.name || provider.provider_type,
      description: provider.base_url || provider.llm_model || provider.provider_type,
      status: provider.health_status || (provider.is_active === false ? 'disabled' : 'active'),
      active: provider.is_active !== false,
      meta: [provider.provider_type, provider.llm_model].filter(Boolean) as string[],
      Icon: CubeIcon,
    };
  }
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return {
      name: skill.name,
      description: skill.description,
      status: skill.status,
      active: skill.status === 'active',
      meta: [skill.scope, `${skill.tools.length} tools`, `v${skill.current_version ?? 0}`],
      Icon: MagicWandIcon,
    };
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return {
      name: plugin.name,
      description: plugin.package || plugin.kind || plugin.source,
      status: plugin.enabled ? 'active' : 'disabled',
      active: plugin.enabled,
      meta: [plugin.source, plugin.version, `${plugin.tool_definitions?.length ?? 0} tools`].filter(
        Boolean,
      ) as string[],
      Icon: ComponentInstanceIcon,
    };
  }
  const agent = item as ManagedAgentDefinition;
  return {
    name: agent.name,
    description: agent.display_name || agent.system_prompt || agent.model_name || agent.id,
    status: agent.enabled === false ? 'disabled' : agent.status || 'active',
    active: agent.enabled !== false,
    meta: [
      agent.model_name,
      `${agent.allowed_tools?.length ?? 0} tools`,
      `${agent.allowed_skills?.length ?? 0} skills`,
    ].filter(Boolean) as string[],
    Icon: PersonIcon,
  };
}

function SettingsState({ text, detail, error = false }: { text: string; detail?: string; error?: boolean }) {
  return (
    <div className={`settings-resource-state ${error ? 'error' : ''}`}>
      <strong>{text}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function isResource(section: SettingsSection): section is ResourceSection {
  return section === 'models' || section === 'skills' || section === 'plugins' || section === 'agents';
}
