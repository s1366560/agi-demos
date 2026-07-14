import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Text } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CheckCircledIcon,
  ClockIcon,
  CodeIcon,
  ExclamationTriangleIcon,
  GridIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { MyWorkGroup, ProjectWorkItem } from '../../types';
import {
  countMyWorkGroups,
  filterMyWorkItems,
  MY_WORK_GROUPS,
  type MyWorkModeFilter,
} from './myWorkModel';
import './MyWorkQueue.css';

type MyWorkQueueProps = {
  items: ProjectWorkItem[];
  error: string | null;
  loading: boolean;
  onRefresh: () => void;
  onOpenSession: (item: ProjectWorkItem) => void;
  onOpenBoard: () => void;
};

export function MyWorkQueue({
  items,
  error,
  loading,
  onRefresh,
  onOpenSession,
  onOpenBoard,
}: MyWorkQueueProps) {
  const { t } = useI18n();
  const [group, setGroup] = useState<MyWorkGroup | 'all'>('all');
  const [mode, setMode] = useState<MyWorkModeFilter>('all');
  const counts = useMemo(() => countMyWorkGroups(items), [items]);
  const visibleItems = useMemo(() => filterMyWorkItems(items, group, mode), [group, items, mode]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedItem =
    visibleItems.find((item) => item.id === selectedId) ?? visibleItems[0] ?? null;

  useEffect(() => {
    if (selectedItem?.id !== selectedId) setSelectedId(selectedItem?.id ?? null);
  }, [selectedId, selectedItem?.id]);

  return (
    <section className="my-work-shell">
      <header className="my-work-header">
        <div>
          <Text size="1" color="gray">
            {t('myWork.eyebrow')}
          </Text>
          <h1>{t('myWork.title')}</h1>
          <p>{t('myWork.description')}</p>
        </div>
        <div>
          <Button variant="soft" color="gray" onClick={onOpenBoard}>
            <GridIcon /> {t('myWork.boardView')}
          </Button>
          <Button variant="soft" loading={loading} onClick={onRefresh}>
            <ReloadIcon /> {t('settings.refresh')}
          </Button>
        </div>
      </header>

      <div className="my-work-filters">
        <div role="tablist" aria-label={t('myWork.statusFilter')}>
          <FilterButton
            active={group === 'all'}
            label={t('settings.all')}
            count={items.length}
            onClick={() => setGroup('all')}
          />
          {MY_WORK_GROUPS.map((value) => (
            <FilterButton
              key={value}
              active={group === value}
              label={t(`myWork.group.${value}`)}
              count={counts[value]}
              onClick={() => setGroup(value)}
            />
          ))}
        </div>
        <label>
          <span>{t('myWork.mode')}</span>
          <select value={mode} onChange={(event) => setMode(event.target.value as MyWorkModeFilter)}>
            <option value="all">{t('settings.all')}</option>
            <option value="work">{t('session.work')}</option>
            <option value="code">{t('session.code')}</option>
          </select>
        </label>
      </div>

      {error ? (
        <div className="my-work-state error" role="alert">
          <ExclamationTriangleIcon />
          <span>
            <strong>{t('myWork.unavailable')}</strong>
            <small>{error}</small>
          </span>
        </div>
      ) : null}

      {!error && !loading && visibleItems.length === 0 ? (
        <div className="my-work-state">
          <CheckCircledIcon />
          <span>
            <strong>{t('myWork.empty')}</strong>
            <small>{t('myWork.emptyDescription')}</small>
          </span>
        </div>
      ) : null}

      {!error && visibleItems.length > 0 ? (
        <div className="my-work-content">
          <div className="my-work-list" aria-label={t('myWork.queue')}>
            {visibleItems.map((item) => (
              <button
                type="button"
                key={item.id}
                className={selectedItem?.id === item.id ? 'selected' : ''}
                onClick={() => setSelectedId(item.id)}
              >
                <span className={`my-work-status status-${item.group}`} aria-hidden />
                <span>
                  <strong>{item.title}</strong>
                  <small>
                    {t(`myWork.group.${item.group}`)} · {t(`session.${item.capability_mode}`)}
                  </small>
                </span>
                <time dateTime={item.updated_at}>{formatRelativeTime(item.updated_at)}</time>
              </button>
            ))}
          </div>

          {selectedItem ? (
            <article className="my-work-detail">
              <header>
                <div>
                  <Text size="1" color="gray">
                    {t(`myWork.group.${selectedItem.group}`).toUpperCase()}
                  </Text>
                  <h2>{selectedItem.title}</h2>
                </div>
                <Badge color={groupColor(selectedItem.group)} variant="soft">
                  {selectedItem.status}
                </Badge>
              </header>
              <dl>
                <div>
                  <dt>{t('myWork.requiredAction')}</dt>
                  <dd>{t(`myWork.action.${selectedItem.required_action}`)}</dd>
                </div>
                <div>
                  <dt>{t('session.overviewRun')}</dt>
                  <dd>
                    {selectedItem.run_id} · r{selectedItem.revision}
                  </dd>
                </div>
                <div>
                  <dt>{t('session.overviewEnvironment')}</dt>
                  <dd>{selectedItem.environment?.label ?? t('session.notAvailable')}</dd>
                </div>
                <div>
                  <dt>{t('session.overviewPermission')}</dt>
                  <dd>{selectedItem.permission_profile}</dd>
                </div>
              </dl>
              {selectedItem.error ? (
                <div className="my-work-error-detail">
                  <ExclamationTriangleIcon /> {selectedItem.error}
                </div>
              ) : null}
              <footer>
                <span>
                  {selectedItem.capability_mode === 'code' ? <CodeIcon /> : <ChatBubbleIcon />}
                  {selectedItem.project_id}
                </span>
                <Button onClick={() => onOpenSession(selectedItem)}>
                  <ClockIcon /> {t('myWork.openSession')}
                </Button>
              </footer>
            </article>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function FilterButton({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <button type="button" role="tab" aria-selected={active} className={active ? 'active' : ''} onClick={onClick}>
      {label} <span>{count}</span>
    </button>
  );
}

function groupColor(group: MyWorkGroup): 'amber' | 'red' | 'blue' | 'green' {
  if (group === 'needs_input') return 'amber';
  if (group === 'needs_approval') return 'red';
  if (group === 'running') return 'blue';
  return 'green';
}

function formatRelativeTime(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}
