import {
  ComponentInstanceIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  MagicWandIcon,
  MagnifyingGlassIcon,
  PersonIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { RuntimeMode } from '../../types';
import type {
  ManagedResource,
  ManagedResourceListFilter,
  ResourceSection,
} from './managedResourceModel';
import {
  managedResourceAction,
  managedResourceCapabilityGroups,
  managedResourceFacts,
  managedResourceView,
  resourceIsImmutable,
} from './managedResourceModel';

import './ManagedResourceViews.css';

export type { ManagedResource, ResourceSection } from './managedResourceModel';
export { resourceIsActive } from './managedResourceModel';

const sectionMeta = {
  skills: {
    label: 'settings.skills',
    eyebrow: 'settings.skillsEyebrow',
    singular: 'settings.skill',
    Icon: MagicWandIcon,
  },
  plugins: {
    label: 'settings.plugins',
    eyebrow: 'settings.pluginsEyebrow',
    singular: 'settings.plugin',
    Icon: ComponentInstanceIcon,
  },
  agents: {
    label: 'settings.agents',
    eyebrow: 'settings.agentsEyebrow',
    singular: 'settings.agent',
    Icon: PersonIcon,
  },
} as const;

export function ManagedResourceWorkspace({
  section,
  items,
  selected,
  query,
  filter,
  loading,
  error,
  actionError,
  busy,
  canManage,
  mode,
  onQueryChange,
  onFilterChange,
  onSelect,
  onRetry,
  onAction,
}: {
  section: ResourceSection;
  items: ManagedResource[];
  selected: ManagedResource | null;
  query: string;
  filter: ManagedResourceListFilter;
  loading: boolean;
  error: string | null;
  actionError: string | null;
  busy: boolean;
  canManage: boolean;
  mode: RuntimeMode;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: ManagedResourceListFilter) => void;
  onSelect: (id: string) => void;
  onRetry: () => void;
  onAction: (item: ManagedResource) => void;
}) {
  const { t } = useI18n();
  const meta = sectionMeta[section];

  return (
    <div className={`managed-resource-workspace ${section}`}>
      <section className="managed-resource-catalog">
        <header>
          <div>
            <span>{t(meta.eyebrow)}</span>
            <h1>{t(meta.label)}</h1>
          </div>
        </header>
        <label className="managed-resource-search">
          <MagnifyingGlassIcon />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={t('settings.searchResources', { resource: t(meta.label).toLowerCase() })}
            aria-label={t('settings.searchResources', { resource: t(meta.label).toLowerCase() })}
          />
        </label>
        <div className="managed-resource-filters" role="group" aria-label={t('settings.status')}>
          {(['all', 'active', 'attention'] as const).map((value) => (
            <button
              type="button"
              key={value}
              className={filter === value ? 'active' : ''}
              aria-pressed={filter === value}
              onClick={() => onFilterChange(value)}
            >
              {t(`settings.${value}`)}
            </button>
          ))}
        </div>
        <div className="managed-resource-count">
          <span>
            {t('settings.resourceCount', { count: items.length, resource: t(meta.label) })}
          </span>
        </div>
        <div className="managed-resource-list">
          {loading ? <CatalogState text={t('settings.loading')} /> : null}
          {!loading && error ? (
            <CatalogState
              error
              text={t('settings.unavailable')}
              detail={error}
              action={t('settings.retry')}
              onAction={onRetry}
            />
          ) : null}
          {!loading && !error && items.length === 0 ? (
            <CatalogState
              text={query.trim() ? t('settings.noMatches') : t('settings.empty')}
              detail={query.trim() ? t('settings.noMatchesDescription') : undefined}
            />
          ) : null}
          {!loading && !error
            ? items.map((item) => (
                <ResourceCatalogItem
                  key={item.id}
                  section={section}
                  item={item}
                  selected={selected?.id === item.id}
                  onSelect={() => onSelect(item.id)}
                />
              ))
            : null}
        </div>
      </section>

      <section className="managed-resource-detail">
        {selected ? (
          <ResourceDetail
            section={section}
            item={selected}
            actionError={actionError}
            busy={busy}
            canManage={canManage}
            mode={mode}
            onAction={() => onAction(selected)}
          />
        ) : (
          <div className="managed-resource-detail-empty">
            <meta.Icon />
            <strong>{t('settings.noResourceSelected')}</strong>
            <span>{t('settings.noResourceSelectedDescription')}</span>
          </div>
        )}
      </section>
    </div>
  );
}

function ResourceCatalogItem({
  section,
  item,
  selected,
  onSelect,
}: {
  section: ResourceSection;
  item: ManagedResource;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const meta = sectionMeta[section];
  const view = managedResourceView(section, item);
  return (
    <button
      type="button"
      className={`managed-resource-item ${selected ? 'selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="managed-resource-item-icon">
        <meta.Icon />
      </span>
      <span className="managed-resource-item-copy">
        <b>{view.title}</b>
        <small>{view.description || t('settings.noDescription')}</small>
        <em>{formatMeta(view.meta, t).join(' · ')}</em>
      </span>
      <StatusPill status={view.status} />
    </button>
  );
}

function ResourceDetail({
  section,
  item,
  actionError,
  busy,
  canManage,
  mode,
  onAction,
}: {
  section: ResourceSection;
  item: ManagedResource;
  actionError: string | null;
  busy: boolean;
  canManage: boolean;
  mode: RuntimeMode;
  onAction: () => void;
}) {
  const { locale, t } = useI18n();
  const meta = sectionMeta[section];
  const view = managedResourceView(section, item);
  const facts = managedResourceFacts(section, item);
  const groups = managedResourceCapabilityGroups(section, item);
  const action = managedResourceAction(section, item, canManage, mode);
  const notice = resourceIsImmutable(section, item, mode)
    ? t('settings.immutableResource')
    : !canManage
      ? t('settings.resourceReadOnly')
      : !action
        ? t('settings.resourceActionUnavailable')
        : null;

  return (
    <>
      <header className="managed-resource-detail-topbar">
        <div className="managed-resource-breadcrumb">
          <span>{t('settings.title')}</span>
          <span>/</span>
          <span>{t(meta.label)}</span>
          <span>/</span>
          <b>{view.title}</b>
        </div>
        <div>
          {notice ? (
            <span className="managed-resource-readonly">
              <LockClosedIcon /> {notice}
            </span>
          ) : null}
          {action ? (
            <button
              type="button"
              className="managed-resource-primary-action"
              disabled={busy}
              onClick={onAction}
            >
              {busy ? <ReloadIcon className="managed-resource-spin" /> : <meta.Icon />}
              {t(action.nextActive ? 'settings.enable' : 'settings.disable')}
            </button>
          ) : null}
        </div>
      </header>
      <div className="managed-resource-detail-scroll">
        <section className="managed-resource-identity">
          <div className={`managed-resource-identity-icon ${section}`}>
            <meta.Icon />
          </div>
          <div>
            <span>
              {t(meta.singular).toUpperCase()} ·{' '}
              {factValue(facts, 'scope')?.toUpperCase() ||
                t('settings.currentScope').toUpperCase()}
            </span>
            <h1>{view.title}</h1>
            <p>{view.description || t('settings.noDescription')}</p>
            <div>
              <StatusPill status={view.status} />
              {notice ? (
                <span className="managed-resource-governance-chip">
                  <LockClosedIcon /> {notice}
                </span>
              ) : null}
              {formatMeta(view.meta, t).map((value) => (
                <span className="managed-resource-chip" key={value}>
                  {value}
                </span>
              ))}
            </div>
          </div>
          <section>
            <small>{t('settings.updatedAt').toUpperCase()}</small>
            <b>{formatFactValue('updatedAt', factValue(facts, 'updatedAt'), locale, t)}</b>
            <small>{item.id}</small>
          </section>
        </section>

        <div className="managed-resource-overview-label">{t('settings.overview')}</div>
        <div className="managed-resource-overview">
          {actionError ? (
            <div className="managed-resource-action-error" role="alert">
              <ExclamationTriangleIcon />
              <span>{actionError}</span>
            </div>
          ) : null}
          <section className="managed-resource-fact-grid">
            {facts.filter((fact) => fact.key !== 'updatedAt').map((fact) => (
              <div key={fact.key}>
                <span>{t(`settings.fact.${fact.key}`)}</span>
                <b>{formatFactValue(fact.key, fact.value, locale, t)}</b>
              </div>
            ))}
            {facts.filter((fact) => fact.key !== 'updatedAt').length === 0 ? (
              <div>
                <span>{t('settings.status')}</span>
                <b>{t(`settings.${view.status}`)}</b>
              </div>
            ) : null}
          </section>

          {groups.length > 0 ? (
            groups.map((group) => (
              <section className="managed-resource-card" key={group.key}>
                <header>
                  <div>
                    <span>{t(`settings.group.${group.key}`).toUpperCase()}</span>
                    <h2>{t(`settings.group.${group.key}Description`)}</h2>
                  </div>
                </header>
                <div className="managed-resource-chips">
                  {group.values.map((value) => (
                    <span key={value}>{value}</span>
                  ))}
                </div>
              </section>
            ))
          ) : (
            <section className="managed-resource-card managed-resource-card-empty">
              <ExclamationTriangleIcon />
              <div>
                <strong>{t('settings.noCapabilities')}</strong>
                <span>{t('settings.noCapabilitiesDescription')}</span>
              </div>
            </section>
          )}
        </div>
      </div>
    </>
  );
}

function StatusPill({ status }: { status: 'active' | 'disabled' | 'attention' }) {
  const { t } = useI18n();
  return (
    <span className={`managed-resource-status ${status}`}>
      <i /> {t(`settings.${status}`)}
    </span>
  );
}

function CatalogState({
  text,
  detail,
  error = false,
  action,
  onAction,
}: {
  text: string;
  detail?: string;
  error?: boolean;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className={`managed-resource-catalog-state ${error ? 'error' : ''}`}>
      <MagnifyingGlassIcon />
      <strong>{text}</strong>
      {detail ? <span>{detail}</span> : null}
      {action && onAction ? (
        <button type="button" onClick={onAction}>
          {action}
        </button>
      ) : null}
    </div>
  );
}

export function SettingsState({
  text,
  detail,
  error = false,
}: {
  text: string;
  detail?: string;
  error?: boolean;
}) {
  return (
    <div className={`settings-resource-state ${error ? 'error' : ''}`}>
      <strong>{text}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function formatMeta(
  values: ReturnType<typeof managedResourceView>['meta'],
  t: (key: string, values?: Record<string, string | number>) => string,
): string[] {
  return values.map((value) => {
    if (value.kind === 'tool_count') return t('settings.toolCount', { count: value.count });
    if (value.kind === 'skill_count') return t('settings.skillCount', { count: value.count });
    if (value.kind === 'version') return t('settings.versionValue', { version: value.value });
    return value.value;
  });
}

function factValue(
  facts: ReturnType<typeof managedResourceFacts>,
  key: ReturnType<typeof managedResourceFacts>[number]['key'],
): string | null {
  return facts.find((fact) => fact.key === key)?.value ?? null;
}

function formatFactValue(
  key: ReturnType<typeof managedResourceFacts>[number]['key'],
  value: string | null,
  locale: string,
  t: (key: string) => string,
): string {
  if (!value) return t('settings.notAvailable');
  if (key === 'discovery') return t(`settings.discovery.${value}`);
  if (key !== 'updatedAt') return value;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)
    : value;
}
