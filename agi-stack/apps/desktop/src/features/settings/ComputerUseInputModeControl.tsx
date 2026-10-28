import { useId } from 'react';
import type { ComputerUseOperation, ComputerUseSnapshot } from '../../api/computerUseContractV2';
import type { ComputerUseInputMode } from '../../api/computerUseInput';
import { useI18n } from '../../i18n';

export function ComputerUseInputModeControl({
  snapshot,
  busy,
  manage,
}: {
  snapshot: ComputerUseSnapshot;
  busy: boolean;
  manage: (operation: ComputerUseOperation) => Promise<void>;
}) {
  const { t } = useI18n();
  const description = useId();
  const mode = snapshot.instance.input_mode ?? 'background';
  const support = snapshot.input_support?.[mode];
  return (
    <div className="computer-use-input-mode">
      <label>
        <span>{t('cua.input.mode')}</span>
        <select
          value={mode}
          aria-describedby={description}
          disabled={
            busy ||
            !snapshot.instance.installed ||
            !snapshot.helper_available ||
            !snapshot.input_support
          }
          onChange={(event) => {
            const selected = event.target.value as ComputerUseInputMode;
            if (selected === mode || !snapshot.input_support?.[selected]?.supported) return;
            void manage({
              action: 'set_input_mode',
              input_mode: selected,
              expected_revision: snapshot.instance.revision,
            });
          }}
        >
          {(['background', 'foreground'] as const).map((option) => (
            <option
              key={option}
              value={option}
              disabled={!snapshot.input_support?.[option]?.supported}
            >
              {t(`cua.input.${option}`)}
            </option>
          ))}
        </select>
      </label>
      <p id={description}>{t(`cua.input.${mode}Description`)}</p>
      {snapshot.sessions.some((session) => !session.stopped) ? (
        <p>{t('cua.input.modeChangeStopsSessions')}</p>
      ) : null}
      <p className="computer-use-input-support" role="status">
        {t(
          support
            ? support.supported
              ? 'cua.input.supported'
              : 'cua.input.unsupported'
            : 'cua.input.unverified',
        )}
        {support?.reason ? <code>{support.reason}</code> : null}
      </p>
    </div>
  );
}
