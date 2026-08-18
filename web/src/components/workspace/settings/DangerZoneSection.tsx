import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Archive, Trash2 } from 'lucide-react';

import { SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import { LazyPopconfirm } from '@/components/ui/lazyAntd';

export interface DangerZoneSectionProps {
  workspaceName: string;
  isDeleting: boolean;
  onDelete: () => Promise<void>;
}

export const DangerZoneSection: React.FC<DangerZoneSectionProps> = ({
  workspaceName,
  isDeleting,
  onDelete,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<Archive size={16} aria-hidden />}
      title={t('workspaceSettings.dangerZone.title')}
      description={t('workspaceSettings.dangerZone.description')}
      tone="danger"
    >
      <div className="flex flex-col gap-3 rounded-md border border-error-border bg-error-bg px-3 py-3 dark:border-error-border-dark dark:bg-error-bg-dark">
        <div>
          <p className="text-sm font-medium text-text-primary dark:text-text-inverse">
            {t('workspaceSettings.dangerZone.deleteWorkspace')}
          </p>
          <p className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
            {t('workspaceSettings.dangerZone.deleteDescription')}
          </p>
        </div>
        <LazyPopconfirm
          title={t('workspaceSettings.dangerZone.deleteConfirm', { name: workspaceName })}
          onConfirm={() => {
            void onDelete();
          }}
          okText={t('common.delete')}
          cancelText={t('common.cancel')}
          okButtonProps={{ danger: true }}
        >
          <button
            type="button"
            disabled={isDeleting}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-error px-3 text-sm font-medium text-surface-light transition-colors hover:bg-error-dark disabled:opacity-50 dark:bg-status-text-error-dark dark:text-surface-dark"
          >
            <Trash2 size={15} />
            {t('common.delete')}
          </button>
        </LazyPopconfirm>
      </div>
    </SettingsSection>
  );
};
