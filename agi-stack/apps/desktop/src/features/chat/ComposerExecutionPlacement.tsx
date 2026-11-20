import { useId, useState } from 'react';

import { useI18n } from '../../i18n';
import {
  executionPlacementMessageKey,
  type ExecutionPlacementTarget,
  type ExecutionSendBlockCode,
} from './executionPlacementModel';

export function executionPlacementNoticeText(
  translate: (key: string, values?: { detail?: string }) => string,
  code: ExecutionSendBlockCode | null,
  detail: string | null,
): string | null {
  if (!code) return null;
  return translate(executionPlacementMessageKey(code), { detail: detail ?? '' });
}

export type ComposerExecutionPlacementProps = {
  variant: 'workspace' | 'session';
  surface?: 'desktop' | 'web';
  target: ExecutionPlacementTarget;
  localRootLabel: string | null;
  readOnly: boolean;
  pathUnavailable: boolean;
  notice: string | null;
  onTargetChange: (target: ExecutionPlacementTarget) => void;
  onPickDirectory: () => void;
  onManageEnvironment: () => void;
};

export function ComposerExecutionPlacement({
  variant,
  surface = 'desktop',
  target,
  localRootLabel,
  readOnly,
  pathUnavailable,
  notice,
  onTargetChange,
  onPickDirectory,
  onManageEnvironment,
}: ComposerExecutionPlacementProps) {
  const { t } = useI18n();
  const menuId = useId();
  const [menuOpen, setMenuOpen] = useState(false);
  const web = surface === 'web';
  const directoryLabel =
    localRootLabel ||
    (pathUnavailable
      ? t('executionPlacement.directoryUnavailable')
      : t('executionPlacement.loadingDirectory'));

  return (
    <div
      className="composer-execution-placement"
      data-variant={variant}
      data-surface={surface}
      data-readonly={readOnly ? 'true' : 'false'}
      role="group"
      aria-label={t('executionPlacement.targetLabel')}
    >
      <div className="composer-execution-capsule" data-capsule="target">
        {web && target === 'local' ? (
          <span className="composer-execution-static">{t('executionTarget.local')}</span>
        ) : web ? (
          <span className="composer-execution-static" data-execution-target="cloud">
            {t('executionTarget.cloud')}
          </span>
        ) : (
          <>
            <button
              type="button"
              aria-pressed={target === 'local'}
              disabled={readOnly}
              data-execution-target="local"
              onClick={() => onTargetChange('local')}
            >
              {t('executionTarget.local')}
            </button>
            <button
              type="button"
              aria-pressed={target === 'cloud'}
              disabled={readOnly}
              data-execution-target="cloud"
              onClick={() => onTargetChange('cloud')}
            >
              {t('executionTarget.cloud')}
            </button>
          </>
        )}
      </div>
      <div className="composer-execution-capsule" data-capsule="resource">
        {target === 'local' ? (
          web ? (
            <span className="composer-execution-static" title={directoryLabel}>
              {directoryLabel}
            </span>
          ) : (
            <button
              type="button"
              disabled={readOnly}
              data-execution-resource="directory"
              title={directoryLabel}
              onClick={onPickDirectory}
            >
              {directoryLabel}
            </button>
          )
        ) : (
          <>
            <span className="composer-execution-static" data-execution-resource="default-environment">
              {t('executionTarget.defaultEnvironment')}
            </span>
            {web ? null : (
              <details
                className="composer-execution-environment-menu"
                open={menuOpen}
                onToggle={(event) => setMenuOpen(event.currentTarget.open)}
              >
                <summary aria-controls={menuId}>{t('executionPlacement.environmentActions')}</summary>
                <div id={menuId} role="menu">
                  <button type="button" role="menuitem" disabled>
                    {t('executionPlacement.createEnvironment')}
                  </button>
                  <button type="button" role="menuitem" onClick={onManageEnvironment}>
                    {t('executionPlacement.manageEnvironment')}
                  </button>
                  <button type="button" role="menuitem" disabled>
                    {t('executionPlacement.moreEnvironments')}
                  </button>
                  <p>{t('executionPlacement.environmentPlaceholder')}</p>
                </div>
              </details>
            )}
          </>
        )}
      </div>
      {notice ? (
        <p className="composer-execution-notice" role="alert">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
