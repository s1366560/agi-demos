import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Select } from 'antd';
import { Users } from 'lucide-react';

import {
  COLLABORATION_MODE_OPTIONS,
  USE_CASE_OPTIONS,
} from '@/pages/tenant/workspaceSettingsModel';
import { Field, OptionLabel, SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { WorkspaceCollaborationMode, WorkspaceUseCase } from '@/types/workspace';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

export interface OperatingModelSectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
  workspaceType: string;
}

export const OperatingModelSection: React.FC<OperatingModelSectionProps> = ({
  draft,
  updateDraft,
  workspaceType,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<Users size={16} aria-hidden />}
      title={t('workspaceSettings.operatingModel.title')}
      description={t('workspaceSettings.operatingModel.description')}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Field label={t('workspaceSettings.operatingModel.useCase')} htmlFor="workspace-use-case">
          <Select
            id="workspace-use-case"
            value={draft.workspaceUseCase}
            onChange={(value: WorkspaceUseCase) => {
              updateDraft('workspaceUseCase', value);
            }}
            options={USE_CASE_OPTIONS.map((option) => ({
              value: option.value,
              label: (
                <OptionLabel label={t(option.labelKey)} description={t(option.descriptionKey)} />
              ),
            }))}
          />
        </Field>

        <Field
          label={t('workspaceSettings.operatingModel.collaborationMode')}
          htmlFor="workspace-collaboration-mode"
        >
          <Select
            id="workspace-collaboration-mode"
            value={draft.collaborationMode}
            onChange={(value: WorkspaceCollaborationMode) => {
              updateDraft('collaborationMode', value);
            }}
            options={COLLABORATION_MODE_OPTIONS.map((option) => ({
              value: option.value,
              label: (
                <OptionLabel label={t(option.labelKey)} description={t(option.descriptionKey)} />
              ),
            }))}
          />
        </Field>
      </div>

      <div className="rounded-md border border-border-light bg-surface-muted px-3 py-2 text-xs leading-5 text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted">
        {t('workspaceSettings.operatingModel.typeHint', {
          type: workspaceType,
        })}
      </div>
    </SettingsSection>
  );
};
