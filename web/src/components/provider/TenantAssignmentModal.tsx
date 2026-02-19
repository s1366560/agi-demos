import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Select, Button, InputNumber, message } from 'antd';

import { providerAPI } from '../../services/api';
import { useTenantStore } from '../../stores/tenant';
import { ProviderConfig } from '../../types/memory';

interface TenantAssignmentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  provider: ProviderConfig | null;
}

export const TenantAssignmentModal: React.FC<TenantAssignmentModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  provider,
}) => {
  const { t } = useTranslation();
  const [selectedTenantId, setSelectedTenantId] = useState<string>('');
  const [operationType, setOperationType] = useState<'llm' | 'embedding' | 'rerank'>('llm');
  const [priority, setPriority] = useState<number>(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { tenants, listTenants } = useTenantStore();

  useEffect(() => {
    if (isOpen) {
      listTenants();
      setSelectedTenantId('');
      setOperationType('llm');
      setPriority(0);
    }
  }, [isOpen, listTenants]);

  const handleSubmit = async () => {
    if (!provider || !selectedTenantId) return;

    setIsSubmitting(true);
    try {
      await providerAPI.assignToTenant(provider.id, selectedTenantId, priority, operationType);
      message.success('Provider assigned to tenant successfully');
      onSuccess();
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Failed to assign provider');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      title="Assign Provider to Tenant"
      open={isOpen}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t('common.cancel')}
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={isSubmitting}
          onClick={handleSubmit}
          disabled={!selectedTenantId}
        >
          {t('common.assign')}
        </Button>,
      ]}
    >
      <div className="flex flex-col gap-4 py-4">
        {provider && (
          <div className="bg-slate-50 dark:bg-slate-800 p-3 rounded-lg mb-2">
            <div className="text-sm text-slate-500">Selected Provider</div>
            <div className="font-medium flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">smart_toy</span>
              {provider.name}
              <span className="text-xs bg-slate-200 dark:bg-slate-700 px-2 py-0.5 rounded text-slate-600 dark:text-slate-300">
                {provider.provider_type}
              </span>
            </div>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium mb-1">Select Tenant</label>
          <Select
            className="w-full"
            placeholder="Select a tenant"
            value={selectedTenantId}
            onChange={setSelectedTenantId}
            options={tenants.map((tenant) => ({
              label: tenant.name,
              value: tenant.id,
            }))}
            showSearch
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Operation Type</label>
          <Select
            className="w-full"
            value={operationType}
            onChange={(value) => setOperationType(value)}
            options={[
              { label: 'LLM (chat/completion)', value: 'llm' },
              { label: 'Embedding (vector generation)', value: 'embedding' },
              { label: 'Rerank (result re-ordering)', value: 'rerank' },
            ]}
          />
          <div className="mt-1 text-xs text-slate-500">
            Assignment applies only to the selected operation type.
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            Priority <span className="text-slate-400 font-normal">(Lower value = higher priority)</span>
          </label>
          <InputNumber
            className="w-full"
            value={priority}
            onChange={(val) => setPriority(val || 0)}
            min={0}
            max={100}
          />
        </div>
      </div>
    </Modal>
  );
};
