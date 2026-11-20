import { useTranslation } from 'react-i18next';

import type { WebComposerPlacement } from './webExecutionPlacement';

export function WebComposerExecutionPlacement({ placement }: { placement: WebComposerPlacement }) {
  const { t } = useTranslation();
  const local = placement.target === 'local';
  const directory =
    placement.localRootLabel ||
    t('agent.executionPlacement.directoryUnavailable', 'This directory is unavailable');
  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-2"
      data-surface="web"
      data-readonly={placement.readOnly ? 'true' : 'false'}
      role="group"
      aria-label={t('agent.executionPlacement.targetLabel', 'Execution location')}
    >
      <span
        className="inline-flex min-h-7 items-center rounded-full bg-slate-100 px-3 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
        data-execution-target={placement.target}
      >
        {local
          ? t('agent.executionTarget.local', 'This computer')
          : t('agent.executionTarget.cloud', 'Cloud')}
      </span>
      <span
        className="inline-flex min-h-7 max-w-full items-center truncate rounded-full bg-slate-100 px-3 text-xs text-slate-500 dark:bg-slate-800"
        data-execution-resource={local ? 'directory' : 'default-environment'}
      >
        {local ? directory : t('agent.executionTarget.defaultEnvironment', 'Default environment')}
      </span>
      {local ? (
        <p className="m-0 basis-full text-xs text-red-600" role="alert">
          {t(
            'agent.executionPlacement.webLocalReadonly',
            'This session ran on a computer. The web composer can only view it.'
          )}
        </p>
      ) : null}
    </div>
  );
}
