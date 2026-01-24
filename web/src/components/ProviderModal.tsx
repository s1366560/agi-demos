import React, { useEffect, useState } from 'react'
import { providerAPI } from '../services/api'
import { ProviderConfig, ProviderCreate, ProviderType, ProviderUpdate } from '../types/memory'

interface ProviderModalProps {
    isOpen: boolean
    onClose: () => void
    onSuccess: () => void
    provider?: ProviderConfig | null
}

const PROVIDER_TYPES: { value: ProviderType; label: string }[] = [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'gemini', label: 'Google Gemini' },
    { value: 'qwen', label: 'Alibaba Dashscope' },
    { value: 'groq', label: 'Groq' },
    { value: 'azure_openai', label: 'Azure OpenAI' },
    { value: 'cohere', label: 'Cohere' },
    { value: 'mistral', label: 'Mistral' },
    { value: 'bedrock', label: 'AWS Bedrock' },
    { value: 'vertex', label: 'Google Vertex AI' },
    { value: 'deepseek', label: 'Deepseek' },
    { value: 'zai', label: 'ZhipuAI (智普AI)' },
]

const DEFAULT_MODELS: Record<ProviderType, { llm: string; small?: string; embedding?: string; reranker?: string }> = {
    openai: { llm: 'gpt-4o', small: 'gpt-4o-mini', embedding: 'text-embedding-3-small' },
    anthropic: { llm: 'claude-sonnet-4-20250514', small: 'claude-3-5-haiku-20241022' },
    gemini: { llm: 'gemini-1.5-pro', small: 'gemini-1.5-flash', embedding: 'text-embedding-004' },
    qwen: { llm: 'qwen-max', small: 'qwen-turbo', embedding: 'text-embedding-v3', reranker: 'qwen3-rerank' },
    groq: { llm: 'llama-3.3-70b-versatile', small: 'llama-3.1-8b-instant' },
    azure_openai: { llm: 'gpt-4o', small: 'gpt-4o-mini', embedding: 'text-embedding-3-small' },
    cohere: { llm: 'command-r-plus', small: 'command-r', embedding: 'embed-english-v3.0', reranker: 'rerank-english-v3.0' },
    mistral: { llm: 'mistral-large-latest', small: 'mistral-small-latest', embedding: 'mistral-embed' },
    bedrock: { llm: 'anthropic.claude-3-sonnet-20240229-v1:0' },
    vertex: { llm: 'gemini-1.5-pro', small: 'gemini-1.5-flash' },
    deepseek: { llm: 'deepseek-chat', small: 'deepseek-coder' },
    zai: { llm: 'glm-4-plus', small: 'glm-4-flash', embedding: 'embedding-3' },
}

export const ProviderModal: React.FC<ProviderModalProps> = ({
    isOpen,
    onClose,
    onSuccess,
    provider,
}) => {
    const isEditing = !!provider
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [activeTab, setActiveTab] = useState<'basic' | 'models' | 'advanced'>('basic')

    const [formData, setFormData] = useState<{
        name: string
        provider_type: ProviderType
        api_key: string
        base_url: string
        llm_model: string
        llm_small_model: string
        embedding_model: string
        reranker_model: string
        is_active: boolean
        is_default: boolean
    }>({
        name: '',
        provider_type: 'openai',
        api_key: '',
        base_url: '',
        llm_model: 'gpt-4o',
        llm_small_model: 'gpt-4o-mini',
        embedding_model: 'text-embedding-3-small',
        reranker_model: '',
        is_active: true,
        is_default: false,
    })

    useEffect(() => {
        if (provider) {
            setFormData({
                name: provider.name,
                provider_type: provider.provider_type,
                api_key: '', // Don't pre-fill API key for security
                base_url: provider.base_url || '',
                llm_model: provider.llm_model,
                llm_small_model: provider.llm_small_model || '',
                embedding_model: provider.embedding_model || '',
                reranker_model: provider.reranker_model || '',
                is_active: provider.is_active,
                is_default: provider.is_default,
            })
        } else {
            // Reset form for new provider
            setFormData({
                name: '',
                provider_type: 'openai',
                api_key: '',
                base_url: '',
                llm_model: 'gpt-4o',
                llm_small_model: 'gpt-4o-mini',
                embedding_model: 'text-embedding-3-small',
                reranker_model: '',
                is_active: true,
                is_default: false,
            })
        }
        setActiveTab('basic')
        setError(null)
    }, [provider, isOpen])

    const handleProviderTypeChange = (type: ProviderType) => {
        const defaults = DEFAULT_MODELS[type]
        setFormData(prev => ({
            ...prev,
            provider_type: type,
            llm_model: defaults?.llm || '',
            llm_small_model: defaults?.small || '',
            embedding_model: defaults?.embedding || '',
            reranker_model: defaults?.reranker || '',
        }))
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setIsSubmitting(true)
        setError(null)

        try {
            if (isEditing && provider) {
                const updateData: ProviderUpdate = {
                    name: formData.name,
                    provider_type: formData.provider_type,
                    base_url: formData.base_url || undefined,
                    llm_model: formData.llm_model,
                    llm_small_model: formData.llm_small_model || undefined,
                    embedding_model: formData.embedding_model || undefined,
                    reranker_model: formData.reranker_model || undefined,
                    is_active: formData.is_active,
                    is_default: formData.is_default,
                }
                // Only include API key if it was changed
                if (formData.api_key) {
                    updateData.api_key = formData.api_key
                }
                await providerAPI.update(provider.id, updateData)
            } else {
                const createData: ProviderCreate = {
                    name: formData.name,
                    provider_type: formData.provider_type,
                    api_key: formData.api_key,
                    base_url: formData.base_url || undefined,
                    llm_model: formData.llm_model,
                    llm_small_model: formData.llm_small_model || undefined,
                    embedding_model: formData.embedding_model || undefined,
                    reranker_model: formData.reranker_model || undefined,
                    is_active: formData.is_active,
                    is_default: formData.is_default,
                }
                await providerAPI.create(createData)
            }
            onSuccess()
        } catch (err: any) {
            console.error('Failed to save provider:', err)
            setError(err.response?.data?.detail || 'Failed to save provider')
        } finally {
            setIsSubmitting(false)
        }
    }

    if (!isOpen) return null

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
                {/* Header */}
                <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-primary/10 rounded-lg text-primary">
                            <span className="material-symbols-outlined">smart_toy</span>
                        </div>
                        <div>
                            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                                {isEditing ? 'Edit Provider' : 'Add LLM Provider'}
                            </h2>
                            <p className="text-sm text-slate-500">
                                {isEditing ? 'Update provider configuration' : 'Configure a new AI model provider'}
                            </p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
                    >
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>

                {/* Tabs */}
                <div className="px-6 border-b border-slate-200 dark:border-slate-700">
                    <nav className="flex gap-6">
                        {[
                            { id: 'basic', label: 'Basic Info', icon: 'info' },
                            { id: 'models', label: 'Models', icon: 'psychology' },
                            { id: 'advanced', label: 'Advanced', icon: 'settings' },
                        ].map((tab) => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id as typeof activeTab)}
                                className={`flex items-center gap-2 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === tab.id
                                    ? 'border-primary text-primary'
                                    : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                                    }`}
                            >
                                <span className="material-symbols-outlined text-[18px]">{tab.icon}</span>
                                {tab.label}
                            </button>
                        ))}
                    </nav>
                </div>

                {/* Content */}
                <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto">
                    <div className="p-6 space-y-6">
                        {error && (
                            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-center gap-3">
                                <span className="material-symbols-outlined text-red-600">error</span>
                                <span className="text-red-800 dark:text-red-200 text-sm">{error}</span>
                            </div>
                        )}

                        {/* Basic Tab */}
                        {activeTab === 'basic' && (
                            <div className="space-y-4">
                                <div>
                                    <label htmlFor="provider-name" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Provider Name *
                                    </label>
                                    <input
                                        id="provider-name"
                                        type="text"
                                        required
                                        value={formData.name}
                                        onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                                        placeholder="e.g., Production OpenAI"
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                </div>

                                <div>
                                    <label htmlFor="provider-type" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Provider Type *
                                    </label>
                                    <select
                                        id="provider-type"
                                        required
                                        value={formData.provider_type}
                                        onChange={(e) => handleProviderTypeChange(e.target.value as ProviderType)}
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    >
                                        {PROVIDER_TYPES.map((type) => (
                                            <option key={type.value} value={type.value}>
                                                {type.label}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                <div>
                                    <label htmlFor="api-key" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        API Key {!isEditing && '*'}
                                    </label>
                                    <input
                                        id="api-key"
                                        type="password"
                                        required={!isEditing}
                                        value={formData.api_key}
                                        onChange={(e) => setFormData(prev => ({ ...prev, api_key: e.target.value }))}
                                        placeholder={isEditing ? 'Leave empty to keep current key' : 'Enter your API key'}
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                    <p className="mt-1 text-xs text-slate-500">
                                        Your API key is encrypted and stored securely.
                                    </p>
                                </div>

                                <div className="flex items-center gap-6">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={formData.is_active}
                                            onChange={(e) => setFormData(prev => ({ ...prev, is_active: e.target.checked }))}
                                            className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                                        />
                                        <span className="text-sm text-slate-700 dark:text-slate-300">Active</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={formData.is_default}
                                            onChange={(e) => setFormData(prev => ({ ...prev, is_default: e.target.checked }))}
                                            className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                                        />
                                        <span className="text-sm text-slate-700 dark:text-slate-300">Set as default provider</span>
                                    </label>
                                </div>
                            </div>
                        )}

                        {/* Models Tab */}
                        {activeTab === 'models' && (
                            <div className="space-y-4">
                                <div>
                                    <label htmlFor="llm-model" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Primary LLM Model *
                                    </label>
                                    <input
                                        id="llm-model"
                                        type="text"
                                        required
                                        value={formData.llm_model}
                                        onChange={(e) => setFormData(prev => ({ ...prev, llm_model: e.target.value }))}
                                        placeholder="e.g., gpt-4o"
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                    <p className="mt-1 text-xs text-slate-500">
                                        Main model for complex tasks and entity extraction.
                                    </p>
                                </div>

                                <div>
                                    <label htmlFor="llm-small-model" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Small/Fast Model
                                    </label>
                                    <input
                                        id="llm-small-model"
                                        type="text"
                                        value={formData.llm_small_model}
                                        onChange={(e) => setFormData(prev => ({ ...prev, llm_small_model: e.target.value }))}
                                        placeholder="e.g., gpt-4o-mini"
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                    <p className="mt-1 text-xs text-slate-500">
                                        Faster model for simpler tasks and cost optimization.
                                    </p>
                                </div>

                                <div>
                                    <label htmlFor="embedding-model" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Embedding Model
                                    </label>
                                    <input
                                        id="embedding-model"
                                        type="text"
                                        value={formData.embedding_model}
                                        onChange={(e) => setFormData(prev => ({ ...prev, embedding_model: e.target.value }))}
                                        placeholder="e.g., text-embedding-3-small"
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                    <p className="mt-1 text-xs text-slate-500">
                                        Model for generating vector embeddings.
                                    </p>
                                </div>

                                <div>
                                    <label htmlFor="reranker-model" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Reranker Model
                                    </label>
                                    <input
                                        id="reranker-model"
                                        type="text"
                                        value={formData.reranker_model}
                                        onChange={(e) => setFormData(prev => ({ ...prev, reranker_model: e.target.value }))}
                                        placeholder="e.g., gpt-4o-mini (optional)"
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                    <p className="mt-1 text-xs text-slate-500">
                                        Model for reranking search results. Uses LLM if not specified.
                                    </p>
                                </div>
                            </div>
                        )}

                        {/* Advanced Tab */}
                        {activeTab === 'advanced' && (
                            <div className="space-y-4">
                                <div>
                                    <label htmlFor="base-url" className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                                        Custom Base URL
                                    </label>
                                    <input
                                        id="base-url"
                                        type="url"
                                        value={formData.base_url}
                                        onChange={(e) => setFormData(prev => ({ ...prev, base_url: e.target.value }))}
                                        placeholder="https://api.example.com/v1"
                                        className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                    />
                                    <p className="mt-1 text-xs text-slate-500">
                                        Override the default API endpoint. Useful for proxies or self-hosted models.
                                    </p>
                                </div>

                                <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4">
                                    <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">Provider Information</h4>
                                    <div className="space-y-2 text-sm text-slate-500">
                                        <p>
                                            <span className="font-medium">Type:</span> {PROVIDER_TYPES.find(t => t.value === formData.provider_type)?.label}
                                        </p>
                                        {isEditing && provider && (
                                            <>
                                                <p>
                                                    <span className="font-medium">Created:</span> {new Date(provider.created_at).toLocaleString()}
                                                </p>
                                                <p>
                                                    <span className="font-medium">Updated:</span> {new Date(provider.updated_at).toLocaleString()}
                                                </p>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Footer */}
                    <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-end gap-3">
                        <button
                            type="button"
                            onClick={onClose}
                            disabled={isSubmitting}
                            className="px-5 py-2.5 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={isSubmitting}
                            className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary hover:bg-primary-dark text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                        >
                            {isSubmitting ? (
                                <>
                                    <span className="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>
                                    Saving...
                                </>
                            ) : (
                                <>
                                    <span className="material-symbols-outlined text-[18px]">save</span>
                                    {isEditing ? 'Update Provider' : 'Create Provider'}
                                </>
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}
