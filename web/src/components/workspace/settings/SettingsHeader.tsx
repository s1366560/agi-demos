import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Check, Loader2, RotateCcw } from 'lucide-react';

import { HostedProjectionBadge } from '@/components/blackboard/HostedProjectionBadge';

export interface SettingsHeaderProps {
  isDirty: boolean;
  isSaving: boolean;
  canSave: boolean;
  onReset: () => Promise<void>;
  onSave: () => Promise<void>;
}

export const SettingsHeader: React.FC<SettingsHeaderProps> = ({
  isDirty,
  isSaving,
  canSave,
  onReset,
  onSave,
}) => {
  const { t } = useTranslation();

  return (
    <header className="flex flex-col gap-4 border-b border-border-light pb-4 dark:border-border-dark lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <HostedProjectionBadge
          labelKey="blackboard.settingsSurfaceHint"
          fallbackLabel="workspace settings projection"
        />
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary dark:text-text-inverse">
          {t('workspaceSettings.title')}
        </h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-text-secondary dark:text-text-muted">
          {t('workspaceSettings.description')}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            void onReset();
          }}
          disabled={!isDirty || isSaving}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt"
        >
          <RotateCcw size={15} aria-hidden />
          {t('workspaceSettings.actions.reset')}
        </button>
        <button
          type="button"
          onClick={() => {
            void onSave();
          }}
          disabled={!canSave}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-text-primary px-3 text-sm font-medium text-surface-light transition-colors hover:bg-text-secondary disabled:cursor-not-allowed disabled:opacity-50 dark:bg-text-inverse dark:text-surface-dark"
        >
          {isSaving ? (
            <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
          ) : (
            <Check size={15} />
          )}
          {t('common.save')}
        </button>
      </div>
    </header>
  );
};
