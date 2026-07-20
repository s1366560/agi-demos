import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  CodeIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const GROUPS = [
  { id: 'input', label: 'Needs input', icon: ExclamationTriangleIcon, statuses: ['input', 'planning'] },
  { id: 'running', label: 'Running', icon: ActivityLogIcon, statuses: ['running'] },
  { id: 'ready', label: 'Ready to review', icon: CheckCircledIcon, statuses: ['ready'] },
];

function InboxCard({ item, onOpen, t }) {
  const ModeIcon = item.mode === 'code' ? CodeIcon : ActivityLogIcon;
  return (
    <button className="inbox-card" type="button" onClick={() => onOpen(item)}>
      <header>
        <i className={`thread-status ${item.status}`} aria-hidden="true" />
        <ModeIcon className="thread-mode-icon" />
        <span className="inbox-card-workspace">{item.workspaceName}</span>
        <em>{t(item.meta)}</em>
      </header>
      <b>{item.title}</b>
      <p>{item.summary}</p>
      <footer>
        <span className="inbox-card-progress"><i style={{ width: `${item.progress}%` }} /></span>
        <small>{t(item.phase)}</small>
        <ArrowRightIcon />
      </footer>
    </button>
  );
}

export function InboxView({ items, onOpenThread }) {
  const { t } = useI18n();
  return (
    <main className="inbox-view">
      <header className="inbox-heading">
        <span className="eyebrow">{t('MY WORK')}</span>
        <h1>{t('Inbox')}</h1>
        <p>{t('Threads that need a decision, are running, or are ready for review — across Work and Code.')}</p>
      </header>
      {GROUPS.map((group) => {
        const groupItems = items.filter((item) => group.statuses.includes(item.status));
        const GroupIcon = group.icon;
        return (
          <section className={`inbox-group ${group.id}`} key={group.id}>
            <header><GroupIcon /><h2>{t(group.label)}</h2><small>{groupItems.length}</small></header>
            {groupItems.length ? (
              <div className="inbox-grid">
                {groupItems.map((item) => <InboxCard key={`${item.mode}-${item.id}`} item={item} onOpen={onOpenThread} t={t} />)}
              </div>
            ) : <p className="inbox-empty">{t('Nothing here right now.')}</p>}
          </section>
        );
      })}
    </main>
  );
}
