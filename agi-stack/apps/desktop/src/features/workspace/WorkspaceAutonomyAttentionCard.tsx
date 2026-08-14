import { ExclamationTriangleIcon } from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type {
  WorkspaceAutonomyAttention,
  WorkspaceAutonomyAttentionSourceKind,
  WorkspaceAuthorityCollection,
} from '../../types';

type WorkspaceAutonomyAttentionCardProps = {
  authority: WorkspaceAuthorityCollection<WorkspaceAutonomyAttention>;
  canRetry: boolean;
  canResolve: boolean;
  retryingAttentionId: string | null;
  resolvingAttentionId: string | null;
  onRetry: (attentionId: string) => void;
  onResolve: (attentionId: string) => void;
  onRefresh: () => void;
};

const RETRYABLE_SOURCE_KINDS = new Set<WorkspaceAutonomyAttentionSourceKind>([
  'progression_dead_letter',
  'bootstrap_dead_letter',
  'task_dispatch_dead_letter',
]);
const RESOLVABLE_SOURCE_KINDS = new Set<WorkspaceAutonomyAttentionSourceKind>([
  'judge_block',
  'judge_escalate',
]);

export function WorkspaceAutonomyAttentionCard({
  authority,
  canRetry,
  canResolve,
  retryingAttentionId,
  resolvingAttentionId,
  onRetry,
  onResolve,
  onRefresh,
}: WorkspaceAutonomyAttentionCardProps) {
  const { locale, t } = useI18n();
  const hasItems = authority.items.length > 0;

  return (
    <article
      className="workspace-design-attention-card"
      data-state={authority.status}
      aria-busy={authority.status === 'loading' || undefined}
    >
      <header>
        <span>
          <ExclamationTriangleIcon aria-hidden="true" />
        </span>
        <div>
          <small>{t('overview.autonomyAttention.eyebrow')}</small>
          <h2>{t('overview.autonomyAttention.title')}</h2>
        </div>
        <em>{t('overview.autonomyAttention.openCount', { count: authority.items.length })}</em>
      </header>

      <div className="workspace-design-attention-body">
        {authority.status === 'loading' ? (
          <p role="status">{t('overview.autonomyAttention.loading')}</p>
        ) : null}
        {authority.status === 'unavailable' ? (
          <div className="workspace-design-attention-notice" role="status">
            <p>{t('overview.autonomyAttention.unavailable')}</p>
            <Button size="1" variant="surface" color="gray" onClick={onRefresh}>
              {t('overview.refresh')}
            </Button>
          </div>
        ) : null}
        {authority.status === 'error' ? (
          <div className="workspace-design-attention-notice" role="alert">
            <p>{authority.error ?? t('overview.autonomyAttention.loadFailed')}</p>
            <Button size="1" variant="surface" color="gray" onClick={onRefresh}>
              {t('overview.refresh')}
            </Button>
          </div>
        ) : null}
        {authority.status === 'ready' && !hasItems ? (
          <p role="status">{t('overview.autonomyAttention.empty')}</p>
        ) : null}

        {hasItems ? (
          <div className="workspace-design-attention-list">
            {authority.items.map((attention) => {
              const retryable = RETRYABLE_SOURCE_KINDS.has(attention.source_kind);
              const resolvable = RESOLVABLE_SOURCE_KINDS.has(attention.source_kind);
              const retrying = retryingAttentionId === attention.attention_id;
              const resolving = resolvingAttentionId === attention.attention_id;
              const actionInProgress =
                retryingAttentionId !== null || resolvingAttentionId !== null;
              return (
                <section key={attention.attention_id}>
                  <div>
                    <b>{t(sourceLabelKey(attention.source_kind))}</b>
                    <small>
                      {t('overview.autonomyAttention.createdAt', {
                        date: formatCreatedAt(attention.created_at_ms, locale),
                      })}
                    </small>
                  </div>
                  <p>{attention.reason}</p>
                  {retryable && canRetry ? (
                    <Button
                      size="1"
                      variant="surface"
                      color="amber"
                      loading={retrying}
                      disabled={actionInProgress}
                      onClick={() => onRetry(attention.attention_id)}
                    >
                      {retrying
                        ? t('overview.autonomyAttention.retrying')
                        : t('overview.autonomyAttention.retry')}
                    </Button>
                  ) : null}
                  {resolvable && canResolve ? (
                    <Button
                      size="1"
                      variant="surface"
                      color="green"
                      loading={resolving}
                      disabled={actionInProgress}
                      onClick={() => onResolve(attention.attention_id)}
                    >
                      {resolving
                        ? t('overview.autonomyAttention.resolving')
                        : t('overview.autonomyAttention.resolve')}
                    </Button>
                  ) : null}
                </section>
              );
            })}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function sourceLabelKey(sourceKind: WorkspaceAutonomyAttentionSourceKind): string {
  switch (sourceKind) {
    case 'judge_block':
      return 'overview.autonomyAttention.source.judgeBlock';
    case 'judge_escalate':
      return 'overview.autonomyAttention.source.judgeEscalate';
    case 'progression_dead_letter':
      return 'overview.autonomyAttention.source.progressionDeadLetter';
    case 'bootstrap_dead_letter':
      return 'overview.autonomyAttention.source.bootstrapDeadLetter';
    case 'task_dispatch_dead_letter':
      return 'overview.autonomyAttention.source.taskDispatchDeadLetter';
  }
}

function formatCreatedAt(createdAtMs: number, locale: string): string {
  const createdAt = new Date(createdAtMs);
  if (Number.isNaN(createdAt.getTime())) return '—';
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(createdAt);
}
