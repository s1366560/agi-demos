import type React from 'react';

import { Switch } from 'antd';

export function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border-light bg-surface-light px-3 py-2 dark:border-border-dark dark:bg-surface-dark">
      <div className="text-[11px] font-medium uppercase text-text-muted dark:text-text-muted">
        {label}
      </div>
      <div className="mt-1 truncate text-sm font-semibold text-text-primary dark:text-text-inverse">
        {value}
      </div>
    </div>
  );
}

export function SettingsSection({
  icon,
  title,
  description,
  children,
  tone = 'default',
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  children: React.ReactNode;
  tone?: 'default' | 'danger';
}) {
  return (
    <section
      className={[
        'rounded-lg border bg-surface-light p-4 dark:bg-surface-dark sm:p-5',
        tone === 'danger'
          ? 'border-error-border dark:border-error-border-dark'
          : 'border-border-light dark:border-border-dark',
      ].join(' ')}
    >
      <div className="mb-4 flex items-start gap-3">
        <div
          className={[
            'mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md',
            tone === 'danger'
              ? 'bg-error-bg text-status-text-error dark:bg-error-bg-dark dark:text-status-text-error-dark'
              : 'bg-surface-muted text-text-secondary dark:bg-surface-dark-alt dark:text-text-muted',
          ].join(' ')}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <h2
            className={[
              'text-base font-semibold tracking-tight',
              tone === 'danger'
                ? 'text-status-text-error dark:text-status-text-error-dark'
                : 'text-text-primary dark:text-text-inverse',
            ].join(' ')}
          >
            {title}
          </h2>
          <p className="mt-1 text-sm leading-5 text-text-secondary dark:text-text-muted">
            {description}
          </p>
        </div>
      </div>
      <div className="grid gap-4">{children}</div>
    </section>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label
        className="mb-1 block text-xs font-semibold text-text-secondary dark:text-text-muted"
        htmlFor={htmlFor}
      >
        {label}
      </label>
      {children}
      {hint ? (
        <p className="mt-1 text-[11px] leading-5 text-text-muted dark:text-text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export function SwitchField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex min-h-9 items-center justify-between gap-3 rounded-md border border-border-light bg-surface-muted px-3 py-2 dark:border-border-dark dark:bg-surface-dark-alt">
      <span className="text-sm text-text-primary dark:text-text-inverse">{label}</span>
      <Switch checked={checked} onChange={onChange} />
    </div>
  );
}

export function OptionLabel({ label, description }: { label: string; description: string }) {
  return (
    <span className="flex min-w-0 flex-col">
      <span className="truncate text-sm">{label}</span>
      <span className="truncate text-[11px] text-text-muted">{description}</span>
    </span>
  );
}
