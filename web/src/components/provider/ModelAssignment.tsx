import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { providerAPI } from '../../services/api';
import { ProviderConfig, TenantProviderMapping } from '../../types/memory';
import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { AssignProviderModal } from './AssignProviderModal';
import { ProviderIcon } from './ProviderIcon';
import { ProviderSelectorModal } from './ProviderSelectorModal';

interface ModelAssignmentProps {
  tenantId: string;
  providers: ProviderConfig[];
}

interface GroupedAssignments {
  llm: TenantProviderMapping[];
  embedding: TenantProviderMapping[];
  rerank: TenantProviderMapping[];
}

export const ModelAssignment: React.FC<ModelAssignmentProps> = ({ tenantId, providers }) => {
  const { t } = useTranslation();
  const [assignments, setAssignments] = useState<TenantProviderMapping[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isAssignModalOpen, setIsAssignModalOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<ProviderConfig | null>(null);

  const [isSelectorOpen, setIsSelectorOpen] = useState(false);
  const [targetType, setTargetType] = useState<'llm' | 'embedding' | 'rerank'>('llm');

  const loadAssignments = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await providerAPI.listTenantAssignments(tenantId);
      setAssignments(data);
    } catch (err: any) {
      console.error('Failed to load assignments:', err);
      setError(err.message || 'Failed to load assignments');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAssignments();
  }, [tenantId]);

  const handleUnassign = async (
    providerId: string,
    operationType: 'llm' | 'embedding' | 'rerank'
  ) => {
    if (!confirm('Are you sure you want to remove this assignment?')) return;
    try {
      await providerAPI.unassignFromTenant(providerId, tenantId, operationType);
      loadAssignments();
    } catch (err: any) {
      console.error('Failed to unassign provider:', err);
      alert(err.message || 'Failed to unassign provider');
    }
  };

  const handleAddClick = (type: 'llm' | 'embedding' | 'rerank') => {
    setTargetType(type);
    setIsSelectorOpen(true);
  };

  const handleEditClick = (mapping: TenantProviderMapping) => {
    const provider = getProvider(mapping.provider_id);
    if (provider) {
      setSelectedProvider(provider);
      setTargetType(mapping.operation_type);
      setIsAssignModalOpen(true);
    }
  };

  const getProvider = (id: string) => providers.find((p) => p.id === id);

  const groupedAssignments: GroupedAssignments = {
    llm: assignments
      .filter((a) => a.operation_type === 'llm')
      .sort((a, b) => a.priority - b.priority),
    embedding: assignments
      .filter((a) => a.operation_type === 'embedding')
      .sort((a, b) => a.priority - b.priority),
    rerank: assignments
      .filter((a) => a.operation_type === 'rerank')
      .sort((a, b) => a.priority - b.priority),
  };

  const renderSection = (
    title: string,
    type: 'llm' | 'embedding' | 'rerank',
    items: TenantProviderMapping[]
  ) => (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden h-full flex flex-col">
      <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 flex justify-between items-center shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white uppercase tracking-wider">
            {title}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            {items.length === 0 ? 'No provider assigned' : `${items.length} provider(s) configured`}
          </p>
        </div>
        <button
          onClick={() => handleAddClick(type)}
          className="text-primary hover:text-primary-dark text-sm font-medium flex items-center gap-1 transition-colors"
        >
          <MaterialIcon name="add" size={16} />
          Add
        </button>
      </div>

      <div className="divide-y divide-slate-100 dark:divide-slate-800 overflow-y-auto flex-1 p-0">
        {items.length === 0 ? (
          <div className="p-8 text-center text-slate-500 dark:text-slate-400 text-sm italic flex flex-col items-center gap-2">
            <MaterialIcon
              name="alt_route"
              size={24}
              className="text-slate-300 dark:text-slate-600"
            />
            No provider assigned. System defaults will be used.
          </div>
        ) : (
          <div className="flex flex-col">
            {items.map((assignment, index) => {
              const provider = getProvider(assignment.provider_id);
              if (!provider) return null;

              return (
                <div
                  key={assignment.id}
                  className="p-4 flex items-center justify-between group hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                >
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-slate-100 dark:bg-slate-800 text-xs font-medium text-slate-500 border border-slate-200 dark:border-slate-700">
                      {assignment.priority}
                    </div>
                    <ProviderIcon providerType={provider.provider_type} size="sm" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-900 dark:text-white flex items-center gap-2 truncate">
                        {provider.name}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-2 truncate">
                        <code className="bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded text-[10px]">
                          {provider.llm_model}
                        </code>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleEditClick(assignment)}
                      className="p-1.5 text-slate-400 hover:text-primary rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                      title="Edit Assignment"
                    >
                      <MaterialIcon name="edit" size={16} />
                    </button>
                    <button
                      onClick={() => handleUnassign(assignment.provider_id, type)}
                      className="p-1.5 text-slate-400 hover:text-red-500 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                      title="Remove Assignment"
                    >
                      <MaterialIcon name="delete" size={16} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="p-12 text-center">
        <MaterialIcon
          name="progress_activity"
          size={32}
          className="animate-spin text-primary mx-auto"
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg flex items-center gap-3 border border-red-200 dark:border-red-800">
        <MaterialIcon name="error" size={20} />
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6 h-full flex flex-col">
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 flex gap-3">
        <MaterialIcon name="info" className="text-blue-600 dark:text-blue-400 shrink-0" size={20} />
        <div className="text-sm text-blue-800 dark:text-blue-200">
          <p className="font-medium mb-1">Provider Routing Configuration</p>
          <p>
            Configure which providers handle specific operations. Requests are routed based on
            priority (lower number = higher priority). If the primary provider fails, the system
            automatically falls back to the next available provider in the list.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 auto-rows-fr">
        {renderSection('LLM (Chat/Completion)', 'llm', groupedAssignments.llm)}
        {renderSection('Embedding', 'embedding', groupedAssignments.embedding)}
        {renderSection('Rerank', 'rerank', groupedAssignments.rerank)}
      </div>

      {isSelectorOpen && (
        <ProviderSelectorModal
          isOpen={isSelectorOpen}
          onClose={() => setIsSelectorOpen(false)}
          onSelect={(provider) => {
            setSelectedProvider(provider);
            setIsSelectorOpen(false);
            setIsAssignModalOpen(true);
          }}
          providers={providers}
          title={`Select Provider for ${targetType === 'llm' ? 'LLM' : targetType === 'embedding' ? 'Embedding' : 'Rerank'}`}
        />
      )}

      {isAssignModalOpen && selectedProvider && (
        <AssignProviderModal
          isOpen={isAssignModalOpen}
          onClose={() => setIsAssignModalOpen(false)}
          onSuccess={() => {
            setIsAssignModalOpen(false);
            loadAssignments();
          }}
          provider={selectedProvider}
          tenantId={tenantId}
          initialOperationType={targetType}
          initialPriority={
            // Find existing assignment priority or default to end of list
            assignments.find(
              (a) => a.provider_id === selectedProvider.id && a.operation_type === targetType
            )?.priority ?? groupedAssignments[targetType].length
          }
        />
      )}
    </div>
  );
};
