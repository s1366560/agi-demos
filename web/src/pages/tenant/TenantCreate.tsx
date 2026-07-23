/**
 * TenantCreateModal - Component for creating new tenants
 */

import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { AppModal } from '@/components/common';
import {
  DEFAULT_TENANT_CREATE_VALUES,
  TenantCreateForm,
} from '@/components/tenant/TenantCreateForm';
import type { TenantCreateFormValues } from '@/components/tenant/TenantCreateForm';

import { tenantService } from '../../services/tenantService';
import { logger } from '../../utils/logger';

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
  const [values, setValues] = useState<TenantCreateFormValues>(DEFAULT_TENANT_CREATE_VALUES);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (submitted: TenantCreateFormValues) => {
    setIsLoading(true);
    setError(null);

    try {
      await tenantService.createTenant(submitted.name.trim(), submitted.description);
      setValues(DEFAULT_TENANT_CREATE_VALUES);
      if (onSuccess) {
        onSuccess();
      }
      onClose();
    } catch (err: unknown) {
      logger.error('Failed to create tenant', err);
      setError(err instanceof Error ? err.message : t('tenant.create_modal.error'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setValues(DEFAULT_TENANT_CREATE_VALUES);
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
      isDirty={() => values.name.trim() !== '' || values.description.trim() !== ''}
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
            disabled={isLoading || !values.name.trim()}
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
      <TenantCreateForm
        formId="tenant-create-page-form"
        values={values}
        onChange={setValues}
        onSubmit={(submitted) => {
          void handleSubmit(submitted);
        }}
        isLoading={isLoading}
        error={error}
      />
    </AppModal>
  );
};
