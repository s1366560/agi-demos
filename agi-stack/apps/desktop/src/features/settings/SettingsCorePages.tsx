import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Badge, Button, Text } from '@radix-ui/themes';
import {
  BellIcon,
  CheckCircledIcon,
  ComponentInstanceIcon,
  CubeIcon,
  FontStyleIcon,
  GlobeIcon,
  LockClosedIcon,
  MagicWandIcon,
  PersonIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import { useThemePreference, type ThemePreference } from '../../theme';
import type {
  AuthState,
  DesktopRuntimeConfig,
  ProjectSummary,
  TenantSummary,
} from '../../types';
import { SettingsState } from './ManagedResourceViews';
import {
  type NotificationDelivery,
  useNotificationPreferences,
} from './notificationPreferences';
import { projectsForTenant, type SettingsSection } from './settingsNavigationModel';
import './SettingsCorePages.css';

type ResourceSection = Extract<
  SettingsSection,
  'models' | 'mcp' | 'skills' | 'plugins' | 'agents' | 'subagents'
>;
export type SettingsResourceCounts = Record<ResourceSection, number | null>;

export function SettingsPage({
  eyebrow,
  title,
  description,
  action,
  children,
  className = '',
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`settings-page ${className}`.trim()}>
      <header className="settings-page-heading">
        <div>
          <Text size="1" color="gray">
            {eyebrow.toUpperCase()}
          </Text>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {action}
      </header>
      {children}
    </div>
  );
}

export function AccountSettingsPage({
  auth,
  tenant,
  config,
  onSignOut,
}: {
  auth: AuthState;
  tenant: TenantSummary | null;
  config: DesktopRuntimeConfig;
  onSignOut: () => void | Promise<void>;
}) {
  const { locale, t } = useI18n();
  const [signingOut, setSigningOut] = useState(false);
  const session = auth.session;
  const user = auth.user;

  const signOut = async () => {
    setSigningOut(true);
    try {
      await onSignOut();
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <SettingsPage
      eyebrow={t('settings.accountEyebrow')}
      title={t('settings.accountTitle')}
      description={t('settings.accountSubtitle')}
      className="settings-account-page"
    >
      <section className="settings-panel settings-account-profile">
        <div className="settings-account-hero">
          <span className="settings-profile-avatar">
            <PersonIcon />
          </span>
          <div>
            <strong>{user?.name || user?.email || t('settings.signedOut')}</strong>
            <small>{user?.email || config.apiBaseUrl}</small>
            <Badge color={auth.status === 'signed_in' ? 'green' : 'gray'} variant="soft">
              {t(`settings.authStatus.${auth.status}`)}
            </Badge>
          </div>
        </div>
        <div className="settings-rows">
          <SettingsRow
            label={t('settings.authMethod')}
            value={session ? authMethodLabel(session.auth_method, t) : t('settings.notAvailable')}
          />
          <SettingsRow
            label={t('settings.currentOrganization')}
            value={tenant?.name || t('settings.notAvailable')}
            description={tenant?.plan || tenant?.slug || undefined}
          />
          <SettingsRow
            label={t('settings.sessionSecurity')}
            value={
              session
                ? t(session.trusted_device ? 'settings.trustedDevice' : 'settings.temporarySession')
                : t('settings.notAvailable')
            }
          />
        </div>
      </section>

      <section className="settings-panel settings-security-panel">
        <header>
          <LockClosedIcon />
          <span>
            <strong>{t('settings.security')}</strong>
            <small>{t('settings.securityDescription')}</small>
          </span>
        </header>
        <div className="settings-rows">
          <SettingsRow
            label={t('settings.sessionExpires')}
            value={
              session?.expires_at
                ? new Date(session.expires_at).toLocaleString(locale)
                : t('settings.notAvailable')
            }
          />
          <SettingsRow
            label={t('settings.accountCreated')}
            value={
              user?.created_at
                ? new Date(user.created_at).toLocaleDateString(locale)
                : t('settings.notAvailable')
            }
          />
          <SettingsRow
            label={t('settings.workspaceRoles')}
            value={user?.roles.length ? user.roles.join(', ') : t('settings.notAvailable')}
          />
        </div>
      </section>

      {auth.status === 'signed_in' ? (
        <button
          className="settings-signout"
          type="button"
          disabled={signingOut}
          onClick={() => void signOut()}
        >
          {signingOut ? t('settings.signingOut') : t('settings.signOutOfMemStack')}
        </button>
      ) : null}
    </SettingsPage>
  );
}

export function WorkspaceSettingsPage({
  auth,
  config,
  onContextChange,
  onApplied,
}: {
  auth: AuthState;
  config: DesktopRuntimeConfig;
  onContextChange: (tenantId: string, projectId: string) => Promise<void>;
  onApplied: () => void;
}) {
  const { t } = useI18n();
  const [tenantId, setTenantId] = useState(config.tenantId);
  const [projectId, setProjectId] = useState(config.projectId);
  const [projects, setProjects] = useState(() =>
    projectsForTenant(auth.projects, config.tenantId),
  );
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [controlPlaneOpening, setControlPlaneOpening] = useState(false);
  const [controlPlaneError, setControlPlaneError] = useState<string | null>(null);
  const [webControlPlaneCapability, setWebControlPlaneCapability] =
    useState<WebControlPlaneCapability>({
      availability: 'unavailable',
      contractVersion: 1,
      reasonCode: 'capability_snapshot_loading',
      source: 'none',
    });
  const applyingRef = useRef(false);
  const getCapabilities = window.__MEMSTACK_DESKTOP__?.getCapabilities;
  const openWebControlPlane = window.__MEMSTACK_DESKTOP__?.openWebControlPlane;

  useEffect(() => {
    setTenantId(config.tenantId);
    setProjectId(config.projectId);
    setProjects(projectsForTenant(auth.projects, config.tenantId));
  }, [auth.projects, config.projectId, config.tenantId]);

  useEffect(() => {
    let active = true;
    if (!getCapabilities) {
      setWebControlPlaneCapability({
        availability: 'unavailable',
        contractVersion: 1,
        reasonCode: 'capability_snapshot_unavailable',
        source: 'none',
      });
      return;
    }
    void getCapabilities()
      .then((snapshot) => {
        if (active) setWebControlPlaneCapability(snapshot.webControlPlane);
      })
      .catch(() => {
        if (!active) return;
        setWebControlPlaneCapability({
          availability: 'unavailable',
          contractVersion: 1,
          reasonCode: 'capability_snapshot_unavailable',
          source: 'none',
        });
      });
    return () => {
      active = false;
    };
  }, [getCapabilities]);

  useEffect(() => {
    if (!tenantId) return;
    const controller = new AbortController();
    const client = new DesktopApiClient({
      ...config,
      tenantId,
      projectId: '',
      workspaceId: '',
    });
    setLoading(true);
    setError(null);
    void client
      .listProjects(tenantId, controller.signal)
      .then((items) => {
        const scopedItems = projectsForTenant(items, tenantId);
        setProjects(scopedItems);
        setProjectId((current) =>
          scopedItems.some((project) => project.id === current)
            ? current
            : scopedItems[0]?.id ?? '',
        );
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setProjects([]);
        setProjectId('');
        setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [config, tenantId]);

  const selectedTenant = auth.tenants.find((tenant) => tenant.id === tenantId) ?? null;
  const selectedProject = projects.find((project) => project.id === projectId) ?? null;
  const currentTenant = auth.tenants.find((tenant) => tenant.id === config.tenantId) ?? null;
  const currentProject = auth.projects.find((project) => project.id === config.projectId) ?? null;
  const hasCurrentContext = Boolean(config.tenantId.trim() && config.projectId.trim());
  const changed = tenantId !== config.tenantId || projectId !== config.projectId;

  const chooseTenant = (nextTenantId: string) => {
    if (loading || applyingRef.current) return;
    setProjects([]);
    setTenantId(nextTenantId);
    setProjectId('');
  };

  const applyContext = async () => {
    if (!tenantId || !projectId || applyingRef.current) return;
    applyingRef.current = true;
    setApplying(true);
    setError(null);
    try {
      await onContextChange(tenantId, projectId);
      onApplied();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      applyingRef.current = false;
      setApplying(false);
    }
  };

  const openProjectControlPlane = async () => {
    if (
      webControlPlaneCapability.availability !== 'available' ||
      !openWebControlPlane ||
      !config.tenantId ||
      !config.projectId
    ) {
      return;
    }
    setControlPlaneOpening(true);
    setControlPlaneError(null);
    try {
      await openWebControlPlane({
        destination: 'project-settings',
        tenantId: config.tenantId,
        projectId: config.projectId,
      });
    } catch (caught) {
      setControlPlaneError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setControlPlaneOpening(false);
    }
  };

  return (
    <SettingsPage
      eyebrow={t('settings.workspaceContextEyebrow')}
      title={t('settings.tenantProject')}
      description={t('settings.tenantProjectDescription')}
      className="settings-workspace-page"
    >
      <section className="settings-current-context">
        <span>
          <small>{t('settings.currentContext')}</small>
          <strong>
            {currentTenant?.name || config.tenantId || t('settings.noTenantSelected')}
            <i>/</i>
            {currentProject?.name || config.projectId || t('settings.noProjectSelected')}
          </strong>
        </span>
        <em>
          <LockClosedIcon /> {t('settings.tenantIsolated')}
        </em>
      </section>

      <ContextStep
        number="1"
        title={t('settings.chooseTenant')}
        description={t('settings.chooseTenantDescription')}
      >
        <div className="settings-tenant-list">
          {auth.tenants.map((tenant) => (
            <button
              type="button"
              key={tenant.id}
              className={tenant.id === tenantId ? 'active' : ''}
              aria-pressed={tenant.id === tenantId}
              disabled={loading || applying}
              onClick={() => chooseTenant(tenant.id)}
            >
              <span className="settings-choice-icon">
                <CubeIcon />
              </span>
              <span>
                <strong>{tenant.name}</strong>
                <small>{tenant.description || tenant.slug || t('settings.noDescription')}</small>
              </span>
              {tenant.plan ? <em>{tenant.plan}</em> : null}
              {tenant.id === tenantId ? <CheckCircledIcon /> : null}
            </button>
          ))}
        </div>
      </ContextStep>

      <ContextStep
        number="2"
        title={t('settings.chooseProject')}
        description={t('settings.chooseProjectDescription')}
      >
        {loading ? <SettingsState text={t('settings.loading')} /> : null}
        {!loading && !tenantId && !error ? (
          <div className="settings-project-empty" role="status">
            <span className="settings-choice-icon">
              <CubeIcon />
            </span>
            <span>
              <strong>{t('settings.noTenantSelected')}</strong>
              <small>{t('settings.chooseTenantFirst')}</small>
            </span>
          </div>
        ) : null}
        {!loading && tenantId && projects.length === 0 && !error ? (
          <div className="settings-project-empty" role="status">
            <span className="settings-choice-icon">
              <CubeIcon />
            </span>
            <span>
              <strong>{t('settings.noProjects')}</strong>
              <small>{t('settings.noProjectsDescription')}</small>
            </span>
          </div>
        ) : null}
        {!loading && projects.length > 0 ? (
          <div className="settings-project-grid">
            {projects.map((project) => (
              <ProjectChoice
                key={project.id}
                project={project}
                selected={project.id === projectId}
                disabled={applying}
                onSelect={() => setProjectId(project.id)}
              />
            ))}
          </div>
        ) : null}
      </ContextStep>

      {error ? <SettingsState error text={t('settings.unavailable')} detail={error} /> : null}

      <footer className="settings-context-apply">
        <div>
          <ReloadIcon />
          <span>
            <strong>{t('settings.contextChange')}</strong>
            <small>{t('settings.contextChangeDescription')}</small>
          </span>
        </div>
        <Button
          disabled={!changed || !tenantId || !projectId || loading || applying}
          loading={applying}
          onClick={() => void applyContext()}
        >
          {!hasCurrentContext || changed
            ? t('settings.switchWorkspace')
            : t('settings.currentWorkspace')}
        </Button>
      </footer>

      <span className="settings-context-preview" aria-live="polite">
        {selectedTenant?.name || t('settings.notAvailable')} /{' '}
        {selectedProject?.name || t('settings.noProjectSelected')}
      </span>

      <section className="settings-panel settings-control-plane-panel">
        <header>
          <GlobeIcon />
          <span>
            <strong>{t('settings.webControlPlane')}</strong>
            <small>{t('settings.webControlPlaneDescription')}</small>
          </span>
          <Button
            disabled={
              webControlPlaneCapability.availability !== 'available' ||
              !openWebControlPlane ||
              !config.tenantId ||
              !config.projectId ||
              controlPlaneOpening
            }
            loading={controlPlaneOpening}
            onClick={() => void openProjectControlPlane()}
          >
            {t('settings.openWebControlPlane')}
          </Button>
        </header>
        {controlPlaneError ? (
          <div className="settings-inline-error" role="alert">
            {controlPlaneError}
          </div>
        ) : null}
      </section>
    </SettingsPage>
  );
}

export function GeneralSettingsPage({
  counts,
  onOpenResource,
}: {
  counts: SettingsResourceCounts;
  onOpenResource: (section: ResourceSection) => void;
}) {
  const { locale, setLocale, t } = useI18n();
  const formatPreview = useMemo(() => {
    const date = new Date(Date.UTC(2026, 6, 11, 12));
    return {
      timezone: new Intl.DateTimeFormat(locale).resolvedOptions().timeZone,
      date: new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date),
      number: new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(12345.67),
    };
  }, [locale]);
  const resources = [
    ['models', CubeIcon],
    ['mcp', ComponentInstanceIcon],
    ['skills', MagicWandIcon],
    ['plugins', ComponentInstanceIcon],
    ['agents', PersonIcon],
    ['subagents', PersonIcon],
  ] as const;

  return (
    <SettingsPage
      eyebrow={t('settings.preferences')}
      title={t('settings.generalTitle')}
      description={t('settings.generalSubtitle')}
      className="settings-general-page"
    >
      <section className="settings-panel settings-language-panel">
        <header>
          <GlobeIcon />
          <span>
            <strong>{t('settings.language')}</strong>
            <small>{t('settings.languageDescription')}</small>
          </span>
          <em>{locale === 'zh-CN' ? 'ZH-CN' : 'EN'}</em>
        </header>
        <div className="settings-language-options" role="group" aria-label={t('settings.language')}>
          <LanguageOption
            badge={t('settings.chineseBadge')}
            label={t('settings.chinese')}
            detail={t('settings.chineseLocaleName')}
            selected={locale === 'zh-CN'}
            onSelect={() => setLocale('zh-CN')}
          />
          <LanguageOption
            badge={t('settings.englishBadge')}
            label={t('settings.english')}
            detail={t('settings.englishLocaleName')}
            selected={locale === 'en'}
            onSelect={() => setLocale('en')}
          />
        </div>
      </section>

      <section className="settings-panel settings-region-panel">
        <header>
          <GlobeIcon />
          <span>
            <strong>{t('settings.region')}</strong>
            <small>{t('settings.regionDescription')}</small>
          </span>
        </header>
        <div className="settings-rows">
          <SettingsRow
            label={t('settings.timezone')}
            value={formatPreview.timezone || t('settings.notAvailable')}
          />
          <SettingsRow label={t('settings.dateFormat')} value={formatPreview.date} />
          <SettingsRow label={t('settings.numberFormat')} value={formatPreview.number} />
        </div>
      </section>

      <section className="settings-panel settings-resource-entry-panel">
        <header>
          <LockClosedIcon />
          <span>
            <strong>{t('settings.aiResources')}</strong>
            <small>{t('settings.agentResourcesDescription')}</small>
          </span>
        </header>
        <div className="settings-resource-entry-grid">
          {resources.map(([section, Icon]) => (
            <button type="button" key={section} onClick={() => onOpenResource(section)}>
              <Icon />
              <span>
                <strong>{t(`settings.${section}`)}</strong>
                <small>{t(`settings.${section}Description`)}</small>
              </span>
              <em>{counts[section] ?? '—'}</em>
              <b>{t('settings.open')}</b>
            </button>
          ))}
        </div>
      </section>
    </SettingsPage>
  );
}

export function PreferenceSummaryPage({
  section,
}: {
  section: 'appearance' | 'notifications';
}) {
  const { t } = useI18n();
  const { preference, setPreference } = useThemePreference();
  const Icon = section === 'appearance' ? FontStyleIcon : BellIcon;
  const themeOptions: { value: ThemePreference; label: string; description: string }[] = [
    {
      value: 'dark',
      label: t('settings.themeDark'),
      description: t('settings.themeDarkDescription'),
    },
    {
      value: 'light',
      label: t('settings.themeLight'),
      description: t('settings.themeLightDescription'),
    },
    {
      value: 'system',
      label: t('settings.themeSystem'),
      description: t('settings.themeSystemDescription'),
    },
  ];
  const rows =
    section === 'appearance'
      ? [
          ['settings.density', 'settings.densityValue'],
          ['settings.motion', 'settings.motionValue'],
        ]
      : [];

  return (
    <SettingsPage
      eyebrow={t('settings.preferences')}
      title={t(`settings.${section}Title`)}
      description={t(`settings.${section}Subtitle`)}
      className="settings-preference-page"
    >
      {section === 'appearance' ? (
        <section className="settings-panel settings-theme-panel">
          <header>
            <FontStyleIcon />
            <span>
              <strong>{t('settings.theme')}</strong>
              <small>{t('settings.themeDescription')}</small>
            </span>
          </header>
          <div
            className="settings-language-options settings-theme-options"
            role="radiogroup"
            aria-label={t('settings.themeGroupLabel')}
          >
            {themeOptions.map((option) => (
              <ThemeOption
                key={option.value}
                label={option.label}
                detail={option.description}
                selected={preference === option.value}
                onSelect={() => setPreference(option.value)}
              />
            ))}
          </div>
        </section>
      ) : null}
      {section === 'notifications' ? (
        <NotificationPreferenceControls />
      ) : (
        <section className="settings-panel settings-preference-summary">
          <header>
            <Icon />
            <span>
              <strong>{t(`settings.${section}Summary`)}</strong>
              <small>{t(`settings.${section}SummaryDescription`)}</small>
            </span>
          </header>
          <div className="settings-rows">
            {rows.map(([label, value]) => (
              <SettingsRow key={label} label={t(label)} value={t(value)} />
            ))}
          </div>
        </section>
      )}
    </SettingsPage>
  );
}

function NotificationPreferenceControls() {
  const { t } = useI18n();
  const { preferences, setPreferences } = useNotificationPreferences();
  const deliveryOptions: Array<{
    value: NotificationDelivery;
    label: string;
  }> = [
    {
      value: 'desktop_and_in_app',
      label: t('settings.deliveryDesktopAndInApp'),
    },
    {
      value: 'desktop',
      label: t('settings.deliveryDesktopOnly'),
    },
    {
      value: 'in_app',
      label: t('settings.deliveryInAppOnly'),
    },
  ];

  return (
    <section className="settings-panel settings-preference-summary">
      <header>
        <BellIcon />
        <span>
          <strong>{t('settings.notificationsSummary')}</strong>
          <small>{t('settings.notificationsSummaryDescription')}</small>
        </span>
      </header>
      <div className="settings-notification-controls">
        <PreferenceSwitch
          label={t('settings.reviewAlerts')}
          description={t('settings.reviewAlertsDescription')}
          checked={preferences.reviewAlerts}
          onChange={(reviewAlerts) =>
            setPreferences((current) => ({ ...current, reviewAlerts }))
          }
        />
        <fieldset className="settings-delivery-options">
          <legend>{t('settings.delivery')}</legend>
          <p>{t('settings.deliveryDescription')}</p>
          <div role="radiogroup" aria-label={t('settings.deliveryGroupLabel')}>
            {deliveryOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={preferences.delivery === option.value}
                className={preferences.delivery === option.value ? 'active' : ''}
                onClick={() =>
                  setPreferences((current) => ({
                    ...current,
                    delivery: option.value,
                  }))
                }
              >
                {option.label}
                {preferences.delivery === option.value ? <CheckCircledIcon /> : null}
              </button>
            ))}
          </div>
        </fieldset>
        <PreferenceSwitch
          label={t('settings.quietHours')}
          description={t('settings.quietHoursDescription')}
          checked={preferences.quietHours.enabled}
          onChange={(enabled) =>
            setPreferences((current) => ({
              ...current,
              quietHours: { ...current.quietHours, enabled },
            }))
          }
        />
        {preferences.quietHours.enabled ? (
          <div className="settings-quiet-hours">
            <label>
              <span>{t('settings.quietHoursStart')}</span>
              <input
                type="time"
                value={preferences.quietHours.start}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    quietHours: {
                      ...current.quietHours,
                      start: event.currentTarget.value,
                    },
                  }))
                }
              />
            </label>
            <label>
              <span>{t('settings.quietHoursEnd')}</span>
              <input
                type="time"
                value={preferences.quietHours.end}
                onChange={(event) =>
                  setPreferences((current) => ({
                    ...current,
                    quietHours: {
                      ...current.quietHours,
                      end: event.currentTarget.value,
                    },
                  }))
                }
              />
            </label>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function PreferenceSwitch({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="settings-preference-switch-row">
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        className={checked ? 'active' : ''}
        onClick={() => onChange(!checked)}
      >
        <i aria-hidden="true" />
        {t(checked ? 'settings.preferenceOn' : 'settings.preferenceOff')}
      </button>
    </div>
  );
}

function ThemeOption({
  label,
  detail,
  selected,
  onSelect,
}: {
  label: string;
  detail: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      className={selected ? 'active' : ''}
      onClick={onSelect}
    >
      <div>
        <strong>{label}</strong>
        <small>{detail}</small>
      </div>
      {selected ? <CheckCircledIcon /> : null}
    </button>
  );
}

function SettingsRow({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description?: string;
}) {
  return (
    <div className="settings-row">
      <span>
        <strong>{label}</strong>
        {description ? <small>{description}</small> : null}
      </span>
      <b>{value}</b>
    </div>
  );
}

function ContextStep({
  number,
  title,
  description,
  children,
}: {
  number: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="settings-context-step">
      <header>
        <span>{number}</span>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </header>
      {children}
    </section>
  );
}

function ProjectChoice({
  project,
  selected,
  disabled,
  onSelect,
}: {
  project: ProjectSummary;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      className={selected ? 'active' : ''}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="settings-choice-icon">
        <CubeIcon />
      </span>
      <span>
        <strong>{project.name}</strong>
        <small>{project.description || t('settings.noDescription')}</small>
        <em>
          {project.member_ids
            ? t(
                project.member_ids.length === 1
                  ? 'settings.memberCountOne'
                  : 'settings.memberCount',
                { count: project.member_ids.length },
              )
            : t('settings.membersUnavailable')}
          {' · '}
          {t(
            project.is_public === undefined
              ? 'settings.visibilityUnavailable'
              : project.is_public
                ? 'settings.publicProject'
                : 'settings.privateProject',
          )}
        </em>
      </span>
      {selected ? <CheckCircledIcon /> : null}
    </button>
  );
}

function LanguageOption({
  badge,
  label,
  detail,
  selected,
  onSelect,
}: {
  badge: string;
  label: string;
  detail: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={selected ? 'active' : ''} onClick={onSelect}>
      <span>{badge}</span>
      <div>
        <strong>{label}</strong>
        <small>{detail}</small>
      </div>
      {selected ? <CheckCircledIcon /> : null}
    </button>
  );
}

function authMethodLabel(method: string, t: (key: string) => string): string {
  const keyByMethod: Record<string, string> = {
    password: 'settings.authMethod.password',
    workspace_sso: 'settings.authMethod.workspaceSso',
    api_key: 'settings.authMethod.apiKey',
    local: 'settings.authMethod.local',
  };
  const key = keyByMethod[method];
  return key ? t(key) : method;
}
