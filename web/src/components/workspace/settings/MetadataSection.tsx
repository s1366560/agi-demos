import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import { Database } from 'lucide-react';

import { Field, SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

const { TextArea } = Input;

export interface MetadataSectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
  metadataError: string | null;
}

export const MetadataSection: React.FC<MetadataSectionProps> = ({
  draft,
  updateDraft,
  metadataError,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<Database size={16} aria-hidden />}
      title={t('workspaceSettings.metadata.title')}
      description={t('workspaceSettings.metadata.description')}
    >
      <Field
        label={t('workspaceSettings.metadata.rawJson')}
        htmlFor="workspace-metadata-json"
        hint={t('workspaceSettings.metadata.rawJsonHint')}
      >
        <TextArea
          id="workspace-metadata-json"
          value={draft.rawMetadata}
          onChange={(event) => {
            updateDraft('rawMetadata', event.target.value);
          }}
          rows={12}
          className="font-mono text-xs"
          {...(metadataError ? { status: 'error' as const } : {})}
        />
      </Field>
      {metadataError ? (
        <p className="text-xs text-status-text-error dark:text-status-text-error-dark">
          {metadataError === 'metadata_object_required'
            ? t('workspaceSettings.metadata.objectRequired')
            : t('workspaceSettings.metadata.invalidJson')}
        </p>
      ) : null}
    </SettingsSection>
  );
};
