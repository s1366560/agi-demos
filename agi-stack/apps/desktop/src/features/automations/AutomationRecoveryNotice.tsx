import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { AutomationJob } from '../../types';
import { automationLocalRecovery } from './automationModel';

export function AutomationRecoveryNotice({
  job,
  runAllowed,
  busy,
  onRun,
}: {
  job: AutomationJob;
  runAllowed: boolean;
  busy: boolean;
  onRun: () => void;
}) {
  const { t } = useI18n();
  const recovery = automationLocalRecovery(job);
  if (!recovery) return null;
  return (
    <aside className="automation-capability-note" aria-label={t('automations.localExecution')}>
      <strong>{t('automations.localExecution')}</strong>
      <span>{t('automations.localExecutionPolicy')}</span>
      {recovery.missedRunCount > 0 ? (
        <>
          <span>{t('automations.missedRuns', { count: recovery.missedRunCount })}</span>
          <Button variant="soft" disabled={busy || !runAllowed} onClick={onRun}>
            {t('automations.catchUpOnce')}
          </Button>
        </>
      ) : null}
    </aside>
  );
}
