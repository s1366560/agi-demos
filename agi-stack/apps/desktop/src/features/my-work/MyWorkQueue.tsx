import { useEffect, useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  CircleBackslashIcon,
  ClockIcon,
  CodeIcon,
  DesktopIcon,
  DotsHorizontalIcon,
  ExclamationTriangleIcon,
  FileIcon,
  LockClosedIcon,
  MagnifyingGlassIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentCapabilityMode,
  DesktopPermissionProfile,
  DesktopRunStatus,
  ProjectWorkItem,
} from '../../types';
import {
  countMyWorkDisplayGroups,
  filterMyWorkItems,
  groupMyWorkDisplayItems,
  myWorkDisplayGroupForAuthorityGroup,
  myWorkItemKey,
  type MyWorkDisplayGroup,
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

const groupIcons = {
  needs_input: ExclamationTriangleIcon,
  running: ActivityLogIcon,
  ready_review: CheckCircledIcon,
} satisfies Record<MyWorkDisplayGroup, typeof ActivityLogIcon>;

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
  const shortcutLabel = isApplePlatform() ? '⌘ K' : 'Ctrl K';
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<MyWorkDisplayGroup>>(new Set());
  const visibleItems = useMemo(
    () => filterMyWorkItems(items, 'all', mode, query),
    [items, mode, query],
  );
  const displayGroups = useMemo(
    () => groupMyWorkDisplayItems(visibleItems),
    [visibleItems],
  );
  const counts = useMemo(
    () => countMyWorkDisplayGroups(visibleItems),
    [visibleItems],
  );
  const selectedItem = error
    ? null
    : (visibleItems.find((item) => myWorkItemKey(item) === selectedId) ??
      visibleItems[0] ??
      null);

  useEffect(() => {
    const selectedKey = selectedItem ? myWorkItemKey(selectedItem) : null;
    if (selectedKey !== selectedId) setSelectedId(selectedKey);
  }, [selectedId, selectedItem]);

  const toggleGroup = (group: MyWorkDisplayGroup) => {
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const resetQueueView = () => {
    setQuery('');
    setCollapsedGroups(new Set());
  };

  return (
    <section className="my-work-shell" aria-busy={loading} aria-label={t('myWork.title')}>
      <aside className="my-work-queue">
        <header className="my-work-queue-header">
          <div>
            <span>{t(mode === 'code' ? 'myWork.codeEyebrow' : 'myWork.eyebrow')}</span>
            <h1>{t('myWork.title')}</h1>
          </div>
          <button
            type="button"
            className="my-work-icon-button"
            aria-label={t('myWork.taskFilters')}
            onClick={resetQueueView}
          >
            <CircleBackslashIcon />
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
          <kbd>{shortcutLabel}</kbd>
        </label>

        <div className="my-work-filter-row" role="group" aria-label={t('myWork.statusFilter')}>
          <button type="button" className="active" aria-pressed="true">
            {t('myWork.filter.all')}
          </button>
          <button
            type="button"
            aria-disabled="true"
            aria-describedby="my-work-filter-unavailable"
          >
            {t('myWork.filter.assigned')}
          </button>
          <button
            type="button"
            aria-disabled="true"
            aria-describedby="my-work-filter-unavailable"
          >
            {t('myWork.filter.recent')}
          </button>
          <span id="my-work-filter-unavailable" className="my-work-visually-hidden">
            {t('myWork.filterUnavailable')}
          </span>
        </div>

        {error ? (
          <div className="my-work-queue-state error" aria-live="polite" role="alert">
            <ExclamationTriangleIcon />
            <span>
              <strong>{t('myWork.unavailable')}</strong>
              <small>{error}</small>
              <button type="button" disabled={loading} onClick={onRefresh}>
                {t('myWork.refresh')}
              </button>
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
              {items.length > 0 && query ? (
                <button type="button" onClick={() => setQuery('')}>
                  {t('myWork.clearFilters')}
                </button>
              ) : null}
            </span>
          </div>
        ) : null}

        {!error && visibleItems.length > 0 ? (
          <div className="my-work-groups" aria-label={t('myWork.queue')}>
            {loading ? (
              <div className="my-work-refreshing" role="status" aria-live="polite">
                <ActivityLogIcon className="spinning" />
                {t('myWork.updating')}
              </div>
            ) : null}
            {displayGroups.map(({ group, items: groupItems }) => {
              const GroupIcon = groupIcons[group];
              const expanded = !collapsedGroups.has(group);
              return (
                <section className="my-work-group" key={group}>
                  <button
                    type="button"
                    className="my-work-group-heading"
                    aria-expanded={expanded}
                    onClick={() => toggleGroup(group)}
                  >
                    <GroupIcon />
                    <span>{t(`myWork.displayGroup.${group}`)}</span>
                    <b>{counts[group]}</b>
                    <ChevronDownIcon className={expanded ? 'expanded' : ''} />
                  </button>
                  {expanded
                    ? groupItems.map((item) => {
                        const itemKey = myWorkItemKey(item);
                        const isSelected = selectedItem
                          ? myWorkItemKey(selectedItem) === itemKey
                          : false;
                        const needsAction =
                          myWorkDisplayGroupForAuthorityGroup(item.group) === 'needs_input';
                        return (
                          <article
                            className={`my-work-task-card ${isSelected ? 'selected' : ''}`}
                            key={itemKey}
                          >
                            <button
                              type="button"
                              className="my-work-item"
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
                            <button
                              type="button"
                              className="my-work-task-menu"
                              aria-label={t('myWork.openTaskActions', { title: item.title })}
                              disabled={loading}
                              onClick={() => onOpenSession(item)}
                            >
                              <DotsHorizontalIcon />
                            </button>
                            {needsAction ? (
                              <button
                                type="button"
                                className="my-work-inline-action"
                                disabled={loading}
                                onClick={() => onOpenSession(item)}
                              >
                                {t(
                                  item.group === 'needs_approval'
                                    ? 'myWork.reviewApproval'
                                    : 'myWork.provideInput',
                                )}
                              </button>
                            ) : null}
                          </article>
                        );
                      })
                    : null}
                </section>
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
          <button type="button" disabled={loading} onClick={onRefresh}>
            {t('myWork.refresh')}
          </button>
        </section>
      ) : selectedItem ? (
        <MyWorkDetail
          item={selectedItem}
          locale={locale}
          projectName={projectName}
          workspaceLabel={
            selectedItem.workspace_id ? (workspaceLabels[selectedItem.workspace_id] ?? null) : null
          }
          refreshing={loading}
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
  refreshing,
  onOpenSession,
}: {
  item: ProjectWorkItem;
  locale: string;
  projectName: string;
  workspaceLabel: string | null;
  refreshing: boolean;
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
  const environmentLabel =
    item.authority_kind === 'desktop_run' && item.environment
      ? item.environment.label || item.environment.kind
      : t('session.notAvailable');
  const permissionLabel =
    item.authority_kind === 'desktop_run'
      ? t(permissionTranslationKey(item.permission_profile))
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
        {refreshing ? (
          <span className="my-work-refreshing" role="status" aria-live="polite">
            <ActivityLogIcon className="spinning" />
            {t('myWork.updating')}
          </span>
        ) : null}
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
            <div className="my-work-progress-number">
              <b>—</b>
              <span>{t(statusTranslationKey(item.status))}</span>
            </div>
          </div>

          <div className="my-work-progress-strip" aria-label={t('myWork.stagesUnavailable')}>
            <span>
              <ActivityLogIcon />
            </span>
            <div>
              <strong>{t('myWork.stagesUnavailable')}</strong>
              <small>{t('myWork.stagesUnavailableDescription')}</small>
            </div>
          </div>

          <div className="my-work-run-facts">
            <span>
              <FileIcon /> {workspaceLabel ?? t('session.notAvailable')}
            </span>
            <span>
              <DesktopIcon /> {environmentLabel}
            </span>
          </div>

          {attention ? (
            <div className="my-work-input-banner">
              <span>
                <strong>{t('myWork.actionRequired')}</strong>
                {t(`myWork.action.${item.required_action}`)}
              </span>
              <button type="button" disabled={refreshing} onClick={onOpenSession}>
                {t('myWork.openSession')}
              </button>
            </div>
          ) : null}
        </section>

        <section className="my-work-insight-grid">
          <article>
            <span>{t('myWork.progress')}</span>
            <strong>{t('myWork.progressUnavailable')}</strong>
            <small>{t('myWork.progressAuthorityDescription')}</small>
          </article>
          <article>
            <span>{t('myWork.executionContext')}</span>
            <strong>{environmentLabel}</strong>
            <small>
              <LockClosedIcon /> {permissionLabel}
            </small>
          </article>
          <article className={attention ? 'attention' : ''}>
            <span>{t(attention ? 'myWork.blocker' : 'myWork.runStatus')}</span>
            <strong>{t(`myWork.group.${item.group}`)}</strong>
            <small>{t(`myWork.action.${item.required_action}`)}</small>
          </article>
        </section>

        <header className="my-work-artifact-heading">
          <div>
            <span>{t('myWork.latestEvidence')}</span>
            <h3>{t(item.capability_mode === 'code' ? 'myWork.codeEvidence' : 'myWork.workEvidence')}</h3>
          </div>
          <span>
            <ClockIcon />{' '}
            {t('myWork.taskUpdated', { time: formatDateTime(item.updated_at, locale) })}
          </span>
        </header>

        <section className="my-work-artifact-panel">
          <header>
            <span>
              <FileIcon /> {t('myWork.scopedTaskEvidence')}
            </span>
          </header>
          <div>
            <span>{t('myWork.evidenceUnavailable')}</span>
            <h3>{t('myWork.evidenceUnavailableTitle')}</h3>
            <p>{t('myWork.evidenceUnavailableDescription')}</p>
            <dl>
              <div>
                <dt>{t('myWork.workspace')}</dt>
                <dd>{workspaceLabel ?? t('session.notAvailable')}</dd>
              </div>
              <div>
                <dt>{t('myWork.mode')}</dt>
                <dd>{modeLabel}</dd>
              </div>
              <div>
                <dt>{t('session.overviewEnvironment')}</dt>
                <dd>{environmentLabel}</dd>
              </div>
            </dl>
          </div>
        </section>
      </div>

      <footer className="my-work-action-dock">
        <div className="my-work-action-buttons">
          <button type="button" className="primary" disabled={refreshing} onClick={onOpenSession}>
            {t('myWork.openSession')}
          </button>
        </div>
        <button
          type="button"
          className="my-work-steer-composer"
          disabled={refreshing}
          onClick={onOpenSession}
        >
          <span>{t('myWork.steeringInSession')}</span>
          <span>
            {modeLabel} · {t('myWork.agent')} <ArrowRightIcon />
          </span>
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

function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  return (
    navigator.platform.startsWith('Mac') ||
    navigator.platform === 'iPhone' ||
    navigator.platform === 'iPad'
  );
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
