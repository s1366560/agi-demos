import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { AlertCircle, Loader2 } from 'lucide-react';

import { AppModal } from '@/components/common';

import { providerAPI } from '../../services/api';

import type { ProviderConfig } from '../../types/memory';


type OperationType = 'llm' | 'embedding' | 'rerank';

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
  const { t } = useTranslation();
  const [operationType, setOperationType] = useState<OperationType>(initialOperationType);
  const [priority, setPriority] = useState(initialPriority);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await providerAPI.assignToTenant(provider.id, tenantId, priority, operationType);
      onSuccess();
    } catch (err: unknown) {
      console.error('Failed to assign provider:', err);
      setError(err instanceof Error ? err.message : t('components.provider.assign.assignFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AppModal
      open={isOpen}
      onClose={onClose}
      title={t('components.provider.assign.title')}
      size="sm"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            form="assign-provider-form"
            disabled={isSubmitting}
            className="px-4 py-2 bg-primary hover:bg-primary-dark text-white font-medium rounded-lg transition-colors shadow-sm disabled:opacity-50 flex items-center gap-2"
          >
            {isSubmitting && (
              <Loader2 size={16} className="animate-spin motion-reduce:animate-none" />
            )}
            {t('components.provider.assign.submit')}
          </button>
        </>
      }
    >
      <form
        id="assign-provider-form"
        onSubmit={(e) => {
          void handleSubmit(e);
        }}
        className="space-y-4"
      >
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm flex items-center gap-2">
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        <div>
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
            {t('components.provider.assign.descriptionPrefix')} <strong>{provider.name}</strong>{' '}
            {t('components.provider.assign.descriptionSuffix')}
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('components.provider.assign.operationType')}
          </label>
          <select
            value={operationType}
            onChange={(e) => {
              const nextOperationType = e.target.value;
              if (
                nextOperationType === 'llm' ||
                nextOperationType === 'embedding' ||
                nextOperationType === 'rerank'
              ) {
                setOperationType(nextOperationType);
              }
            }}
            className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
          >
            <option value="llm">{t('components.provider.operationTypes.llm')}</option>
            <option value="embedding">
              {t('components.provider.operationTypes.embedding')}
            </option>
            <option value="rerank">{t('components.provider.operationTypes.rerank')}</option>
          </select>
          <p className="text-xs text-slate-500">
            {t('components.provider.assign.operationTypeHelp')}
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('components.provider.assign.priority')}
          </label>
          <input
            type="number"
            value={priority}
            onChange={(e) => {
              setPriority(parseInt(e.target.value));
            }}
            min={0}
            className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-shadow"
          />
          <p className="text-xs text-slate-500">{t('components.provider.assign.priorityHelp')}</p>
        </div>
      </form>
    </AppModal>
  );
};
