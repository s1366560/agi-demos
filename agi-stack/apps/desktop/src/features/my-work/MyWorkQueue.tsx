import { useEffect, useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ClockIcon,
  CodeIcon,
  DesktopIcon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  ReloadIcon,
  RocketIcon,
  StopIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentCapabilityMode,
  DesktopPermissionProfile,
  DesktopRunStatus,
  MyWorkGroup,
  ProjectWorkItem,
} from '../../types';
import {
  countMyWorkGroups,
  describeMyWorkAuthority,
  filterMyWorkItems,
  MY_WORK_GROUPS,
  myWorkItemKey,
} from './myWorkModel';
import './MyWorkQueue.css';

type MyWorkQueueProps = {
  items: ProjectWorkItem[];
  error: string | null;
  loading: boolean;
  mode: AgentCapabilityMode;
  projectName: string;
  workspaceLabels: Record<string, string>;
  onRefresh: () => void;
  onOpenSession: (item: ProjectWorkItem) => void;
};

type MyWorkQueueFilter = 'all' | 'attention' | 'running' | 'ready_review';

const groupIcons = {
  needs_input: ExclamationTriangleIcon,
  needs_approval: StopIcon,
  running: ActivityLogIcon,
  ready_review: CheckCircledIcon,
} satisfies Record<MyWorkGroup, typeof ActivityLogIcon>;

export function MyWorkQueue({
  items,
  error,
  loading,
  mode,
  projectName,
  workspaceLabels,
  onRefresh,
  onOpenSession,
}: MyWorkQueueProps) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<MyWorkQueueFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<MyWorkGroup>>(new Set());
  const modeItems = useMemo(
    () => filterMyWorkItems(items, 'all', mode, query),
    [items, mode, query],
  );
  const visibleItems = useMemo(
    () => modeItems.filter((item) => queueFilterMatches(filter, item.group)),
    [filter, modeItems],
  );
  const counts = useMemo(() => countMyWorkGroups(visibleItems), [visibleItems]);
  const selectedItem = error
    ? null
    : (visibleItems.find((item) => myWorkItemKey(item) === selectedId) ??
      visibleItems[0] ??
      null);

  useEffect(() => {
    const selectedKey = selectedItem ? myWorkItemKey(selectedItem) : null;
    if (selectedKey !== selectedId) setSelectedId(selectedKey);
  }, [selectedId, selectedItem]);

  const toggleGroup = (group: MyWorkGroup) => {
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  return (
    <section
      className="my-work-shell"
      aria-busy={loading}
      aria-label={t('myWork.title')}
    >
      <aside className="my-work-queue">
        <header className="my-work-queue-header">
          <div>
            <span>{t('myWork.eyebrow')}</span>
            <h1>{t('myWork.title')}</h1>
          </div>
          <button
            type="button"
            className="my-work-icon-button"
            aria-label={t('myWork.refresh')}
            disabled={loading}
            onClick={onRefresh}
          >
            <ReloadIcon className={loading ? 'spinning' : ''} />
          </button>
        </header>

        <label className="my-work-search">
          <MagnifyingGlassIcon />
          <input
            name="my-work-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('myWork.search')}
            aria-label={t('myWork.search')}
            autoComplete="off"
            spellCheck={false}
          />
        </label>

        <div className="my-work-filter-row" aria-label={t('myWork.statusFilter')}>
          {(['all', 'attention', 'running', 'ready_review'] as const).map((value) => (
            <button
              type="button"
              className={filter === value ? 'active' : ''}
              aria-pressed={filter === value}
              key={value}
              onClick={() => setFilter(value)}
            >
              {t(`myWork.filter.${value}`)}
            </button>
          ))}
        </div>

        {error ? (
          <div className="my-work-queue-state error" aria-live="polite" role="alert">
            <ExclamationTriangleIcon />
            <span>
              <strong>{t('myWork.unavailable')}</strong>
              <small>{error}</small>
            </span>
          </div>
        ) : null}

        {!error && loading && visibleItems.length === 0 ? (
          <div className="my-work-queue-state" aria-live="polite" role="status">
            <ActivityLogIcon className="spinning" />
            <span>
              <strong>{t('myWork.loading')}</strong>
              <small>{t('myWork.loadingDescription')}</small>
            </span>
          </div>
        ) : null}

        {!error && !loading && visibleItems.length === 0 ? (
          <div className="my-work-queue-state" aria-live="polite" role="status">
            <CheckCircledIcon />
            <span>
              <strong>{t(items.length === 0 ? 'myWork.empty' : 'myWork.noMatches')}</strong>
              <small>
                {t(items.length === 0 ? 'myWork.emptyDescription' : 'myWork.noMatchesDescription')}
              </small>
              {items.length > 0 && (query || filter !== 'all') ? (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    setFilter('all');
                  }}
                >
                  {t('myWork.clearFilters')}
                </button>
              ) : null}
            </span>
          </div>
        ) : null}

        {!error && visibleItems.length > 0 ? (
          <div className="my-work-groups" aria-label={t('myWork.queue')}>
            {MY_WORK_GROUPS.map((group) => {
              const GroupIcon = groupIcons[group];
              const groupItems = visibleItems.filter((item) => item.group === group);
              const expanded = !collapsedGroups.has(group);
              return (
                <div className="my-work-group" key={group}>
                  <button
                    type="button"
                    className="my-work-group-heading"
                    aria-expanded={expanded}
                    onClick={() => toggleGroup(group)}
                  >
                    <GroupIcon />
                    <span>{t(`myWork.group.${group}`)}</span>
                    <b>{counts[group]}</b>
                    <ChevronDownIcon className={expanded ? 'expanded' : ''} />
                  </button>
                  {expanded
                    ? groupItems.map((item) => {
                        const itemKey = myWorkItemKey(item);
                        const isSelected = selectedItem
                          ? myWorkItemKey(selectedItem) === itemKey
                          : false;
                        return (
                          <button
                            type="button"
                            key={itemKey}
                            className={`my-work-item ${isSelected ? 'selected' : ''}`}
                            aria-current={isSelected ? 'true' : undefined}
                            onClick={() => setSelectedId(itemKey)}
                          >
                            <span className={`my-work-status status-${item.group}`} aria-hidden />
                            <span>
                              <strong>{item.title}</strong>
                              <small>{t(`myWork.action.${item.required_action}`)}</small>
                              <em>
                                {t('myWork.updated', {
                                  time: formatRelativeTime(item.updated_at, locale),
                                })}
                              </em>
                            </span>
                          </button>
                        );
                      })
                    : null}
                </div>
              );
            })}
          </div>
        ) : null}
      </aside>

      {error ? (
        <section className="my-work-detail-empty error" aria-live="polite" role="alert">
          <ExclamationTriangleIcon />
          <strong>{t('myWork.unavailable')}</strong>
          <small>{t('myWork.staleHidden')}</small>
        </section>
      ) : selectedItem ? (
        <MyWorkDetail
          item={selectedItem}
          locale={locale}
          projectName={projectName}
          workspaceLabel={
            selectedItem.workspace_id ? (workspaceLabels[selectedItem.workspace_id] ?? null) : null
          }
          onOpenSession={() => onOpenSession(selectedItem)}
        />
      ) : (
        <section className="my-work-detail-empty">
          {loading ? <ActivityLogIcon className="spinning" /> : <CheckCircledIcon />}
          <strong>{loading ? t('myWork.loading') : t('myWork.empty')}</strong>
          <small>{loading ? t('myWork.loadingDescription') : t('myWork.emptyDescription')}</small>
        </section>
      )}
    </section>
  );
}

function MyWorkDetail({
  item,
  locale,
  projectName,
  workspaceLabel,
  onOpenSession,
}: {
  item: ProjectWorkItem;
  locale: string;
  projectName: string;
  workspaceLabel: string | null;
  onOpenSession: () => void;
}) {
  const { t } = useI18n();
  const ModeIcon =
    item.capability_mode === 'code'
      ? CodeIcon
      : item.capability_mode === 'work'
        ? RocketIcon
        : ActivityLogIcon;
  const attention = item.group === 'needs_input' || item.group === 'needs_approval';
  const authority = describeMyWorkAuthority(item);
  const environmentLabel = authority.runtime?.environment
    ? authority.runtime.environment.label || authority.runtime.environment.kind
    : t('session.notAvailable');
  const permissionLabel = authority.runtime?.permissionProfile
    ? t(permissionTranslationKey(authority.runtime.permissionProfile))
    : t('session.notAvailable');
  const modeLabel =
    item.capability_mode === null
      ? t('myWork.modeUnclassified')
      : t(item.capability_mode === 'code' ? 'session.code' : 'session.work');

  return (
    <article className="my-work-detail">
      <header className="my-work-detail-topbar">
        <div>
          <span>{projectName}</span>
          <ArrowRightIcon />
          <strong>{item.title}</strong>
        </div>
        <time dateTime={item.updated_at}>
          <ClockIcon />
          {formatDateTime(item.updated_at, locale)}
        </time>
      </header>

      <div className="my-work-detail-content">
        <section className="my-work-summary-card">
          <div className="my-work-summary-title">
            <span className={`my-work-mode-icon ${item.capability_mode ?? 'unclassified'}`}>
              <ModeIcon />
            </span>
            <div>
              <small>{modeLabel}</small>
              <h2>{item.title}</h2>
              <p>{t(`myWork.action.${item.required_action}`)}</p>
            </div>
            <span className={`my-work-status-badge status-${item.group}`}>
              <i /> {t(statusTranslationKey(item.status))}
            </span>
          </div>

          <dl className="my-work-run-facts">
            <div>
              <dt>{t('myWork.workspace')}</dt>
              <dd>{workspaceLabel ?? t('session.notAvailable')}</dd>
            </div>
            <div>
              <dt>{t('myWork.authoritySource')}</dt>
              <dd>
                <ActivityLogIcon /> {t(authority.sourceKey)}
              </dd>
            </div>
            <div>
              <dt>{t('myWork.lastUpdated')}</dt>
              <dd>
                <ClockIcon /> {formatRelativeTime(item.updated_at, locale)}
              </dd>
            </div>
          </dl>

          {attention || item.group === 'ready_review' ? (
            <div className={`my-work-action-banner ${attention ? 'attention' : 'review'}`}>
              {attention ? <StopIcon /> : <CheckCircledIcon />}
              <span>
                <strong>{t(attention ? 'myWork.actionRequired' : 'myWork.reviewAvailable')}</strong>
                <small>{t(`myWork.action.${item.required_action}`)}</small>
              </span>
              <button type="button" onClick={onOpenSession}>
                {t('myWork.openSession')} <ArrowRightIcon />
              </button>
            </div>
          ) : null}
        </section>

        <section className="my-work-insight-grid">
          <article>
            <span>{t('myWork.authorityId')}</span>
            <strong translate="no">{authority.identifier}</strong>
            <small>{t(authority.sourceKey)}</small>
          </article>
          <article>
            <span>{t('myWork.requiredAction')}</span>
            <strong>{t(`myWork.group.${item.group}`)}</strong>
            <small>{t(`myWork.action.${item.required_action}`)}</small>
          </article>
          <article>
            <span>{t('myWork.lastUpdated')}</span>
            <strong>{formatRelativeTime(item.updated_at, locale)}</strong>
            <small>{t('myWork.persistedRecordOnly')}</small>
          </article>
        </section>

        <section className="my-work-authority-card">
          <header>
            <div>
              <span>{t('myWork.authoritySource')}</span>
              <h3>{t('myWork.currentAuthority')}</h3>
            </div>
            <span className={`my-work-status-badge status-${item.group}`}>
              <i /> {t(statusTranslationKey(item.status))}
            </span>
          </header>
          <p>{t(authority.descriptionKey)}</p>
          <dl>
            <div>
              <dt>{t('myWork.authorityType')}</dt>
              <dd>{t(authority.sourceKey)}</dd>
            </div>
            <div>
              <dt>{t('myWork.authorityId')}</dt>
              <dd translate="no">{authority.identifier}</dd>
            </div>
            {authority.sequence ? (
              <div>
                <dt>{t(authority.sequence.labelKey)}</dt>
                <dd>{authority.sequence.value}</dd>
              </div>
            ) : null}
            <div>
              <dt>{t('myWork.recordStatus')}</dt>
              <dd>{t(statusTranslationKey(item.status))}</dd>
            </div>
            <div>
              <dt>{t('myWork.lastUpdated')}</dt>
              <dd>{formatDateTime(item.updated_at, locale)}</dd>
            </div>
            {authority.runtime ? (
              <>
                <div>
                  <dt>{t('session.overviewEnvironment')}</dt>
                  <dd>{environmentLabel}</dd>
                </div>
                <div>
                  <dt>{t('session.overviewPermission')}</dt>
                  <dd>{permissionLabel}</dd>
                </div>
                <div>
                  <dt>{t('myWork.lastHeartbeat')}</dt>
                  <dd>
                    {authority.runtime.lastHeartbeatAt
                      ? formatDateTime(authority.runtime.lastHeartbeatAt, locale)
                      : t('session.notAvailable')}
                  </dd>
                </div>
              </>
            ) : null}
          </dl>
          {!authority.runtime ? (
            <div className="my-work-runtime-unavailable">
              <DesktopIcon />
              <span>
                <strong>{t('myWork.desktopRuntimeUnavailable')}</strong>
                <small>{t('myWork.desktopRuntimeUnavailableDescription')}</small>
              </span>
            </div>
          ) : null}
          {item.error ? (
            <div className="my-work-run-error">
              <ExclamationTriangleIcon /> {t('myWork.failureRecorded')}
            </div>
          ) : null}
        </section>
      </div>

      <footer className="my-work-action-dock">
        <span>
          <strong>{t('myWork.openSession')}</strong>
          <small>{t('myWork.openSessionDescription')}</small>
        </span>
        <button type="button" onClick={onOpenSession}>
          {t('myWork.openSession')} <ArrowRightIcon />
        </button>
      </footer>
    </article>
  );
}

function statusTranslationKey(status: DesktopRunStatus): string {
  const keys: Record<DesktopRunStatus, string> = {
    queued: 'session.statusQueued',
    running: 'session.statusRunning',
    needs_input: 'session.statusNeedsInput',
    needs_approval: 'session.statusNeedsApproval',
    paused: 'session.statusPaused',
    ready_review: 'session.statusReadyReview',
    completed: 'session.statusCompleted',
    failed: 'session.statusFailed',
    disconnected: 'session.statusDisconnected',
    interrupted: 'session.statusInterrupted',
    cancelled: 'session.statusCancelled',
  };
  return keys[status];
}

function permissionTranslationKey(profile: DesktopPermissionProfile): string {
  if (profile === 'read_only') return 'task.permissionReadOnly';
  if (profile === 'workspace_write') return 'task.permissionWorkspaceWrite';
  return 'task.permissionFullAccess';
}

function queueFilterMatches(filter: MyWorkQueueFilter, group: MyWorkGroup): boolean {
  if (filter === 'all') return true;
  if (filter === 'attention') return group === 'needs_input' || group === 'needs_approval';
  return group === filter;
}

function formatRelativeTime(value: string, locale: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  const minutes = Math.round((timestamp - Date.now()) / 60_000);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour');
  return formatter.format(Math.round(hours / 24), 'day');
}

function formatDateTime(value: string, locale: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}
