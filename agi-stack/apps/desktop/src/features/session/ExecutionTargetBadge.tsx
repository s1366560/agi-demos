import { useI18n } from '../../i18n';

export type ExecutionTarget = 'local' | 'cloud';
export type ExecutionTargetFilter = 'all' | ExecutionTarget;

export function executionTargetOf(value: unknown): ExecutionTarget {
  return value === 'local' ? 'local' : 'cloud';
}

export function ExecutionTargetBadge({
  executionTarget,
  localRootLabel,
  running = false,
}: {
  executionTarget?: string | null;
  localRootLabel?: string | null;
  running?: boolean;
}) {
  const { t } = useI18n();
  const target = executionTargetOf(executionTarget);
  const label =
    target === 'local' ? t('executionTarget.local') : t('executionTarget.cloud');
  const detail =
    target === 'local'
      ? localRootLabel?.trim() || t('executionTarget.localDirectory')
      : t('executionTarget.defaultEnvironment');
  return (
    <span className="execution-target-badge" data-execution-target={target} data-running={running ? 'true' : 'false'}>
      <strong>{label}</strong>
      <small title={detail}>{detail}</small>
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
  const { t } = useI18n();
  const options: Array<{ id: ExecutionTargetFilter; label: string }> = [
    { id: 'all', label: t('executionTarget.all') },
    { id: 'local', label: t('executionTarget.local') },
    { id: 'cloud', label: t('executionTarget.cloud') },
  ];
  return (
    <div className="execution-target-filter" role="group" aria-label={t('executionTarget.filterLabel')}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          data-execution-target={option.id}
          onClick={() => onChange(option.id)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
