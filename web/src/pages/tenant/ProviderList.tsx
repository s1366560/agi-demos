import React, { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { providerAPI } from '../../services/api'
import { ProviderConfig, ProviderType, SystemResilienceStatus } from '../../types/memory'
import { ProviderCard, ProviderHealthPanel, ProviderConfigModal } from '@/components/provider'

const PROVIDER_TYPE_LABELS: Record<ProviderType, string> = {
    openai: 'OpenAI',
    qwen: 'Dashscope',
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
}

type ViewMode = 'cards' | 'table'

export const ProviderList: React.FC = () => {
    const { t } = useTranslation()
    const [providers, setProviders] = useState<ProviderConfig[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [search, setSearch] = useState('')
    const [typeFilter, setTypeFilter] = useState<string>('all')
    const [statusFilter, setStatusFilter] = useState<string>('all')
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingProvider, setEditingProvider] = useState<ProviderConfig | null>(null)
    const [checkingHealth, setCheckingHealth] = useState<string | null>(null)
    const [systemStatus, setSystemStatus] = useState<SystemResilienceStatus | null>(null)
    const [resettingCircuitBreaker, setResettingCircuitBreaker] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<ViewMode>('cards')

    const loadProviders = useCallback(async () => {
        setIsLoading(true)
        setError(null)
        try {
            const params: { provider_type?: string } = {}
            if (typeFilter !== 'all') {
                params.provider_type = typeFilter
            }
            const response = await providerAPI.list(params)
            setProviders(response)
        } catch (err) {
            console.error('Failed to load providers:', err)
            setError(t('common.error'))
        } finally {
            setIsLoading(false)
        }
    }, [typeFilter, t])

    const loadSystemStatus = useCallback(async () => {
        try {
            const status = await providerAPI.getSystemStatus()
            setSystemStatus(status)
        } catch (err) {
            console.error('Failed to load system status:', err)
        }
    }, [])

    useEffect(() => {
        loadProviders()
        loadSystemStatus()
    }, [loadProviders, loadSystemStatus])

    const handleCheckHealth = async (providerId: string) => {
        setCheckingHealth(providerId)
        try {
            await providerAPI.checkHealth(providerId)
            await loadProviders()
        } catch (err) {
            console.error('Health check failed:', err)
        } finally {
            setCheckingHealth(null)
        }
    }

    const handleResetCircuitBreaker = async (providerType: string) => {
        setResettingCircuitBreaker(providerType)
        try {
            await providerAPI.resetCircuitBreaker(providerType)
            await loadProviders()
            await loadSystemStatus()
        } catch (err) {
            console.error('Failed to reset circuit breaker:', err)
            alert(t('common.error'))
        } finally {
            setResettingCircuitBreaker(null)
        }
    }

    const handleDelete = async (providerId: string) => {
        if (!confirm(t('tenant.providers.deleteConfirm'))) return
        try {
            await providerAPI.delete(providerId)
            await loadProviders()
        } catch (err) {
            console.error('Failed to delete provider:', err)
            alert(t('common.error'))
        }
    }

    const handleEdit = (provider: ProviderConfig) => {
        setEditingProvider(provider)
        setIsModalOpen(true)
    }

    const handleCreate = () => {
        setEditingProvider(null)
        setIsModalOpen(true)
    }

    const handleModalClose = () => {
        setIsModalOpen(false)
        setEditingProvider(null)
    }

    const handleModalSuccess = () => {
        handleModalClose()
        loadProviders()
    }

    const filteredProviders = providers.filter(provider => {
        const matchesSearch = provider.name.toLowerCase().includes(search.toLowerCase()) ||
            provider.llm_model.toLowerCase().includes(search.toLowerCase())
        const matchesType = typeFilter === 'all' || provider.provider_type === typeFilter
        const matchesStatus = statusFilter === 'all' ||
            (statusFilter === 'active' && provider.is_active) ||
            (statusFilter === 'inactive' && !provider.is_active) ||
            (statusFilter === 'healthy' && provider.health_status === 'healthy') ||
            (statusFilter === 'unhealthy' && provider.health_status === 'unhealthy')
        return matchesSearch && matchesType && matchesStatus
    })

    return (
        <div className="max-w-full mx-auto w-full flex flex-col gap-6">
            {/* Header Area */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">{t('tenant.providers.title')}</h1>
                    <p className="text-sm text-slate-500 mt-1">{t('tenant.providers.subtitle')}</p>
                </div>
                <button
                    onClick={handleCreate}
                    className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
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
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-center gap-3">
                    <span className="material-symbols-outlined text-red-600">error</span>
                    <span className="text-red-800 dark:text-red-200">{error}</span>
                    <button onClick={loadProviders} className="ml-auto text-red-600 hover:text-red-800 text-sm font-medium">
                        {t('common.actions.retry')}
                    </button>
                </div>
            )}

            {/* Main Content Card */}
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col">
                {/* Filters Toolbar */}
                <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex flex-col sm:flex-row gap-4 justify-between items-center bg-slate-50/50 dark:bg-slate-800/20">
                    <div className="relative w-full sm:w-96">
                        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                            <span className="material-symbols-outlined text-slate-400 text-[20px]">search</span>
                        </div>
                        <input
                            className="block w-full pl-10 pr-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg leading-5 bg-white dark:bg-surface-dark text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary sm:text-sm"
                            placeholder={t('tenant.providers.searchPlaceholder')}
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>
                    <div className="flex items-center gap-3 w-full sm:w-auto">
                        <div className="relative">
                            <select
                                className="appearance-none bg-white dark:bg-surface-dark border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2 pl-3 pr-8 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary cursor-pointer"
                                value={typeFilter}
                                onChange={(e) => setTypeFilter(e.target.value)}
                            >
                                <option value="all">{t('tenant.providers.allTypes')}</option>
                                <option value="openai">OpenAI</option>
                                <option value="anthropic">Anthropic</option>
                                <option value="gemini">Google Gemini</option>
                                <option value="qwen">Qwen</option>
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
                        <div className="relative">
                            <select
                                className="appearance-none bg-white dark:bg-surface-dark border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2 pl-3 pr-8 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary cursor-pointer"
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
                        <div className="flex items-center bg-white dark:bg-surface-dark border border-slate-300 dark:border-slate-600 rounded-lg overflow-hidden">
                            <button
                                onClick={() => setViewMode('cards')}
                                className={`p-2 transition-colors ${viewMode === 'cards' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                                title="Card View"
                            >
                                <span className="material-symbols-outlined text-[18px]">grid_view</span>
                            </button>
                            <button
                                onClick={() => setViewMode('table')}
                                className={`p-2 transition-colors ${viewMode === 'table' ? 'bg-primary text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                                title="Table View"
                            >
                                <span className="material-symbols-outlined text-[18px]">view_list</span>
                            </button>
                        </div>
                    </div>
                </div>

                {/* Content Area */}
                {isLoading ? (
                    <div className="p-8 text-center text-slate-500">
                        <span className="material-symbols-outlined animate-spin mr-2">progress_activity</span>
                        {t('common.loading')}
                    </div>
                ) : filteredProviders.length === 0 ? (
                    <div className="p-8 text-center text-slate-500">
                        <div className="flex flex-col items-center gap-2">
                            <span className="material-symbols-outlined text-4xl text-slate-300">smart_toy</span>
                            <p>{t('tenant.providers.noProviders')}</p>
                            <button
                                onClick={handleCreate}
                                className="text-primary hover:text-primary-dark text-sm font-medium"
                            >
                                {t('tenant.providers.addFirstProvider')}
                            </button>
                        </div>
                    </div>
                ) : viewMode === 'cards' ? (
                    /* Card View */
                    <div className="p-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                        {filteredProviders.map((provider) => (
                            <ProviderCard
                                key={provider.id}
                                provider={provider}
                                onEdit={handleEdit}
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
                            <thead className="bg-slate-50 dark:bg-slate-800">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider" scope="col">Provider</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider" scope="col">{t('common.forms.type')}</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider" scope="col">{t('common.forms.model')}</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider" scope="col">{t('common.forms.status')}</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider" scope="col">{t('common.stats.healthStatus')}</th>
                                    <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider" scope="col">Circuit Breaker</th>
                                    <th className="relative px-6 py-3" scope="col">
                                        <span className="sr-only">Actions</span>
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="bg-surface-light dark:bg-surface-dark divide-y divide-slate-200 dark:divide-slate-700">
                                {filteredProviders.map((provider) => (
                                    <tr key={provider.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center">
                                                <div className="flex-shrink-0 h-10 w-10 bg-primary/10 rounded-lg flex items-center justify-center text-primary">
                                                    <span className="material-symbols-outlined">smart_toy</span>
                                                </div>
                                                <div className="ml-4">
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-sm font-medium text-slate-900 dark:text-white">{provider.name}</span>
                                                        {provider.is_default && (
                                                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300">
                                                                Default
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="text-sm text-slate-500">{provider.api_key_masked}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300">
                                                {PROVIDER_TYPE_LABELS[provider.provider_type] || provider.provider_type}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-white">
                                            {provider.llm_model}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            {provider.is_active ? (
                                                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                                                    <span className="h-1.5 w-1.5 rounded-full bg-green-500"></span> {t('common.status.active')}
                                                </span>
                                            ) : (
                                                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400">
                                                    <span className="h-1.5 w-1.5 rounded-full bg-slate-400"></span> {t('common.status.inactive')}
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center gap-2">
                                                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                                                    provider.health_status === 'healthy' 
                                                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
                                                        : provider.health_status === 'degraded'
                                                        ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300'
                                                        : provider.health_status === 'unhealthy'
                                                        ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
                                                        : 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300'
                                                }`}>
                                                    <span className={`h-1.5 w-1.5 rounded-full ${
                                                        provider.health_status === 'healthy' ? 'bg-green-500'
                                                        : provider.health_status === 'degraded' ? 'bg-yellow-500'
                                                        : provider.health_status === 'unhealthy' ? 'bg-red-500'
                                                        : 'bg-slate-400'
                                                    }`}></span>
                                                    {provider.health_status || t('common.status.unknown')}
                                                </span>
                                                {provider.response_time_ms && (
                                                    <span className="text-xs text-slate-400">{provider.response_time_ms}ms</span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center gap-2">
                                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                                                    provider.resilience?.circuit_breaker_state === 'closed'
                                                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
                                                        : provider.resilience?.circuit_breaker_state === 'open'
                                                        ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
                                                        : provider.resilience?.circuit_breaker_state === 'half_open'
                                                        ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300'
                                                        : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400'
                                                }`}>
                                                    <span className={`h-1.5 w-1.5 rounded-full ${
                                                        provider.resilience?.circuit_breaker_state === 'closed' ? 'bg-green-500'
                                                        : provider.resilience?.circuit_breaker_state === 'open' ? 'bg-red-500'
                                                        : provider.resilience?.circuit_breaker_state === 'half_open' ? 'bg-yellow-500'
                                                        : 'bg-slate-400'
                                                    }`}></span>
                                                    {provider.resilience?.circuit_breaker_state || 'Unknown'}
                                                </span>
                                                {provider.resilience && provider.resilience.circuit_breaker_state !== 'closed' && (
                                                    <button
                                                        onClick={() => handleResetCircuitBreaker(provider.provider_type)}
                                                        disabled={resettingCircuitBreaker === provider.provider_type}
                                                        className="p-1 text-slate-400 hover:text-primary transition-colors disabled:opacity-50"
                                                        title="Reset Circuit Breaker"
                                                    >
                                                        <span className={`material-symbols-outlined text-[14px] ${resettingCircuitBreaker === provider.provider_type ? 'animate-spin' : ''}`}>
                                                            {resettingCircuitBreaker === provider.provider_type ? 'progress_activity' : 'refresh'}
                                                        </span>
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <div className="flex items-center justify-end gap-2">
                                                <button
                                                    onClick={() => handleCheckHealth(provider.id)}
                                                    disabled={checkingHealth === provider.id}
                                                    className="p-1.5 text-slate-400 hover:text-primary transition-colors disabled:opacity-50"
                                                    title={t('common.actions.checkHealth')}
                                                >
                                                    <span className={`material-symbols-outlined text-[18px] ${checkingHealth === provider.id ? 'animate-spin' : ''}`}>
                                                        {checkingHealth === provider.id ? 'progress_activity' : 'monitor_heart'}
                                                    </span>
                                                </button>
                                                <button
                                                    onClick={() => handleEdit(provider)}
                                                    className="p-1.5 text-slate-400 hover:text-primary transition-colors"
                                                    title={t('common.edit')}
                                                >
                                                    <span className="material-symbols-outlined text-[18px]">edit</span>
                                                </button>
                                                <button
                                                    onClick={() => handleDelete(provider.id)}
                                                    className="p-1.5 text-slate-400 hover:text-red-600 transition-colors"
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
                
                {/* Footer */}
                <div className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between sm:px-6">
                    <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                        <div>
                            <p className="text-sm text-slate-700 dark:text-slate-400">
                                {t('tenant.users.showingResults', { start: filteredProviders.length > 0 ? 1 : 0, end: filteredProviders.length, total: providers.length })}
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Provider Config Modal - New Step-by-Step Wizard */}
            <ProviderConfigModal
                isOpen={isModalOpen}
                onClose={handleModalClose}
                onSuccess={handleModalSuccess}
                provider={editingProvider}
            />
        </div>
    )
}
