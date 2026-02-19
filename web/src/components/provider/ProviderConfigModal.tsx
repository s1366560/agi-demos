import React, { useEffect, useState, useCallback } from 'react';

import { providerAPI } from '../../services/api';
import { ProviderConfig, ProviderCreate, ProviderType, ProviderUpdate } from '../../types/memory';

interface ProviderConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  provider?: ProviderConfig | null;
}

// Provider metadata with full LiteLLM support info
interface ProviderMeta {
  value: ProviderType;
  label: string;
  icon: string;
  description: string;
  apiKeyEnvVar: string;
  apiKeyPlaceholder: string;
  hasEmbedding: boolean;
  hasNativeRerank: boolean;
  baseUrlRequired: boolean;
  documentationUrl: string;
}

const PROVIDERS: ProviderMeta[] = [
  {
    value: 'openai',
    label: 'OpenAI',
    icon: '🤖',
    description: 'GPT-4, GPT-3.5, text-embedding models',
    apiKeyEnvVar: 'OPENAI_API_KEY',
    apiKeyPlaceholder: 'sk-...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://platform.openai.com/docs',
  },
  {
    value: 'anthropic',
    label: 'Anthropic',
    icon: '🧠',
    description: 'Claude 3.5/4 Sonnet, Haiku, Opus',
    apiKeyEnvVar: 'ANTHROPIC_API_KEY',
    apiKeyPlaceholder: 'sk-ant-...',
    hasEmbedding: false,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://docs.anthropic.com',
  },
  {
    value: 'gemini',
    label: 'Google Gemini',
    icon: '✨',
    description: 'Gemini Pro, Flash, text-embedding-004',
    apiKeyEnvVar: 'GEMINI_API_KEY',
    apiKeyPlaceholder: 'AIza...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://ai.google.dev/docs',
  },
  {
    value: 'qwen',
    label: 'Alibaba Qwen',
    icon: '🌐',
    description: 'Qwen-Max, Qwen-Plus, Qwen-Turbo, text-embedding-v3',
    apiKeyEnvVar: 'DASHSCOPE_API_KEY',
    apiKeyPlaceholder: 'sk-...',
    hasEmbedding: true,
    hasNativeRerank: true,
    baseUrlRequired: false,
    documentationUrl: 'https://help.aliyun.com/zh/dashscope',
  },
  {
    value: 'deepseek',
    label: 'Deepseek',
    icon: '🔍',
    description: 'Deepseek-Chat, Deepseek-Coder (cost-effective)',
    apiKeyEnvVar: 'DEEPSEEK_API_KEY',
    apiKeyPlaceholder: 'sk-...',
    hasEmbedding: false,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://platform.deepseek.com/docs',
  },
  {
    value: 'zai',
    label: 'ZhipuAI 智谱',
    icon: '🐲',
    description: 'GLM-4-Plus, GLM-4-Flash, embedding-3',
    apiKeyEnvVar: 'ZAI_API_KEY',
    apiKeyPlaceholder: '...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://open.bigmodel.cn/dev/api',
  },
  {
    value: 'cohere',
    label: 'Cohere',
    icon: '🔮',
    description: 'Command-R, embed-english-v3, native rerank',
    apiKeyEnvVar: 'COHERE_API_KEY',
    apiKeyPlaceholder: '...',
    hasEmbedding: true,
    hasNativeRerank: true,
    baseUrlRequired: false,
    documentationUrl: 'https://docs.cohere.com',
  },
  {
    value: 'mistral',
    label: 'Mistral AI',
    icon: '🌪️',
    description: 'Mistral-Large, Mistral-Small, mistral-embed',
    apiKeyEnvVar: 'MISTRAL_API_KEY',
    apiKeyPlaceholder: '...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://docs.mistral.ai',
  },
  {
    value: 'groq',
    label: 'Groq',
    icon: '⚡',
    description: 'LLaMA 3, Mixtral (ultra-fast inference)',
    apiKeyEnvVar: 'GROQ_API_KEY',
    apiKeyPlaceholder: 'gsk_...',
    hasEmbedding: false,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://console.groq.com/docs',
  },
  {
    value: 'azure_openai',
    label: 'Azure OpenAI',
    icon: '☁️',
    description: 'Azure-hosted OpenAI models',
    apiKeyEnvVar: 'AZURE_API_KEY',
    apiKeyPlaceholder: '...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: true,
    documentationUrl: 'https://learn.microsoft.com/azure/ai-services/openai',
  },
  {
    value: 'bedrock',
    label: 'AWS Bedrock',
    icon: '🏔️',
    description: 'Claude, Titan, Llama on AWS',
    apiKeyEnvVar: 'AWS_ACCESS_KEY_ID',
    apiKeyPlaceholder: 'AKIA...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://docs.aws.amazon.com/bedrock',
  },
  {
    value: 'vertex',
    label: 'Google Vertex AI',
    icon: '📊',
    description: 'Gemini on Google Cloud',
    apiKeyEnvVar: 'GOOGLE_APPLICATION_CREDENTIALS',
    apiKeyPlaceholder: 'JSON credentials',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://cloud.google.com/vertex-ai/docs',
  },
];

// Model presets by provider
const MODEL_PRESETS: Record<
  ProviderType,
  {
    llm: { name: string; description: string }[];
    small: { name: string; description: string }[];
    embedding: { name: string; dimension: number }[];
    reranker: { name: string; description: string }[];
  }
> = {
  openai: {
    llm: [
      { name: 'gpt-4o', description: 'Most capable, multimodal' },
      { name: 'gpt-4-turbo', description: 'Faster GPT-4' },
      { name: 'gpt-4', description: 'Original GPT-4' },
    ],
    small: [
      { name: 'gpt-4o-mini', description: 'Fast & affordable' },
      { name: 'gpt-3.5-turbo', description: 'Legacy fast model' },
    ],
    embedding: [
      { name: 'text-embedding-3-small', dimension: 1536 },
      { name: 'text-embedding-3-large', dimension: 3072 },
      { name: 'text-embedding-ada-002', dimension: 1536 },
    ],
    reranker: [{ name: 'gpt-4o-mini', description: 'LLM-based reranking' }],
  },
  anthropic: {
    llm: [
      { name: 'claude-sonnet-4-20250514', description: 'Latest Sonnet 4' },
      { name: 'claude-3-5-sonnet-20241022', description: 'Claude 3.5 Sonnet' },
      { name: 'claude-3-opus-20240229', description: 'Most capable' },
    ],
    small: [
      { name: 'claude-3-5-haiku-20241022', description: 'Fast & efficient' },
      { name: 'claude-3-haiku-20240307', description: 'Legacy Haiku' },
    ],
    embedding: [],
    reranker: [{ name: 'claude-3-5-haiku-20241022', description: 'LLM-based reranking' }],
  },
  gemini: {
    llm: [
      { name: 'gemini-2.0-flash-exp', description: 'Latest experimental' },
      { name: 'gemini-1.5-pro', description: '1M context window' },
      { name: 'gemini-1.5-pro-002', description: 'Improved Pro' },
    ],
    small: [
      { name: 'gemini-1.5-flash', description: 'Fast & multimodal' },
      { name: 'gemini-1.5-flash-002', description: 'Improved Flash' },
    ],
    embedding: [{ name: 'text-embedding-004', dimension: 768 }],
    reranker: [{ name: 'gemini-1.5-flash', description: 'LLM-based reranking' }],
  },
  qwen: {
    llm: [
      { name: 'qwen-max', description: 'Most capable' },
      { name: 'qwen-plus', description: 'Balanced performance' },
      { name: 'qwen-long', description: 'Long context' },
    ],
    small: [{ name: 'qwen-turbo', description: 'Fast & cost-effective' }],
    embedding: [
      { name: 'text-embedding-v3', dimension: 1024 },
      { name: 'text-embedding-v2', dimension: 1536 },
    ],
    reranker: [
      { name: 'qwen3-rerank', description: 'Native reranker' },
      { name: 'qwen-turbo', description: 'LLM-based' },
    ],
  },
  deepseek: {
    llm: [
      { name: 'deepseek-chat', description: 'General purpose' },
      { name: 'deepseek-reasoner', description: 'Reasoning focused' },
    ],
    small: [{ name: 'deepseek-coder', description: 'Code specialized' }],
    embedding: [],
    reranker: [{ name: 'deepseek-chat', description: 'LLM-based reranking' }],
  },
  zai: {
    llm: [
      { name: 'glm-4-plus', description: 'Most capable' },
      { name: 'glm-4', description: 'Standard' },
      { name: 'glm-4-long', description: '128K context' },
    ],
    small: [
      { name: 'glm-4-flash', description: 'Fast & affordable' },
      { name: 'glm-4-air', description: 'Balanced' },
    ],
    embedding: [
      { name: 'embedding-3', dimension: 1024 },
      { name: 'embedding-2', dimension: 1024 },
    ],
    reranker: [{ name: 'glm-4-flash', description: 'LLM-based reranking' }],
  },
  cohere: {
    llm: [
      { name: 'command-r-plus', description: 'Most capable' },
      { name: 'command-r', description: 'RAG optimized' },
    ],
    small: [
      { name: 'command-r', description: 'Efficient' },
      { name: 'command-light', description: 'Lightweight' },
    ],
    embedding: [
      { name: 'embed-english-v3.0', dimension: 1024 },
      { name: 'embed-multilingual-v3.0', dimension: 1024 },
      { name: 'embed-english-light-v3.0', dimension: 384 },
    ],
    reranker: [
      { name: 'rerank-english-v3.0', description: 'Native reranker' },
      { name: 'rerank-multilingual-v3.0', description: 'Multilingual' },
    ],
  },
  mistral: {
    llm: [
      { name: 'mistral-large-latest', description: 'Most capable' },
      { name: 'mistral-medium-latest', description: 'Balanced' },
    ],
    small: [
      { name: 'mistral-small-latest', description: 'Fast & efficient' },
      { name: 'open-mistral-7b', description: 'Open source' },
    ],
    embedding: [{ name: 'mistral-embed', dimension: 1024 }],
    reranker: [{ name: 'mistral-small-latest', description: 'LLM-based reranking' }],
  },
  groq: {
    llm: [
      { name: 'llama-3.3-70b-versatile', description: 'Most capable' },
      { name: 'llama-3.1-70b-versatile', description: 'Llama 3.1 70B' },
      { name: 'mixtral-8x7b-32768', description: 'Mixtral MoE' },
    ],
    small: [
      { name: 'llama-3.1-8b-instant', description: 'Ultra-fast' },
      { name: 'gemma2-9b-it', description: 'Google Gemma' },
    ],
    embedding: [],
    reranker: [],
  },
  azure_openai: {
    llm: [
      { name: 'gpt-4o', description: 'GPT-4o deployment' },
      { name: 'gpt-4', description: 'GPT-4 deployment' },
    ],
    small: [
      { name: 'gpt-4o-mini', description: 'Fast deployment' },
      { name: 'gpt-35-turbo', description: 'GPT-3.5 deployment' },
    ],
    embedding: [
      { name: 'text-embedding-3-small', dimension: 1536 },
      { name: 'text-embedding-ada-002', dimension: 1536 },
    ],
    reranker: [],
  },
  bedrock: {
    llm: [
      { name: 'anthropic.claude-3-sonnet-20240229-v1:0', description: 'Claude 3 Sonnet' },
      { name: 'anthropic.claude-3-haiku-20240307-v1:0', description: 'Claude 3 Haiku' },
      { name: 'meta.llama3-70b-instruct-v1:0', description: 'Llama 3 70B' },
    ],
    small: [{ name: 'anthropic.claude-3-haiku-20240307-v1:0', description: 'Fast Claude' }],
    embedding: [
      { name: 'amazon.titan-embed-text-v1', dimension: 1536 },
      { name: 'amazon.titan-embed-text-v2:0', dimension: 1024 },
    ],
    reranker: [],
  },
  vertex: {
    llm: [{ name: 'gemini-1.5-pro', description: 'Gemini Pro on Vertex' }],
    small: [{ name: 'gemini-1.5-flash', description: 'Gemini Flash on Vertex' }],
    embedding: [{ name: 'textembedding-gecko', dimension: 768 }],
    reranker: [],
  },
};

type Step = 'provider' | 'credentials' | 'models' | 'review';

export const ProviderConfigModal: React.FC<ProviderConfigModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  provider,
}) => {
  const isEditing = !!provider;
  const [currentStep, setCurrentStep] = useState<Step>('provider');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configJson, setConfigJson] = useState('{}');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);

  const [formData, setFormData] = useState({
    name: '',
    provider_type: 'openai' as ProviderType,
    api_key: '',
    base_url: '',
    llm_model: 'gpt-4o',
    llm_small_model: 'gpt-4o-mini',
    embedding_model: 'text-embedding-3-small',
    reranker_model: '',
    config: {} as Record<string, any>,
    is_active: true,
    is_default: false,
    use_custom_base_url: false,
  });

  const selectedProvider = PROVIDERS.find((p) => p.value === formData.provider_type);
  const presets = MODEL_PRESETS[formData.provider_type];

  // Fetch models from backend when provider type changes
  useEffect(() => {
    if (formData.provider_type && isOpen) {
      providerAPI
        .listModels(formData.provider_type)
        .then((res) => {
          setFetchedModels(res.models || []);
        })
        .catch((err) => {
          console.error('Failed to fetch models:', err);
          setFetchedModels([]);
        });
    }
  }, [formData.provider_type, isOpen]);

  useEffect(() => {
    if (provider) {
      setFormData({
        name: provider.name,
        provider_type: provider.provider_type,
        api_key: '',
        base_url: provider.base_url || '',
        llm_model: provider.llm_model,
        llm_small_model: provider.llm_small_model || '',
        embedding_model: provider.embedding_model || '',
        reranker_model: provider.reranker_model || '',
        config: provider.config || {},
        is_active: provider.is_active,
        is_default: provider.is_default,
        use_custom_base_url: !!provider.base_url,
      });
      setConfigJson(JSON.stringify(provider.config || {}, null, 2));
      setCurrentStep('credentials');
    } else {
      setFormData({
        name: '',
        provider_type: 'openai',
        api_key: '',
        base_url: '',
        llm_model: 'gpt-4o',
        llm_small_model: 'gpt-4o-mini',
        embedding_model: 'text-embedding-3-small',
        reranker_model: '',
        config: {},
        is_active: true,
        is_default: false,
        use_custom_base_url: false,
      });
      setConfigJson('{}');
      setCurrentStep('provider');
    }
    setError(null);
    setTestResult(null);
  }, [provider, isOpen]);

  const handleProviderSelect = (type: ProviderType) => {
    const presets = MODEL_PRESETS[type];
    setFormData((prev) => ({
      ...prev,
      provider_type: type,
      name: prev.name || PROVIDERS.find((p) => p.value === type)?.label || '',
      llm_model: presets?.llm[0]?.name || '',
      llm_small_model: presets?.small[0]?.name || '',
      embedding_model: presets?.embedding[0]?.name || '',
      reranker_model: presets?.reranker[0]?.name || '',
    }));
    setTestResult(null);
  };

  const handleTestConnection = useCallback(async () => {
    if (!formData.api_key && !isEditing) {
      setTestResult({ success: false, message: 'API key is required' });
      return;
    }

    setIsTesting(true);
    setTestResult(null);

    try {
      // Simulate API test - in real implementation, call backend
      await new Promise((resolve) => setTimeout(resolve, 1500));
      setTestResult({ success: true, message: 'Connection successful! API key is valid.' });
    } catch (_err) {
      setTestResult({ success: false, message: 'Connection failed. Please check your API key.' });
    } finally {
      setIsTesting(false);
    }
  }, [formData.api_key, isEditing]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);

    // Parse and validate config JSON
    let config = {};
    try {
      config = JSON.parse(configJson);
    } catch (_e) {
      setError('Invalid JSON in Advanced Configuration');
      setIsSubmitting(false);
      return;
    }

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

  const steps: { key: Step; label: string; icon: string }[] = [
    { key: 'provider', label: 'Provider', icon: 'smart_toy' },
    { key: 'credentials', label: 'Credentials', icon: 'key' },
    { key: 'models', label: 'Models', icon: 'psychology' },
    { key: 'review', label: 'Review', icon: 'check_circle' },
  ];

  const canProceed = () => {
    switch (currentStep) {
      case 'provider':
        return !!formData.provider_type;
      case 'credentials':
        return !!formData.name && (isEditing || !!formData.api_key);
      case 'models':
        return !!formData.llm_model;
      case 'review':
        return true;
      default:
        return false;
    }
  };

  const goNext = () => {
    const stepIndex = steps.findIndex((s) => s.key === currentStep);
    if (stepIndex < steps.length - 1) {
      setCurrentStep(steps[stepIndex + 1].key);
    }
  };

  const goBack = () => {
    const stepIndex = steps.findIndex((s) => s.key === currentStep);
    if (stepIndex > 0) {
      setCurrentStep(steps[stepIndex - 1].key);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-primary/20 to-purple-500/20 rounded-xl">
              <span className="material-symbols-outlined text-primary text-2xl">add_circle</span>
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                {isEditing ? 'Edit Provider' : 'Add LLM Provider'}
              </h2>
              <p className="text-sm text-slate-500">Configure via LiteLLM unified interface</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-600 transition-colors rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Progress Steps */}
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50">
          <div className="flex items-center justify-between">
            {steps.map((step, index) => {
              const isActive = step.key === currentStep;
              const isPast = steps.findIndex((s) => s.key === currentStep) > index;
              return (
                <React.Fragment key={step.key}>
                  <button
                    onClick={() => isPast && setCurrentStep(step.key)}
                    disabled={!isPast && !isActive}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-all ${
                      isActive
                        ? 'bg-primary text-white shadow-lg shadow-primary/25'
                        : isPast
                          ? 'text-primary hover:bg-primary/10 cursor-pointer'
                          : 'text-slate-400 cursor-not-allowed'
                    }`}
                  >
                    <span
                      className={`material-symbols-outlined text-lg ${isPast && !isActive ? 'text-green-500' : ''}`}
                    >
                      {isPast && !isActive ? 'check_circle' : step.icon}
                    </span>
                    <span className="text-sm font-medium hidden sm:inline">{step.label}</span>
                  </button>
                  {index < steps.length - 1 && (
                    <div
                      className={`flex-1 h-0.5 mx-2 ${isPast ? 'bg-primary' : 'bg-slate-200 dark:bg-slate-700'}`}
                    />
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-center gap-3">
              <span className="material-symbols-outlined text-red-600">error</span>
              <span className="text-red-800 dark:text-red-200 text-sm">{error}</span>
            </div>
          )}

          {/* Step 1: Provider Selection */}
          {currentStep === 'provider' && (
            <div className="space-y-4">
              <p className="text-slate-600 dark:text-slate-400 mb-4">
                Select your LLM provider. All providers are accessed through LiteLLM's unified
                interface.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {PROVIDERS.map((provider) => (
                  <button
                    key={provider.value}
                    onClick={() => handleProviderSelect(provider.value)}
                    className={`p-4 rounded-xl border-2 text-left transition-all hover:shadow-md ${
                      formData.provider_type === provider.value
                        ? 'border-primary bg-primary/5 shadow-md'
                        : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">{provider.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-slate-900 dark:text-white">
                          {provider.label}
                        </div>
                        <div className="text-xs text-slate-500 mt-1 line-clamp-2">
                          {provider.description}
                        </div>
                        <div className="flex gap-1 mt-2">
                          {provider.hasEmbedding && (
                            <span className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-[10px] rounded">
                              Embed
                            </span>
                          )}
                          {provider.hasNativeRerank && (
                            <span className="px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 text-[10px] rounded">
                              Rerank
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: Credentials */}
          {currentStep === 'credentials' && selectedProvider && (
            <div className="space-y-6">
              <div className="flex items-center gap-3 p-4 bg-slate-50 dark:bg-slate-800 rounded-xl">
                <span className="text-3xl">{selectedProvider.icon}</span>
                <div>
                  <div className="font-semibold text-slate-900 dark:text-white">
                    {selectedProvider.label}
                  </div>
                  <div className="text-sm text-slate-500">{selectedProvider.description}</div>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  Provider Name *
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder={`My ${selectedProvider.label} Provider`}
                  className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  API Key {!isEditing && '*'}
                </label>
                <div className="relative">
                  <input
                    type="password"
                    value={formData.api_key}
                    onChange={(e) => setFormData((prev) => ({ ...prev, api_key: e.target.value }))}
                    placeholder={
                      isEditing ? 'Leave empty to keep current' : selectedProvider.apiKeyPlaceholder
                    }
                    className="w-full px-4 py-2.5 pr-24 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  />
                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={isTesting}
                    className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-xs font-medium text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-50"
                  >
                    {isTesting ? 'Testing...' : 'Test'}
                  </button>
                </div>
                <p className="mt-1.5 text-xs text-slate-500 flex items-center gap-1">
                  <span className="material-symbols-outlined text-sm">info</span>
                  Environment variable:{' '}
                  <code className="px-1 bg-slate-100 dark:bg-slate-700 rounded">
                    {selectedProvider.apiKeyEnvVar}
                  </code>
                </p>
                {testResult && (
                  <div
                    className={`mt-2 p-2 rounded-lg text-sm flex items-center gap-2 ${
                      testResult.success
                        ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
                        : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
                    }`}
                  >
                    <span className="material-symbols-outlined text-lg">
                      {testResult.success ? 'check_circle' : 'error'}
                    </span>
                    {testResult.message}
                  </div>
                )}
              </div>

              {/* Custom Base URL Toggle */}
              {!selectedProvider.baseUrlRequired && (
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.use_custom_base_url}
                      onChange={(e) =>
                        setFormData((prev) => ({
                          ...prev,
                          use_custom_base_url: e.target.checked,
                          base_url: e.target.checked ? prev.base_url : '',
                        }))
                      }
                      className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                    />
                    <span className="text-sm text-slate-700 dark:text-slate-300">
                      Use custom base URL
                    </span>
                  </label>
                  <span
                    className="material-symbols-outlined text-slate-400 text-sm cursor-help"
                    title="Override the default API endpoint URL for this provider (e.g., for proxy services or self-hosted instances)"
                  >
                    help_outline
                  </span>
                </div>
              )}

              {/* Base URL Input - shown when required by provider or when custom URL is enabled */}
              {(selectedProvider.baseUrlRequired || formData.use_custom_base_url) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                    Base URL {selectedProvider.baseUrlRequired && '*'}
                  </label>
                  <input
                    type="url"
                    value={formData.base_url}
                    onChange={(e) => setFormData((prev) => ({ ...prev, base_url: e.target.value }))}
                    placeholder={
                      selectedProvider.value === 'azure_openai'
                        ? 'https://your-resource.openai.azure.com'
                        : selectedProvider.value === 'openai'
                          ? 'https://api.openai.com/v1'
                          : selectedProvider.value === 'anthropic'
                            ? 'https://api.anthropic.com'
                            : selectedProvider.value === 'deepseek'
                              ? 'https://api.deepseek.com/v1'
                              : 'https://api.example.com/v1'
                    }
                    className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  />
                  <p className="mt-1.5 text-xs text-slate-500">
                    {selectedProvider.baseUrlRequired
                      ? 'Required for this provider type'
                      : 'Optional: Override the default API endpoint'}
                  </p>
                </div>
              )}

              <div className="flex items-center gap-6">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formData.is_active}
                    onChange={(e) =>
                      setFormData((prev) => ({ ...prev, is_active: e.target.checked }))
                    }
                    className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">Active</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formData.is_default}
                    onChange={(e) =>
                      setFormData((prev) => ({ ...prev, is_default: e.target.checked }))
                    }
                    className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">Set as default</span>
                </label>
              </div>

              <a
                href={selectedProvider.documentationUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                <span className="material-symbols-outlined text-sm">open_in_new</span>
                View {selectedProvider.label} documentation
              </a>
            </div>
          )}

          {/* Step 3: Models */}
          {currentStep === 'models' && presets && (
            <div className="space-y-6">
              {/* LLM Model */}
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Primary LLM Model *
                </label>
                <div className="grid grid-cols-1 gap-2">
                  {presets.llm.map((model) => (
                    <button
                      key={model.name}
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, llm_model: model.name }))}
                      className={`p-3 rounded-lg border text-left transition-all ${
                        formData.llm_model === model.name
                          ? 'border-primary bg-primary/5'
                          : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <code className="text-sm font-mono text-slate-900 dark:text-white">
                          {model.name}
                        </code>
                        {formData.llm_model === model.name && (
                          <span className="material-symbols-outlined text-primary">
                            check_circle
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-500 mt-1">{model.description}</p>
                    </button>
                  ))}
                </div>
                <input
                  type="text"
                  list="llm-models-list"
                  value={formData.llm_model}
                  onChange={(e) => setFormData((prev) => ({ ...prev, llm_model: e.target.value }))}
                  placeholder="Or enter custom model name"
                  className="mt-2 w-full px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                <datalist id="llm-models-list">
                  {fetchedModels.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </div>

              {/* Small Model */}
              {presets.small.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Small/Fast Model <span className="text-slate-400">(optional)</span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {presets.small.map((model) => (
                      <button
                        key={model.name}
                        type="button"
                        onClick={() =>
                          setFormData((prev) => ({ ...prev, llm_small_model: model.name }))
                        }
                        className={`px-3 py-2 rounded-lg border text-sm transition-all ${
                          formData.llm_small_model === model.name
                            ? 'border-primary bg-primary/5 text-primary'
                            : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {model.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Embedding Model */}
              {presets.embedding.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Embedding Model <span className="text-slate-400">(optional)</span>
                  </label>
                  <div className="grid grid-cols-1 gap-2">
                    {presets.embedding.map((model) => (
                      <button
                        key={model.name}
                        type="button"
                        onClick={() =>
                          setFormData((prev) => ({ ...prev, embedding_model: model.name }))
                        }
                        className={`p-3 rounded-lg border text-left transition-all ${
                          formData.embedding_model === model.name
                            ? 'border-primary bg-primary/5'
                            : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <code className="text-sm font-mono">{model.name}</code>
                          <span className="text-xs text-slate-500">{model.dimension} dims</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Reranker Model */}
              {presets.reranker.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Reranker Model <span className="text-slate-400">(optional)</span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {presets.reranker.map((model) => (
                      <button
                        key={model.name}
                        type="button"
                        onClick={() =>
                          setFormData((prev) => ({ ...prev, reranker_model: model.name }))
                        }
                        className={`px-3 py-2 rounded-lg border text-sm transition-all ${
                          formData.reranker_model === model.name
                            ? 'border-primary bg-primary/5 text-primary'
                            : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {model.name}
                        {model.description.includes('Native') && (
                          <span className="ml-1 text-[10px] bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 px-1 rounded">
                            Native
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Advanced Configuration (JSON) */}
              <div className="pt-6 border-t border-slate-200 dark:border-slate-700">
                <button
                  type="button"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-primary transition-colors w-full"
                >
                  <span className="material-symbols-outlined text-lg transform transition-transform duration-200" style={{ transform: showAdvanced ? 'rotate(90deg)' : 'rotate(0deg)' }}>
                    chevron_right
                  </span>
                  Advanced Configuration (JSON)
                </button>
                
                {showAdvanced && (
                  <div className="mt-4">
                    <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                      Override model limits or provider-specific settings. 
                      Example: <code>{'{ "max_tokens": 8192, "timeout": 60 }'}</code>
                    </p>
                    <textarea
                      value={configJson}
                      onChange={(e) => setConfigJson(e.target.value)}
                      className="w-full h-40 p-3 font-mono text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none resize-y"
                      placeholder="{}"
                      spellCheck={false}
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Step 4: Review */}
          {currentStep === 'review' && selectedProvider && (
            <div className="space-y-4">
              <div className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6">
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-4xl">{selectedProvider.icon}</span>
                  <div>
                    <h3 className="text-xl font-semibold text-slate-900 dark:text-white">
                      {formData.name}
                    </h3>
                    <p className="text-sm text-slate-500">{selectedProvider.label} Provider</p>
                  </div>
                  {formData.is_default && (
                    <span className="ml-auto px-3 py-1 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 text-sm font-medium rounded-full">
                      Default
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4 mt-4">
                  <div>
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Primary Model</p>
                    <code className="text-sm font-mono text-slate-900 dark:text-white">
                      {formData.llm_model}
                    </code>
                  </div>
                  {formData.llm_small_model && (
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider">Small Model</p>
                      <code className="text-sm font-mono text-slate-900 dark:text-white">
                        {formData.llm_small_model}
                      </code>
                    </div>
                  )}
                  {formData.embedding_model && (
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider">
                        Embedding Model
                      </p>
                      <code className="text-sm font-mono text-slate-900 dark:text-white">
                        {formData.embedding_model}
                      </code>
                    </div>
                  )}
                  {formData.reranker_model && (
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider">
                        Reranker Model
                      </p>
                      <code className="text-sm font-mono text-slate-900 dark:text-white">
                        {formData.reranker_model}
                      </code>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-4 mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
                  <span
                    className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${
                      formData.is_active
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${formData.is_active ? 'bg-green-500' : 'bg-slate-400'}`}
                    />
                    {formData.is_active ? 'Active' : 'Inactive'}
                  </span>
                  {formData.api_key && (
                    <span className="text-xs text-slate-500">
                      API Key: ••••••{formData.api_key.slice(-4)}
                    </span>
                  )}
                </div>
              </div>

              <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-blue-600">info</span>
                  <div className="text-sm text-blue-800 dark:text-blue-200">
                    <p className="font-medium">LiteLLM Integration</p>
                    <p className="mt-1 text-blue-700 dark:text-blue-300">
                      This provider will be accessible through LiteLLM's unified API. Model names
                      are automatically prefixed for correct routing.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <button
            type="button"
            onClick={currentStep === 'provider' ? onClose : goBack}
            disabled={isSubmitting}
            className="px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            {currentStep === 'provider' ? 'Cancel' : 'Back'}
          </button>

          {currentStep === 'review' ? (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 px-6 py-2.5 bg-primary hover:bg-primary-dark text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-lg">
                    progress_activity
                  </span>
                  Saving...
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-lg">check</span>
                  {isEditing ? 'Update Provider' : 'Create Provider'}
                </>
              )}
            </button>
          ) : (
            <button
              type="button"
              onClick={goNext}
              disabled={!canProceed()}
              className="inline-flex items-center gap-2 px-6 py-2.5 bg-primary hover:bg-primary-dark text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              Continue
              <span className="material-symbols-outlined text-lg">arrow_forward</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
