import type React from 'react';

export const panelClass =
  'rounded-md bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-slate-950 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]';

export const secondaryButtonClass =
  'inline-flex min-h-9 items-center justify-center gap-2 rounded border border-gray-200 bg-white px-3 text-sm font-medium text-gray-900 transition-colors hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:hover:border-slate-600 dark:hover:bg-slate-900';

interface SettingsSectionProps {
  id?: string;
  icon: React.ReactNode;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  tone?: 'default' | 'danger';
}

export const SettingsSection: React.FC<SettingsSectionProps> = ({
  id,
  icon,
  title,
  aside,
  children,
  tone = 'default',
}) => (
  <section
    id={id}
    className={`${panelClass} overflow-hidden ${
      tone === 'danger' ? 'shadow-[0_0_0_1px_rgba(220,38,38,0.22)]' : ''
    }`}
  >
    <div className="flex flex-col gap-3 border-b border-gray-100 px-5 py-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded border ${
            tone === 'danger'
              ? 'border-red-200 bg-red-50 text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300'
              : 'border-gray-200 bg-gray-50 text-gray-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
          }`}
        >
          {icon}
        </div>
        <h2
          className={`truncate text-base font-semibold ${
            tone === 'danger' ? 'text-red-900 dark:text-red-200' : 'text-gray-950 dark:text-white'
          }`}
        >
          {title}
        </h2>
      </div>
      {aside}
    </div>
    <div className="p-5">{children}</div>
  </section>
);
