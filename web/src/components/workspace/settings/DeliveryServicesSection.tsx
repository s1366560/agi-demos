import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import { Plus, Trash2 } from 'lucide-react';

import { Field, SwitchField } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import { DraftNumberInput } from './DraftNumberInput';

import type { WorkspaceDeliveryServiceConfig } from '@/types/workspace';

import type { UpdateDeliveryService } from './types';

const { TextArea } = Input;

export interface DeliveryServicesSectionProps {
  services: WorkspaceDeliveryServiceConfig[];
  onAddService: () => void;
  onRemoveService: (index: number) => void;
  onUpdateService: UpdateDeliveryService;
}

export const DeliveryServicesSection: React.FC<DeliveryServicesSectionProps> = ({
  services,
  onAddService,
  onRemoveService,
  onUpdateService,
}) => {
  const { t } = useTranslation();

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
            {t('workspaceSettings.delivery.previewServices')}
          </div>
          <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
            {t('workspaceSettings.delivery.previewServicesDescription')}
          </p>
        </div>
        <button
          type="button"
          className="inline-flex h-8 shrink-0 items-center justify-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          onClick={onAddService}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t('workspaceSettings.delivery.addService')}
        </button>
      </div>

      {services.length === 0 ? (
        <div className="rounded-md border border-dashed border-border-light px-3 py-3 text-xs text-text-secondary dark:border-border-dark dark:text-text-muted">
          {t('workspaceSettings.delivery.emptyServices')}
        </div>
      ) : (
        <div className="grid gap-3">
          {services.map((service, index) => (
            <div
              key={`${service.service_id}-${String(index)}`}
              className="min-w-0 rounded-md border border-border-light bg-surface-muted p-3 dark:border-border-dark dark:bg-surface-dark-alt"
            >
              <div className="mb-3 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-text-primary dark:text-text-inverse">
                    {service.name || service.service_id}
                  </div>
                  <p className="mt-1 break-words font-mono text-[11px] text-text-secondary dark:text-text-muted">
                    {service.service_id} · {service.internal_scheme || 'http'}://0.0.0.0:
                    {service.internal_port}
                  </p>
                </div>
                <button
                  type="button"
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded border border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
                  onClick={() => {
                    onRemoveService(index);
                  }}
                  aria-label={t('workspaceSettings.delivery.removeService')}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>

              <div className="grid gap-3 lg:grid-cols-4">
                <Field
                  label={t('workspaceSettings.delivery.serviceId')}
                  htmlFor={`delivery-service-id-${String(index)}`}
                >
                  <Input
                    id={`delivery-service-id-${String(index)}`}
                    value={service.service_id}
                    onChange={(event) => {
                      onUpdateService(index, 'service_id', event.target.value);
                    }}
                  />
                </Field>
                <Field
                  label={t('workspaceSettings.delivery.serviceName')}
                  htmlFor={`delivery-service-name-${String(index)}`}
                >
                  <Input
                    id={`delivery-service-name-${String(index)}`}
                    value={service.name}
                    onChange={(event) => {
                      onUpdateService(index, 'name', event.target.value);
                    }}
                  />
                </Field>
                <Field
                  label={t('workspaceSettings.delivery.port')}
                  htmlFor={`delivery-service-port-${String(index)}`}
                >
                  <DraftNumberInput
                    id={`delivery-service-port-${String(index)}`}
                    min={1}
                    value={service.internal_port}
                    fallback={3000}
                    onCommit={(next) => {
                      onUpdateService(index, 'internal_port', next);
                    }}
                  />
                </Field>
                <Field
                  label={t('workspaceSettings.delivery.path')}
                  htmlFor={`delivery-service-path-${String(index)}`}
                >
                  <Input
                    id={`delivery-service-path-${String(index)}`}
                    value={service.path_prefix ?? '/'}
                    onChange={(event) => {
                      onUpdateService(index, 'path_prefix', event.target.value);
                    }}
                  />
                </Field>
              </div>

              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <Field
                  label={t('workspaceSettings.delivery.startCommand')}
                  htmlFor={`delivery-service-start-${String(index)}`}
                >
                  <TextArea
                    id={`delivery-service-start-${String(index)}`}
                    value={service.start_command}
                    onChange={(event) => {
                      onUpdateService(index, 'start_command', event.target.value);
                    }}
                    placeholder="pnpm dev --host 0.0.0.0 --port 3000"
                    className="font-mono text-xs"
                    rows={3}
                  />
                </Field>
                <Field
                  label={t('workspaceSettings.delivery.healthPath')}
                  htmlFor={`delivery-service-health-path-${String(index)}`}
                >
                  <Input
                    id={`delivery-service-health-path-${String(index)}`}
                    value={service.health_path ?? '/'}
                    onChange={(event) => {
                      onUpdateService(index, 'health_path', event.target.value);
                    }}
                    placeholder="/"
                  />
                </Field>
              </div>

              <div className="mt-3">
                <Field
                  label={t('workspaceSettings.delivery.healthCommandOverride')}
                  htmlFor={`delivery-service-health-command-${String(index)}`}
                >
                  <TextArea
                    id={`delivery-service-health-command-${String(index)}`}
                    value={service.health_command ?? ''}
                    onChange={(event) => {
                      onUpdateService(index, 'health_command', event.target.value);
                    }}
                    placeholder="curl -fsS http://127.0.0.1:3000/"
                    className="font-mono text-xs"
                    rows={2}
                  />
                </Field>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <SwitchField
                  label={t('workspaceSettings.delivery.required')}
                  checked={service.required ?? true}
                  onChange={(checked) => {
                    onUpdateService(index, 'required', checked);
                  }}
                />
                <SwitchField
                  label={t('workspaceSettings.delivery.autoOpen')}
                  checked={service.auto_open ?? true}
                  onChange={(checked) => {
                    onUpdateService(index, 'auto_open', checked);
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
