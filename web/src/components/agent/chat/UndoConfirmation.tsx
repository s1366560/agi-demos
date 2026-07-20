/**
 * UndoConfirmation - Confirmation dialog for undoing tool executions
 */
import { memo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Undo2, AlertTriangle, Loader2 } from 'lucide-react';

import { AppModal } from '@/components/common';

interface UndoConfirmationProps {
  toolName: string;
  visible: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

export const UndoConfirmation = memo<UndoConfirmationProps>(
  ({ toolName, visible, onConfirm, onCancel }) => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);

    if (!visible) return null;

    const handleConfirm = async () => {
      setLoading(true);
      try {
        await onConfirm();
      } finally {
        setLoading(false);
      }
    };

    const undoDescription = t(
      'agent.undo.description',
      'This will ask the agent to undo the action. The agent will attempt to revert any changes made.'
    );

    return (
      <AppModal
        open={visible}
        onClose={onCancel}
        title={t('agent.undo.title', 'Undo Action')}
        description={undoDescription}
        size="sm"
        isDirty={loading}
        closeOnBackdrop={!loading}
        closeOnEscape={!loading}
        footer={
          <>
            <button
              type="button"
              onClick={onCancel}
              disabled={loading}
              className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleConfirm();
              }}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-4 py-2 text-sm text-slate-50 hover:bg-amber-600 disabled:opacity-50"
            >
              {loading ? (
                <Loader2
                  size={14}
                  className="animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : (
                <Undo2 size={14} aria-hidden="true" />
              )}
              {t('agent.undo.confirm', 'Undo')}
            </button>
          </>
        }
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
            <AlertTriangle size={20} className="text-amber-600" aria-hidden="true" />
          </div>
        </div>
        {toolName && (
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
            <span className="font-mono font-medium">{toolName}</span>
          </p>
        )}
      </AppModal>
    );
  }
);
UndoConfirmation.displayName = 'UndoConfirmation';
