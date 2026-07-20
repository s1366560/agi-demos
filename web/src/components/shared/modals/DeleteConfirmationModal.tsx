import React from 'react';

import { useTranslation } from 'react-i18next';

import { AlertTriangle, Loader2, Trash2 } from 'lucide-react';

import { AppModal } from '@/components/common';

interface DeleteConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  isDeleting?: boolean | undefined;
}

export const DeleteConfirmationModal: React.FC<DeleteConfirmationModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  isDeleting = false,
}) => {
  const { t } = useTranslation();

  return (
    <AppModal
      open={isOpen}
      onClose={onClose}
      title={title}
      ariaLabel={title}
      size="sm"
      isDirty={isDeleting}
      closeOnBackdrop={!isDeleting}
      closeOnEscape={!isDeleting}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={isDeleting}
            className="px-4 py-2 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50"
          >
            {t('components.deleteConfirmation.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium shadow-lg shadow-red-600/20 transition-[color,background-color,border-color,box-shadow,opacity] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-70 disabled:cursor-not-allowed"
          >
            {isDeleting ? (
              <>
                <Loader2 size={18} className="animate-spin motion-reduce:animate-none" />
                {t('components.deleteConfirmation.deleting', { defaultValue: 'Deleting...' })}
              </>
            ) : (
              <>
                <Trash2 size={18} />
                {t('components.deleteConfirmation.delete', { defaultValue: 'Delete' })}
              </>
            )}
          </button>
        </>
      }
    >
      <div className="flex items-center gap-3 text-red-600 dark:text-red-400 mb-4">
        <AlertTriangle size={30} />
      </div>
      <p className="text-slate-600 dark:text-slate-300 leading-relaxed">{message}</p>
    </AppModal>
  );
};
