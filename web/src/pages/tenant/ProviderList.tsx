import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { App } from 'antd';
import {
  Activity,
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Bot,
  ChevronDown,
  ExternalLink,
  LayoutGrid,
  List,
  Loader2,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import {
  ProviderCard,
  ProviderHealthPanel,
  ProviderConfigModal,
  ProviderUsageStats,
  AssignProviderModal,
  ModelAssignment,
} from '@/components/provider';

import { PROVIDERS } from '../../constants/providers';
import { providerAPI } from '../../services/api';
import { useProviderStore } from '../../stores/provider';
import { useTenantStore } from '../../stores/tenant';
import { ProviderConfig, ProviderType, SystemResilienceStatus } from '../../types/memory';
import { confirmAction } from '../../utils/confirmAction';

const PROVIDER_TYPE_LABELS: Record<ProviderType, string> = {
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  dashscope: 'Dashscope',
  dashscope_coding: 'Dashscope Coding',
  dashscope_embedding: 'Dashscope Embedding',
  dashscope_reranker: 'Dashscope Reranker',
  kimi: 'Moonshot Kimi',
  kimi_coding: 'Kimi Coding',
  kimi_embedding: 'Kimi Embedding',
  kimi_reranker: 'Kimi Reranker',
  gemini: 'Google Gemini',
  anthropic: 'Anthropic',
  groq: 'Groq',
  azure_openai: 'Azure OpenAI',
  cohere: 'Cohere',
  mistral: 'Mistral',
  bedrock: 'AWS Bedrock',
  vertex: 'Google Vertex AI',
  deepseek: 'DeepSeek',
  minimax: 'MiniMax',
  minimax_coding: 'MiniMax Coding',
  minimax_embedding: 'MiniMax Embedding',
  minimax_reranker: 'MiniMax Reranker',
  zai: 'ZhipuAI',
  zai_coding: 'Z.AI Coding',
  zai_embedding: 'Z.AI Embedding',
  zai_reranker: 'Z.AI Reranker',
  ollama: 'Ollama',
  lmstudio: 'LM Studio',
  volcengine: 'Volcengine \u706B\u5C71\u5F15\u64CE',
  volcengine_coding: 'Volcengine Coding',
  volcengine_embedding: 'Volcengine Embedding',
  volcengine_reranker: 'Volcengine Reranker',
};

const PROVIDER_TYPE_FILTER_OPTIONS: Array<{ value: ProviderType; label: string }> = [
  { value: 'openai', label: PROVIDER_TYPE_LABELS.openai },
  { value: 'anthropic', label: PROVIDER_TYPE_LABELS.anthropic },
  { value: 'gemini', label: PROVIDER_TYPE_LABELS.gemini },
  { value: 'dashscope', label: PROVIDER_TYPE_LABELS.dashscope },
  { value: 'deepseek', label: PROVIDER_TYPE_LABELS.deepseek },
  { value: 'minimax', label: PROVIDER_TYPE_LABELS.minimax },
  { value: 'zai', label: PROVIDER_TYPE_LABELS.zai },
  { value: 'groq', label: PROVIDER_TYPE_LABELS.groq },
  { value: 'cohere', label: PROVIDER_TYPE_LABELS.cohere },
  { value: 'mistral', label: PROVIDER_TYPE_LABELS.mistral },
];

type ViewMode = 'cards' | 'table';
type SortField = 'name' | 'health' | 'responseTime';
type SortOrder = 'asc' | 'desc';

interface SortableThProps {
  field: SortField;
  sortField: SortField;
  sortOrder: SortOrder;
  onSort: (field: SortField) => void;
  children: React.ReactNode;
}

const SortableTh: React.FC<SortableThProps> = ({
  field,
  sortField,
  sortOrder,
  onSort,
  children,
}) => {
  const isActive = sortField === field;
  return (
    <th
      scope="col"
      aria-sort={isActive ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
    >
      <button
        type="button"
        onClick={() => {
          onSort(field);
        }}
        className="flex items-center gap-2 rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
      >
        {children}
        {isActive ? (
          sortOrder === 'asc' ? (
            <ArrowUp size={14} aria-hidden="true" />
          ) : (
            <ArrowDown size={14} aria-hidden="true" />
          )
        ) : (
          <ArrowUpDown size={14} className="opacity-50" aria-hidden="true" />
        )}
      </button>
    </th>
  );
};

export const ProviderList: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string | undefined }>();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;

  const { providers, isLoading, error } = useProviderStore(
    useShallow((state) => ({
      providers: state.providers,
      isLoading: state.loading,
      error: state.error,
    }))
  );

  const { fetchProviders, deleteProvider } = useProviderStore(
    useShallow((state) => ({
      fetchProviders: state.fetchProviders,
      deleteProvider: state.deleteProvider,
    }))
  );

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
    await fetchProviders();
  }, [fetchProviders]);

  const loadSystemStatus = useCallback(async () => {
    try {
      const status = await providerAPI.getSystemStatus();
      setSystemStatus(status);
    } catch (err) {
      console.error('Failed to load system status:', err);
      message.error(t('tenant.providers.systemStatusError'));
    }
  }, [message, t]);

  useEffect(() => {
    void loadProviders();
    void loadSystemStatus();
  }, [loadProviders, loadSystemStatus]);

  const handleCheckHealth = async (providerId: string) => {
    setCheckingHealth(providerId);
    try {
      const validation = await providerAPI.checkHealth(providerId);
      await Promise.all([loadProviders(), loadSystemStatus()]);
      if (validation.probed === false && validation.status === 'configuration_valid') {
        message.success(
          t('tenant.providers.connectionTest.configurationValid', {
            defaultValue:
              'Configuration validated. Network probing is not supported for this provider.',
          })
        );
      }
    } catch (err) {
      console.error('Health check failed:', err);
      message.error(t('tenant.providers.healthCheckError'));
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
      message.error(t('common.error'));
    } finally {
      setResettingCircuitBreaker(null);
    }
  };

  const handleDelete = async (providerId: string) => {
    if (!(await confirmAction({ title: t('tenant.providers.deleteConfirm'), danger: true })))
      return;
    try {
      await deleteProvider(providerId);
      message.success(t('tenant.providers.deleteSuccess'));
      await loadProviders();
      await loadSystemStatus();
    } catch (err) {
      console.error('Failed to delete provider:', err);
      message.error(t('common.error'));
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
    void loadProviders();
    void loadSystemStatus();
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
        (provider.llm_model || '').toLowerCase().includes(search.toLowerCase());
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
            configuration_valid: 1,
            degraded: 2,
            unhealthy: 3,
            unknown: 4,
          };
          comparison =
            (healthOrder[a.health_status || 'unknown'] ?? 4) -
            (healthOrder[b.health_status || 'unknown'] ?? 4);
          break;
        }
        case 'responseTime':
          comparison = (a.response_time_ms || 0) - (b.response_time_ms || 0);
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
          type="button"
          onClick={() => {
            handleCreate();
          }}
          className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
        >
          <Plus size={20} />
          {t('tenant.providers.addProvider')}
        </button>
      </div>

      {/* View Toggle */}
      <div
        role="tablist"
        aria-label={t('tenant.providers.title')}
        className="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-lg w-fit"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'my-providers'}
          onClick={() => {
            setActiveTab('my-providers');
          }}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'my-providers'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          {t('tenant.providers.tabs.myProviders')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'marketplace'}
          onClick={() => {
            setActiveTab('marketplace');
          }}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'marketplace'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          {t('tenant.providers.tabs.marketplace')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'assignments'}
          onClick={() => {
            setActiveTab('assignments');
          }}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'assignments'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
          }`}
        >
          {t('tenant.providers.tabs.assignments')}
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
              <AlertCircle size={20} className="text-red-600" />
              <span className="text-red-800 dark:text-red-200">{error}</span>
              <button
                type="button"
                onClick={() => {
                  void loadProviders();
                }}
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
                  <Search size={20} className="text-slate-400" />
                </div>
                <input
                  className="block w-full pl-10 pr-4 py-2.5 border border-slate-300 dark:border-slate-700 rounded-lg leading-5 bg-white dark:bg-slate-900 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                  aria-label={t('tenant.providers.searchPlaceholder')}
                  placeholder={t('tenant.providers.searchPlaceholder')}
                  type="text"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                  }}
                />
              </div>
              <div className="flex items-center gap-3 w-full lg:w-auto overflow-x-auto">
                <div className="relative shrink-0">
                  <select
                    aria-label={t('tenant.providers.typeFilterLabel')}
                    className="appearance-none bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 py-2.5 pl-4 pr-8 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent cursor-pointer"
                    value={typeFilter}
                    onChange={(e) => {
                      setTypeFilter(e.target.value);
                    }}
                  >
                    <option value="all">{t('tenant.providers.allTypes')}</option>
                    {PROVIDER_TYPE_FILTER_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                    <ChevronDown size={16} />
                  </div>
                </div>
                <div className="relative shrink-0">
                  <select
                    aria-label={t('tenant.providers.statusFilterLabel')}
                    className="appearance-none bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 py-2.5 pl-4 pr-8 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent cursor-pointer"
                    value={statusFilter}
                    onChange={(e) => {
                      setStatusFilter(e.target.value);
                    }}
                  >
                    <option value="all">{t('common.status.all')}</option>
                    <option value="active">{t('common.status.active')}</option>
                    <option value="inactive">{t('common.status.inactive')}</option>
                    <option value="healthy">{t('common.status.healthy')}</option>
                    <option value="unhealthy">{t('common.status.unhealthy')}</option>
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                    <ChevronDown size={16} />
                  </div>
                </div>

                {/* View Mode Toggle */}
                <div className="flex items-center bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg overflow-hidden shrink-0">
                  <button
                    type="button"
                    onClick={() => {
                      setViewMode('cards');
                    }}
                    aria-label={t('tenant.providers.view.card')}
                    className={`p-2 transition-colors ${viewMode === 'cards' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                    title={t('tenant.providers.view.card')}
                  >
                    <LayoutGrid size={18} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setViewMode('table');
                    }}
                    aria-label={t('tenant.providers.view.table')}
                    className={`p-2 transition-colors ${viewMode === 'table' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                    title={t('tenant.providers.view.table')}
                  >
                    <List size={18} />
                  </button>
                </div>
              </div>
            </div>

            {/* Content Area */}
            {isLoading ? (
              <div className="p-12 text-center">
                <Loader2
                  size={32}
                  className="animate-spin motion-reduce:animate-none text-primary mx-auto"
                />
                <p className="mt-4 text-slate-500 dark:text-slate-400">{t('common.loading')}</p>
              </div>
            ) : filteredAndSortedProviders.length === 0 ? (
              <div className="p-12 text-center">
                <div className="flex flex-col items-center gap-4">
                  <div className="p-4 bg-slate-100 dark:bg-slate-800 rounded-full">
                    <Bot size={32} className="text-slate-400" />
                  </div>
                  <div>
                    <p className="text-lg font-medium text-slate-900 dark:text-white">
                      {t('tenant.providers.noProviders')}
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                      {t('tenant.providers.emptyHint')}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      handleCreate();
                    }}
                    className="mt-2 inline-flex items-center gap-2 text-primary hover:text-primary-dark font-medium"
                  >
                    <Plus size={18} />
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
                    onDelete={(providerId) => {
                      void handleDelete(providerId);
                    }}
                    onCheckHealth={(providerId) => {
                      void handleCheckHealth(providerId);
                    }}
                    onResetCircuitBreaker={(providerType) => {
                      void handleResetCircuitBreaker(providerType);
                    }}
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
                      <SortableTh
                        field="name"
                        sortField={sortField}
                        sortOrder={sortOrder}
                        onSort={handleSort}
                      >
                        {t('tenant.providers.columns.provider')}
                      </SortableTh>
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
                      <SortableTh
                        field="health"
                        sortField={sortField}
                        sortOrder={sortOrder}
                        onSort={handleSort}
                      >
                        {t('common.stats.healthStatus')}
                      </SortableTh>
                      <SortableTh
                        field="responseTime"
                        sortField={sortField}
                        sortOrder={sortOrder}
                        onSort={handleSort}
                      >
                        {t('tenant.providers.columns.responseTime')}
                      </SortableTh>
                      <th className="relative px-6 py-3" scope="col">
                        <span className="sr-only">{t('tenant.providers.columns.actions')}</span>
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
                              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
                                <Bot size={20} className="text-primary" />
                              </div>
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-slate-900 dark:text-white">
                                  {provider.name}
                                </span>
                                {provider.is_default && (
                                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-primary/10 text-primary border border-primary/20">
                                    <Star size={10} fill="currentColor" />
                                    <span className="ml-0.5">
                                      {t('tenant.providers.defaultBadge')}
                                    </span>
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
                                provider.health_status === 'healthy' ||
                                provider.health_status === 'configuration_valid'
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
                                  provider.health_status === 'healthy' ||
                                  provider.health_status === 'configuration_valid'
                                    ? 'bg-emerald-500'
                                    : provider.health_status === 'degraded'
                                      ? 'bg-amber-500'
                                      : provider.health_status === 'unhealthy'
                                        ? 'bg-red-500'
                                        : 'bg-slate-400'
                                }`}
                              />
                              {provider.health_status === 'configuration_valid'
                                ? t('common.status.configurationValid', {
                                    defaultValue: 'Configuration validated',
                                  })
                                : provider.health_status
                                  ? t(`common.status.${provider.health_status}`, {
                                      defaultValue: provider.health_status,
                                    })
                                  : t('common.status.unknown')}
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm tabular-nums text-slate-600 dark:text-slate-400">
                          {provider.response_time_ms
                            ? `${String(provider.response_time_ms)}ms`
                            : t('tenant.providers.notAvailable')}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                void handleCheckHealth(provider.id);
                              }}
                              disabled={checkingHealth === provider.id}
                              className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-[color,background-color,border-color,box-shadow,opacity,transform] disabled:opacity-50"
                              title={t('common.actions.checkHealth')}
                              aria-label={t('common.actions.checkHealth')}
                            >
                              {checkingHealth === provider.id ? (
                                <Loader2
                                  size={18}
                                  className="animate-spin motion-reduce:animate-none"
                                />
                              ) : (
                                <Activity size={18} />
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                handleEdit(provider);
                              }}
                              className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                              title={t('common.edit')}
                              aria-label={t('common.edit')}
                            >
                              <Pencil size={18} />
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                void handleDelete(provider.id);
                              }}
                              className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                              title={t('common.delete')}
                              aria-label={t('common.delete')}
                            >
                              <Trash2 size={18} />
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
              className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 flex flex-col items-center text-center hover:shadow-lg transition-[color,background-color,border-color,box-shadow,opacity,transform]"
            >
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-lg bg-slate-50 text-4xl dark:bg-slate-800">
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
                  {t('tenant.providers.marketplace.docs')}
                  <ExternalLink size={14} />
                </a>
                <button
                  type="button"
                  onClick={() => {
                    handleCreate(providerMeta.value);
                  }}
                  className="px-4 py-2 bg-primary hover:bg-primary-dark text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
                >
                  <Plus size={16} />
                  {t('tenant.providers.marketplace.connect')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'assignments' &&
        (tenantId ? (
          <ModelAssignment tenantId={tenantId} providers={providers} />
        ) : (
          <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
            {t('common.noTenant')}
          </div>
        ))}

      {/* Modals */}
      <ProviderConfigModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        provider={editingProvider}
        initialProviderType={selectedProviderType}
      />

      {viewingStats && (
        <ProviderUsageStats
          provider={viewingStats}
          onClose={() => {
            setViewingStats(null);
          }}
        />
      )}

      {assigningProvider && tenantId && (
        <AssignProviderModal
          isOpen={!!assigningProvider}
          onClose={() => {
            setAssigningProvider(null);
          }}
          onSuccess={() => {
            setAssigningProvider(null);
            void loadProviders();
          }}
          provider={assigningProvider}
          tenantId={tenantId}
        />
      )}
    </div>
  );
};
