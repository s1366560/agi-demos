import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { AlertTriangle, Loader2, Trash2 } from 'lucide-react';

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

  useEffect(() => {
    if (!isOpen || isDeleting) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isDeleting, isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-confirmation-title"
        className="mx-4 w-full max-w-md overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg animate-in fade-in zoom-in duration-200 dark:border-slate-800 dark:bg-surface-dark"
      >
        <div className="p-6">
          <div className="flex items-center gap-3 text-red-600 dark:text-red-400 mb-4">
            <AlertTriangle size={30} />
            <h3 id="delete-confirmation-title" className="text-xl font-bold">
              {title}
            </h3>
          </div>
          <p className="text-slate-600 dark:text-slate-300 leading-relaxed">{message}</p>
        </div>
        <div className="bg-slate-50 dark:bg-slate-800/50 px-6 py-4 flex justify-end gap-3 border-t border-slate-100 dark:border-slate-800">
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
        </div>
      </div>
    </div>
  );
};
