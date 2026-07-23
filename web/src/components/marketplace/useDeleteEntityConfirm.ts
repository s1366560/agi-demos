/**
 * useDeleteEntityConfirm - destructive delete flow for marketplace entities.
 *
 * Shared by the gene and genome detail pages. Renders a confirm dialog whose
 * title names the entity, runs the delete action, surfaces store errors, and
 * invokes `onDeleted` (typically navigating back to the list) on success.
 */

import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, message } from 'antd';

import { showGeneActionError } from '@/pages/tenant/utils/geneFormUtils';

import { marketplaceEntityCopy } from './entityI18n';

import type { MarketplaceEntityKind } from './entityI18n';

interface UseDeleteEntityConfirmOptions {
  entityKind: MarketplaceEntityKind;
  deleteEntity: (id: string, options: { tenant_id: string }) => Promise<unknown>;
  onDeleted: () => void;
}

interface ConfirmDeleteArgs {
  entityId: string | null | undefined;
  tenantId: string | null;
  entityName: string;
}

export const useDeleteEntityConfirm = ({
  entityKind,
  deleteEntity,
  onDeleted,
}: UseDeleteEntityConfirmOptions) => {
  const { t } = useTranslation();
  const copy = marketplaceEntityCopy(entityKind);
  const [isDeleting, setIsDeleting] = useState(false);

  const confirmDelete = ({ entityId, tenantId, entityName }: ConfirmDeleteArgs) => {
    if (!entityId || !tenantId) {
      return;
    }

    Modal.confirm({
      title: t(copy.deleteConfirmTitle.key, {
        name: entityName,
        defaultValue: copy.deleteConfirmTitle.fallback,
      }),
      content: t(copy.deleteConfirmContent.key, copy.deleteConfirmContent.fallback),
      okText: t('common.delete', 'Delete'),
      okType: 'danger',
      cancelText: t('common.cancel', 'Cancel'),
      onOk: async () => {
        setIsDeleting(true);
        try {
          await deleteEntity(entityId, { tenant_id: tenantId });
          message.success(t(copy.deleteSuccess.key, copy.deleteSuccess.fallback));
          setIsDeleting(false);
          onDeleted();
        } catch {
          showGeneActionError(t(copy.deleteError.key, copy.deleteError.fallback));
          setIsDeleting(false);
        }
      },
    });
  };

  return { isDeleting, confirmDelete };
};
