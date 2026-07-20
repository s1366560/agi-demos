import { useState } from 'react';
import {
  CheckCircledIcon,
  Cross2Icon,
  LockClosedIcon,
  StopIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

export function ApprovalCard({ mode, onResolve }) {
  const { t } = useI18n();
  const [instruction, setInstruction] = useState('');

  const title = mode === 'code' ? 'Approve the fixture ownership boundary' : 'Choose the strategic priority';
  const scope = mode === 'code'
    ? 'Scope: src/pipeline and src/tests only. No changes to the public API or release configuration.'
    : 'Scope: this brief only. No external sharing or new data collection until you approve it.';

  return (
    <article className="approval-card" aria-label={t('Approval request')}>
      <header>
        <span className="approval-card-icon"><StopIcon /></span>
        <div>
          <small>{t('HUMAN DECISION')}</small>
          <b>{t(title)}</b>
          <p>{t('The agent is paused before changing the approved scope.')}</p>
        </div>
      </header>
      <div className="approval-card-scope"><LockClosedIcon /><span>{t(scope)}</span></div>
      <label className="approval-card-instruction">
        <span>{t('Your instruction (optional)')}</span>
        <textarea
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder={t('Add guidance for this decision…')}
        />
      </label>
      <div className="approval-card-actions">
        <button type="button" onClick={() => onResolve('deny', instruction)}><Cross2Icon /> {t('Deny')}</button>
        <button type="button" onClick={() => onResolve('allow-always', instruction)}><LockClosedIcon /> {t('Always allow')}</button>
        <button className="primary" type="button" onClick={() => onResolve('allow-once', instruction)}><CheckCircledIcon /> {t('Allow once')}</button>
      </div>
    </article>
  );
}
