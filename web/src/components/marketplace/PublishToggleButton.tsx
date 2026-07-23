/**
 * PublishToggleButton - publish/unpublish action for marketplace entities.
 *
 * Shared by the gene and genome detail pages. Publishing happens immediately;
 * unpublishing removes marketplace visibility so it is gated behind a confirm
 * dialog whose title names the entity.
 */

import { useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Modal, message } from 'antd';
import { ArchiveX, UploadCloud } from 'lucide-react';

import { showGeneActionError } from '@/pages/tenant/utils/geneFormUtils';

import { marketplaceEntityCopy } from './entityI18n';

import type { MarketplaceEntityKind } from './entityI18n';

export interface PublishToggleActions {
  publish: (id: string, options: { tenant_id: string }) => Promise<unknown>;
  unpublish: (id: string, options: { tenant_id: string }) => Promise<unknown>;
}

interface PublishToggleButtonProps {
  entityKind: MarketplaceEntityKind;
  entityId: string | null | undefined;
  tenantId: string | null;
  entityName: string;
  isPublished: boolean;
  actions: PublishToggleActions;
}

export const PublishToggleButton: FC<PublishToggleButtonProps> = ({
  entityKind,
  entityId,
  tenantId,
  entityName,
  isPublished,
  actions,
}) => {
  const { t } = useTranslation();
  const copy = marketplaceEntityCopy(entityKind);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const runToggle = async () => {
    if (!entityId || !tenantId) {
      return;
    }
    setIsSubmitting(true);
    try {
      if (isPublished) {
        await actions.unpublish(entityId, { tenant_id: tenantId });
        message.success(t(copy.unpublishSuccess.key, copy.unpublishSuccess.fallback));
      } else {
        await actions.publish(entityId, { tenant_id: tenantId });
        message.success(t(copy.publishSuccess.key, copy.publishSuccess.fallback));
      }
    } catch {
      showGeneActionError(
        isPublished
          ? t(copy.unpublishError.key, copy.unpublishError.fallback)
          : t(copy.publishError.key, copy.publishError.fallback)
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClick = () => {
    if (!isPublished) {
      void runToggle();
      return;
    }
    // Unpublishing removes marketplace visibility — confirm first
    Modal.confirm({
      title: t(copy.unpublishConfirmTitle.key, {
        name: entityName,
        defaultValue: copy.unpublishConfirmTitle.fallback,
      }),
      content: t(copy.unpublishConfirmContent.key, copy.unpublishConfirmContent.fallback),
      okText: t('tenant.genes.unpublishAction', 'Unpublish'),
      okType: 'danger',
      cancelText: t('common.cancel', 'Cancel'),
      onOk: runToggle,
    });
  };

  return (
    <Button
      onClick={handleClick}
      loading={isSubmitting}
      danger={isPublished}
      icon={isPublished ? <ArchiveX className="w-4 h-4" /> : <UploadCloud className="w-4 h-4" />}
    >
      {isPublished
        ? t('tenant.genes.unpublishAction', 'Unpublish')
        : t('tenant.genes.publishAction', 'Publish')}
    </Button>
  );
};
