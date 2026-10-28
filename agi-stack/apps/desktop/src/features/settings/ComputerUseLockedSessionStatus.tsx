import type { ComputerUseSnapshot } from '../../api/computerUseContractV2';
import { useI18n } from '../../i18n';
import { computerUseLockedSessionView } from './computerUseLockedSessionModel';
import './ComputerUseLockedSessionStatus.css';

export function ComputerUseLockedSessionStatus({ session }: {
  session: ComputerUseSnapshot['sessions'][number];
}) {
  const { t } = useI18n();
  const view = computerUseLockedSessionView(session);
  if (!view) return null;
  return (
    <section className="computer-use-locked-session" aria-label={t('cua.lockedUse.session')}>
      <p role={view.phase === 'failed' ? 'alert' : 'status'}>
        <strong>{t('cua.capability.locked_use')}</strong>
        {' · '}{t(`cua.lockedUse.phase.${view.phase}`)}
      </p>
      <p>{t(`cua.lockedUse.hint.${view.phase}`)}</p>
      {view.requiresManualUnlock ? <p role="alert">{t('cua.lockedUse.manualUnlock')}</p> : null}
      {view.reason ? <details>
        <summary>{t('cua.lockedUse.reason')}</summary>
        <code>{view.reason}</code>
      </details> : null}
    </section>
  );
}
