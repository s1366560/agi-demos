import { memo, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { message } from 'antd';
import { useTemplateStore, useTemplateActions } from '@/stores/templateStore';
import { useCurrentTenant } from '@/stores/tenant';
import { confirmAction } from '@/utils/confirmAction';
import {
  PromptTemplateLibraryView,
  type PromptTemplateLibraryProps,
} from '@business/agent/ui/web/chat/PromptTemplateLibraryView';
export type {
  PromptTemplate,
  TemplateCategory,
} from '@business/agent/ui/web/chat/PromptTemplateLibraryView';

export const PromptTemplateLibrary = memo<PromptTemplateLibraryProps>((props) => {
  const { visible } = props;
  const { t } = useTranslation();
  const currentTenant = useCurrentTenant();
  const customTemplates = useTemplateStore((s) => s.templates);
  const customLoading = useTemplateStore((s) => s.loading);
  const { fetchTemplates, deleteTemplate } = useTemplateActions();

  // Fetch custom templates on open
  useEffect(() => {
    if (visible && currentTenant?.id) {
      void fetchTemplates(currentTenant.id);
    }
  }, [visible, currentTenant?.id, fetchTemplates]);

  const handleDeleteCustom = useCallback(
    (e: React.MouseEvent, templateId: string) => {
      e.stopPropagation();
      void (async () => {
        const confirmed = await confirmAction({
          title: t('agent.templates.deleteConfirmTitle', 'Delete this template?'),
          content: t('agent.templates.deleteConfirmContent', 'This action cannot be undone.'),
          okText: t('common.delete', 'Delete'),
          cancelText: t('common.cancel', 'Cancel'),
          danger: true,
        });
        if (!confirmed) return;
        const previousError = useTemplateStore.getState().error;
        await deleteTemplate(templateId);
        const deleteError = useTemplateStore.getState().error;
        if (deleteError && deleteError !== previousError) {
          void message.error(t('agent.templates.deleteFailed', 'Failed to delete template'));
        } else {
          void message.success(t('agent.templates.deleted', 'Template deleted'));
        }
      })();
    },
    [deleteTemplate, t]
  );

  return (
    <PromptTemplateLibraryView
      {...props}
      customTemplates={customTemplates}
      customLoading={customLoading}
      handleDeleteCustom={handleDeleteCustom}
    />
  );
});
PromptTemplateLibrary.displayName = 'PromptTemplateLibrary';
