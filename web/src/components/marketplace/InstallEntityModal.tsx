/**
 * InstallEntityModal - instance picker + JSON config override install dialog.
 *
 * Shared by the gene and genome detail pages. Owns its form state, parses the
 * optional JSON config override, and delegates the actual install call to the
 * injected `installEntity` action (the gene and genome install endpoints take
 * different payloads, so payload shaping stays in the page).
 */

import { useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Form, Input, Modal, message } from 'antd';

import { showGeneActionError } from '@/pages/tenant/utils/geneFormUtils';
import { InstanceSelect } from '@/pages/tenant/utils/InstanceSelect';

import { marketplaceEntityCopy } from './entityI18n';

import type { MarketplaceEntityKind } from './entityI18n';

interface InstallFormValues {
  instance_id: string;
  config_override?: string;
}

interface InstallEntityModalProps {
  open: boolean;
  onClose: () => void;
  entityKind: MarketplaceEntityKind;
  installEntity: (instanceId: string, config: Record<string, unknown>) => Promise<unknown>;
}

export const InstallEntityModal: FC<InstallEntityModalProps> = ({
  open,
  onClose,
  entityKind,
  installEntity,
}) => {
  const { t } = useTranslation();
  const copy = marketplaceEntityCopy(entityKind);
  const [form] = Form.useForm<InstallFormValues>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleClose = () => {
    onClose();
    form.resetFields();
  };

  const handleSubmit = async () => {
    let values: InstallFormValues;
    try {
      values = await form.validateFields();
    } catch {
      // antd validation errors are shown inline on the form
      return;
    }
    let configOverride: Record<string, unknown> = {};
    if (values.config_override) {
      try {
        configOverride = JSON.parse(values.config_override) as Record<string, unknown>;
      } catch {
        message.error(t('tenant.genes.invalidJson', 'Invalid JSON format'));
        return;
      }
    }

    setIsSubmitting(true);
    try {
      await installEntity(values.instance_id, configOverride);
      message.success(t(copy.installSuccess.key, copy.installSuccess.fallback));
      handleClose();
    } catch {
      showGeneActionError(t(copy.installError.key, copy.installError.fallback));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      title={t(copy.installTitle.key, copy.installTitle.fallback)}
      open={open}
      onOk={() => {
        void handleSubmit();
      }}
      onCancel={handleClose}
      confirmLoading={isSubmitting}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="instance_id"
          label={t('tenant.genes.instanceId', 'Instance ID')}
          rules={[
            {
              required: true,
              message: t('tenant.genes.instanceIdRequired', 'Instance ID is required'),
            },
          ]}
        >
          <InstanceSelect placeholder={t('tenant.genes.instanceIdPlaceholder', 'Enter instance ID')} />
        </Form.Item>

        <Form.Item
          name="config_override"
          label={t('tenant.genes.configOverride', 'Config Override (JSON)')}
          tooltip={t(copy.configOverrideTooltip.key, copy.configOverrideTooltip.fallback)}
        >
          <Input.TextArea
            rows={4}
            placeholder={t(copy.configOverridePlaceholder.key, copy.configOverridePlaceholder.fallback)}
            className="font-mono text-sm"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
};
