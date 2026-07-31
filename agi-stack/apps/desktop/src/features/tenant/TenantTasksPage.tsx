import {
  Cross2Icon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  ReloadIcon,
  ResumeIcon,
  StopIcon,
} from '@radix-ui/react-icons';
import { Button, TextField } from '@radix-ui/themes';
import { useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import type { TenantTaskRecord } from './tenantTasksClient';
import type {
  TenantTasksController,
  TenantTasksViewModel,
} from './tenantTasksController';
import './TenantTasksPage.css';

const DISPLAY_STATES = new Set([
  'ready',
  'degraded',
  'empty',
  'stale',
  'conflict',
  'forbidden',
]);

export function TenantTasksPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantTasksViewModel;
  controller: TenantTasksController;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [confirmingTaskId, setConfirmingTaskId] = useState<string | null>(null);
  const stopTriggerRef = useRef<HTMLButtonElement | null>(null);
  if (!DISPLAY_STATES.has(model.state) || model.lastUpdatedAt === null) {
    return <TenantTasksState model={model} onRetry={onRetry} />;
  }
  const closeStopDialog = (): void => {
    setConfirmingTaskId(null);
    queueMicrotask(() => stopTriggerRef.current?.focus());
  };
  const confirmingTask =
    model.tasks.find((task) => task.id === confirmingTaskId) ?? null;
  return (
    <section className="tenant-tasks-page" data-state={model.state}>
      <header className="tenant-tasks-header">
        <div>
          <span>{t('tenantTasks.eyebrow')}</span>
          <h1>{t('tenantTasks.title')}</h1>
          <p>{t('tenantTasks.subtitle')}</p>
        </div>
        <div className="tenant-tasks-header-actions">
          {model.allowedActions.includes('retry-pending') ? (
            <Button
              color="gray"
              disabled={model.busyAction !== null || model.stats.pending === 0}
              onClick={() => {
                void controller.retryPending(5).catch(() => undefined);
              }}
            >
              <ResumeIcon />
              {t('tenantTasks.resumePending')}
            </Button>
          ) : null}
          <Button
            color="gray"
            variant="soft"
            disabled={model.busyAction !== null}
            onClick={onRetry}
          >
            <ReloadIcon />
            {t('common.refresh')}
          </Button>
        </div>
      </header>
      {model.state !== 'ready' && model.state !== 'empty' ? (
        <div className="tenant-tasks-notice" role="status">
          <ExclamationTriangleIcon />
          <span>{t(`tenantTasks.notice.${model.state}`)}</span>
          {model.reasonCode ? <code>{model.reasonCode}</code> : null}
          {model.retryVisible ? (
            <Button color="gray" variant="ghost" onClick={onRetry}>
              {t('common.retry')}
            </Button>
          ) : null}
        </div>
      ) : null}
      <div className="tenant-tasks-scope">
        <span>
          {t(
            model.authority === 'cloud'
              ? 'tenantTasks.scope.tenant'
              : 'tenantTasks.scope.project',
          )}
        </span>
        <code>
          {model.authority === 'cloud'
            ? model.scope.tenantId
            : model.scope.projectId}
        </code>
        <small>
          {t('tenantTasks.updated', {
            time: model.lastUpdatedAt
              ? new Date(model.lastUpdatedAt).toLocaleTimeString()
              : '—',
          })}
        </small>
      </div>
      <TaskStats model={model} />
      <section
        className="tenant-tasks-queue"
        aria-label={t('tenantTasks.queue.title')}
      >
        <header>
          <div>
            <h2>{t('tenantTasks.queue.title')}</h2>
            <p>{t('tenantTasks.queue.description')}</p>
          </div>
          <strong>{model.queue.current}</strong>
        </header>
        {model.queue.history.length ? (
          <div className="tenant-tasks-queue-bars" aria-hidden="true">
            {model.queue.history.map((point) => (
              <i
                key={`${point.timestamp}:${point.depth}`}
                title={`${point.timestamp}: ${point.depth}`}
                style={{
                  height: `${Math.max(4, Math.min(100, point.depth * 10)).toString()}%`,
                }}
              />
            ))}
          </div>
        ) : (
          <p className="tenant-tasks-queue-unavailable">
            {t('tenantTasks.queue.historyUnavailable')}
          </p>
        )}
      </section>
      <section className="tenant-tasks-list">
        <header>
          <h2>{t('tenantTasks.list.title')}</h2>
          <div>
            <label>
              <span>{t('tenantTasks.search')}</span>
              <MagnifyingGlassIcon />
              <TextField.Root
                aria-label={t('tenantTasks.search')}
                value={model.query.search}
                placeholder={t('tenantTasks.search')}
                onChange={(event) => {
                  void controller
                    .setQuery({ search: event.target.value, offset: 0 })
                    .catch(() => undefined);
                }}
              />
            </label>
            <label>
              <span>{t('tenantTasks.status')}</span>
              <select
                value={model.query.status}
                aria-label={t('tenantTasks.status')}
                onChange={(event) => {
                  void controller
                    .setQuery({ status: event.target.value, offset: 0 })
                    .catch(() => undefined);
                }}
              >
                {[
                  'all',
                  'pending',
                  'processing',
                  'completed',
                  'failed',
                  'stopped',
                ].map((status) => (
                  <option value={status} key={status}>
                    {t(`tenantTasks.status.${status}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>
        {model.tasks.length ? (
          <TaskTable
            model={model}
            onRetryTask={(task) => {
              void controller.retryTask(task.id).catch(() => undefined);
            }}
            onStopTask={(task, trigger) => {
              stopTriggerRef.current = trigger;
              setConfirmingTaskId(task.id);
            }}
          />
        ) : (
          <div className="tenant-tasks-empty">
            <h3>{t('tenantTasks.empty.title')}</h3>
            <p>{t('tenantTasks.empty.description')}</p>
          </div>
        )}
        <footer>
          <span>
            {t('tenantTasks.pagination', {
              count: model.tasks.length,
              total: model.total,
            })}
          </span>
          <div>
            <Button
              color="gray"
              variant="soft"
              disabled={model.offset === 0 || model.busyAction !== null}
              onClick={() => {
                void controller
                  .setQuery({ offset: Math.max(0, model.offset - model.limit) })
                  .catch(() => undefined);
              }}
            >
              {t('tenantTasks.previous')}
            </Button>
            <Button
              color="gray"
              variant="soft"
              disabled={!model.hasMore || model.busyAction !== null}
              onClick={() => {
                void controller
                  .setQuery({ offset: model.offset + model.limit })
                  .catch(() => undefined);
              }}
            >
              {t('tenantTasks.next')}
            </Button>
          </div>
        </footer>
      </section>
      <nav className="tenant-tasks-links" aria-label={t('tenantTasks.related')}>
        {model.allowedActions.includes('navigate-dead-letter-queue') ? (
          <a
            href={`#/tenant/${encodeURIComponent(model.scope.tenantId)}/dead-letter-queue`}
          >
            {t('tenantTasks.deadLetterQueue')}
          </a>
        ) : null}
      </nav>
      {confirmingTask ? (
        <StopTaskDialog
          task={confirmingTask}
          busy={model.busyAction !== null}
          onCancel={closeStopDialog}
          onConfirm={async () => {
            await controller.stopTask(confirmingTask.id);
            closeStopDialog();
          }}
        />
      ) : null}
    </section>
  );
}

function TaskStats({ model }: Readonly<{ model: TenantTasksViewModel }>) {
  const { t } = useI18n();
  const rows = [
    ['total', model.stats.total],
    ['throughput', `${model.stats.throughputPerMinute.toFixed(1)}/min`],
    ['pending', model.stats.pending],
    ['failed', model.stats.failed],
  ] as const;
  return (
    <div className="tenant-tasks-stats">
      {rows.map(([key, value]) => (
        <article key={key}>
          <span>{t(`tenantTasks.stats.${key}`)}</span>
          <strong>{value}</strong>
          {key === 'failed' ? (
            <small>{model.stats.errorRate.toFixed(1)}%</small>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function TaskTable({
  model,
  onRetryTask,
  onStopTask,
}: Readonly<{
  model: TenantTasksViewModel;
  onRetryTask: (task: TenantTaskRecord) => void;
  onStopTask: (task: TenantTaskRecord, trigger: HTMLButtonElement) => void;
}>) {
  const { t } = useI18n();
  return (
    <div className="tenant-tasks-table-scroll">
      <table>
        <thead>
          <tr>
            {['status', 'task', 'entity', 'created', 'actions'].map(
              (column) => (
                <th key={column}>{t(`tenantTasks.column.${column}`)}</th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {model.tasks.map((task) => (
            <tr key={task.id}>
              <td>
                <span className={`tenant-task-status status-${task.status}`}>
                  {task.status}
                </span>
              </td>
              <td>
                <strong>{task.name}</strong>
                <code>{task.id}</code>
              </td>
              <td>
                {task.entityId
                  ? `${task.entityType ?? 'entity'}:${task.entityId}`
                  : '—'}
              </td>
              <td>{new Date(task.createdAt).toLocaleString()}</td>
              <td>
                {task.canRetry &&
                model.allowedActions.includes('retry-task') ? (
                  <Button
                    color="gray"
                    variant="ghost"
                    disabled={model.busyAction !== null}
                    onClick={() => onRetryTask(task)}
                  >
                    <ReloadIcon />
                    {t('tenantTasks.retryTask')}
                  </Button>
                ) : null}
                {task.canStop && model.allowedActions.includes('stop-task') ? (
                  <Button
                    color="red"
                    variant="ghost"
                    disabled={model.busyAction !== null}
                    onClick={(event) => onStopTask(task, event.currentTarget)}
                  >
                    <StopIcon />
                    {t('tenantTasks.stopTask')}
                  </Button>
                ) : null}
                {model.allowedActions.includes('open-workspace') &&
                task.projectId &&
                task.workspaceId ? (
                  <a
                    href={`#/tenant/${encodeURIComponent(model.scope.tenantId)}/project/${encodeURIComponent(
                      task.projectId,
                    )}/workspace/${encodeURIComponent(task.workspaceId)}`}
                  >
                    {t('tenantTasks.openWorkspace')}
                  </a>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StopTaskDialog({
  task,
  busy,
  onCancel,
  onConfirm,
}: Readonly<{
  task: TenantTaskRecord;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}>) {
  const { t } = useI18n();
  return (
    <div className="tenant-tasks-dialog">
      <div
        className="tenant-tasks-dialog-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tenant-task-stop-title"
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !busy) onCancel();
        }}
      >
        <button type="button" aria-label={t('common.close')} onClick={onCancel}>
          <Cross2Icon />
        </button>
        <h2 id="tenant-task-stop-title">{t('tenantTasks.stopDialog.title')}</h2>
        <p>{t('tenantTasks.stopDialog.description', { task: task.name })}</p>
        <div>
          <Button
            autoFocus
            color="gray"
            variant="soft"
            disabled={busy}
            onClick={onCancel}
          >
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            disabled={busy}
            onClick={() => {
              void onConfirm().catch(() => undefined);
            }}
          >
            {t('tenantTasks.stopTask')}
          </Button>
        </div>
      </div>
    </div>
  );
}

function TenantTasksState({
  model,
  onRetry,
}: Readonly<{
  model: TenantTasksViewModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  return (
    <section className="tenant-tasks-state" data-state={model.state}>
      <h1>{t(`tenantTasks.state.${model.state}.title`)}</h1>
      <p>{t(`tenantTasks.state.${model.state}.description`)}</p>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.retryVisible ? (
        <Button color="gray" variant="soft" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}
