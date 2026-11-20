import { useTranslation } from 'react-i18next';

import { executionTargetOf, type ExecutionTargetFilter } from './executionTargetModel';

export type { ExecutionTargetFilter };

export function ExecutionTargetBadge({
  executionTarget,
  localRootLabel,
  running = false,
}: {
  executionTarget?: string | null | undefined;
  localRootLabel?: string | null | undefined;
  running?: boolean;
}) {
  const { t } = useTranslation();
  const target = executionTargetOf(executionTarget);
  const label =
    target === 'local'
      ? t('agent.executionTarget.local', 'This computer')
      : t('agent.executionTarget.cloud', 'Cloud');
  const detail =
    target === 'local'
      ? localRootLabel?.trim() || t('agent.executionTarget.localDirectory', 'Local directory')
      : t('agent.executionTarget.defaultEnvironment', 'Default environment');
  return (
    <span
      className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300"
      data-execution-target={target}
      data-running={running ? 'true' : 'false'}
    >
      <span>{label}</span>
      <span className="truncate font-normal text-slate-400" title={detail}>
        {detail}
      </span>
    </span>
  );
}

export function ExecutionTargetFilterBar({
  value,
  onChange,
}: {
  value: ExecutionTargetFilter;
  onChange: (value: ExecutionTargetFilter) => void;
}) {
  const { t } = useTranslation();
  const options: Array<{ id: ExecutionTargetFilter; label: string }> = [
    { id: 'all', label: t('agent.executionTarget.all', 'All') },
    { id: 'local', label: t('agent.executionTarget.local', 'This computer') },
    { id: 'cloud', label: t('agent.executionTarget.cloud', 'Cloud') },
  ];
  return (
    <div
      role="group"
      aria-label={t('agent.executionTarget.filterLabel', 'Execution location')}
      className="mb-2 flex gap-1"
    >
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          data-execution-target={option.id}
          onClick={() => {
            onChange(option.id);
          }}
          className={`rounded-full border px-2 py-0.5 text-xs ${
            value === option.id
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-slate-200 text-slate-500 dark:border-slate-700'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
