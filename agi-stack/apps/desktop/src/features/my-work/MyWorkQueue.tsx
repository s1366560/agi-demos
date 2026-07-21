import { useMemo } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  CodeIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentCapabilityMode, ProjectWorkItem } from '../../types';
import {
  groupMyWorkDisplayItems,
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

const GROUP_ICONS = {
  needs_input: ExclamationTriangleIcon,
  running: ActivityLogIcon,
  ready_review: CheckCircledIcon,
} satisfies Record<MyWorkDisplayGroup, typeof ActivityLogIcon>;

export function MyWorkQueue({
  items,
  error,
  loading,
  projectName,
  workspaceLabels,
  onOpenSession,
}: MyWorkQueueProps) {
  const { locale, t } = useI18n();
  const groups = useMemo(() => groupMyWorkDisplayItems(items), [items]);

  return (
    <main className="my-work-inbox" aria-busy={loading} aria-label={t('myWork.title')}>
      <header className="my-work-inbox-heading">
        <div>
          <span>{t('myWork.eyebrow')}</span>
          <h1>{t('myWork.inboxTitle')}</h1>
          <p>{t('myWork.inboxDescription')}</p>
        </div>
      </header>

      {error ? (
        <section className="my-work-inbox-state error" role="alert">
          <ExclamationTriangleIcon />
          <div>
            <strong>{t('myWork.unavailable')}</strong>
            <p>{error}</p>
          </div>
        </section>
      ) : null}

      {!error && !loading && items.length === 0 ? (
        <section className="my-work-inbox-state" role="status">
          <CheckCircledIcon />
          <div>
            <strong>{t('myWork.empty')}</strong>
            <p>
              {t('myWork.emptyDescription')}
            </p>
          </div>
        </section>
      ) : null}

      {!error ? (
        <div className="my-work-inbox-groups">
          {groups.map(({ group, items: groupItems }) => {
            const GroupIcon = GROUP_ICONS[group];
            return (
              <section className={`my-work-inbox-group ${group}`} key={group}>
                <header>
                  <GroupIcon />
                  <h2>{t(`myWork.displayGroup.${group}`)}</h2>
                  <span>{groupItems.length}</span>
                </header>
                {groupItems.length > 0 ? (
                  <div className="my-work-inbox-grid">
                    {groupItems.map((item) => (
                      <InboxCard
                        key={`${item.authority_kind}:${item.authority_id}`}
                        item={item}
                        locale={locale}
                        projectName={projectName}
                        workspaceLabel={
                          item.workspace_name ??
                          (item.workspace_id ? workspaceLabels[item.workspace_id] : null) ??
                          projectName
                        }
                        onOpen={() => onOpenSession(item)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="my-work-inbox-empty">{t('myWork.groupEmpty')}</p>
                )}
              </section>
            );
          })}
        </div>
      ) : null}
    </main>
  );
}

function InboxCard({
  item,
  locale,
  projectName,
  workspaceLabel,
  onOpen,
}: {
  item: ProjectWorkItem;
  locale: string;
  projectName: string;
  workspaceLabel: string;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const ModeIcon = item.capability_mode === 'code' ? CodeIcon : ActivityLogIcon;
  const progress =
    typeof item.progress === 'number'
      ? Math.max(0, Math.min(100, item.progress))
      : null;
  return (
    <button className="my-work-inbox-card" type="button" onClick={onOpen}>
      <header>
        <i className={`status-${item.group}`} aria-hidden="true" />
        <ModeIcon />
        <span>{workspaceLabel}</span>
        <time>{formatRelativeTime(item.updated_at || item.created_at, locale)}</time>
      </header>
      <strong>{item.title}</strong>
      <p>{item.summary || t(`myWork.action.${item.required_action}`)}</p>
      <footer>
        <span className={`my-work-inbox-progress ${progress === null ? 'indeterminate' : ''}`}>
          <i style={progress === null ? undefined : { width: `${progress}%` }} />
        </span>
        <small>{item.phase || t(`myWork.status.${item.status}`)}</small>
        <em>{projectName}</em>
        <ArrowRightIcon />
      </footer>
    </button>
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
