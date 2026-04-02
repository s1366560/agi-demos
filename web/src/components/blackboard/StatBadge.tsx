export interface StatBadgeProps {
  label: string;
  value: string;
}

export function StatBadge({ label, value }: StatBadgeProps) {
  return (
    <div className="rounded-full border border-border-light bg-surface-light px-3 py-2 dark:border-border-dark dark:bg-surface-dark-alt">
      <dt className="text-[11px] uppercase tracking-[0.16em] text-text-muted">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm font-semibold text-text-primary dark:text-text-inverse">
        {value}
      </dd>
    </div>
  );
}
