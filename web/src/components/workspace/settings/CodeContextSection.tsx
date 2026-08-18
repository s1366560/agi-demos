import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import { Code2 } from 'lucide-react';

import { Field, SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

export interface CodeContextSectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
  codeRootValid: boolean;
}

export const CodeContextSection: React.FC<CodeContextSectionProps> = ({
  draft,
  updateDraft,
  codeRootValid,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<Code2 size={16} aria-hidden />}
      title={t('workspaceSettings.codeContext.title')}
      description={t('workspaceSettings.codeContext.description')}
    >
      <Field
        label={t('workspaceSettings.codeContext.codeRoot')}
        htmlFor="workspace-code-root"
        hint={t('workspaceSettings.codeContext.codeRootHint')}
      >
        <Input
          id="workspace-code-root"
          value={draft.sandboxCodeRoot}
          onChange={(event) => {
            updateDraft('sandboxCodeRoot', event.target.value);
          }}
          placeholder="/workspace/my-evo"
          {...(!codeRootValid ? { status: 'error' as const } : {})}
        />
      </Field>
      {!codeRootValid ? (
        <p className="text-xs text-status-text-error dark:text-status-text-error-dark">
          {t('workspaceSettings.codeContext.codeRootInvalid')}
        </p>
      ) : null}
    </SettingsSection>
  );
};
