import type { ComputerUseOperation, ComputerUseSnapshot } from '../../api/computerUseClientV2';
import { useI18n } from '../../i18n';

export function ComputerUseLockedUse({ snapshot, busy, manage }: {
  snapshot: ComputerUseSnapshot;
  busy: boolean;
  manage: (operation: ComputerUseOperation) => Promise<void>;
}) {
  const { t } = useI18n();
  const status = snapshot.locked_use;
  const phase = status?.phase && ['idle', 'armed', 'covering', 'unlocking', 'guarded', 'relocking'].includes(status.phase)
    ? status.phase : null;
  return (
    <section aria-label={t('cua.lockedUse.component')}>
      <h4>{t('cua.lockedUse.component')}</h4>
      <p>{t('cua.lockedUse.mechanism')}</p>
      <p role="status">
        {t(!status ? 'cua.lockedUse.unchecked' : status.installed ? 'cua.lockedUse.installed' : 'cua.lockedUse.missing')}
        {phase ? <> · {t(`cua.lockedUse.phase.${phase}`)}</> : null}
      </p>
      {status?.reason === 'accessibility_and_input_monitoring_required'
        ? <p>{t('cua.lockedUse.permissions')}</p> : null}
      {status?.requires_manual_unlock ? <p role="alert">{t('cua.lockedUse.manualUnlock')}</p> : null}
      <div className="computer-use-actions">
        <button type="button" disabled={busy || !snapshot.helper_available}
          onClick={() => void manage({ action: 'locked_use_status' })}>
          {t('cua.lockedUse.check')}
        </button>
        <button type="button" disabled={busy || !snapshot.helper_available}
          onClick={() => void manage({ action: status?.installed ? 'locked_use_uninstall' : 'locked_use_install', expected_revision: snapshot.instance.revision })}>
          {t(status?.installed ? 'cua.lockedUse.uninstall' : 'cua.lockedUse.install')}
        </button>
      </div>
      <p>{t('cua.lockedUse.administrator')}</p>
    </section>
  );
}
