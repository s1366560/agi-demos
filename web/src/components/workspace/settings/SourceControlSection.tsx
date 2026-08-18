import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Select } from 'antd';
import { GitBranch } from 'lucide-react';

import { SOURCE_CONTROL_PROVIDER_OPTIONS } from '@/pages/tenant/workspaceSettingsModel';
import { Field, SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { WorkspaceSourceControlProvider } from '@/types/workspace';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

export interface SourceControlSectionProps {
  draft: SettingsDraft;
  updateSourceControlProvider: (provider: WorkspaceSourceControlProvider) => void;
  updateSourceControlDraft: UpdateDraft;
}

export const SourceControlSection: React.FC<SourceControlSectionProps> = ({
  draft,
  updateSourceControlProvider,
  updateSourceControlDraft,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<GitBranch size={16} aria-hidden />}
      title={t('workspaceSettings.sourceControl.title')}
      description={t('workspaceSettings.sourceControl.description')}
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <Field
          label={t('workspaceSettings.sourceControl.provider')}
          htmlFor="workspace-source-control-provider"
        >
          <Select
            id="workspace-source-control-provider"
            value={draft.sourceControlProvider}
            onChange={updateSourceControlProvider}
            options={SOURCE_CONTROL_PROVIDER_OPTIONS.map((option) => ({
              value: option.value,
              label: t(option.labelKey),
            }))}
          />
        </Field>
        <Field
          label={t('workspaceSettings.sourceControl.repo')}
          htmlFor="workspace-source-control-repo"
        >
          <Input
            id="workspace-source-control-repo"
            value={draft.sourceControlRepo}
            onChange={(event) => {
              updateSourceControlDraft('sourceControlRepo', event.target.value);
            }}
            placeholder="memstack/my-workspace"
          />
        </Field>
        <Field
          label={t('workspaceSettings.sourceControl.defaultBranch')}
          htmlFor="workspace-source-control-branch"
        >
          <Input
            id="workspace-source-control-branch"
            value={draft.sourceControlDefaultBranch}
            onChange={(event) => {
              updateSourceControlDraft('sourceControlDefaultBranch', event.target.value);
            }}
            placeholder="main"
          />
        </Field>
        <Field
          label={t('workspaceSettings.sourceControl.serverUrl')}
          htmlFor="workspace-source-control-server-url"
        >
          <Input
            id="workspace-source-control-server-url"
            value={draft.sourceControlServerUrl}
            onChange={(event) => {
              updateSourceControlDraft('sourceControlServerUrl', event.target.value);
            }}
            placeholder="https://github.com"
          />
        </Field>
        <Field
          label={t('workspaceSettings.sourceControl.authTokenEnv')}
          htmlFor="workspace-source-control-token-env"
        >
          <Input
            id="workspace-source-control-token-env"
            value={draft.sourceControlAuthTokenEnv}
            onChange={(event) => {
              updateSourceControlDraft('sourceControlAuthTokenEnv', event.target.value);
            }}
            placeholder="GITHUB_TOKEN"
          />
        </Field>
        <Field
          label={t('workspaceSettings.sourceControl.cloneUrl')}
          htmlFor="workspace-source-control-clone-url"
        >
          <Input
            id="workspace-source-control-clone-url"
            value={draft.sourceControlCloneUrl}
            onChange={(event) => {
              updateSourceControlDraft('sourceControlCloneUrl', event.target.value);
            }}
            placeholder="https://github.com/memstack/my-workspace.git"
          />
        </Field>
      </div>
    </SettingsSection>
  );
};
