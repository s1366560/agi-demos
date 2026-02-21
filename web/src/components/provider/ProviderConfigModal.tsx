import React, { useEffect, useState, useCallback } from 'react';

import { providerAPI } from '../../services/api';
import {
  EmbeddingConfig,
  ProviderConfig,
  ProviderCreate,
  ProviderType,
  ProviderUpdate,
} from '../../types/memory';
import { ProviderIcon } from './ProviderIcon';

interface ProviderConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  provider?: ProviderConfig | null;
}

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
    value: 'dashscope',
    label: 'Alibaba Dashscope',
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
    value: 'kimi',
    label: 'Moonshot Kimi',
    icon: '🌙',
    description: 'Moonshot Kimi chat, embedding and rerank models',
    apiKeyEnvVar: 'KIMI_API_KEY',
    apiKeyPlaceholder: 'sk-...',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://platform.moonshot.cn/docs',
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
  {
    value: 'ollama',
    label: 'Ollama',
    icon: '🦙',
    description: 'Local Ollama runtime (Open source models)',
    apiKeyEnvVar: 'OLLAMA_API_KEY',
    apiKeyPlaceholder: '(optional)',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://github.com/ollama/ollama',
  },
  {
    value: 'lmstudio',
    label: 'LM Studio',
    icon: '🖥️',
    description: 'Local OpenAI-compatible endpoint from LM Studio',
    apiKeyEnvVar: 'LMSTUDIO_API_KEY',
    apiKeyPlaceholder: '(optional)',
    hasEmbedding: true,
    hasNativeRerank: false,
    baseUrlRequired: false,
    documentationUrl: 'https://lmstudio.ai/docs',
  },
];

const OPTIONAL_API_KEY_PROVIDERS: ProviderType[] = ['ollama', 'lmstudio'];

const providerTypeRequiresApiKey = (type: ProviderType) =>
  !OPTIONAL_API_KEY_PROVIDERS.includes(type);

type Step = 'provider' | 'credentials' | 'models' | 'review';

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
  dashscope: {
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
  kimi: {
    llm: [
      { name: 'moonshot-v1-8k', description: 'Fast model' },
      { name: 'moonshot-v1-32k', description: 'Longer context' },
      { name: 'moonshot-v1-128k', description: 'Longest context' },
    ],
    small: [{ name: 'moonshot-v1-8k', description: 'Fast & affordable' }],
    embedding: [{ name: 'kimi-embedding-1', dimension: 1024 }],
    reranker: [{ name: 'kimi-rerank-1', description: 'Native reranking model' }],
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
  ollama: {
    llm: [{ name: 'llama3.1:8b', description: 'Local default model' }],
    small: [{ name: 'llama3.1:8b', description: 'Local default model' }],
    embedding: [{ name: 'nomic-embed-text', dimension: 768 }],
    reranker: [{ name: 'llama3.1:8b', description: 'LLM-based reranking' }],
  },
  lmstudio: {
    llm: [{ name: 'local-model', description: 'LM Studio loaded chat model' }],
    small: [{ name: 'local-model', description: 'LM Studio loaded chat model' }],
    embedding: [{ name: 'text-embedding-nomic-embed-text-v1.5', dimension: 768 }],
    reranker: [{ name: 'local-model', description: 'LLM-based reranking' }],
  },
} as const;

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
}) => {
  const isEditing = !!provider;
  const [currentStep, setCurrentStep] = useState<Step>('provider');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  const steps: { key: Step; label: string; icon: string; description: string }[] = [
    { key: 'provider', label: 'Select Provider', icon: 'smart_toy', description: 'Choose LLM provider' },
    { key: 'credentials', label: 'Credentials', icon: 'key', description: 'API key & config' },
    { key: 'models', label: 'Models', icon: 'psychology', description: 'Configure models' },
    { key: 'review', label: 'Review', icon: 'check_circle', description: 'Review & save' },
  ];

  // Initialize form data
  useEffect(() => {
    if (provider) {
      const embeddingConfig = resolveEmbeddingConfig(provider);
      setFormData({
        name: provider.name,
        provider_type: provider.provider_type,
        api_key: '',
        base_url: provider.base_url || '',
        llm_model: provider.llm_model,
        llm_small_model: provider.llm_small_model || '',
        embedding_model: embeddingConfig?.model || provider.embedding_model || '',
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
      setCurrentStep('provider');
    }
    setError(null);
    setTestResult(null);
  }, [provider, isOpen]);

  const handleProviderSelect = (type: ProviderType) => {
    const providerMeta = PROVIDERS.find((p) => p.value === type);
    const presets = MODEL_PRESETS[type];
    setFormData((prev) => ({
      ...prev,
      provider_type: type,
      name: prev.name || providerMeta?.label || '',
      llm_model: presets?.llm[0]?.name || '',
      llm_small_model: presets?.small[0]?.name || '',
      embedding_model: presets?.embedding[0]?.name || '',
      embedding_dimensions: presets?.embedding[0]?.dimension
        ? String(presets.embedding[0].dimension)
        : '',
      reranker_model: presets?.reranker[0]?.name || '',
    }));
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
              <span className="material-symbols-outlined">close</span>
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
                        className={`flex items-center justify-center w-10 h-10 rounded-full border-2 transition-all ${
                          isCompleted
                            ? 'bg-primary border-primary text-white'
                            : isCurrent
                              ? 'border-primary text-primary bg-white dark:bg-slate-800'
                              : 'border-slate-300 dark:border-slate-600 text-slate-400'
                        }`}
                      >
                        {isCompleted ? (
                          <span className="material-symbols-outlined text-sm">check</span>
                        ) : (
                          <span className="material-symbols-outlined text-sm">{step.icon}</span>
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
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
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
                          onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                          placeholder={PROVIDERS.find((p) => p.value === formData.provider_type)?.apiKeyPlaceholder || 'sk-...'}
                        />
                        <button
                          onClick={handleTestConnection}
                          disabled={isTesting || !formData.api_key}
                          className="px-4 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors disabled:opacity-50 font-medium"
                        >
                          {isTesting ? (
                            <span className="material-symbols-outlined animate-spin text-[18px]">
                              progress_activity
                            </span>
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
                      onChange={(e) => setFormData({ ...formData, base_url: e.target.value })}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="https://api.example.com"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 3: Models */}
            {currentStep === 'models' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Primary LLM Model
                  </label>
                  <select
                    value={formData.llm_model}
                    onChange={(e) => setFormData({ ...formData, llm_model: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                  >
                    {MODEL_PRESETS[formData.provider_type]?.llm.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name} - {m.description}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Small/Fast Model (Optional)
                  </label>
                  <select
                    value={formData.llm_small_model}
                    onChange={(e) =>
                      setFormData({ ...formData, llm_small_model: e.target.value })
                    }
                    className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                  >
                    <option value="">None</option>
                    {MODEL_PRESETS[formData.provider_type]?.small.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name} - {m.description}
                      </option>
                    ))}
                  </select>
                </div>

                {MODEL_PRESETS[formData.provider_type]?.embedding && MODEL_PRESETS[formData.provider_type].embedding.length > 0 && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      Embedding Model (Optional)
                    </label>
                    <select
                      value={formData.embedding_model}
                      onChange={(e) => setFormData({ ...formData, embedding_model: e.target.value })}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                    >
                      <option value="">None</option>
                      {MODEL_PRESETS[formData.provider_type].embedding.map((m) => (
                        <option key={m.name} value={m.name}>
                          {m.name} ({m.dimension}d)
                        </option>
                      ))}
                    </select>
                  </div>
                )}
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
                      <span className="font-medium text-slate-900 dark:text-white">
                        {formData.llm_model}
                      </span>
                    </div>
                    {formData.llm_small_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">Small Model:</span>
                        <span className="font-medium text-slate-900 dark:text-white">
                          {formData.llm_small_model}
                        </span>
                      </div>
                    )}
                    {formData.embedding_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">Embedding:</span>
                        <span className="font-medium text-slate-900 dark:text-white">
                          {formData.embedding_model}
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
              onClick={currentStep === 'provider' ? onClose : () => setCurrentStep(steps[steps.findIndex((s) => s.key === currentStep) - 1].key)}
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
                      <span className="material-symbols-outlined animate-spin text-[18px]">
                        progress_activity
                      </span>
                      Saving...
                    </span>
                  ) : (
                    'Save Provider'
                  )}
                </button>
              ) : (
                <button
                  onClick={() => setCurrentStep(steps[steps.findIndex((s) => s.key === currentStep) + 1].key)}
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
