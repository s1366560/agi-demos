/**
 * RateEntityModal - score + comment rating dialog for marketplace entities.
 *
 * Shared by the gene and genome detail pages. Owns its form state, submits
 * through the injected `rateEntity` action, and surfaces store errors via
 * `showGeneActionError`.
 */

import { useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Form, Input, Modal, Rate, message } from 'antd';

import { showGeneActionError } from '@/pages/tenant/utils/geneFormUtils';

import { marketplaceEntityCopy } from './entityI18n';

import type { MarketplaceEntityKind } from './entityI18n';

interface RateFormValues {
  score: number;
  comment?: string;
}

interface RateEntityModalProps {
  open: boolean;
  onClose: () => void;
  entityKind: MarketplaceEntityKind;
  entityId: string | null | undefined;
  tenantId: string | null;
  rateEntity: (
    id: string,
    data: { rating: number; comment: string | null },
    options: { tenant_id: string }
  ) => Promise<unknown>;
}

export const RateEntityModal: FC<RateEntityModalProps> = ({
  open,
  onClose,
  entityKind,
  entityId,
  tenantId,
  rateEntity,
}) => {
  const { t } = useTranslation();
  const copy = marketplaceEntityCopy(entityKind);
  const [form] = Form.useForm<RateFormValues>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleClose = () => {
    onClose();
    form.resetFields();
  };

  const handleSubmit = async () => {
    let values: RateFormValues;
    try {
      values = await form.validateFields();
    } catch {
      // antd validation errors are shown inline on the form
      return;
    }
    if (!entityId || !tenantId) {
      return;
    }
    setIsSubmitting(true);
    try {
      await rateEntity(
        entityId,
        {
          rating: values.score,
          comment: values.comment ?? null,
        },
        { tenant_id: tenantId }
      );
      message.success(t(copy.rateSuccess.key, copy.rateSuccess.fallback));
      handleClose();
    } catch {
      showGeneActionError(t(copy.rateError.key, copy.rateError.fallback));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      title={t(copy.rateTitle.key, copy.rateTitle.fallback)}
      open={open}
      onOk={() => {
        void handleSubmit();
      }}
      onCancel={handleClose}
      confirmLoading={isSubmitting}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4" initialValues={{ score: 5 }}>
        <Form.Item
          name="score"
          label={t('tenant.genes.rating')}
          rules={[{ required: true, message: t('tenant.genes.ratingRequired') }]}
        >
          <Rate allowHalf />
        </Form.Item>

        <Form.Item name="comment" label={t('tenant.genes.comment')}>
          <Input.TextArea rows={4} placeholder={t('tenant.genes.commentPlaceholder')} />
        </Form.Item>
      </Form>
    </Modal>
  );
};
