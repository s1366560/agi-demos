import React, { useState } from 'react';

import { providerAPI } from '../../services/api';
import { ProviderConfig } from '../../types/memory';
import { MaterialIcon } from '../agent/shared/MaterialIcon';

interface AssignProviderModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  provider: ProviderConfig;
  tenantId: string;
  initialOperationType?: 'llm' | 'embedding' | 'rerank' | undefined;
  initialPriority?: number | undefined;
}

export const AssignProviderModal: React.FC<AssignProviderModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  provider,
  tenantId,
  initialOperationType = 'llm',
  initialPriority = 0,
}) => {
  const [operationType, setOperationType] = useState<'llm' | 'embedding' | 'rerank'>(
    initialOperationType
  );
  const [priority, setPriority] = useState(initialPriority);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await providerAPI.assignToTenant(provider.id, tenantId, priority, operationType);
      onSuccess();
    } catch (err: any) {
      console.error('Failed to assign provider:', err);
      setError(err.message || 'Failed to assign provider');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative w-full max-w-md bg-white dark:bg-slate-800 rounded-2xl shadow-xl overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
              Assign Provider
            </h2>
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <MaterialIcon name="close" size={20} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {error && (
              <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm flex items-center gap-2">
                <MaterialIcon name="error" size={16} />
                {error}
              </div>
            )}

            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
                Assign <strong>{provider.name}</strong> to the current tenant.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                Operation Type
              </label>
              <select
                value={operationType}
                onChange={(e) => { setOperationType(e.target.value as any); }}
                className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
              >
                <option value="llm">LLM (Chat/Completion)</option>
                <option value="embedding">Embedding</option>
                <option value="rerank">Rerank</option>
              </select>
              <p className="text-xs text-slate-500">
                The type of operation this provider will handle.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                Priority
              </label>
              <input
                type="number"
                value={priority}
                onChange={(e) => { setPriority(parseInt(e.target.value)); }}
                min={0}
                className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
              />
              <p className="text-xs text-slate-500">
                Higher priority providers are tried first (default: 0).
              </p>
            </div>

            <div className="pt-4 flex justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="px-4 py-2 bg-primary hover:bg-primary-dark text-white font-medium rounded-lg transition-colors shadow-sm disabled:opacity-50 flex items-center gap-2"
              >
                {isSubmitting && (
                  <MaterialIcon name="progress_activity" className="animate-spin" size={16} />
                )}
                Assign
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
