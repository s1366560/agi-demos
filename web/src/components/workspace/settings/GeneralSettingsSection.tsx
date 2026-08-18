import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Switch } from 'antd';
import { SlidersHorizontal } from 'lucide-react';

import { Field, SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

const { TextArea } = Input;

export interface GeneralSettingsSectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
}

export const GeneralSettingsSection: React.FC<GeneralSettingsSectionProps> = ({
  draft,
  updateDraft,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<SlidersHorizontal size={16} aria-hidden />}
      title={t('workspaceSettings.generalSettings')}
      description={t('workspaceSettings.generalDescription')}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Field label={t('workspaceSettings.nameLabel')} htmlFor="workspace-name">
          <Input
            id="workspace-name"
            value={draft.name}
            onChange={(event) => {
              updateDraft('name', event.target.value);
            }}
            placeholder={t('workspaceSettings.namePlaceholder')}
            maxLength={255}
            {...(!draft.name.trim() ? { status: 'error' as const } : {})}
          />
        </Field>

        <Field label={t('workspaceSettings.archiveLabel')} htmlFor="workspace-archive">
          <div className="flex h-9 items-center justify-between rounded-md border border-border-light bg-surface-muted px-3 dark:border-border-dark dark:bg-surface-dark-alt">
            <span className="text-sm text-text-primary dark:text-text-inverse">
              {draft.isArchived ? t('workspaceSettings.archived') : t('workspaceSettings.active')}
            </span>
            <Switch
              id="workspace-archive"
              checked={draft.isArchived}
              onChange={(checked) => {
                updateDraft('isArchived', checked);
              }}
            />
          </div>
        </Field>
      </div>

      <Field label={t('workspaceSettings.descriptionLabel')} htmlFor="workspace-description">
        <TextArea
          id="workspace-description"
          value={draft.description}
          onChange={(event) => {
            updateDraft('description', event.target.value);
          }}
          placeholder={t('workspaceSettings.descriptionPlaceholder')}
          rows={4}
          maxLength={1000}
          showCount
        />
      </Field>
    </SettingsSection>
  );
};
