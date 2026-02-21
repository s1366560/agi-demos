import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { ProviderCard, ProviderHealthPanel, ProviderConfigModal, ProviderUsageStats } from '@/components/provider';

import { providerAPI } from '../../services/api';
import { ProviderConfig, ProviderType, SystemResilienceStatus } from '../../types/memory';

const PROVIDER_TYPE_LABELS: Record<ProviderType, string> = {
  openai: 'OpenAI',
  dashscope: 'Dashscope',
  kimi: 'Moonshot Kimi',
  gemini: 'Google Gemini',
  anthropic: 'Anthropic',
  groq: 'Groq',
  azure_openai: 'Azure OpenAI',
  cohere: 'Cohere',
  mistral: 'Mistral',
  bedrock: 'AWS Bedrock',
  vertex: 'Google Vertex AI',
  deepseek: 'Deepseek',
  zai: 'ZhipuAI',
  ollama: 'Ollama',
  lmstudio: 'LM Studio',
};

type ViewMode = 'cards' | 'table';
type SortField = 'name' | 'health' | 'responseTime' | 'createdAt';
type SortOrder = 'asc' | 'desc';

export const ProviderList: React.FC = () => {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ProviderConfig | null>(null);
  const [checkingHealth, setCheckingHealth] = useState<string | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemResilienceStatus | null>(null);
  const [resettingCircuitBreaker, setResettingCircuitBreaker] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortOrder, setSortOrder] = useState<SortOrder>('asc');
  const [viewingStats, setViewingStats] = useState<ProviderConfig | null>(null);

  const loadProviders = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params: { provider_type?: string } = {};
      if (typeFilter !== 'all') {
        params.provider_type = typeFilter;
      }
      const response = await providerAPI.list(params);
      setProviders(response);
    } catch (err) {
      console.error('Failed to load providers:', err);
      setError(t('common.error'));
    } finally {
      setIsLoading(false);
    }
  }, [typeFilter, t]);

  const loadSystemStatus = useCallback(async () => {
    try {
      const status = await providerAPI.getSystemStatus();
      setSystemStatus(status);
    } catch (err) {
      console.error('Failed to load system status:', err);
    }
  }, []);

  useEffect(() => {
    loadProviders();
    loadSystemStatus();
  }, [loadProviders, loadSystemStatus]);

  const handleCheckHealth = async (providerId: string) => {
    setCheckingHealth(providerId);
    try {
      await providerAPI.checkHealth(providerId);
      await loadProviders();
      await loadSystemStatus();
    } catch (err) {
      console.error('Health check failed:', err);
    } finally {
      setCheckingHealth(null);
    }
  };

  const handleResetCircuitBreaker = async (providerType: string) => {
    setResettingCircuitBreaker(providerType);
    try {
      await providerAPI.resetCircuitBreaker(providerType);
      await loadProviders();
      await loadSystemStatus();
    } catch (err) {
      console.error('Failed to reset circuit breaker:', err);
      alert(t('common.error'));
    } finally {
      setResettingCircuitBreaker(null);
    }
  };

  const handleDelete = async (providerId: string) => {
    if (!confirm(t('tenant.providers.deleteConfirm'))) return;
    try {
      await providerAPI.delete(providerId);
      await loadProviders();
      await loadSystemStatus();
    } catch (err) {
      console.error('Failed to delete provider:', err);
      alert(t('common.error'));
    }
  };

  const handleEdit = (provider: ProviderConfig) => {
    setEditingProvider(provider);
    setIsModalOpen(true);
  };

  const handleCreate = () => {
    setEditingProvider(null);
    setIsModalOpen(true);
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
    setEditingProvider(null);
  };

  const handleModalSuccess = () => {
    handleModalClose();
    loadProviders();
    loadSystemStatus();
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('asc');
    }
  };

  const filteredAndSortedProviders = providers
    .filter((provider) => {
      const matchesSearch =
        provider.name.toLowerCase().includes(search.toLowerCase()) ||
        provider.llm_model.toLowerCase().includes(search.toLowerCase());
      const matchesType = typeFilter === 'all' || provider.provider_type === typeFilter;
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'active' && provider.is_active) ||
        (statusFilter === 'inactive' && !provider.is_active) ||
        (statusFilter === 'healthy' && provider.health_status === 'healthy') ||
        (statusFilter === 'unhealthy' && provider.health_status === 'unhealthy');
      return matchesSearch && matchesType && matchesStatus;
    })
    .sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case 'name':
          comparison = a.name.localeCompare(b.name);
          break;
        case 'health':
          const healthOrder = { healthy: 0, degraded: 1, unhealthy: 2, unknown: 3 };
          comparison =
            (healthOrder[a.health_status || 'unknown'] || 3) -
            (healthOrder[b.health_status || 'unknown'] || 3);
          break;
        case 'responseTime':
          comparison = (a.response_time_ms || 0) - (b.response_time_ms || 0);
          break;
        case 'createdAt':
          comparison = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
      }
      return sortOrder === 'asc' ? comparison : -comparison;
    });

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-6">
      {/* Header Area */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
            {t('tenant.providers.title')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t('tenant.providers.subtitle')}
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="inline-flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-primary-dark hover:from-primary-dark hover:to-primary text-white px-6 py-3 rounded-xl text-sm font-medium transition-all shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
        >
          <span className="material-symbols-outlined text-[20px]">add</span>
          {t('tenant.providers.addProvider')}
        </button>
      </div>

      {/* Health Dashboard */}
      <ProviderHealthPanel
        providers={providers}
        systemStatus={systemStatus}
        isLoading={isLoading}
      />

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 flex items-center gap-3">
          <span className="material-symbols-outlined text-red-600">error</span>
          <span className="text-red-800 dark:text-red-200">{error}</span>
          <button
            onClick={loadProviders}
            className="ml-auto text-red-600 hover:text-red-800 text-sm font-medium"
          >
            {t('common.actions.retry')}
          </button>
        </div>
      )}

      {/* Main Content Card */}
      <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col overflow-hidden">
        {/* Filters Toolbar */}
        <div className="p-5 border-b border-slate-200 dark:border-slate-700 flex flex-col lg:flex-row gap-4 justify-between items-start lg:items-center bg-gradient-to-r from-slate-50/50 to-transparent dark:from-slate-800/50">
          <div className="relative w-full lg:w-96">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <span className="material-symbols-outlined text-slate-400 text-[20px]">search</span>
            </div>
            <input
              className="block w-full pl-10 pr-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-xl leading-5 bg-white dark:bg-slate-700 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all"
              placeholder={t('tenant.providers.searchPlaceholder')}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3 w-full lg:w-auto overflow-x-auto">
            <div className="relative shrink-0">
              <select
                className="appearance-none bg-white dark:bg-slate-700 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2.5 pl-4 pr-10 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent cursor-pointer"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              >
                <option value="all">{t('tenant.providers.allTypes')}</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="gemini">Google Gemini</option>
                <option value="dashscope">Dashscope</option>
                <option value="deepseek">Deepseek</option>
                <option value="zai">ZhipuAI</option>
                <option value="groq">Groq</option>
                <option value="cohere">Cohere</option>
                <option value="mistral">Mistral</option>
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                <span className="material-symbols-outlined text-[16px]">expand_more</span>
              </div>
            </div>
            <div className="relative shrink-0">
              <select
                className="appearance-none bg-white dark:bg-slate-700 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2.5 pl-4 pr-10 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent cursor-pointer"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">{t('common.status.all')}</option>
                <option value="active">{t('common.status.active')}</option>
                <option value="inactive">{t('common.status.inactive')}</option>
                <option value="healthy">{t('common.status.healthy')}</option>
                <option value="unhealthy">{t('common.status.unhealthy')}</option>
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                <span className="material-symbols-outlined text-[16px]">expand_more</span>
              </div>
            </div>

            {/* View Mode Toggle */}
            <div className="flex items-center bg-white dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-xl overflow-hidden shrink-0">
              <button
                onClick={() => setViewMode('cards')}
                className={`p-2.5 transition-colors ${viewMode === 'cards' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-600'}`}
                title="Card View"
              >
                <span className="material-symbols-outlined text-[18px]">grid_view</span>
              </button>
              <button
                onClick={() => setViewMode('table')}
                className={`p-2.5 transition-colors ${viewMode === 'table' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-600'}`}
                title="Table View"
              >
                <span className="material-symbols-outlined text-[18px]">view_list</span>
              </button>
            </div>
          </div>
        </div>

        {/* Content Area */}
        {isLoading ? (
          <div className="p-12 text-center">
            <span className="material-symbols-outlined animate-spin text-4xl text-primary">
              progress_activity
            </span>
            <p className="mt-4 text-slate-500 dark:text-slate-400">{t('common.loading')}</p>
          </div>
        ) : filteredAndSortedProviders.length === 0 ? (
          <div className="p-12 text-center">
            <div className="flex flex-col items-center gap-4">
              <div className="p-4 bg-slate-100 dark:bg-slate-700 rounded-full">
                <span className="material-symbols-outlined text-4xl text-slate-400">smart_toy</span>
              </div>
              <div>
                <p className="text-lg font-medium text-slate-900 dark:text-white">
                  {t('tenant.providers.noProviders')}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                  Get started by adding your first LLM provider
                </p>
              </div>
              <button
                onClick={handleCreate}
                className="mt-2 inline-flex items-center gap-2 text-primary hover:text-primary-dark font-medium"
              >
                <span className="material-symbols-outlined text-[18px]">add</span>
                {t('tenant.providers.addFirstProvider')}
              </button>
            </div>
          </div>
        ) : viewMode === 'cards' ? (
          /* Card View */
          <div className="p-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 bg-slate-50/50 dark:bg-slate-900/50">
            {filteredAndSortedProviders.map((provider) => (
              <ProviderCard
                key={provider.id}
                provider={provider}
                onEdit={handleEdit}
                onAssign={() => {}}
                onDelete={handleDelete}
                onCheckHealth={handleCheckHealth}
                onResetCircuitBreaker={handleResetCircuitBreaker}
                isCheckingHealth={checkingHealth === provider.id}
                isResettingCircuitBreaker={resettingCircuitBreaker === provider.provider_type}
              />
            ))}
          </div>
        ) : (
          /* Table View */
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
              <thead className="bg-slate-50 dark:bg-slate-700/50">
                <tr>
                  <th
                    className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-primary"
                    onClick={() => handleSort('name')}
                  >
                    <div className="flex items-center gap-2">
                      Provider
                      <span className="material-symbols-outlined text-[14px]">
                        {sortField === 'name' ? (sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'swap_vert'}
                      </span>
                    </div>
                  </th>
                  <th
                    className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                    scope="col"
                  >
                    {t('common.forms.type')}
                  </th>
                  <th
                    className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                    scope="col"
                  >
                    {t('common.forms.model')}
                  </th>
                  <th
                    className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-primary"
                    onClick={() => handleSort('health')}
                  >
                    <div className="flex items-center gap-2">
                      {t('common.stats.healthStatus')}
                      <span className="material-symbols-outlined text-[14px]">
                        {sortField === 'health' ? (sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'swap_vert'}
                      </span>
                    </div>
                  </th>
                  <th
                    className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-primary"
                    onClick={() => handleSort('responseTime')}
                  >
                    <div className="flex items-center gap-2">
                      Response Time
                      <span className="material-symbols-outlined text-[14px]">
                        {sortField === 'responseTime' ? (sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'swap_vert'}
                      </span>
                    </div>
                  </th>
                  <th className="relative px-6 py-3" scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                {filteredAndSortedProviders.map((provider) => (
                  <tr
                    key={provider.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-3">
                        <div className="flex-shrink-0">
                          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
                            <span className="material-symbols-outlined text-primary">smart_toy</span>
                          </div>
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-slate-900 dark:text-white">
                              {provider.name}
                            </span>
                            {provider.is_default && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gradient-to-r from-purple-500 to-pink-500 text-white">
                                <span className="material-symbols-outlined text-[12px] mr-0.5">star</span>
                                Default
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-slate-500">{provider.api_key_masked}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
                        {PROVIDER_TYPE_LABELS[provider.provider_type] || provider.provider_type}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <code className="text-sm text-slate-600 dark:text-slate-400 font-mono">
                        {provider.llm_model}
                      </code>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                            provider.health_status === 'healthy'
                              ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                              : provider.health_status === 'degraded'
                                ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400'
                                : provider.health_status === 'unhealthy'
                                  ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
                          }`}
                        >
                          <span
                            className={`h-2 w-2 rounded-full ${
                              provider.health_status === 'healthy'
                                ? 'bg-green-500'
                                : provider.health_status === 'degraded'
                                  ? 'bg-yellow-500'
                                  : provider.health_status === 'unhealthy'
                                    ? 'bg-red-500'
                                    : 'bg-slate-400'
                            }`}
                          ></span>
                          {provider.health_status || t('common.status.unknown')}
                        </span>
                        {provider.response_time_ms && (
                          <span className="text-xs text-slate-400">
                            {provider.response_time_ms}ms
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600 dark:text-slate-400">
                      {provider.response_time_ms ? `${provider.response_time_ms}ms` : 'N/A'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleCheckHealth(provider.id)}
                          disabled={checkingHealth === provider.id}
                          className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-all disabled:opacity-50"
                          title={t('common.actions.checkHealth')}
                        >
                          <span
                            className={`material-symbols-outlined text-[18px] ${checkingHealth === provider.id ? 'animate-spin' : ''}`}
                          >
                            {checkingHealth === provider.id ? 'progress_activity' : 'monitor_heart'}
                          </span>
                        </button>
                        <button
                          onClick={() => handleEdit(provider)}
                          className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-all"
                          title={t('common.edit')}
                        >
                          <span className="material-symbols-outlined text-[18px]">edit</span>
                        </button>
                        <button
                          onClick={() => handleDelete(provider.id)}
                          className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all"
                          title={t('common.delete')}
                        >
                          <span className="material-symbols-outlined text-[18px]">delete</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modals */}
      <ProviderConfigModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        provider={editingProvider}
      />

      {viewingStats && (
        <ProviderUsageStats
          provider={viewingStats}
          onClose={() => setViewingStats(null)}
        />
      )}
    </div>
  );
};
