import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';

import { Field } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import type { UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

const { TextArea } = Input;

export interface DeliveryCommandsSectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
}

export const DeliveryCommandsSection: React.FC<DeliveryCommandsSectionProps> = ({
  draft,
  updateDraft,
}) => {
  const { t } = useTranslation();

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Field
        label={t('workspaceSettings.delivery.installCommand')}
        htmlFor="workspace-delivery-install"
      >
        <TextArea
          id="workspace-delivery-install"
          value={draft.deliveryInstallCommand}
          onChange={(event) => {
            updateDraft('deliveryInstallCommand', event.target.value);
          }}
          placeholder="pnpm install --frozen-lockfile"
          className="font-mono text-xs"
          rows={3}
        />
      </Field>
      <Field label={t('workspaceSettings.delivery.lintCommand')} htmlFor="workspace-delivery-lint">
        <TextArea
          id="workspace-delivery-lint"
          value={draft.deliveryLintCommand}
          onChange={(event) => {
            updateDraft('deliveryLintCommand', event.target.value);
          }}
          placeholder="pnpm lint"
          className="font-mono text-xs"
          rows={3}
        />
      </Field>
      <Field label={t('workspaceSettings.delivery.testCommand')} htmlFor="workspace-delivery-test">
        <TextArea
          id="workspace-delivery-test"
          value={draft.deliveryTestCommand}
          onChange={(event) => {
            updateDraft('deliveryTestCommand', event.target.value);
          }}
          placeholder="pnpm test"
          className="font-mono text-xs"
          rows={3}
        />
      </Field>
      <Field
        label={t('workspaceSettings.delivery.buildCommand')}
        htmlFor="workspace-delivery-build"
      >
        <TextArea
          id="workspace-delivery-build"
          value={draft.deliveryBuildCommand}
          onChange={(event) => {
            updateDraft('deliveryBuildCommand', event.target.value);
          }}
          placeholder="pnpm build"
          className="font-mono text-xs"
          rows={3}
        />
      </Field>
      <Field
        label={t('workspaceSettings.delivery.deployCommand')}
        htmlFor="workspace-delivery-deploy"
      >
        <TextArea
          id="workspace-delivery-deploy"
          value={draft.deliveryDeployCommand}
          onChange={(event) => {
            updateDraft('deliveryDeployCommand', event.target.value);
          }}
          placeholder="pnpm start --host 0.0.0.0 --port 3000"
          className="font-mono text-xs"
          rows={3}
        />
      </Field>
      <Field
        label={t('workspaceSettings.delivery.healthCommand')}
        htmlFor="workspace-delivery-health-command"
      >
        <TextArea
          id="workspace-delivery-health-command"
          value={draft.deliveryHealthCommand}
          onChange={(event) => {
            updateDraft('deliveryHealthCommand', event.target.value);
          }}
          placeholder="curl -fsS http://127.0.0.1:3000 >/dev/null"
          className="font-mono text-xs"
          rows={3}
        />
      </Field>
    </div>
  );
};
