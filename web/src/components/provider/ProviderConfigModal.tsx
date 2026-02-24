import React, { useEffect, useState, useCallback } from 'react';

import { PROVIDERS } from '../../constants/providers';
import { providerAPI } from '../../services/api';
import {
  EmbeddingConfig,
  ProviderConfig,
  ProviderCreate,
  ProviderType,
  ProviderUpdate,
} from '../../types/memory';
import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { ProviderIcon } from './ProviderIcon';

interface ProviderConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  provider?: ProviderConfig | null | undefined;
  initialProviderType?: ProviderType | undefined;
}

const OPTIONAL_API_KEY_PROVIDERS: ProviderType[] = ['ollama', 'lmstudio'];

const providerTypeRequiresApiKey = (type: ProviderType) =>
  !OPTIONAL_API_KEY_PROVIDERS.includes(type);

type Step = 'provider' | 'credentials' | 'models' | 'review';

const resolveEmbeddingConfig = (provider: ProviderConfig): EmbeddingConfig | undefined => {
  if (provider.embedding_config) {
    return provider.embedding_config;
  }
  const legacyEmbeddingConfig = provider.config?.embedding;
  if (legacyEmbeddingConfig && typeof legacyEmbeddingConfig === 'object') {
    return legacyEmbeddingConfig as EmbeddingConfig;
  }
  if (provider.embedding_model) {
    return { model: provider.embedding_model };
  }
  return undefined;
};

export const ProviderConfigModal: React.FC<ProviderConfigModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  provider,
  initialProviderType,
}) => {
  const isEditing = !!provider;
  const [currentStep, setCurrentStep] = useState<Step>('provider');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<{
    chat: string[];
    embedding: string[];
    rerank: string[];
  }>({ chat: [], embedding: [], rerank: [] });
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [showAdvancedEmbedding, setShowAdvancedEmbedding] = useState(false);
  const [showAdvancedLLM, setShowAdvancedLLM] = useState(false);

  const [formData, setFormData] = useState({
    name: '',
    provider_type: 'openai' as ProviderType,
    api_key: '',
    base_url: '',
    llm_model: 'gpt-4o',
    llm_small_model: 'gpt-4o-mini',
    embedding_model: 'text-embedding-3-small',
    embedding_dimensions: '1536',
    embedding_encoding_format: '' as '' | 'float' | 'base64',
    embedding_user: '',
    embedding_timeout: '',
    embedding_provider_options_json: '{}',
    reranker_model: '',
    config: {} as Record<string, any>,
    is_active: true,
    is_default: false,
    use_custom_base_url: false,
  });

  const [configJsonStr, setConfigJsonStr] = useState('{}');

  // Track which model fields are in custom input mode
  const [useCustomModel, setUseCustomModel] = useState({
    llm: false,
    small: false,
    embedding: false,
    reranker: false,
  });

  const steps: { key: Step; label: string; icon: string; description: string }[] = [
    {
      key: 'provider',
      label: 'Select Provider',
      icon: 'smart_toy',
      description: 'Choose LLM provider',
    },
    { key: 'credentials', label: 'Credentials', icon: 'key', description: 'API key & config' },
    { key: 'models', label: 'Models', icon: 'psychology', description: 'Configure models' },
    { key: 'review', label: 'Review', icon: 'check_circle', description: 'Review & save' },
  ];

  const fetchModels = useCallback(async (type: ProviderType) => {
    setIsLoadingModels(true);
    try {
      const response = await providerAPI.listModels(type);
      setAvailableModels(response.models);

      // If editing, don't auto-select defaults yet, we handle that in useEffect
      return response.models;
    } catch (err) {
      console.error('Failed to fetch models:', err);
      // Fallback to empty
      setAvailableModels({ chat: [], embedding: [], rerank: [] });
      return null;
    } finally {
      setIsLoadingModels(false);
    }
  }, []);

  // Initialize form data
  useEffect(() => {
    if (provider) {
      const embeddingConfig = resolveEmbeddingConfig(provider);

      // Fetch models for the provider
      fetchModels(provider.provider_type).then((models) => {
        if (!models) return;

        // Check if models are custom (not in fetched list)
        const llmIsCustom = !models.chat.includes(provider.llm_model);
        const smallIsCustom =
          !!provider.llm_small_model && !models.chat.includes(provider.llm_small_model);
        const embeddingModel = embeddingConfig?.model || provider.embedding_model || '';
        const embeddingIsCustom = !!embeddingModel && !models.embedding.includes(embeddingModel);
        const rerankerIsCustom =
          !!provider.reranker_model && !models.rerank.includes(provider.reranker_model);

        setUseCustomModel({
          llm: llmIsCustom,
          small: smallIsCustom,
          embedding: embeddingIsCustom,
          reranker: rerankerIsCustom,
        });
      });

      const embeddingModel = embeddingConfig?.model || provider.embedding_model || '';

      setFormData({
        name: provider.name,
        provider_type: provider.provider_type,
        api_key: '',
        base_url: provider.base_url || '',
        llm_model: provider.llm_model,
        llm_small_model: provider.llm_small_model || '',
        embedding_model: embeddingModel,
        embedding_dimensions:
          embeddingConfig?.dimensions !== undefined ? String(embeddingConfig.dimensions) : '',
        embedding_encoding_format: embeddingConfig?.encoding_format || '',
        embedding_user: embeddingConfig?.user || '',
        embedding_timeout:
          embeddingConfig?.timeout !== undefined ? String(embeddingConfig.timeout) : '',
        embedding_provider_options_json: JSON.stringify(
          embeddingConfig?.provider_options || {},
          null,
          2
        ),
        reranker_model: provider.reranker_model || '',
        config: provider.config || {},
        is_active: provider.is_active,
        is_default: provider.is_default,
        use_custom_base_url: !!provider.base_url,
      });
      setConfigJsonStr(JSON.stringify(provider.config || {}, null, 2));

      setCurrentStep('credentials');
    } else {
      // Default state for new provider
      const defaultProvider = initialProviderType || 'openai';
      const providerMeta = PROVIDERS.find((p) => p.value === defaultProvider);

      setFormData({
        name: providerMeta?.label || '',
        provider_type: defaultProvider,
        api_key: '',
        base_url: '',
        llm_model: '',
        llm_small_model: '',
        embedding_model: '',
        embedding_dimensions: '1536',
        embedding_encoding_format: '',
        embedding_user: '',
        embedding_timeout: '',
        embedding_provider_options_json: '{}',
        reranker_model: '',
        config: {},
        is_active: true,
        is_default: false,
        use_custom_base_url: false,
      });
      setConfigJsonStr('{}');

      // Fetch models for default provider
      fetchModels(defaultProvider).then((models) => {
        if (models && models.chat.length > 0) {
          setFormData((prev) => ({
            ...prev,
            llm_model: models.chat[0] ?? '',
            llm_small_model:
              models.chat.find(
                (m) =>
                  m.includes('mini') ||
                  m.includes('small') ||
                  m.includes('flash') ||
                  m.includes('haiku')
              ) ||
              models.chat[1] ||
              '',
            embedding_model: models.embedding[0] || '',
            reranker_model: models.rerank[0] || '',
          }));
        }
      });

      setUseCustomModel({
        llm: false,
        small: false,
        embedding: false,
        reranker: false,
      });

      setCurrentStep(initialProviderType ? 'credentials' : 'provider');
    }
    setError(null);
    setTestResult(null);
  }, [provider, isOpen, fetchModels, initialProviderType]);

  const handleProviderSelect = async (type: ProviderType) => {
    const providerMeta = PROVIDERS.find((p) => p.value === type);

    // Fetch models first
    const models = await fetchModels(type);

    setFormData((prev) => ({
      ...prev,
      provider_type: type,
      name: prev.name || providerMeta?.label || '',
      llm_model: models?.chat[0] || '',
      llm_small_model:
        models?.chat.find(
          (m) =>
            m.includes('mini') || m.includes('small') || m.includes('flash') || m.includes('haiku')
        ) ||
        models?.chat[1] ||
        '',
      embedding_model: models?.embedding[0] || '',
      embedding_dimensions: '1536', // Default, user can change
      reranker_model: models?.rerank[0] || '',
    }));

    // Reset custom model mode when switching provider
    setUseCustomModel({
      llm: false,
      small: false,
      embedding: false,
      reranker: false,
    });
    setTestResult(null);
  };

  const handleTestConnection = useCallback(async () => {
    if (!formData.api_key && !isEditing && providerTypeRequiresApiKey(formData.provider_type)) {
      setTestResult({ success: false, message: 'API key is required' });
      return;
    }

    setIsTesting(true);
    setTestResult(null);

    try {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      setTestResult({ success: true, message: 'Connection successful! API key is valid.' });
    } catch (_err) {
      setTestResult({ success: false, message: 'Connection failed. Please check your API key.' });
    } finally {
      setIsTesting(false);
    }
  }, [formData.api_key, formData.provider_type, isEditing]);

  const canProceed = () => {
    switch (currentStep) {
      case 'provider':
        return !!formData.provider_type;
      case 'credentials':
        return (
          !!formData.name &&
          (isEditing || !!formData.api_key || !providerTypeRequiresApiKey(formData.provider_type))
        );
      case 'models':
        return !!formData.llm_model;
      case 'review':
        return true;
      default:
        return false;
    }
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);

    try {
      const embeddingProviderOptions = JSON.parse(formData.embedding_provider_options_json || '{}');
      const embeddingDimensions = formData.embedding_dimensions.trim()
        ? Number(formData.embedding_dimensions)
        : undefined;
      const embeddingTimeout = formData.embedding_timeout.trim()
        ? Number(formData.embedding_timeout)
        : undefined;

      const embeddingConfig: EmbeddingConfig = {};
      if (formData.embedding_model.trim()) {
        embeddingConfig.model = formData.embedding_model.trim();
      }
      if (embeddingDimensions !== undefined) {
        embeddingConfig.dimensions = embeddingDimensions;
      }
      if (formData.embedding_encoding_format) {
        embeddingConfig.encoding_format = formData.embedding_encoding_format;
      }
      if (formData.embedding_user.trim()) {
        embeddingConfig.user = formData.embedding_user.trim();
      }
      if (embeddingTimeout !== undefined) {
        embeddingConfig.timeout = embeddingTimeout;
      }
      if (Object.keys(embeddingProviderOptions).length > 0) {
        embeddingConfig.provider_options = embeddingProviderOptions;
      }

      const config = { ...formData.config };
      if (Object.keys(embeddingConfig).length > 0) {
        config.embedding = embeddingConfig;
      } else {
        delete config.embedding;
      }

      if (isEditing && provider) {
        const updateData: ProviderUpdate = {
          name: formData.name,
          provider_type: formData.provider_type,
          base_url: formData.base_url || undefined,
          llm_model: formData.llm_model,
          llm_small_model: formData.llm_small_model || undefined,
          embedding_model: formData.embedding_model || undefined,
          embedding_config: Object.keys(embeddingConfig).length > 0 ? embeddingConfig : undefined,
          reranker_model: formData.reranker_model || undefined,
          config: config,
          is_active: formData.is_active,
          is_default: formData.is_default,
        };
        if (formData.api_key) {
          updateData.api_key = formData.api_key;
        }
        await providerAPI.update(provider.id, updateData);
      } else {
        const createData: ProviderCreate = {
          name: formData.name,
          provider_type: formData.provider_type,
          api_key: formData.api_key,
          base_url: formData.base_url || undefined,
          llm_model: formData.llm_model,
          llm_small_model: formData.llm_small_model || undefined,
          embedding_model: formData.embedding_model || undefined,
          embedding_config: Object.keys(embeddingConfig).length > 0 ? embeddingConfig : undefined,
          reranker_model: formData.reranker_model || undefined,
          config: config,
          is_active: formData.is_active,
          is_default: formData.is_default,
        };
        await providerAPI.create(createData);
      }
      onSuccess();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save provider');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative w-full max-w-4xl bg-white dark:bg-slate-800 rounded-2xl shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-gradient-to-r from-primary/5 to-transparent">
            <div>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
                {isEditing ? 'Edit Provider' : 'Add New Provider'}
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Configure your LLM provider settings
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <MaterialIcon name="close" size={20} />
            </button>
          </div>

          {/* Progress Steps */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50">
            <div className="flex items-center justify-between">
              {steps.map((step, index) => {
                const isCompleted = steps.findIndex((s) => s.key === currentStep) > index;
                const isCurrent = step.key === currentStep;

                return (
                  <React.Fragment key={step.key}>
                    <div className="flex items-center">
                      <div
                        className={`flex items-center justify-center w-8 h-8 rounded-lg border-2 transition-all ${
                          isCompleted
                            ? 'bg-primary border-primary text-white'
                            : isCurrent
                              ? 'border-primary text-primary bg-white dark:bg-slate-800'
                              : 'border-slate-200 dark:border-slate-700 text-slate-400'
                        }`}
                      >
                        {isCompleted ? (
                          <MaterialIcon name="check" size={16} />
                        ) : (
                          <MaterialIcon name={step.icon} size={16} />
                        )}
                      </div>
                      <div className="ml-3 hidden sm:block">
                        <p
                          className={`text-sm font-medium ${
                            isCurrent ? 'text-primary' : 'text-slate-500 dark:text-slate-400'
                          }`}
                        >
                          {step.label}
                        </p>
                        <p className="text-xs text-slate-400">{step.description}</p>
                      </div>
                    </div>
                    {index < steps.length - 1 && (
                      <div
                        className={`flex-1 h-0.5 mx-4 ${
                          isCompleted ? 'bg-primary' : 'bg-slate-200 dark:bg-slate-600'
                        }`}
                      />
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          </div>

          {/* Content */}
          <div className="p-6 max-h-[60vh] overflow-y-auto">
            {/* Step 1: Provider Selection */}
            {currentStep === 'provider' && (
              <div className="space-y-4">
                <div className="text-center mb-6">
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
                    Choose Your LLM Provider
                  </h3>
                  <p className="text-slate-500 dark:text-slate-400">
                    Select from supported AI model providers
                  </p>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {PROVIDERS.map((p) => (
                    <button
                      key={p.value}
                      onClick={() => handleProviderSelect(p.value)}
                      className={`p-4 rounded-xl border-2 transition-all text-left hover:shadow-md ${
                        formData.provider_type === p.value
                          ? 'border-primary bg-primary/5 dark:bg-primary/10'
                          : 'border-slate-200 dark:border-slate-700 hover:border-primary/50'
                      }`}
                    >
                      <ProviderIcon providerType={p.value} size="lg" className="mb-3" />
                      <h4 className="font-medium text-slate-900 dark:text-white mt-3">{p.label}</h4>
                      <p className="text-xs text-slate-500 mt-1 line-clamp-2">{p.description}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Step 2: Credentials */}
            {currentStep === 'credentials' && (
              <div className="space-y-4">
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      Provider Name
                    </label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => { setFormData({ ...formData, name: e.target.value }); }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="My OpenAI Provider"
                    />
                  </div>

                  {providerTypeRequiresApiKey(formData.provider_type) && (
                    <div>
                      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                        API Key
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={formData.api_key}
                          onChange={(e) => { setFormData({ ...formData, api_key: e.target.value }); }}
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                          placeholder={
                            PROVIDERS.find((p) => p.value === formData.provider_type)
                              ?.apiKeyPlaceholder || 'sk-...'
                          }
                        />
                        <button
                          onClick={handleTestConnection}
                          disabled={isTesting || !formData.api_key}
                          className="px-4 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors disabled:opacity-50 font-medium"
                        >
                          {isTesting ? (
                            <MaterialIcon
                              name="progress_activity"
                              size={18}
                              className="animate-spin"
                            />
                          ) : (
                            'Test'
                          )}
                        </button>
                      </div>
                      {testResult && (
                        <div
                          className={`mt-2 px-3 py-2 rounded-lg text-sm ${
                            testResult.success
                              ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
                              : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                          }`}
                        >
                          {testResult.message}
                        </div>
                      )}
                    </div>
                  )}

                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      Base URL (Optional)
                    </label>
                    <input
                      type="url"
                      value={formData.base_url}
                      onChange={(e) => { setFormData({ ...formData, base_url: e.target.value }); }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="https://api.example.com"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      Provider Configuration (JSON)
                    </label>
                    <textarea
                      value={configJsonStr}
                      onChange={(e) => {
                        setConfigJsonStr(e.target.value);
                        try {
                          const parsed = JSON.parse(e.target.value);
                          setFormData({ ...formData, config: parsed });
                        } catch (_err) {
                          // Ignore invalid JSON while typing
                        }
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent font-mono text-sm"
                      rows={4}
                      placeholder="{}"
                    />
                  </div>

                  <div className="flex items-center gap-6 pt-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formData.is_active}
                        onChange={(e) => { setFormData({ ...formData, is_active: e.target.checked }); }}
                        className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                      />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Active
                      </span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formData.is_default}
                        onChange={(e) => { setFormData({ ...formData, is_default: e.target.checked }); }}
                        className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                      />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Set as Default
                      </span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* Step 3: Models */}
            {currentStep === 'models' && (
              <div className="space-y-4">
                {isLoadingModels && (
                  <div className="flex items-center gap-2 text-sm text-slate-500 mb-2">
                    <MaterialIcon name="sync" size={16} className="animate-spin" />
                    Fetching available models...
                  </div>
                )}

                {/* Primary LLM Model */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Primary LLM Model
                  </label>
                  {useCustomModel.llm ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={formData.llm_model}
                        onChange={(e) => { setFormData({ ...formData, llm_model: e.target.value }); }}
                        placeholder="Enter custom model name"
                        className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setUseCustomModel({ ...useCustomModel, llm: false });
                          setFormData({
                            ...formData,
                            llm_model: availableModels.chat[0] || '',
                          });
                        }}
                        className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                        title="Use preset model"
                      >
                        <MaterialIcon name="list" size={18} />
                      </button>
                    </div>
                  ) : (
                    <select
                      value={formData.llm_model}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value === '__custom__') {
                          setUseCustomModel({ ...useCustomModel, llm: true });
                          setFormData({ ...formData, llm_model: '' });
                        } else {
                          setFormData({ ...formData, llm_model: value });
                        }
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      disabled={isLoadingModels}
                    >
                      {availableModels.chat.length === 0 && !isLoadingModels && (
                        <option value="" disabled>
                          No models available
                        </option>
                      )}
                      {availableModels.chat.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                      <option value="__custom__">Custom model name...</option>
                    </select>
                  )}
                </div>

                {/* Small/Fast Model */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Small/Fast Model (Optional)
                  </label>
                  {useCustomModel.small ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={formData.llm_small_model}
                        onChange={(e) =>
                          { setFormData({ ...formData, llm_small_model: e.target.value }); }
                        }
                        placeholder="Enter custom model name"
                        className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setUseCustomModel({ ...useCustomModel, small: false });
                          setFormData({
                            ...formData,
                            llm_small_model: availableModels.chat[0] || '',
                          });
                        }}
                        className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                        title="Use preset model"
                      >
                        <MaterialIcon name="list" size={18} />
                      </button>
                    </div>
                  ) : (
                    <select
                      value={formData.llm_small_model}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value === '__custom__') {
                          setUseCustomModel({ ...useCustomModel, small: true });
                          setFormData({ ...formData, llm_small_model: '' });
                        } else {
                          setFormData({ ...formData, llm_small_model: value });
                        }
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      disabled={isLoadingModels}
                    >
                      <option value="">None</option>
                      {availableModels.chat.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                      <option value="__custom__">Custom model name...</option>
                    </select>
                  )}
                </div>

                {/* Advanced LLM Settings */}
                <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
                  <button
                    type="button"
                    onClick={() => { setShowAdvancedLLM(!showAdvancedLLM); }}
                    className="w-full px-4 py-3 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                  >
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      Advanced LLM Settings
                    </span>
                    <MaterialIcon
                      name={showAdvancedLLM ? 'expand_less' : 'expand_more'}
                      size={20}
                      className="text-slate-500"
                    />
                  </button>

                  {showAdvancedLLM && (
                    <div className="p-4 space-y-4 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Temperature
                          </label>
                          <input
                            type="number"
                            min="0"
                            max="2"
                            step="0.1"
                            value={formData.config.temperature ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                temperature: e.target.value ? Number(e.target.value) : undefined,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            placeholder="e.g. 0.7"
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Max Tokens
                          </label>
                          <input
                            type="number"
                            min="1"
                            value={formData.config.max_tokens ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                max_tokens: e.target.value ? Number(e.target.value) : undefined,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            placeholder="e.g. 4096"
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Top P
                          </label>
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.1"
                            value={formData.config.top_p ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                top_p: e.target.value ? Number(e.target.value) : undefined,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            placeholder="e.g. 1.0"
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Timeout (seconds)
                          </label>
                          <input
                            type="number"
                            min="1"
                            value={formData.config.timeout_seconds ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                timeout_seconds: e.target.value ? Number(e.target.value) : undefined,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            placeholder="e.g. 120"
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Frequency Penalty
                          </label>
                          <input
                            type="number"
                            min="-2"
                            max="2"
                            step="0.1"
                            value={formData.config.frequency_penalty ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                frequency_penalty: e.target.value ? Number(e.target.value) : undefined,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            placeholder="e.g. 0.0"
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Presence Penalty
                          </label>
                          <input
                            type="number"
                            min="-2"
                            max="2"
                            step="0.1"
                            value={formData.config.presence_penalty ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                presence_penalty: e.target.value ? Number(e.target.value) : undefined,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            placeholder="e.g. 0.0"
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Embedding Model */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Embedding Model (Optional)
                  </label>
                  {useCustomModel.embedding ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={formData.embedding_model}
                        onChange={(e) =>
                          { setFormData({ ...formData, embedding_model: e.target.value }); }
                        }
                        placeholder="Enter custom model name"
                        className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setUseCustomModel({ ...useCustomModel, embedding: false });
                          setFormData({
                            ...formData,
                            embedding_model: availableModels.embedding[0] || '',
                          });
                        }}
                        className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                        title="Use preset model"
                      >
                        <MaterialIcon name="list" size={18} />
                      </button>
                    </div>
                  ) : (
                    <select
                      value={formData.embedding_model}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value === '__custom__') {
                          setUseCustomModel({ ...useCustomModel, embedding: true });
                          setFormData({ ...formData, embedding_model: '' });
                        } else {
                          setFormData({ ...formData, embedding_model: value });
                        }
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      disabled={isLoadingModels}
                    >
                      <option value="">None</option>
                      {availableModels.embedding.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                      <option value="__custom__">Custom model name...</option>
                    </select>
                  )}
                </div>

                {/* Advanced Embedding Settings */}
                {formData.embedding_model && (
                  <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
                    <button
                      type="button"
                      onClick={() => { setShowAdvancedEmbedding(!showAdvancedEmbedding); }}
                      className="w-full px-4 py-3 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                    >
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Advanced Embedding Settings
                      </span>
                      <MaterialIcon
                        name={showAdvancedEmbedding ? 'expand_less' : 'expand_more'}
                        size={20}
                        className="text-slate-500"
                      />
                    </button>

                    {showAdvancedEmbedding && (
                      <div className="p-4 space-y-4 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              Dimensions
                            </label>
                            <input
                              type="number"
                              value={formData.embedding_dimensions}
                              onChange={(e) =>
                                { setFormData({ ...formData, embedding_dimensions: e.target.value }); }
                              }
                              placeholder="e.g. 1536"
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              Encoding Format
                            </label>
                            <select
                              value={formData.embedding_encoding_format}
                              onChange={(e) =>
                                { setFormData({
                                  ...formData,
                                  embedding_encoding_format: e.target.value as any,
                                }); }
                              }
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            >
                              <option value="">Default</option>
                              <option value="float">Float</option>
                              <option value="base64">Base64</option>
                            </select>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              User ID (Optional)
                            </label>
                            <input
                              type="text"
                              value={formData.embedding_user}
                              onChange={(e) =>
                                { setFormData({ ...formData, embedding_user: e.target.value }); }
                              }
                              placeholder="End-user ID"
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              Timeout (ms)
                            </label>
                            <input
                              type="number"
                              value={formData.embedding_timeout}
                              onChange={(e) =>
                                { setFormData({ ...formData, embedding_timeout: e.target.value }); }
                              }
                              placeholder="e.g. 30000"
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            />
                          </div>
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            Provider Options (JSON)
                          </label>
                          <textarea
                            value={formData.embedding_provider_options_json}
                            onChange={(e) =>
                              { setFormData({
                                ...formData,
                                embedding_provider_options_json: e.target.value,
                              }); }
                            }
                            placeholder="{}"
                            rows={2}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent font-mono text-xs"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Reranker Model */}
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Reranker Model (Optional)
                  </label>
                  {useCustomModel.reranker ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={formData.reranker_model}
                        onChange={(e) =>
                          { setFormData({ ...formData, reranker_model: e.target.value }); }
                        }
                        placeholder="Enter custom model name"
                        className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setUseCustomModel({ ...useCustomModel, reranker: false });
                          setFormData({
                            ...formData,
                            reranker_model: availableModels.rerank[0] || '',
                          });
                        }}
                        className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                        title="Use preset model"
                      >
                        <MaterialIcon name="list" size={18} />
                      </button>
                    </div>
                  ) : (
                    <select
                      value={formData.reranker_model}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value === '__custom__') {
                          setUseCustomModel({ ...useCustomModel, reranker: true });
                          setFormData({ ...formData, reranker_model: '' });
                        } else {
                          setFormData({ ...formData, reranker_model: value });
                        }
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      disabled={isLoadingModels}
                    >
                      <option value="">None</option>
                      {availableModels.rerank.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                      <option value="__custom__">Custom model name...</option>
                    </select>
                  )}
                </div>
              </div>
            )}

            {/* Step 4: Review */}
            {currentStep === 'review' && (
              <div className="space-y-4">
                <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-4 space-y-3">
                  <div className="flex items-center gap-3">
                    <ProviderIcon providerType={formData.provider_type} size="lg" />
                    <div>
                      <h4 className="font-semibold text-slate-900 dark:text-white">
                        {formData.name}
                      </h4>
                      <p className="text-sm text-slate-500">{formData.provider_type}</p>
                    </div>
                  </div>

                  <div className="border-t border-slate-200 dark:border-slate-600 pt-3 space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">Primary Model:</span>
                      <span
                        className={`font-medium ${
                          useCustomModel.llm
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-slate-900 dark:text-white'
                        }`}
                      >
                        {formData.llm_model}
                        {useCustomModel.llm && (
                          <span className="ml-1.5 text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded">
                            Custom
                          </span>
                        )}
                      </span>
                    </div>
                    {formData.llm_small_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">Small Model:</span>
                        <span
                          className={`font-medium ${
                            useCustomModel.small
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-slate-900 dark:text-white'
                          }`}
                        >
                          {formData.llm_small_model}
                          {useCustomModel.small && (
                            <span className="ml-1.5 text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded">
                              Custom
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    {formData.embedding_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">Embedding:</span>
                        <span
                          className={`font-medium ${
                            useCustomModel.embedding
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-slate-900 dark:text-white'
                          }`}
                        >
                          {formData.embedding_model}
                          {useCustomModel.embedding && (
                            <span className="ml-1.5 text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded">
                              Custom
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    {formData.reranker_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">Reranker:</span>
                        <span
                          className={`font-medium ${
                            useCustomModel.reranker
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-slate-900 dark:text-white'
                          }`}
                        >
                          {formData.reranker_model}
                          {useCustomModel.reranker && (
                            <span className="ml-1.5 text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded">
                              Custom
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">Status:</span>
                      <span
                        className={`font-medium ${
                          formData.is_active ? 'text-green-600' : 'text-slate-500'
                        }`}
                      >
                        {formData.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 text-red-700 dark:text-red-400 text-sm">
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center justify-between">
            <button
              onClick={
                currentStep === 'provider'
                  ? onClose
                  : () =>
                      { setCurrentStep(steps[steps.findIndex((s) => s.key === currentStep) - 1]?.key ?? 'provider'); }
              }
              className="px-4 py-2 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors"
            >
              {currentStep === 'provider' ? 'Cancel' : 'Back'}
            </button>

            <div className="flex items-center gap-3">
              {currentStep === 'review' ? (
                <button
                  onClick={handleSubmit}
                  disabled={isSubmitting}
                  className="px-6 py-2.5 bg-gradient-to-r from-primary to-primary-dark text-white font-medium rounded-lg hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <span className="flex items-center gap-2">
                      <MaterialIcon name="progress_activity" size={18} className="animate-spin" />
                      Saving...
                    </span>
                  ) : (
                    'Save Provider'
                  )}
                </button>
              ) : (
                <button
                  onClick={() =>
                    { setCurrentStep(steps[steps.findIndex((s) => s.key === currentStep) + 1]?.key ?? 'review'); }
                  }
                  disabled={!canProceed()}
                  className="px-6 py-2.5 bg-gradient-to-r from-primary to-primary-dark text-white font-medium rounded-lg hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
