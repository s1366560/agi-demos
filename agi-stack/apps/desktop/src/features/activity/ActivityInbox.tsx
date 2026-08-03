import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  CheckIcon,
  ExclamationTriangleIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ActivityCategory, ActivityInboxEntry, ActivityInboxGroup } from './activityInboxModel';
import './ActivityInbox.css';

type ActivityInboxProps = {
  groups: ActivityInboxGroup[];
  isEntryRead: (entry: ActivityInboxEntry) => boolean;
  unreadCount: number;
  error: string | null;
  loading: boolean;
  projectName: string;
  workspaceLabels: Record<string, string>;
  onRefresh: () => void;
  onOpen: (entry: ActivityInboxEntry) => void;
  onMarkRead: (entryId: string) => void;
  onMarkAllRead: () => void;
};

const CATEGORY_ICONS = {
  needs_input: ExclamationTriangleIcon,
  ready_for_review: CheckCircledIcon,
  attention: ActivityLogIcon,
} satisfies Record<ActivityCategory, typeof ActivityLogIcon>;

export function ActivityInbox({
  groups,
  isEntryRead,
  unreadCount,
  error,
  loading,
  projectName,
  workspaceLabels,
  onRefresh,
  onOpen,
  onMarkRead,
  onMarkAllRead,
}: ActivityInboxProps) {
  const { locale, t } = useI18n();
  const visibleEntryCount = groups.reduce((count, group) => count + group.entries.length, 0);

  return (
    <main className="activity-inbox" aria-busy={loading} aria-label={t('activity.title')}>
      <header className="activity-inbox-heading">
        <div>
          <span>{t('activity.eyebrow')}</span>
          <h1>{t('activity.title')}</h1>
          <p>{t('activity.description')}</p>
        </div>
        <div className="activity-inbox-actions">
          <button
            type="button"
            disabled={unreadCount === 0}
            onClick={onMarkAllRead}
          >
            <CheckIcon />
            {t('activity.markAllRead')}
          </button>
          <button type="button" disabled={loading} onClick={onRefresh}>
            <ReloadIcon className={loading ? 'spinning' : undefined} />
            {t('common.refresh')}
          </button>
        </div>
      </header>

      {error ? (
        <section className="activity-inbox-state error" role="alert">
          <ExclamationTriangleIcon />
          <div>
            <strong>{t('activity.unavailable')}</strong>
            <p>{error}</p>
          </div>
        </section>
      ) : null}

      {!error && !loading && visibleEntryCount === 0 ? (
        <section className="activity-inbox-state" role="status">
          <CheckCircledIcon />
          <div>
            <strong>{t('activity.empty')}</strong>
            <p>{t('activity.emptyDescription')}</p>
          </div>
        </section>
      ) : null}

      {!error ? (
        <div className="activity-inbox-groups">
          {groups.map(({ category, entries }) => {
            const CategoryIcon = CATEGORY_ICONS[category];
            return (
              <section className={`activity-inbox-group ${category}`} key={category}>
                <header>
                  <CategoryIcon />
                  <h2>{t(`activity.category.${category}`)}</h2>
                  <span>{entries.length}</span>
                </header>
                {entries.length > 0 ? (
                  <div className="activity-inbox-list">
                    {entries.map((entry) => (
                      <InboxRow
                        key={entry.id}
                        entry={entry}
                        read={isEntryRead(entry)}
                        locale={locale}
                        projectName={projectName}
                        workspaceLabel={
                          entry.item.workspace_name ??
                          (entry.item.workspace_id
                            ? workspaceLabels[entry.item.workspace_id]
                            : null) ??
                          projectName
                        }
                        onOpen={() => onOpen(entry)}
                        onMarkRead={() => onMarkRead(entry.id)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="activity-inbox-group-empty">{t('activity.groupEmpty')}</p>
                )}
              </section>
            );
          })}
        </div>
      ) : null}
    </main>
  );
}

function InboxRow({
  entry,
  read,
  locale,
  projectName,
  workspaceLabel,
  onOpen,
  onMarkRead,
}: {
  entry: ActivityInboxEntry;
  read: boolean;
  locale: string;
  projectName: string;
  workspaceLabel: string;
  onOpen: () => void;
  onMarkRead: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className={`activity-inbox-row ${read ? 'read' : 'unread'}`}>
      <button className="activity-inbox-open" type="button" onClick={onOpen}>
        <i className="activity-inbox-unread-dot" aria-hidden="true" />
        <span className="activity-inbox-row-body">
          <strong>{entry.title}</strong>
          <small>{entry.subtitle || t(entry.actionKey)}</small>
        </span>
        <span className="activity-inbox-row-meta">
          <em>{workspaceLabel}</em>
          <time>{formatRelativeTime(entry.timestamp, locale)}</time>
        </span>
        <ArrowRightIcon />
      </button>
      {!read ? (
        <button
          className="activity-inbox-mark-read"
          type="button"
          aria-label={t('activity.markRead')}
          title={t('activity.markRead')}
          onClick={onMarkRead}
        >
          <CheckIcon />
        </button>
      ) : null}
    </div>
  );
}

function formatRelativeTime(value: string, locale: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '—';
  const minutes = Math.round((timestamp - Date.now()) / 60_000);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour');
  return formatter.format(Math.round(hours / 24), 'day');
}
