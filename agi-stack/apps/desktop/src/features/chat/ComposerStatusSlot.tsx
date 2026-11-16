import { ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import './ComposerStatusSlot.css';

type ComposerStatusSlotProps = {
  notice?: {
    tone: 'loading' | 'warning' | 'error';
    title: string;
    description: string;
    actionLabel?: string;
  } | null;
  queueLoading: boolean;
};

/** Reserve one line for transient recovery and empty-queue synchronization.
 * Actionable notices and failures remain on their full, separate surfaces. */
export function ComposerStatusSlot({ notice, queueLoading }: ComposerStatusSlotProps) {
  const { t } = useI18n();
  const recovery = notice?.tone === 'loading' && !notice.actionLabel ? notice : null;
  return (
    <div className="composer-status-slot" role="status" aria-live="polite" aria-atomic="true">
      {recovery ? (
        <span className="composer-status-recovery" title={`${recovery.title} ${recovery.description}`}>
          <ReloadIcon aria-hidden="true" />
          <strong>{recovery.title}</strong>
          <span>{recovery.description}</span>
        </span>
      ) : null}
      {queueLoading ? <span className="composer-status-queue">{t('session.queueLoading')}</span> : null}
    </div>
  );
}
