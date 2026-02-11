/**
 * UndoConfirmation - Confirmation dialog for undoing tool executions
 */
import { memo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Undo2, AlertTriangle, Loader2 } from 'lucide-react';

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

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-white dark:bg-slate-800 rounded-xl p-6 w-96 shadow-2xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
              <AlertTriangle size={20} className="text-amber-600" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">
                {t('agent.undo.title', 'Undo Action')}
              </h3>
              <p className="text-xs text-slate-400">{toolName}</p>
            </div>
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
            {t(
              'agent.undo.description',
              'This will ask the agent to undo the action. The agent will attempt to revert any changes made.'
            )}
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={onCancel}
              disabled={loading}
              className="px-4 py-2 text-sm rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="px-4 py-2 text-sm bg-amber-500 hover:bg-amber-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1.5"
            >
              {loading ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Undo2 size={14} />
              )}
              {t('agent.undo.confirm', 'Undo')}
            </button>
          </div>
        </div>
      </div>
    );
  }
);
UndoConfirmation.displayName = 'UndoConfirmation';
