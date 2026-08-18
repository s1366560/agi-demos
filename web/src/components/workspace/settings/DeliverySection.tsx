import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import { Rocket } from 'lucide-react';

import { Field, SettingsSection, SwitchField } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import { DeliveryCommandsSection } from './DeliveryCommandsSection';
import { DeliveryDroneSection } from './DeliveryDroneSection';
import { DeliveryServicesSection } from './DeliveryServicesSection';
import { DraftNumberInput } from './DraftNumberInput';

import type { UpdateDeliveryService, UpdateDraft } from './types';
import type { SettingsDraft } from '@/pages/tenant/workspaceSettingsModel';

export interface DeliverySectionProps {
  draft: SettingsDraft;
  updateDraft: UpdateDraft;
  onAddService: () => void;
  onRemoveService: (index: number) => void;
  onUpdateService: UpdateDeliveryService;
}

export const DeliverySection: React.FC<DeliverySectionProps> = ({
  draft,
  updateDraft,
  onAddService,
  onRemoveService,
  onUpdateService,
}) => {
  const { t } = useTranslation();

  return (
    <SettingsSection
      icon={<Rocket size={16} aria-hidden />}
      title={t('workspaceSettings.delivery.title')}
      description={t('workspaceSettings.delivery.description')}
    >
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(180px,0.35fr)]">
        <div className="rounded-md border border-border-light bg-surface-muted px-3 py-3 dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                  {t('workspaceSettings.delivery.contractSummary')}
                </div>
                <span className="rounded border border-border-light bg-surface-light px-2 py-0.5 text-[11px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                  {draft.deliveryAgentManaged
                    ? t('workspaceSettings.delivery.modeAuto')
                    : t('workspaceSettings.delivery.modeManualLocked')}
                </span>
              </div>
              <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
                {draft.deliveryContractSource || 'metadata'} ·{' '}
                {t('workspaceSettings.delivery.contractConfidence', {
                  percent: Math.round(draft.deliveryContractConfidence * 100),
                })}
              </p>
              <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                <span className="max-w-full truncate rounded border border-border-light bg-surface-light px-2 py-1 font-mono text-[11px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                  {draft.deliveryProvider || 'sandbox_native'}
                </span>
                <span className="rounded border border-border-light bg-surface-light px-2 py-1 text-[11px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                  {t('workspaceSettings.delivery.serviceCount', {
                    count: draft.deliveryServices.length,
                  })}
                </span>
                <span className="rounded border border-border-light bg-surface-light px-2 py-1 text-[11px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                  {draft.deliveryAutoDeploy
                    ? t('workspaceSettings.delivery.autoPreview')
                    : t('workspaceSettings.delivery.pipelineOnly')}
                </span>
              </div>
            </div>
            <SwitchField
              label={t('workspaceSettings.delivery.manualLock')}
              checked={!draft.deliveryAgentManaged}
              onChange={(checked) => {
                updateDraft('deliveryAgentManaged', !checked);
              }}
            />
          </div>
        </div>
        <Field
          label={t('workspaceSettings.delivery.contractSource')}
          htmlFor="workspace-delivery-contract-source"
        >
          <Input
            id="workspace-delivery-contract-source"
            value={draft.deliveryContractSource}
            onChange={(event) => {
              updateDraft('deliveryContractSource', event.target.value);
            }}
            disabled={draft.deliveryAgentManaged}
          />
        </Field>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Field
          label={t('workspaceSettings.delivery.provider')}
          htmlFor="workspace-delivery-provider"
        >
          <Input
            id="workspace-delivery-provider"
            value={draft.deliveryProvider}
            onChange={(event) => {
              updateDraft('deliveryProvider', event.target.value);
            }}
            placeholder="sandbox_native"
          />
        </Field>
        <Field
          label={t('workspaceSettings.delivery.timeoutSeconds')}
          htmlFor="workspace-delivery-timeout"
        >
          <DraftNumberInput
            id="workspace-delivery-timeout"
            min={1}
            value={draft.deliveryTimeoutSeconds}
            fallback={600}
            onCommit={(next) => {
              updateDraft('deliveryTimeoutSeconds', next);
            }}
          />
        </Field>
        <Field
          label={t('workspaceSettings.delivery.previewPort')}
          htmlFor="workspace-delivery-port"
        >
          <DraftNumberInput
            id="workspace-delivery-port"
            min={1}
            value={draft.deliveryPreviewPort}
            fallback={3000}
            onCommit={(next) => {
              updateDraft('deliveryPreviewPort', next);
            }}
          />
        </Field>
      </div>

      {draft.deliveryProvider === 'drone' ? (
        <DeliveryDroneSection draft={draft} updateDraft={updateDraft} />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Field
          label={t('workspaceSettings.delivery.healthUrl')}
          htmlFor="workspace-delivery-health-url"
        >
          <Input
            id="workspace-delivery-health-url"
            value={draft.deliveryHealthUrl}
            onChange={(event) => {
              updateDraft('deliveryHealthUrl', event.target.value);
            }}
            placeholder="http://127.0.0.1:3000"
          />
        </Field>
        <SwitchField
          label={t('workspaceSettings.delivery.autoPreviewDeploy')}
          checked={draft.deliveryAutoDeploy}
          onChange={(checked) => {
            updateDraft('deliveryAutoDeploy', checked);
          }}
        />
      </div>

      <DeliveryServicesSection
        services={draft.deliveryServices}
        onAddService={onAddService}
        onRemoveService={onRemoveService}
        onUpdateService={onUpdateService}
      />

      <DeliveryCommandsSection draft={draft} updateDraft={updateDraft} />
    </SettingsSection>
  );
};
