/**
 * TenantCreateModal - Component for creating new tenants
 */

import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { AppModal } from '@/components/common';

import { tenantService } from '../../services/tenantService';

interface TenantCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (() => void) | undefined;
}

export const TenantCreateModal: React.FC<TenantCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      await tenantService.createTenant(name.trim(), description);
      setName('');
      setDescription('');
      if (onSuccess) {
        onSuccess();
      }
      onClose();
    } catch (err: unknown) {
      console.error('Failed to create tenant:', err);
      setError(err instanceof Error ? err.message : t('tenant.create_modal.error'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setName('');
      setDescription('');
      setError(null);
      onClose();
    }
  };

  return (
    <AppModal
      open={isOpen}
      onClose={handleClose}
      title={t('tenant.create_modal.title')}
      size="md"
      isDirty={() => name.trim() !== '' || description.trim() !== ''}
      closeOnBackdrop={!isLoading}
      footer={
        <>
          <button
            type="button"
            onClick={handleClose}
            disabled={isLoading}
            className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-slate-300 bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-md hover:bg-gray-50 dark:hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('tenant.create_modal.cancel')}
          </button>
          <button
            type="submit"
            form="tenant-create-page-form"
            disabled={isLoading || !name.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-primary rounded-md hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center space-x-2"
          >
            {isLoading ? (
              <>
                <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>{t('tenant.create_modal.creating')}</span>
              </>
            ) : (
              <span>{t('tenant.create_modal.create')}</span>
            )}
          </button>
        </>
      }
    >
      <form
        id="tenant-create-page-form"
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
      >
        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md">
            <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
          </div>
        )}

        <div className="mb-4">
          <label
            htmlFor="name"
            className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2"
          >
            {t('tenant.create_modal.name')} <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            id="name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
            required
            disabled={isLoading}
            className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-primary text-gray-900 dark:text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed"
            placeholder={t('tenant.create_modal.name_placeholder')}
          />
        </div>

        <div className="mb-6">
          <label
            htmlFor="description"
            className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2"
          >
            {t('tenant.create_modal.description')}
          </label>
          <textarea
            id="description"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
            }}
            disabled={isLoading}
            rows={3}
            className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-primary text-gray-900 dark:text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed resize-y"
            placeholder={t('tenant.create_modal.desc_placeholder')}
          />
        </div>
      </form>
    </AppModal>
  );
};
