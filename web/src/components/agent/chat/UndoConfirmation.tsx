/**
 * UndoConfirmation - Confirmation dialog for undoing tool executions
 */
import { memo, useEffect, useId, useState } from 'react';

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
    const titleId = useId();
    const descriptionId = useId();
    const [loading, setLoading] = useState(false);

    useEffect(() => {
      if (!visible || loading) return undefined;
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          onCancel();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => {
        window.removeEventListener('keydown', handleKeyDown);
      };
    }, [visible, loading, onCancel]);

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
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50">
        <div
          className="w-96 rounded-lg border border-slate-200 bg-slate-50 p-6 shadow-lg dark:border-slate-700 dark:bg-slate-900"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
              <AlertTriangle size={20} className="text-amber-600" aria-hidden="true" />
            </div>
            <div>
              <h3 id={titleId} className="text-lg font-semibold text-slate-800 dark:text-slate-200">
                {t('agent.undo.title', 'Undo Action')}
              </h3>
              <p className="text-xs text-slate-400">{toolName}</p>
            </div>
          </div>
          <p id={descriptionId} className="text-sm text-slate-600 dark:text-slate-300 mb-4">
            {t(
              'agent.undo.description',
              'This will ask the agent to undo the action. The agent will attempt to revert any changes made.'
            )}
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              disabled={loading}
              className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              autoFocus
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
          </div>
        </div>
      </div>
    );
  }
);
UndoConfirmation.displayName = 'UndoConfirmation';
