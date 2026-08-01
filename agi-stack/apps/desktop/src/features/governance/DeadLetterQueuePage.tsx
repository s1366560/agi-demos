import { Cross2Icon, EyeOpenIcon, ReloadIcon, ResumeIcon, TrashIcon } from '@radix-ui/react-icons';
import { Button, TextField } from '@radix-ui/themes';
import { useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import type { DeadLetterQueueMessage } from './deadLetterQueueClient';
import type {
  DeadLetterQueueController,
  DeadLetterQueueResourceState,
  DeadLetterQueueViewModel,
} from './deadLetterQueueController';
import './DeadLetterQueuePage.css';

export function DeadLetterQueuePage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: DeadLetterQueueViewModel;
  controller: DeadLetterQueueController;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [discardTargetIds, setDiscardTargetIds] = useState<readonly string[]>([]);
  const [discardIsBatch, setDiscardIsBatch] = useState(false);
  const [discardReason, setDiscardReason] = useState('');
  const [cleanupKind, setCleanupKind] = useState<'expired' | 'resolved' | null>(null);
  const dialogTriggerRef = useRef<HTMLButtonElement | null>(null);
  const closeDialog = (): void => {
    setDiscardTargetIds([]);
    setDiscardIsBatch(false);
    setDiscardReason('');
    setCleanupKind(null);
    queueMicrotask(() => dialogTriggerRef.current?.focus());
  };
  const canMutate =
    model.authority === 'cloud' && model.busyAction === null && model.allowedActions.length > 0;
  return (
    <section className="dead-letter-queue-page" data-authority={model.authority}>
      <header className="dead-letter-queue-header">
        <div>
          <span>{t('deadLetterQueue.eyebrow')}</span>
          <h1>{t('deadLetterQueue.title')}</h1>
          <p>{t('deadLetterQueue.subtitle')}</p>
        </div>
        <div className="dead-letter-queue-header-actions">
          {model.allowedActions.includes('cleanup') ? (
            <>
              <Button
                color="gray"
                variant="soft"
                disabled={!canMutate}
                ref={dialogTriggerRef}
                onClick={() => setCleanupKind('expired')}
              >
                <TrashIcon />
                {t('deadLetterQueue.cleanupExpired')}
              </Button>
              <Button
                color="gray"
                variant="soft"
                disabled={!canMutate}
                onClick={(event) => {
                  dialogTriggerRef.current = event.currentTarget;
                  setCleanupKind('resolved');
                }}
              >
                <TrashIcon />
                {t('deadLetterQueue.cleanupResolved')}
              </Button>
            </>
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

      <div className="dead-letter-queue-scope">
        <span>{t('deadLetterQueue.scope')}</span>
        <code>{model.scope.tenantId}</code>
        {model.lastUpdatedAt ? (
          <small>
            {t('deadLetterQueue.updated', {
              time: new Date(model.lastUpdatedAt).toLocaleTimeString(),
            })}
          </small>
        ) : null}
      </div>

      <ResourceNotice
        resource="stats"
        state={model.statsState}
        reasonCode={model.statsReasonCode}
        retryVisible={model.retryStatsVisible}
        onRetry={onRetry}
      />
      <StatsGrid model={model} />

      <ResourceNotice
        resource="messages"
        state={model.messagesState}
        reasonCode={model.messagesReasonCode}
        retryVisible={model.retryMessagesVisible}
        onRetry={onRetry}
      />
      <section className="dead-letter-queue-catalog">
        <header>
          <div>
            <h2>{t('deadLetterQueue.messages.title')}</h2>
            <p>
              {t('deadLetterQueue.messages.count', {
                count: model.messages.length,
                total: model.total,
              })}
            </p>
          </div>
          <div className="dead-letter-queue-batch-actions">
            {model.allowedActions.includes('retry-batch') ? (
              <Button
                color="gray"
                disabled={!canMutate || model.selectedIds.length === 0}
                onClick={() => {
                  void controller.retrySelected().catch(() => undefined);
                }}
              >
                <ResumeIcon />
                {t('deadLetterQueue.retrySelected')}
              </Button>
            ) : null}
            {model.allowedActions.includes('discard') ? (
              <Button
                color="red"
                variant="soft"
                disabled={!canMutate || model.selectedIds.length === 0}
                onClick={(event) => {
                  dialogTriggerRef.current = event.currentTarget;
                  setDiscardTargetIds(model.selectedIds);
                  setDiscardIsBatch(true);
                }}
              >
                <TrashIcon />
                {t('deadLetterQueue.discardSelected')}
              </Button>
            ) : null}
          </div>
        </header>
        <Filters model={model} controller={controller} />
        {model.messagesState === 'empty' ? (
          <div className="dead-letter-queue-empty">
            <h3>{t('deadLetterQueue.empty.title')}</h3>
            <p>{t('deadLetterQueue.empty.description')}</p>
          </div>
        ) : model.messages.length > 0 ? (
          <MessageTable
            model={model}
            onToggleSelection={(messageId) => controller.toggleSelection(messageId)}
            onInspect={(message) => {
              void controller.openDetail(message.id);
            }}
            onRetry={(message) => {
              void controller.retryMessage(message.id).catch(() => undefined);
            }}
            onDiscard={(message, trigger) => {
              dialogTriggerRef.current = trigger;
              setDiscardTargetIds([message.id]);
              setDiscardIsBatch(false);
            }}
          />
        ) : null}
        <footer>
          <span>
            {t('deadLetterQueue.messages.count', {
              count: model.messages.length,
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
              {t('deadLetterQueue.previous')}
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
              {t('deadLetterQueue.next')}
            </Button>
          </div>
        </footer>
      </section>

      {model.mutationState !== 'idle' ? (
        <div
          className="dead-letter-queue-mutation-notice"
          role="alert"
          data-state={model.mutationState}
        >
          <strong>{t(`deadLetterQueue.mutation.${model.mutationState}`)}</strong>
          {model.mutationReasonCode ? <code>{model.mutationReasonCode}</code> : null}
        </div>
      ) : null}
      {model.detailState !== 'idle' ? (
        <MessageDetail model={model} onClose={() => controller.closeDetail()} />
      ) : null}
      {discardTargetIds.length > 0 ? (
        <DiscardDialog
          count={discardTargetIds.length}
          reason={discardReason}
          busy={model.busyAction !== null}
          onReasonChange={setDiscardReason}
          onCancel={closeDialog}
          onConfirm={async () => {
            if (discardIsBatch) {
              await controller.discardMessages(discardTargetIds, discardReason);
            } else {
              await controller.discardMessage(discardTargetIds[0] ?? '', discardReason);
            }
            closeDialog();
          }}
        />
      ) : null}
      {cleanupKind ? (
        <ConfirmDialog
          title={t(`deadLetterQueue.cleanup.${cleanupKind}.title`)}
          description={t(`deadLetterQueue.cleanup.${cleanupKind}.description`)}
          confirmLabel={t('deadLetterQueue.cleanup.confirm')}
          busy={model.busyAction !== null}
          onCancel={closeDialog}
          onConfirm={async () => {
            await controller.cleanup(cleanupKind, cleanupKind === 'expired' ? 168 : 24);
            closeDialog();
          }}
        />
      ) : null}
    </section>
  );
}

function StatsGrid({ model }: Readonly<{ model: DeadLetterQueueViewModel }>) {
  const { t } = useI18n();
  if (model.statsState === 'loading' && model.stats === null) {
    return (
      <div className="dead-letter-queue-loading" role="status">
        {t('deadLetterQueue.stats.loading')}
      </div>
    );
  }
  if (model.stats === null) return null;
  const rows = [
    ['total', model.stats.totalMessages],
    ['pending', model.stats.pendingCount],
    ['retrying', model.stats.retryingCount],
    ['resolved', model.stats.resolvedCount],
    ['discarded', model.stats.discardedCount],
    ['expired', model.stats.expiredCount],
  ] as const;
  return (
    <div className="dead-letter-queue-stats">
      {rows.map(([key, value]) => (
        <article key={key}>
          <span>{t(`deadLetterQueue.stats.${key}`)}</span>
          <strong>{value}</strong>
        </article>
      ))}
    </div>
  );
}

function Filters({
  model,
  controller,
}: Readonly<{ model: DeadLetterQueueViewModel; controller: DeadLetterQueueController }>) {
  const { t } = useI18n();
  const update = (query: Parameters<typeof controller.setQuery>[0]): void => {
    void controller.setQuery({ ...query, offset: 0 }).catch(() => undefined);
  };
  return (
    <div className="dead-letter-queue-filters">
      <label>
        <span>{t('deadLetterQueue.filter.status')}</span>
        <select
          value={model.query.status}
          onChange={(event) => update({ status: event.target.value as typeof model.query.status })}
        >
          {['all', 'pending', 'retrying', 'discarded', 'expired', 'resolved'].map((status) => (
            <option key={status} value={status}>
              {t(`deadLetterQueue.status.${status}`)}
            </option>
          ))}
        </select>
      </label>
      {[
        ['eventType', 'eventType'],
        ['errorType', 'errorType'],
        ['routingKey', 'routingKey'],
      ].map(([field, key]) => (
        <label key={field}>
          <span>{t(`deadLetterQueue.filter.${key}`)}</span>
          <TextField.Root
            value={model.query[field as keyof typeof model.query] as string}
            aria-label={t(`deadLetterQueue.filter.${key}`)}
            onChange={(event) => update({ [field]: event.target.value })}
          />
        </label>
      ))}
    </div>
  );
}

function MessageTable({
  model,
  onToggleSelection,
  onInspect,
  onRetry,
  onDiscard,
}: Readonly<{
  model: DeadLetterQueueViewModel;
  onToggleSelection: (messageId: string) => void;
  onInspect: (message: DeadLetterQueueMessage) => void;
  onRetry: (message: DeadLetterQueueMessage) => void;
  onDiscard: (message: DeadLetterQueueMessage, trigger: HTMLButtonElement) => void;
}>) {
  const { t } = useI18n();
  return (
    <div className="dead-letter-queue-table-scroll">
      <table>
        <thead>
          <tr>
            <th>{t('deadLetterQueue.column.select')}</th>
            {['status', 'event', 'error', 'retries', 'failedAt', 'actions'].map((column) => (
              <th key={column}>{t(`deadLetterQueue.column.${column}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {model.messages.map((message) => (
            <tr key={message.id}>
              <td>
                <input
                  type="checkbox"
                  checked={model.selectedIds.includes(message.id)}
                  aria-label={t('deadLetterQueue.selectMessage', { id: message.id })}
                  disabled={model.busyAction !== null}
                  onChange={() => onToggleSelection(message.id)}
                />
              </td>
              <td>
                <span className={`dead-letter-status status-${message.status}`}>
                  {t(`deadLetterQueue.status.${message.status}`)}
                </span>
              </td>
              <td>
                <strong>{message.eventType}</strong>
                <code>{message.routingKey}</code>
              </td>
              <td>
                <strong>{message.errorType}</strong>
                <span>{message.error}</span>
              </td>
              <td>
                {message.retryCount}/{message.maxRetries}
              </td>
              <td>{new Date(message.lastFailedAt).toLocaleString()}</td>
              <td>
                <Button color="gray" variant="ghost" onClick={() => onInspect(message)}>
                  <EyeOpenIcon />
                  {t('deadLetterQueue.inspect')}
                </Button>
                {message.canRetry && model.allowedActions.includes('retry-message') ? (
                  <Button
                    color="gray"
                    variant="ghost"
                    disabled={model.busyAction !== null}
                    onClick={() => onRetry(message)}
                  >
                    <ResumeIcon />
                    {t('deadLetterQueue.retry')}
                  </Button>
                ) : null}
                {model.allowedActions.includes('discard') ? (
                  <Button
                    color="red"
                    variant="ghost"
                    disabled={model.busyAction !== null}
                    onClick={(event) => onDiscard(message, event.currentTarget)}
                  >
                    <TrashIcon />
                    {t('deadLetterQueue.discard')}
                  </Button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResourceNotice({
  resource,
  state,
  reasonCode,
  retryVisible,
  onRetry,
}: Readonly<{
  resource: 'messages' | 'stats';
  state: DeadLetterQueueResourceState;
  reasonCode: string | null;
  retryVisible: boolean;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (state === 'ready' || state === 'empty') return null;
  return (
    <div className="dead-letter-queue-resource-notice" data-state={state}>
      <strong>{t(`deadLetterQueue.${resource}.state.${state}`)}</strong>
      {reasonCode ? <code>{reasonCode}</code> : null}
      {retryVisible ? (
        <Button color="gray" variant="ghost" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      ) : null}
    </div>
  );
}

function MessageDetail({
  model,
  onClose,
}: Readonly<{ model: DeadLetterQueueViewModel; onClose: () => void }>) {
  const { t } = useI18n();
  return (
    <aside className="dead-letter-queue-detail" aria-label={t('deadLetterQueue.detail.title')}>
      <header>
        <h2>{t('deadLetterQueue.detail.title')}</h2>
        <Button color="gray" variant="ghost" onClick={onClose}>
          <Cross2Icon />
          {t('common.close')}
        </Button>
      </header>
      {model.detailState === 'loading' ? (
        <p>{t('deadLetterQueue.detail.loading')}</p>
      ) : model.detail ? (
        <dl>
          {[
            ['id', model.detail.id],
            ['eventId', model.detail.eventId],
            ['eventType', model.detail.eventType],
            ['routingKey', model.detail.routingKey],
            ['errorType', model.detail.errorType],
            ['error', model.detail.error],
            ['eventData', model.detail.eventData],
            ['traceback', model.detail.errorTraceback ?? '—'],
            ['metadata', JSON.stringify(model.detail.metadata, null, 2)],
          ].map(([key, value]) => (
            <div key={key}>
              <dt>{t(`deadLetterQueue.detail.${key}`)}</dt>
              <dd>
                <pre>{value}</pre>
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>
          {t(
            model.detailState === 'forbidden'
              ? 'deadLetterQueue.detail.forbidden'
              : 'deadLetterQueue.detail.loadError',
          )}
        </p>
      )}
    </aside>
  );
}

function DiscardDialog({
  count,
  reason,
  busy,
  onReasonChange,
  onCancel,
  onConfirm,
}: Readonly<{
  count: number;
  reason: string;
  busy: boolean;
  onReasonChange: (reason: string) => void;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}>) {
  const { t } = useI18n();
  return (
    <div className="dead-letter-queue-dialog-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-label={t('deadLetterQueue.discardDialog.title')}
      >
        <h2>{t('deadLetterQueue.discardDialog.title')}</h2>
        <p>{t('deadLetterQueue.discardDialog.description', { count })}</p>
        <label>
          <span>{t('deadLetterQueue.discardDialog.reason')}</span>
          <textarea
            autoFocus
            maxLength={500}
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
          />
        </label>
        <footer>
          <Button color="gray" variant="soft" disabled={busy} onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            disabled={busy || !reason.trim()}
            onClick={() => void onConfirm().catch(() => undefined)}
          >
            {t('deadLetterQueue.discard')}
          </Button>
        </footer>
      </section>
    </div>
  );
}

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: Readonly<{
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}>) {
  return (
    <div className="dead-letter-queue-dialog-backdrop">
      <section role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        <p>{description}</p>
        <footer>
          <Button color="gray" variant="soft" disabled={busy} onClick={onCancel}>
            <DialogCancelLabel />
          </Button>
          <Button
            color="red"
            disabled={busy}
            onClick={() => void onConfirm().catch(() => undefined)}
          >
            {confirmLabel}
          </Button>
        </footer>
      </section>
    </div>
  );
}

function DialogCancelLabel() {
  const { t } = useI18n();
  return t('common.cancel');
}
