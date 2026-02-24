import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import {
  ProviderCard,
  ProviderHealthPanel,
  ProviderConfigModal,
  ProviderUsageStats,
  AssignProviderModal,
  ModelAssignment,
} from '@/components/provider';

import { MaterialIcon } from '../../components/agent/shared/MaterialIcon';
import { PROVIDERS } from '../../constants/providers';
import { providerAPI } from '../../services/api';
import { useTenantStore } from '../../stores/tenant';
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
  minimax: 'MiniMax',
  zai: 'ZhipuAI',
  ollama: 'Ollama',
  lmstudio: 'LM Studio',
};

type ViewMode = 'cards' | 'table';
type SortField = 'name' | 'health' | 'responseTime' | 'createdAt';
type SortOrder = 'asc' | 'desc';

export const ProviderList: React.FC = () => {
  const { t } = useTranslation();
  const currentTenant = useTenantStore((state) => state.currentTenant);
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
  const [assigningProvider, setAssigningProvider] = useState<ProviderConfig | null>(null);
  const [activeTab, setActiveTab] = useState<'my-providers' | 'marketplace' | 'assignments'>(
    'my-providers'
  );
  const [selectedProviderType, setSelectedProviderType] = useState<ProviderType | undefined>(
    undefined
  );

  const loadProviders = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params: { provider_type?: string | undefined } = {};
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

  const handleCreate = (type?: ProviderType) => {
    setEditingProvider(null);
    setSelectedProviderType(type);
    setIsModalOpen(true);
  };

  const handleAssign = (provider: ProviderConfig) => {
    setAssigningProvider(provider);
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
    setEditingProvider(null);
    setSelectedProviderType(undefined);
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
        case 'health': {
          const healthOrder: Record<string, number> = {
            healthy: 0,
            degraded: 1,
            unhealthy: 2,
            unknown: 3,
          };
          comparison =
            (healthOrder[a.health_status || 'unknown'] || 3) -
            (healthOrder[b.health_status || 'unknown'] || 3);
          break;
        }
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
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            {t('tenant.providers.title')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t('tenant.providers.subtitle')}
          </p>
        </div>
        <button
          onClick={() => { handleCreate(); }}
          className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
        >
          <MaterialIcon name="add" size={20} />
          {t('tenant.providers.addProvider')}
        </button>
      </div>

      {/* View Toggle */}
      <div className="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-lg w-fit">
        <button
          onClick={() => { setActiveTab('my-providers'); }}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'my-providers'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          My Providers
        </button>
        <button
          onClick={() => { setActiveTab('marketplace'); }}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'marketplace'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          Marketplace
        </button>
        <button
          onClick={() => { setActiveTab('assignments'); }}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'assignments'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          Routing & Assignments
        </button>
      </div>

      {activeTab === 'my-providers' && (
        <>
          {/* Health Dashboard */}
          <ProviderHealthPanel
            providers={providers}
            systemStatus={systemStatus}
            isLoading={isLoading}
          />

          {/* Error State */}
          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-center gap-3">
              <MaterialIcon name="error" size={20} className="text-red-600" />
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
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col overflow-hidden">
            {/* Filters Toolbar */}
            <div className="p-4 border-b border-slate-100 dark:border-slate-800 flex flex-col lg:flex-row gap-4 justify-between items-start lg:items-center bg-slate-50/50 dark:bg-slate-800/30">
              <div className="relative w-full lg:w-96">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <MaterialIcon name="search" size={20} className="text-slate-400" />
                </div>
                <input
                  className="block w-full pl-10 pr-4 py-2.5 border border-slate-300 dark:border-slate-700 rounded-lg leading-5 bg-white dark:bg-slate-900 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all"
                  placeholder={t('tenant.providers.searchPlaceholder')}
                  type="text"
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); }}
                />
              </div>
              <div className="flex items-center gap-3 w-full lg:w-auto overflow-x-auto">
                <div className="relative shrink-0">
                  <select
                    className="appearance-none bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 py-2.5 pl-4 pr-8 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent cursor-pointer"
                    value={typeFilter}
                    onChange={(e) => { setTypeFilter(e.target.value); }}
                  >
                    <option value="all">{t('tenant.providers.allTypes')}</option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="dashscope">Dashscope</option>
                    <option value="deepseek">Deepseek</option>
                    <option value="minimax">MiniMax</option>
                    <option value="zai">ZhipuAI</option>
                    <option value="groq">Groq</option>
                    <option value="cohere">Cohere</option>
                    <option value="mistral">Mistral</option>
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                    <MaterialIcon name="expand_more" size={16} />
                  </div>
                </div>
                <div className="relative shrink-0">
                  <select
                    className="appearance-none bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 py-2.5 pl-4 pr-8 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent cursor-pointer"
                    value={statusFilter}
                    onChange={(e) => { setStatusFilter(e.target.value); }}
                  >
                    <option value="all">{t('common.status.all')}</option>
                    <option value="active">{t('common.status.active')}</option>
                    <option value="inactive">{t('common.status.inactive')}</option>
                    <option value="healthy">{t('common.status.healthy')}</option>
                    <option value="unhealthy">{t('common.status.unhealthy')}</option>
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                    <MaterialIcon name="expand_more" size={16} />
                  </div>
                </div>

                {/* View Mode Toggle */}
                <div className="flex items-center bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg overflow-hidden shrink-0">
                  <button
                    onClick={() => { setViewMode('cards'); }}
                    className={`p-2 transition-colors ${viewMode === 'cards' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                    title="Card View"
                  >
                    <MaterialIcon name="grid_view" size={18} />
                  </button>
                  <button
                    onClick={() => { setViewMode('table'); }}
                    className={`p-2 transition-colors ${viewMode === 'table' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                    title="Table View"
                  >
                    <MaterialIcon name="view_list" size={18} />
                  </button>
                </div>
              </div>
            </div>

            {/* Content Area */}
            {isLoading ? (
              <div className="p-12 text-center">
                <MaterialIcon
                  name="progress_activity"
                  size={32}
                  className="animate-spin text-primary mx-auto"
                />
                <p className="mt-4 text-slate-500 dark:text-slate-400">{t('common.loading')}</p>
              </div>
            ) : filteredAndSortedProviders.length === 0 ? (
              <div className="p-12 text-center">
                <div className="flex flex-col items-center gap-4">
                  <div className="p-4 bg-slate-100 dark:bg-slate-800 rounded-full">
                    <MaterialIcon name="smart_toy" size={32} className="text-slate-400" />
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
                    onClick={() => { handleCreate(); }}
                    className="mt-2 inline-flex items-center gap-2 text-primary hover:text-primary-dark font-medium"
                  >
                    <MaterialIcon name="add" size={18} />
                    {t('tenant.providers.addFirstProvider')}
                  </button>
                </div>
              </div>
            ) : viewMode === 'cards' ? (
              /* Card View */
              <div className="p-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 bg-slate-50/50 dark:bg-slate-800/30">
                {filteredAndSortedProviders.map((provider) => (
                  <ProviderCard
                    key={provider.id}
                    provider={provider}
                    onEdit={handleEdit}
                    onAssign={handleAssign}
                    onDelete={handleDelete}
                    onCheckHealth={handleCheckHealth}
                    onResetCircuitBreaker={handleResetCircuitBreaker}
                    onViewStats={setViewingStats}
                    isCheckingHealth={checkingHealth === provider.id}
                    isResettingCircuitBreaker={resettingCircuitBreaker === provider.provider_type}
                  />
                ))}
              </div>
            ) : (
              /* Table View */
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
                  <thead className="bg-slate-50 dark:bg-slate-800/50">
                    <tr>
                      <th
                        className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-primary"
                        onClick={() => { handleSort('name'); }}
                      >
                        <div className="flex items-center gap-2">
                          Provider
                          <MaterialIcon
                            name={
                              sortField === 'name'
                                ? sortOrder === 'asc'
                                  ? 'arrow_upward'
                                  : 'arrow_downward'
                                : 'swap_vert'
                            }
                            size={14}
                          />
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
                        onClick={() => { handleSort('health'); }}
                      >
                        <div className="flex items-center gap-2">
                          {t('common.stats.healthStatus')}
                          <MaterialIcon
                            name={
                              sortField === 'health'
                                ? sortOrder === 'asc'
                                  ? 'arrow_upward'
                                  : 'arrow_downward'
                                : 'swap_vert'
                            }
                            size={14}
                          />
                        </div>
                      </th>
                      <th
                        className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-primary"
                        onClick={() => { handleSort('responseTime'); }}
                      >
                        <div className="flex items-center gap-2">
                          Response Time
                          <MaterialIcon
                            name={
                              sortField === 'responseTime'
                                ? sortOrder === 'asc'
                                  ? 'arrow_upward'
                                  : 'arrow_downward'
                                : 'swap_vert'
                            }
                            size={14}
                          />
                        </div>
                      </th>
                      <th className="relative px-6 py-3" scope="col">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-slate-900 divide-y divide-slate-200 dark:divide-slate-800">
                    {filteredAndSortedProviders.map((provider) => (
                      <tr
                        key={provider.id}
                        className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                      >
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-3">
                            <div className="flex-shrink-0">
                              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
                                <MaterialIcon name="smart_toy" size={20} className="text-primary" />
                              </div>
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-slate-900 dark:text-white">
                                  {provider.name}
                                </span>
                                {provider.is_default && (
                                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-primary/10 text-primary border border-primary/20">
                                    <MaterialIcon name="star" size={10} filled />
                                    <span className="ml-0.5">Default</span>
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-slate-500">
                                {provider.api_key_masked}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                            {PROVIDER_TYPE_LABELS[provider.provider_type] || provider.provider_type}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex flex-col gap-1">
                            <code className="text-sm text-slate-600 dark:text-slate-400 font-mono">
                              {provider.llm_model}
                            </code>
                            {provider.embedding_model && (
                              <code className="text-xs text-slate-500 dark:text-slate-500 font-mono">
                                {provider.embedding_model}
                              </code>
                            )}
                            {provider.reranker_model && (
                              <code className="text-xs text-slate-500 dark:text-slate-500 font-mono">
                                {provider.reranker_model}
                              </code>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span
                              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                                provider.health_status === 'healthy'
                                  ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                                  : provider.health_status === 'degraded'
                                    ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800'
                                    : provider.health_status === 'unhealthy'
                                      ? 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800'
                                      : 'bg-slate-50 dark:bg-slate-800/50 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700'
                              }`}
                            >
                              <span
                                className={`h-2 w-2 rounded-full ${
                                  provider.health_status === 'healthy'
                                    ? 'bg-emerald-500'
                                    : provider.health_status === 'degraded'
                                      ? 'bg-amber-500'
                                      : provider.health_status === 'unhealthy'
                                        ? 'bg-red-500'
                                        : 'bg-slate-400'
                                }`}
                              />
                              {provider.health_status || t('common.status.unknown')}
                            </span>
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
                              <MaterialIcon
                                name={
                                  checkingHealth === provider.id
                                    ? 'progress_activity'
                                    : 'monitor_heart'
                                }
                                size={18}
                                className={checkingHealth === provider.id ? 'animate-spin' : ''}
                              />
                            </button>
                            <button
                              onClick={() => { handleEdit(provider); }}
                              className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-all"
                              title={t('common.edit')}
                            >
                              <MaterialIcon name="edit" size={18} />
                            </button>
                            <button
                              onClick={() => handleDelete(provider.id)}
                              className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all"
                              title={t('common.delete')}
                            >
                              <MaterialIcon name="delete" size={18} />
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
        </>
      )}

      {activeTab === 'marketplace' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {PROVIDERS.map((providerMeta) => (
            <div
              key={providerMeta.value}
              className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 flex flex-col items-center text-center hover:shadow-lg transition-all"
            >
              <div className="w-16 h-16 rounded-2xl bg-slate-50 dark:bg-slate-800 flex items-center justify-center mb-4 text-4xl">
                {providerMeta.icon}
              </div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
                {providerMeta.label}
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-6 line-clamp-2">
                {providerMeta.description}
              </p>

              <div className="mt-auto w-full pt-4 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-4">
                <a
                  href={providerMeta.documentationUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-slate-500 hover:text-primary flex items-center gap-1"
                >
                  Docs <MaterialIcon name="open_in_new" size={14} />
                </a>
                <button
                  onClick={() => { handleCreate(providerMeta.value); }}
                  className="px-4 py-2 bg-primary hover:bg-primary-dark text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
                >
                  <MaterialIcon name="add" size={16} />
                  Connect
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'assignments' && (
        <ModelAssignment tenantId={currentTenant?.id ?? ''} providers={providers} />
      )}

      {/* Modals */}
      <ProviderConfigModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        provider={editingProvider}
        initialProviderType={selectedProviderType}
      />

      {viewingStats && (
        <ProviderUsageStats provider={viewingStats} onClose={() => { setViewingStats(null); }} />
      )}

      {assigningProvider && currentTenant && (
        <AssignProviderModal
          isOpen={!!assigningProvider}
          onClose={() => { setAssigningProvider(null); }}
          onSuccess={() => {
            setAssigningProvider(null);
            loadProviders();
          }}
          provider={assigningProvider}
          tenantId={currentTenant.id}
        />
      )}
    </div>
  );
};
