import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Select } from 'antd';
import { ShieldCheck } from 'lucide-react';

import { VERIFICATION_GRADE_OPTIONS } from '@/pages/tenant/workspaceSettingsModel';
import { Field, SettingsSection, SwitchField } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { WorkspaceVerificationGrade } from '@/types/workspace';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

const { TextArea } = Input;

export interface AutonomySectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
}

export const AutonomySection: React.FC<AutonomySectionProps> = ({ draft, updateDraft }) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<ShieldCheck size={16} aria-hidden />}
      title={t('workspaceSettings.autonomy.title')}
      description={t('workspaceSettings.autonomy.description')}
    >
      <div className="grid gap-3 lg:grid-cols-3">
        <SwitchField
          label={t('workspaceSettings.autonomy.allowInternalArtifacts')}
          checked={draft.allowInternalTaskArtifacts}
          onChange={(checked) => {
            updateDraft('allowInternalTaskArtifacts', checked);
          }}
        />
        <SwitchField
          label={t('workspaceSettings.autonomy.requiresExternalArtifact')}
          checked={draft.requiresExternalArtifact}
          onChange={(checked) => {
            updateDraft('requiresExternalArtifact', checked);
          }}
        />
        <Field
          label={t('workspaceSettings.autonomy.minimumVerificationGrade')}
          htmlFor="workspace-min-grade"
        >
          <Select
            id="workspace-min-grade"
            value={draft.minimumVerificationGrade}
            onChange={(value: WorkspaceVerificationGrade) => {
              updateDraft('minimumVerificationGrade', value);
            }}
            options={VERIFICATION_GRADE_OPTIONS.map((value) => ({
              value,
              label: t(`workspaceSettings.autonomy.grade.${value}`),
            }))}
          />
        </Field>
      </div>

      <Field
        label={t('workspaceSettings.autonomy.requiredArtifactPrefixes')}
        htmlFor="workspace-artifact-prefixes"
        hint={t('workspaceSettings.autonomy.requiredArtifactPrefixesHint')}
      >
        <TextArea
          id="workspace-artifact-prefixes"
          value={draft.requiredArtifactPrefixes}
          onChange={(event) => {
            updateDraft('requiredArtifactPrefixes', event.target.value);
          }}
          placeholder="git_diff:, patch:, commit:, test_run:"
          rows={3}
        />
      </Field>
    </SettingsSection>
  );
};
