import React, { useEffect, useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Select, Slider, InputNumber } from 'antd';
import {
  X,
  Check,
  ChevronDown,
  ChevronUp,
  Phone,
  List,
  Sparkles,
  Loader2,
  Bot,
  Key,
  Brain,
  CheckCircle,
  type LucideIcon,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { PROVIDERS } from '../../constants/providers';
import { providerAPI } from '../../services/api';
import { useProviderStore } from '../../stores/provider';
import {
  EmbeddingConfig,
  LLMConfigOverrides,
  ModelCatalogEntry,
  ProviderConfig,
  ProviderCreate,
  ProviderHealth,
  ProviderType,
  ProviderUpdate,
} from '../../types/memory';

import { ProviderIcon } from './ProviderIcon';

import type { TFunction } from 'i18next';

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
type ProviderModels = { chat: string[]; embedding: string[]; rerank: string[] };
type EmbeddingEncodingFormat = '' | NonNullable<EmbeddingConfig['encoding_format']>;
type ModelTier = '' | 'small' | 'medium' | 'large';

interface ProviderModalConfig extends LLMConfigOverrides {
  rtc_app_id?: string | undefined;
  rtc_app_key?: string | undefined;
  volc_ak?: string | undefined;
  volc_sk?: string | undefined;
  speech_app_id?: string | undefined;
  speech_access_token?: string | undefined;
  doubao_endpoint_id?: string | undefined;
  timeout_seconds?: number | null | undefined;
  embedding?: EmbeddingConfig | undefined;
  [key: string]: unknown;
}

interface ProviderFormData {
  name: string;
  provider_type: ProviderType;
  api_key: string;
  base_url: string;
  llm_model: string;
  llm_small_model: string;
  embedding_model: string;
  embedding_dimensions: string;
  embedding_encoding_format: EmbeddingEncodingFormat;
  embedding_user: string;
  embedding_timeout: string;
  embedding_provider_options_json: string;
  reranker_model: string;
  config: ProviderModalConfig;
  is_active: boolean;
  is_default: boolean;
  use_custom_base_url: boolean;
  pool_enabled: boolean;
  pool_weight: number;
  model_tier: ModelTier;
  secondary_models: string[];
}

const PROVIDER_MODEL_PARENT: Partial<Record<ProviderType, ProviderType>> = {
  dashscope_coding: 'dashscope',
  dashscope_embedding: 'dashscope',
  dashscope_reranker: 'dashscope',
  kimi_coding: 'kimi',
  kimi_embedding: 'kimi',
  kimi_reranker: 'kimi',
  minimax_coding: 'minimax',
  minimax_embedding: 'minimax',
  minimax_reranker: 'minimax',
  zai_coding: 'zai',
  zai_embedding: 'zai',
  zai_reranker: 'zai',
  volcengine_coding: 'volcengine',
  volcengine_embedding: 'volcengine',
  volcengine_reranker: 'volcengine',
};

const resolveCatalogProviderType = (providerType: ProviderType): ProviderType =>
  PROVIDER_MODEL_PARENT[providerType] ?? providerType;

type ProviderCategory = 'chat' | 'coding' | 'embedding' | 'reranker';
const getProviderCategory = (pt: ProviderType): ProviderCategory => {
  if (pt.endsWith('_coding')) return 'coding';
  if (pt.endsWith('_embedding')) return 'embedding';
  if (pt.endsWith('_reranker')) return 'reranker';
  return 'chat';
};

const resolvePrimaryLlmModel = (models?: ProviderModels | null): string =>
  models?.chat[0] || models?.embedding[0] || models?.rerank[0] || '';

const getLlmCandidates = (models?: ProviderModels | null): string[] =>
  models?.chat.length ? models.chat : [...(models?.embedding || []), ...(models?.rerank || [])];

const resolveSmallLlmModel = (models?: ProviderModels | null, primaryModel = ''): string => {
  const chatModels = getLlmCandidates(models);
  const keywords = ['mini', 'small', 'flash', 'haiku', 'turbo', 'nano', 'lite'];
  const keywordMatch = chatModels.find(
    (m) => m !== primaryModel && keywords.some((keyword) => m.toLowerCase().includes(keyword))
  );
  if (keywordMatch) return keywordMatch;

  const fallbackChat = chatModels.find((m) => m !== primaryModel);
  if (fallbackChat) return fallbackChat;

  return primaryModel;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const toProviderModalConfig = (value: unknown): ProviderModalConfig =>
  isRecord(value) ? { ...value } : {};

const getProviderErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }

  if (!isRecord(error)) return fallback;

  const response = error.response;
  if (isRecord(response)) {
    const data = response.data;
    if (isRecord(data) && typeof data.detail === 'string') {
      return data.detail;
    }
  }

  return fallback;
};

const parseConfigJson = (value: string): ProviderModalConfig | null => {
  const parsed = JSON.parse(value) as unknown;
  return isRecord(parsed) ? { ...parsed } : null;
};

const filterModelOption = (input: string, option?: { label?: string | undefined }): boolean =>
  (option?.label ?? '').toLowerCase().includes(input.toLowerCase());

const formatCompactCount = (value: number): string => {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${String(Math.round(value / 1000))}k`;
  return String(value);
};

const formatModelCost = (
  inputCost: number | null | undefined,
  outputCost: number | null | undefined
): string => {
  if (inputCost == null) return 'N/A';
  const output = outputCost == null ? '?' : `$${String(outputCost)}`;
  return `$${String(inputCost)} / ${output}`;
};

const toNullableNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const resolveEmbeddingConfig = (provider: ProviderConfig): EmbeddingConfig | undefined => {
  if (provider.embedding_config) {
    return provider.embedding_config;
  }
  const legacyEmbeddingConfig = toProviderModalConfig(provider.config).embedding;
  if (legacyEmbeddingConfig) {
    return legacyEmbeddingConfig;
  }
  if (provider.embedding_model) {
    return { model: provider.embedding_model };
  }
  return undefined;
};

const formatProviderHealthResult = (
  health: ProviderHealth,
  t: TFunction,
  savedProvider = false
): { success: boolean; message: string } => {
  const responseTime =
    typeof health.response_time_ms === 'number' ? ` (${String(health.response_time_ms)} ms)` : '';
  const prefix = t(
    savedProvider
      ? 'tenant.providers.connectionTest.savedPrefix'
      : 'tenant.providers.connectionTest.livePrefix'
  );

  if (health.status === 'healthy') {
    return {
      success: true,
      message: t('tenant.providers.connectionTest.passed', { prefix, responseTime }),
    };
  }

  const detail = health.error_message ? `: ${health.error_message}` : '';
  return {
    success: false,
    message: t('tenant.providers.connectionTest.returned', {
      prefix,
      status: health.status,
      responseTime,
      detail,
    }),
  };
};

export const ProviderConfigModal: React.FC<ProviderConfigModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  provider,
  initialProviderType,
}) => {
  const { t } = useTranslation();
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
  const [envProviders, setEnvProviders] = useState<
    Record<
      string,
      {
        provider_type: string;
        api_key: string | null;
        base_url: string | null;
        llm_model: string | null;
        llm_small_model: string | null;
        embedding_model: string | null;
        reranker_model: string | null;
      }
    >
  >({});

  const { searchModels, modelSearchResults, fetchModelCatalog, modelCatalog } = useProviderStore(
    useShallow((s) => ({
      searchModels: s.searchModels,
      modelSearchResults: s.modelSearchResults,
      fetchModelCatalog: s.fetchModelCatalog,
      modelCatalog: s.modelCatalog,
    }))
  );

  const [formData, setFormData] = useState<ProviderFormData>({
    name: '',
    provider_type: 'openai' as ProviderType,
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
    pool_enabled: true,
    pool_weight: 1.0,
    model_tier: '',
    secondary_models: [],
  });

  const selectedModelMeta: ModelCatalogEntry | null = useMemo(() => {
    if (!formData.llm_model || !modelCatalog.length) return null;
    return modelCatalog.find((m) => m.name === formData.llm_model) ?? null;
  }, [formData.llm_model, modelCatalog]);

  useEffect(() => {
    void fetchModelCatalog(resolveCatalogProviderType(formData.provider_type));
  }, [fetchModelCatalog, formData.provider_type]);

  const [configJsonStr, setConfigJsonStr] = useState('{}');

  // Track which model fields are in custom input mode
  const [useCustomModel, setUseCustomModel] = useState({
    llm: false,
    small: false,
    embedding: false,
    reranker: false,
  });

  const steps: { key: Step; label: string; icon: LucideIcon; description: string }[] = [
    {
      key: 'provider',
      label: t('components.provider.config.steps.provider.label', {
        defaultValue: 'Select Provider',
      }),
      icon: Bot,
      description: t('components.provider.config.steps.provider.description', {
        defaultValue: 'Choose LLM provider',
      }),
    },
    {
      key: 'credentials',
      label: t('components.provider.config.steps.credentials.label', {
        defaultValue: 'Credentials',
      }),
      icon: Key,
      description: t('components.provider.config.steps.credentials.description', {
        defaultValue: 'API key & config',
      }),
    },
    {
      key: 'models',
      label: t('components.provider.config.steps.models.label', {
        defaultValue: 'Models',
      }),
      icon: Brain,
      description: t('components.provider.config.steps.models.description', {
        defaultValue: 'Configure models',
      }),
    },
    {
      key: 'review',
      label: t('components.provider.config.steps.review.label', {
        defaultValue: 'Review',
      }),
      icon: CheckCircle,
      description: t('components.provider.config.steps.review.description', {
        defaultValue: 'Review & save',
      }),
    },
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
      void fetchModels(provider.provider_type).then((models) => {
        if (!models) return;
        const llmCandidates = getLlmCandidates(models);

        // Check if models are custom (not in fetched list)
        const llmIsCustom = !!provider.llm_model && !llmCandidates.includes(provider.llm_model);
        const smallIsCustom =
          !!provider.llm_small_model && !llmCandidates.includes(provider.llm_small_model);
        const embeddingModel = embeddingConfig?.model ?? provider.embedding_model ?? '';
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
        base_url: provider.base_url ?? '',
        llm_model: provider.llm_model ?? '',
        llm_small_model: provider.llm_small_model ?? '',
        embedding_model: embeddingModel,
        embedding_dimensions:
          embeddingConfig?.dimensions !== undefined ? String(embeddingConfig.dimensions) : '',
        embedding_encoding_format: embeddingConfig?.encoding_format ?? '',
        embedding_user: embeddingConfig?.user ?? '',
        embedding_timeout:
          embeddingConfig?.timeout !== undefined ? String(embeddingConfig.timeout) : '',
        embedding_provider_options_json: JSON.stringify(
          embeddingConfig?.provider_options ?? {},
          null,
          2
        ),
        reranker_model: provider.reranker_model ?? '',
        config: toProviderModalConfig(provider.config),
        is_active: provider.is_active,
        is_default: provider.is_default,
        use_custom_base_url: !!provider.base_url,
        pool_enabled: provider.pool_enabled ?? true,
        pool_weight: provider.pool_weight ?? 1.0,
        model_tier: provider.model_tier ?? '',
        secondary_models: provider.secondary_models ?? [],
      });
      setConfigJsonStr(JSON.stringify(toProviderModalConfig(provider.config), null, 2));

      setCurrentStep('credentials');
    } else {
      const envDetectionPromise = providerAPI
        .detectEnvKeys()
        .then((res) => {
          setEnvProviders(res.detected_providers);
          return res.detected_providers;
        })
        .catch(() => null);

      // Default state for new provider
      const defaultProvider = initialProviderType ?? 'openai';
      const providerMeta = PROVIDERS.find((p) => p.value === defaultProvider);

      setFormData({
        name: providerMeta?.label ?? '',
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
        pool_enabled: true,
        pool_weight: 1.0,
        model_tier: '',
        secondary_models: [],
      });
      setConfigJsonStr('{}');

      // Fetch models for default provider
      void fetchModels(defaultProvider).then((models) => {
        if (models) {
          const primaryModel = resolvePrimaryLlmModel(models);
          setFormData((prev) => ({
            ...prev,
            llm_model: primaryModel,
            llm_small_model: resolveSmallLlmModel(models, primaryModel),
            embedding_model: models.embedding[0] ?? '',
            reranker_model: models.rerank[0] ?? '',
          }));

          void envDetectionPromise.then((envData) => {
            if (envData && envData[defaultProvider]) {
              const envValues = envData[defaultProvider];
              setFormData((prev) => {
                const newData = { ...prev };
                if (envValues.api_key) newData.api_key = envValues.api_key;
                if (envValues.base_url) {
                  newData.base_url = envValues.base_url;
                  newData.use_custom_base_url = true;
                }
                if (envValues.llm_model) newData.llm_model = envValues.llm_model;
                if (envValues.llm_small_model) newData.llm_small_model = envValues.llm_small_model;
                if (envValues.embedding_model) newData.embedding_model = envValues.embedding_model;
                if (envValues.reranker_model) newData.reranker_model = envValues.reranker_model;
                return newData;
              });
            }
          });
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
    const primaryModel = resolvePrimaryLlmModel(models);

    setFormData((prev) => {
      const newData = {
        ...prev,
        provider_type: type,
        name: providerMeta?.label ?? prev.name,
        llm_model: primaryModel,
        llm_small_model: resolveSmallLlmModel(models, primaryModel),
        embedding_model: models?.embedding[0] ?? '',
        embedding_dimensions: '1536', // Default, user can change
        reranker_model: models?.rerank[0] ?? '',
      };

      const envValues = envProviders[type];
      if (envValues) {
        if (envValues.api_key) newData.api_key = envValues.api_key;
        if (envValues.base_url) {
          newData.base_url = envValues.base_url;
          newData.use_custom_base_url = true;
        }
        if (envValues.llm_model) newData.llm_model = envValues.llm_model;
        if (envValues.llm_small_model) newData.llm_small_model = envValues.llm_small_model;
        if (envValues.embedding_model) newData.embedding_model = envValues.embedding_model;
        if (envValues.reranker_model) newData.reranker_model = envValues.reranker_model;
      }

      return newData;
    });

    // Reset custom model mode when switching provider
    setUseCustomModel({
      llm: false,
      small: false,
      embedding: false,
      reranker: false,
    });
    void fetchModelCatalog(resolveCatalogProviderType(type));
    setTestResult(null);
  };

  const handleTestConnection = useCallback(async () => {
    if (!formData.api_key && !isEditing && providerTypeRequiresApiKey(formData.provider_type)) {
      setTestResult({
        success: false,
        message: t('tenant.providers.connectionTest.apiKeyRequired'),
      });
      return;
    }

    setIsTesting(true);
    setTestResult(null);

    try {
      if (!formData.api_key && provider?.id) {
        const health = await providerAPI.checkHealth(provider.id);
        setTestResult(formatProviderHealthResult(health, t, true));
        return;
      }

      const categoryForTest = getProviderCategory(formData.provider_type);
      const providerMetaForTest = PROVIDERS.find(
        (p) => p.value === resolveCatalogProviderType(formData.provider_type)
      );
      const includeLlmFields = categoryForTest === 'chat' || categoryForTest === 'coding';
      const includeEmbeddingFields =
        categoryForTest === 'embedding' ||
        (categoryForTest === 'chat' && !!providerMetaForTest?.hasEmbedding);
      const includeRerankerFields =
        categoryForTest === 'reranker' ||
        (categoryForTest === 'chat' && !!providerMetaForTest?.hasNativeRerank);

      const testData: ProviderCreate = {
        name: formData.name || `${formData.provider_type}-connection-test`,
        provider_type: formData.provider_type,
        api_key: formData.api_key,
        base_url: formData.base_url || undefined,
        llm_model: includeLlmFields ? formData.llm_model : undefined,
        llm_small_model: includeLlmFields ? formData.llm_small_model || undefined : undefined,
        embedding_model: includeEmbeddingFields ? formData.embedding_model || undefined : undefined,
        reranker_model: includeRerankerFields ? formData.reranker_model || undefined : undefined,
        config: formData.config,
        is_active: formData.is_active,
        is_default: formData.is_default,
        pool_enabled: formData.pool_enabled,
        pool_weight: formData.pool_weight,
        ...(formData.model_tier ? { model_tier: formData.model_tier } : {}),
        secondary_models: formData.secondary_models,
      };

      const health = await providerAPI.testConnection(testData);
      setTestResult(formatProviderHealthResult(health, t));
    } catch (err) {
      setTestResult({
        success: false,
        message: getProviderErrorMessage(err, t('tenant.providers.connectionTest.failed')),
      });
    } finally {
      setIsTesting(false);
    }
  }, [formData, isEditing, provider?.id, t]);

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
      const embeddingProviderOptions = parseConfigJson(
        formData.embedding_provider_options_json || '{}'
      );
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
      if (embeddingProviderOptions && Object.keys(embeddingProviderOptions).length > 0) {
        embeddingConfig.provider_options = embeddingProviderOptions;
      }

      const config = { ...formData.config };
      if (Object.keys(embeddingConfig).length > 0) {
        config.embedding = embeddingConfig;
      } else {
        delete config.embedding;
      }

      if (provider) {
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
          pool_enabled: formData.pool_enabled,
          pool_weight: formData.pool_weight,
          model_tier: formData.model_tier ? formData.model_tier : null,
          secondary_models: formData.secondary_models,
        };
        if (!showLlmFields) {
          delete updateData.llm_model;
          delete updateData.llm_small_model;
        }
        if (!showEmbeddingFields) {
          delete updateData.embedding_model;
          delete updateData.embedding_config;
        }
        if (!showRerankerFields) {
          delete updateData.reranker_model;
        }
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
          pool_enabled: formData.pool_enabled,
          pool_weight: formData.pool_weight,
          ...(formData.model_tier ? { model_tier: formData.model_tier } : {}),
          secondary_models: formData.secondary_models,
        };
        if (!showLlmFields) {
          delete createData.llm_model;
          delete createData.llm_small_model;
        }
        if (!showEmbeddingFields) {
          delete createData.embedding_model;
          delete createData.embedding_config;
        }
        if (!showRerankerFields) {
          delete createData.reranker_model;
        }
        await providerAPI.create(createData);
      }
      onSuccess();
    } catch (err: unknown) {
      setError(getProviderErrorMessage(err, 'Failed to save provider'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const getLlmOptions = () => {
    const customModelOptionLabel = t('components.provider.config.customModelNameOption', {
      defaultValue: 'Custom model name...',
    });
    const catalogProvider = resolveCatalogProviderType(formData.provider_type);
    const fallbackLlmModels =
      availableModels.chat.length > 0
        ? availableModels.chat
        : [...availableModels.embedding, ...availableModels.rerank];
    const chatModels = Array.from(
      new Set([
        ...fallbackLlmModels,
        ...(Array.isArray(modelSearchResults) ? modelSearchResults : [])
          .filter(
            (m) =>
              m.provider === catalogProvider &&
              (m.capabilities.includes('chat') ||
                (availableModels.chat.length === 0 &&
                  (m.capabilities.includes('embedding') ||
                    m.capabilities.includes('rerank') ||
                    m.capabilities.includes('reranking'))))
          )
          .map((m) => m.name),
      ])
    );
    return [
      ...chatModels.map((m) => ({ value: m, label: m })),
      { value: '__custom__', label: customModelOptionLabel },
    ];
  };

  const getEmbeddingOptions = () => {
    const customModelOptionLabel = t('components.provider.config.customModelNameOption', {
      defaultValue: 'Custom model name...',
    });
    const catalogProvider = resolveCatalogProviderType(formData.provider_type);
    const embedModels = Array.from(
      new Set([
        ...availableModels.embedding,
        ...(Array.isArray(modelSearchResults) ? modelSearchResults : [])
          .filter((m) => m.capabilities.includes('embedding') && m.provider === catalogProvider)
          .map((m) => m.name),
      ])
    );
    return [
      ...embedModels.map((m) => ({ value: m, label: m })),
      { value: '__custom__', label: customModelOptionLabel },
    ];
  };

  const getRerankerOptions = () => {
    const customModelOptionLabel = t('components.provider.config.customModelNameOption', {
      defaultValue: 'Custom model name...',
    });
    const catalogProvider = resolveCatalogProviderType(formData.provider_type);
    const rerankModels = Array.from(
      new Set([
        ...availableModels.rerank,
        ...(Array.isArray(modelSearchResults) ? modelSearchResults : [])
          .filter(
            (m) =>
              (m.capabilities.includes('reranking') || m.name.includes('rerank')) &&
              m.provider === catalogProvider
          )
          .map((m) => m.name),
      ])
    );
    return [
      ...rerankModels.map((m) => ({ value: m, label: m })),
      { value: '__custom__', label: customModelOptionLabel },
    ];
  };

  const category = getProviderCategory(formData.provider_type);
  const providerMeta = PROVIDERS.find(
    (p) => p.value === resolveCatalogProviderType(formData.provider_type)
  );
  const showLlmFields = category === 'chat' || category === 'coding';
  const showEmbeddingFields =
    category === 'embedding' || (category === 'chat' && !!providerMeta?.hasEmbedding);
  const showRerankerFields =
    category === 'reranker' || (category === 'chat' && !!providerMeta?.hasNativeRerank);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-slate-950/60 transition-opacity" onClick={onClose} />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative w-full max-w-4xl overflow-hidden rounded-lg bg-white shadow-lg dark:bg-slate-800">
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-slate-50/80 dark:bg-slate-900/40">
            <div>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
                {isEditing
                  ? t('components.provider.config.editTitle', {
                      defaultValue: 'Edit Provider',
                    })
                  : t('components.provider.config.addTitle', {
                      defaultValue: 'Add New Provider',
                    })}
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t('components.provider.config.subtitle', {
                  defaultValue: 'Configure your LLM provider settings',
                })}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('components.provider.config.close', {
                defaultValue: isEditing ? 'Close edit provider' : 'Close add provider',
              })}
              title={t('components.provider.config.close', {
                defaultValue: isEditing ? 'Close edit provider' : 'Close add provider',
              })}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <X size={20} />
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
                        className={`flex items-center justify-center w-8 h-8 rounded-lg border transition-[color,background-color,border-color,box-shadow,opacity,transform] ${
                          isCompleted
                            ? 'bg-primary border-primary text-white'
                            : isCurrent
                              ? 'border-primary text-primary bg-white dark:bg-slate-800'
                              : 'border-slate-200 dark:border-slate-700 text-slate-400'
                        }`}
                      >
                        {isCompleted ? <Check size={16} /> : <step.icon size={16} />}
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
                    {t('components.provider.config.chooseProviderTitle', {
                      defaultValue: 'Choose Your LLM Provider',
                    })}
                  </h3>
                  <p className="text-slate-500 dark:text-slate-400">
                    {t('components.provider.config.chooseProviderDescription', {
                      defaultValue: 'Select from supported AI model providers',
                    })}
                  </p>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {PROVIDERS.map((p) => (
                    <button
                      type="button"
                      key={p.value}
                      onClick={() => {
                        void handleProviderSelect(p.value);
                      }}
                      className={`p-4 rounded-lg border transition-[color,background-color,border-color,box-shadow,opacity] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 text-left hover:shadow-md ${
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
                {!isEditing && envProviders[formData.provider_type] && (
                  <div className="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-start gap-3">
                    <Sparkles size={20} className="text-green-600 dark:text-green-400 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-medium text-green-800 dark:text-green-300">
                        {t('components.provider.config.envDetectedTitle', {
                          defaultValue: 'Environment Variables Detected',
                        })}
                      </h4>
                      <p className="text-xs text-green-600 dark:text-green-400 mt-0.5">
                        {t('components.provider.config.envDetectedDescription', {
                          defaultValue:
                            'We found configuration in your environment variables. The fields below have been auto-filled.',
                        })}
                      </p>
                    </div>
                  </div>
                )}
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      {t('components.provider.config.providerName', {
                        defaultValue: 'Provider Name',
                      })}
                    </label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => {
                        setFormData({ ...formData, name: e.target.value });
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder={t('components.provider.config.providerNamePlaceholder', {
                        defaultValue: 'My OpenAI Provider',
                      })}
                    />
                  </div>

                  {providerTypeRequiresApiKey(formData.provider_type) && (
                    <div>
                      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                        {t('components.provider.config.apiKey', { defaultValue: 'API Key' })}
                        {!isEditing && envProviders[formData.provider_type]?.api_key && (
                          <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                            {t('components.provider.config.fromEnv', { defaultValue: 'From ENV' })}
                          </span>
                        )}
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={formData.api_key}
                          onChange={(e) => {
                            setFormData({ ...formData, api_key: e.target.value });
                          }}
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                          placeholder={
                            PROVIDERS.find((p) => p.value === formData.provider_type)
                              ?.apiKeyPlaceholder || 'sk-...'
                          }
                        />
                        <button
                          type="button"
                          onClick={() => {
                            void handleTestConnection();
                          }}
                          disabled={isTesting || (!formData.api_key && !provider?.id)}
                          className="px-4 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 font-medium"
                        >
                          {isTesting ? (
                            <Loader2
                              size={18}
                              className="animate-spin motion-reduce:animate-none"
                            />
                          ) : (
                            t('common.test', { defaultValue: 'Test' })
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
                      {t('components.provider.config.baseUrl', { defaultValue: 'Base URL' })}{' '}
                      <span className="font-normal text-slate-500">
                        ({t('common.optional', { defaultValue: 'Optional' })})
                      </span>
                      {!isEditing && envProviders[formData.provider_type]?.base_url && (
                        <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                          {t('components.provider.config.fromEnv', { defaultValue: 'From ENV' })}
                        </span>
                      )}
                    </label>
                    <input
                      type="url"
                      value={formData.base_url}
                      onChange={(e) => {
                        setFormData({ ...formData, base_url: e.target.value });
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="https://api.example.com"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      {t('components.provider.config.providerConfigurationJson', {
                        defaultValue: 'Provider Configuration (JSON)',
                      })}
                    </label>
                    <textarea
                      value={configJsonStr}
                      onChange={(e) => {
                        setConfigJsonStr(e.target.value);
                        try {
                          const parsed = parseConfigJson(e.target.value);
                          if (parsed) {
                            setFormData({ ...formData, config: parsed });
                          }
                        } catch (_err) {
                          // Ignore invalid JSON while typing
                        }
                      }}
                      className="w-full px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent font-mono text-sm"
                      rows={4}
                      placeholder="{}"
                    />
                  </div>

                  {/* Volcengine RTC Configuration */}
                  {(formData.provider_type === 'volcengine' ||
                    formData.provider_type.startsWith('volcengine_')) && (
                    <div className="border border-slate-200 dark:border-slate-600 rounded-lg overflow-hidden">
                      <button
                        type="button"
                        onClick={() => {
                          const el = document.getElementById('rtc-config-section');
                          if (el) el.classList.toggle('hidden');
                        }}
                        className="w-full px-4 py-3 flex items-center justify-between bg-slate-50 dark:bg-slate-700/50 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
                      >
                        <div className="flex items-center gap-2">
                          <Phone size={18} className="text-primary" />
                          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                            Voice & Video Call Settings (RTC)
                          </span>
                        </div>
                        <ChevronDown size={18} className="text-slate-400" />
                      </button>
                      <div
                        id="rtc-config-section"
                        className="hidden p-4 space-y-3 border-t border-slate-200 dark:border-slate-600"
                      >
                        <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                          {t('components.provider.config.rtcDescription', {
                            defaultValue:
                              'Configure Volcengine RTC for real-time voice and video AI conversations. Leave blank to use environment variables as fallback.',
                          })}
                        </p>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            RTC App ID
                          </label>
                          <input
                            type="text"
                            value={formData.config.rtc_app_id ?? ''}
                            onChange={(e) => {
                              const newConfig = { ...formData.config, rtc_app_id: e.target.value };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t('components.provider.config.rtcAppIdPlaceholder', {
                              defaultValue: 'Your RTC App ID',
                            })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            RTC App Key
                          </label>
                          <input
                            type="password"
                            value={formData.config.rtc_app_key ?? ''}
                            onChange={(e) => {
                              const newConfig = { ...formData.config, rtc_app_key: e.target.value };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t('components.provider.config.rtcAppKeyPlaceholder', {
                              defaultValue: 'Your RTC App Key',
                            })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            Volcengine Access Key (AK)
                          </label>
                          <input
                            type="password"
                            value={formData.config.volc_ak ?? ''}
                            onChange={(e) => {
                              const newConfig = { ...formData.config, volc_ak: e.target.value };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t('components.provider.config.accessKeyPlaceholder', {
                              defaultValue: 'Your Volcengine Access Key',
                            })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            Volcengine Secret Key (SK)
                          </label>
                          <input
                            type="password"
                            value={formData.config.volc_sk ?? ''}
                            onChange={(e) => {
                              const newConfig = { ...formData.config, volc_sk: e.target.value };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t('components.provider.config.secretKeyPlaceholder', {
                              defaultValue: 'Your Volcengine Secret Key',
                            })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            Speech App ID
                          </label>
                          <input
                            type="text"
                            value={formData.config.speech_app_id ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                speech_app_id: e.target.value,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t('components.provider.config.speechAppIdPlaceholder', {
                              defaultValue: 'Speech App ID from Volcengine Speech Console',
                            })}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            Speech Access Token
                          </label>
                          <input
                            type="password"
                            value={formData.config.speech_access_token ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                speech_access_token: e.target.value,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t(
                              'components.provider.config.speechAccessTokenPlaceholder',
                              {
                                defaultValue: 'Access Token from Volcengine Speech Console',
                              }
                            )}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            {t('components.provider.config.doubaoEndpointId', {
                              defaultValue: 'Doubao Endpoint ID',
                            })}
                          </label>
                          <input
                            type="text"
                            value={formData.config.doubao_endpoint_id ?? ''}
                            onChange={(e) => {
                              const newConfig = {
                                ...formData.config,
                                doubao_endpoint_id: e.target.value,
                              };
                              setFormData({ ...formData, config: newConfig });
                              setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                            }}
                            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-primary focus:border-transparent"
                            placeholder={t('components.provider.config.endpointIdPlaceholder', {
                              defaultValue: 'Doubao model endpoint ID for voice chat',
                            })}
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-6 pt-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formData.is_active}
                        onChange={(e) => {
                          setFormData({ ...formData, is_active: e.target.checked });
                        }}
                        className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                      />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        {t('components.provider.config.active', {
                          defaultValue: 'Active',
                        })}
                      </span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formData.is_default}
                        onChange={(e) => {
                          setFormData({ ...formData, is_default: e.target.checked });
                        }}
                        className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                      />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        {t('components.provider.config.setAsDefault', {
                          defaultValue: 'Set as Default',
                        })}
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
                    <Loader2 size={16} className="animate-spin motion-reduce:animate-none" />
                    {t('components.provider.config.fetchingModels', {
                      defaultValue: 'Fetching available models...',
                    })}
                  </div>
                )}

                {/* Primary LLM Model */}
                {showLlmFields && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                        {t('components.provider.config.primaryLlmModel', {
                          defaultValue: 'Primary LLM Model',
                        })}
                      </label>
                      {useCustomModel.llm ? (
                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={formData.llm_model}
                            onChange={(e) => {
                              setFormData({ ...formData, llm_model: e.target.value });
                            }}
                            placeholder={t('components.provider.config.customModelPlaceholder', {
                              defaultValue: 'Enter custom model name',
                            })}
                            className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                          />
                          <button
                            type="button"
                            onClick={() => {
                              setUseCustomModel({ ...useCustomModel, llm: false });
                              const primaryModel = resolvePrimaryLlmModel(availableModels);
                              setFormData({
                                ...formData,
                                llm_model: primaryModel,
                              });
                            }}
                            className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                            title={t('components.provider.config.usePresetModel', {
                              defaultValue: 'Use preset model',
                            })}
                          >
                            <List size={18} />
                          </button>
                        </div>
                      ) : (
                        <Select
                          showSearch={{ onSearch: searchModels, filterOption: filterModelOption }}
                          value={formData.llm_model}
                          onChange={(value) => {
                            if (value === '__custom__') {
                              setUseCustomModel({ ...useCustomModel, llm: true });
                              setFormData({ ...formData, llm_model: '' });
                            } else {
                              setFormData({ ...formData, llm_model: value });
                            }
                          }}
                          options={getLlmOptions()}
                          className="w-full h-[42px] custom-ant-select"
                          disabled={isLoadingModels}
                          placeholder={
                            isLoadingModels
                              ? t('components.provider.config.loadingModels', {
                                  defaultValue: 'Loading models...',
                                })
                              : t('components.provider.config.selectModel', {
                                  defaultValue: 'Select a model',
                                })
                          }
                        />
                      )}
                    </div>

                    {/* Model Info Card */}
                    {selectedModelMeta && (
                      <div className="p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg border border-slate-200 dark:border-slate-600 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">
                            {t('components.provider.config.modelInfo', {
                              defaultValue: 'Model Info',
                            })}
                          </span>
                          {selectedModelMeta.is_deprecated && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 rounded">
                              {t('components.provider.config.deprecated', {
                                defaultValue: 'Deprecated',
                              })}
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <div>
                            <span className="text-slate-400 dark:text-slate-500">
                              {t('components.provider.config.context', { defaultValue: 'Context' })}
                            </span>
                            <div className="font-medium text-slate-700 dark:text-slate-300">
                              {formatCompactCount(selectedModelMeta.context_length)}
                            </div>
                          </div>
                          <div>
                            <span className="text-slate-400 dark:text-slate-500">
                              {t('components.provider.config.maxOutput', {
                                defaultValue: 'Max Output',
                              })}
                            </span>
                            <div className="font-medium text-slate-700 dark:text-slate-300">
                              {formatCompactCount(selectedModelMeta.max_output_tokens)}
                            </div>
                          </div>
                          <div>
                            <span className="text-slate-400 dark:text-slate-500">
                              {t('components.provider.config.costPerMillion', {
                                defaultValue: 'Cost ($/1M)',
                              })}
                            </span>
                            <div className="font-medium text-slate-700 dark:text-slate-300">
                              {formatModelCost(
                                selectedModelMeta.input_cost_per_1m,
                                selectedModelMeta.output_cost_per_1m
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {selectedModelMeta.reasoning && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 rounded">
                              Reasoning
                            </span>
                          )}
                          {selectedModelMeta.supports_tool_call && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 rounded">
                              Tools
                            </span>
                          )}
                          {selectedModelMeta.capabilities.includes('vision') && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 rounded">
                              Vision
                            </span>
                          )}
                          {selectedModelMeta.supports_structured_output && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 rounded">
                              Structured
                            </span>
                          )}
                          {selectedModelMeta.supports_temperature && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400 rounded">
                              Temperature
                            </span>
                          )}
                          {selectedModelMeta.open_weights && (
                            <span className="px-1.5 py-0.5 text-2xs font-medium bg-slate-200 text-slate-700 dark:bg-slate-600 dark:text-slate-300 rounded">
                              Open
                            </span>
                          )}
                        </div>
                        {selectedModelMeta.knowledge_cutoff && (
                          <div className="text-2xs text-slate-400 dark:text-slate-500">
                            Knowledge cutoff: {selectedModelMeta.knowledge_cutoff}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}

                {/* Small/Fast Model */}
                {showLlmFields && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      {t('components.provider.config.smallFastModelOptional', {
                        defaultValue: 'Small/Fast Model (Optional)',
                      })}
                    </label>
                    {useCustomModel.small ? (
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={formData.llm_small_model}
                          onChange={(e) => {
                            setFormData({ ...formData, llm_small_model: e.target.value });
                          }}
                          placeholder={t('components.provider.config.customModelPlaceholder', {
                            defaultValue: 'Enter custom model name',
                          })}
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setUseCustomModel({ ...useCustomModel, small: false });
                            const primaryModel =
                              formData.llm_model || resolvePrimaryLlmModel(availableModels);
                            setFormData({
                              ...formData,
                              llm_small_model: resolveSmallLlmModel(availableModels, primaryModel),
                            });
                          }}
                          className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                          title={t('components.provider.config.usePresetModel', {
                            defaultValue: 'Use preset model',
                          })}
                        >
                          <List size={18} />
                        </button>
                      </div>
                    ) : (
                      <Select
                        showSearch={{ onSearch: searchModels, filterOption: filterModelOption }}
                        allowClear
                        value={formData.llm_small_model || undefined}
                        onChange={(value) => {
                          if (value === '__custom__') {
                            setUseCustomModel({ ...useCustomModel, small: true });
                            setFormData({ ...formData, llm_small_model: '' });
                          } else {
                            setFormData({ ...formData, llm_small_model: value || '' });
                          }
                        }}
                        options={getLlmOptions()}
                        className="w-full h-[42px] custom-ant-select"
                        disabled={isLoadingModels}
                      />
                    )}
                  </div>
                )}

                {/* Advanced LLM Settings */}
                {showLlmFields && (
                  <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
                    <button
                      type="button"
                      onClick={() => {
                        setShowAdvancedLLM(!showAdvancedLLM);
                      }}
                      className="w-full px-4 py-3 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
                    >
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Advanced LLM Settings
                      </span>
                      {showAdvancedLLM ? (
                        <ChevronUp size={20} className="text-slate-500" />
                      ) : (
                        <ChevronDown size={20} className="text-slate-500" />
                      )}
                    </button>

                    {showAdvancedLLM && (
                      <div className="p-4 space-y-4 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
                        <div className="grid grid-cols-2 gap-4">
                          {selectedModelMeta?.supports_temperature !== false && (
                            <div>
                              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                                Temperature
                              </label>
                              <div className="flex items-center gap-3">
                                <div style={{ flex: 1 }}>
                                  <Slider
                                    min={selectedModelMeta?.temperature_range?.[0] ?? 0}
                                    max={selectedModelMeta?.temperature_range?.[1] ?? 2}
                                    step={0.01}
                                    value={
                                      typeof formData.config.temperature === 'number'
                                        ? formData.config.temperature
                                        : (selectedModelMeta?.temperature_range?.[0] ?? 0)
                                    }
                                    onChange={(val) => {
                                      const newConfig = {
                                        ...formData.config,
                                        temperature: toNullableNumber(val),
                                      };
                                      setFormData({ ...formData, config: newConfig });
                                      setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                    }}
                                  />
                                </div>
                                <InputNumber
                                  min={selectedModelMeta?.temperature_range?.[0] ?? 0}
                                  max={selectedModelMeta?.temperature_range?.[1] ?? 2}
                                  step={0.01}
                                  size="small"
                                  className="w-20"
                                  value={formData.config.temperature ?? null}
                                  onChange={(val) => {
                                    const newConfig = {
                                      ...formData.config,
                                      temperature: toNullableNumber(val),
                                    };
                                    setFormData({ ...formData, config: newConfig });
                                    setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                  }}
                                />
                              </div>
                            </div>
                          )}
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              Max Tokens
                            </label>
                            <InputNumber
                              min={1}
                              size="small"
                              className="w-full"
                              placeholder={
                                selectedModelMeta?.max_output_tokens
                                  ? `Max: ${selectedModelMeta.max_output_tokens.toLocaleString()}`
                                  : 'e.g. 4096'
                              }
                              value={formData.config.max_tokens ?? null}
                              onChange={(val) => {
                                const newConfig = {
                                  ...formData.config,
                                  max_tokens: toNullableNumber(val),
                                };
                                setFormData({ ...formData, config: newConfig });
                                setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                              }}
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                          {selectedModelMeta?.supports_top_p !== false && (
                            <div>
                              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                                Top P
                              </label>
                              <div className="flex items-center gap-3">
                                <div style={{ flex: 1 }}>
                                  <Slider
                                    min={selectedModelMeta?.top_p_range?.[0] ?? 0}
                                    max={selectedModelMeta?.top_p_range?.[1] ?? 1}
                                    step={0.01}
                                    value={
                                      typeof formData.config.top_p === 'number'
                                        ? formData.config.top_p
                                        : (selectedModelMeta?.top_p_range?.[0] ?? 0)
                                    }
                                    onChange={(val) => {
                                      const newConfig = {
                                        ...formData.config,
                                        top_p: toNullableNumber(val),
                                      };
                                      setFormData({ ...formData, config: newConfig });
                                      setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                    }}
                                  />
                                </div>
                                <InputNumber
                                  min={selectedModelMeta?.top_p_range?.[0] ?? 0}
                                  max={selectedModelMeta?.top_p_range?.[1] ?? 1}
                                  step={0.01}
                                  size="small"
                                  className="w-20"
                                  value={formData.config.top_p ?? null}
                                  onChange={(val) => {
                                    const newConfig = {
                                      ...formData.config,
                                      top_p: toNullableNumber(val),
                                    };
                                    setFormData({ ...formData, config: newConfig });
                                    setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                  }}
                                />
                              </div>
                            </div>
                          )}
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              Timeout (seconds)
                            </label>
                            <InputNumber
                              min={1}
                              size="small"
                              className="w-full"
                              placeholder="e.g. 120"
                              value={formData.config.timeout_seconds ?? null}
                              onChange={(val) => {
                                const newConfig = {
                                  ...formData.config,
                                  timeout_seconds: toNullableNumber(val),
                                };
                                setFormData({ ...formData, config: newConfig });
                                setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                              }}
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                          {selectedModelMeta?.supports_frequency_penalty !== false && (
                            <div>
                              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                                Frequency Penalty
                              </label>
                              <div className="flex items-center gap-3">
                                <div style={{ flex: 1 }}>
                                  <Slider
                                    min={-2}
                                    max={2}
                                    step={0.1}
                                    value={
                                      typeof formData.config.frequency_penalty === 'number'
                                        ? formData.config.frequency_penalty
                                        : 0
                                    }
                                    onChange={(val) => {
                                      const newConfig = {
                                        ...formData.config,
                                        frequency_penalty: toNullableNumber(val),
                                      };
                                      setFormData({ ...formData, config: newConfig });
                                      setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                    }}
                                  />
                                </div>
                                <InputNumber
                                  min={-2}
                                  max={2}
                                  step={0.1}
                                  size="small"
                                  className="w-20"
                                  value={formData.config.frequency_penalty ?? null}
                                  onChange={(val) => {
                                    const newConfig = {
                                      ...formData.config,
                                      frequency_penalty: toNullableNumber(val),
                                    };
                                    setFormData({ ...formData, config: newConfig });
                                    setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                  }}
                                />
                              </div>
                            </div>
                          )}
                          {selectedModelMeta?.supports_presence_penalty !== false && (
                            <div>
                              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                                Presence Penalty
                              </label>
                              <div className="flex items-center gap-3">
                                <div style={{ flex: 1 }}>
                                  <Slider
                                    min={-2}
                                    max={2}
                                    step={0.1}
                                    value={
                                      typeof formData.config.presence_penalty === 'number'
                                        ? formData.config.presence_penalty
                                        : 0
                                    }
                                    onChange={(val) => {
                                      const newConfig = {
                                        ...formData.config,
                                        presence_penalty: toNullableNumber(val),
                                      };
                                      setFormData({ ...formData, config: newConfig });
                                      setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                    }}
                                  />
                                </div>
                                <InputNumber
                                  min={-2}
                                  max={2}
                                  step={0.1}
                                  size="small"
                                  className="w-20"
                                  value={formData.config.presence_penalty ?? null}
                                  onChange={(val) => {
                                    const newConfig = {
                                      ...formData.config,
                                      presence_penalty: toNullableNumber(val),
                                    };
                                    setFormData({ ...formData, config: newConfig });
                                    setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                  }}
                                />
                              </div>
                            </div>
                          )}
                        </div>

                        {selectedModelMeta?.supports_seed !== false && (
                          <div className="grid grid-cols-2 gap-4">
                            <div>
                              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                                Seed
                              </label>
                              <InputNumber
                                size="small"
                                className="w-full"
                                placeholder="e.g. 42"
                                precision={0}
                                value={formData.config.seed ?? null}
                                onChange={(val) => {
                                  const newConfig = {
                                    ...formData.config,
                                    seed: toNullableNumber(val),
                                  };
                                  setFormData({ ...formData, config: newConfig });
                                  setConfigJsonStr(JSON.stringify(newConfig, null, 2));
                                }}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Embedding Model */}
                {showEmbeddingFields && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      {category === 'embedding'
                        ? t('components.provider.config.embeddingModel', {
                            defaultValue: 'Embedding Model',
                          })
                        : t('components.provider.config.embeddingModelOptional', {
                            defaultValue: 'Embedding Model (Optional)',
                          })}
                    </label>
                    {useCustomModel.embedding ? (
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={formData.embedding_model}
                          onChange={(e) => {
                            setFormData({ ...formData, embedding_model: e.target.value });
                          }}
                          placeholder={t('components.provider.config.customModelPlaceholder', {
                            defaultValue: 'Enter custom model name',
                          })}
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setUseCustomModel({ ...useCustomModel, embedding: false });
                            setFormData({
                              ...formData,
                              embedding_model: availableModels.embedding[0] ?? '',
                            });
                          }}
                          className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                          title={t('components.provider.config.usePresetModel', {
                            defaultValue: 'Use preset model',
                          })}
                        >
                          <List size={18} />
                        </button>
                      </div>
                    ) : (
                      <Select
                        showSearch={{ onSearch: searchModels, filterOption: filterModelOption }}
                        allowClear
                        value={formData.embedding_model || undefined}
                        onChange={(value) => {
                          if (value === '__custom__') {
                            setUseCustomModel({ ...useCustomModel, embedding: true });
                            setFormData({ ...formData, embedding_model: '' });
                          } else {
                            setFormData({ ...formData, embedding_model: value || '' });
                          }
                        }}
                        options={getEmbeddingOptions()}
                        className="w-full h-[42px] custom-ant-select"
                        disabled={isLoadingModels}
                      />
                    )}
                  </div>
                )}

                {/* Advanced Embedding Settings */}
                {showEmbeddingFields && formData.embedding_model && (
                  <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
                    <button
                      type="button"
                      onClick={() => {
                        setShowAdvancedEmbedding(!showAdvancedEmbedding);
                      }}
                      className="w-full px-4 py-3 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
                    >
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        Advanced Embedding Settings
                      </span>
                      {showAdvancedEmbedding ? (
                        <ChevronUp size={20} className="text-slate-500" />
                      ) : (
                        <ChevronDown size={20} className="text-slate-500" />
                      )}
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
                              onChange={(e) => {
                                setFormData({ ...formData, embedding_dimensions: e.target.value });
                              }}
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
                              onChange={(e) => {
                                setFormData({
                                  ...formData,
                                  embedding_encoding_format: e.target
                                    .value as EmbeddingEncodingFormat,
                                });
                              }}
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            >
                              <option value="">
                                {t('components.provider.config.default', {
                                  defaultValue: 'Default',
                                })}
                              </option>
                              <option value="float">
                                {t('components.provider.config.float', { defaultValue: 'Float' })}
                              </option>
                              <option value="base64">
                                {t('components.provider.config.base64', { defaultValue: 'Base64' })}
                              </option>
                            </select>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              {t('components.provider.config.userIdOptional', {
                                defaultValue: 'User ID (Optional)',
                              })}
                            </label>
                            <input
                              type="text"
                              value={formData.embedding_user}
                              onChange={(e) => {
                                setFormData({ ...formData, embedding_user: e.target.value });
                              }}
                              placeholder={t('components.provider.config.userIdPlaceholder', {
                                defaultValue: 'End-user ID',
                              })}
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                              {t('components.provider.config.timeoutMs', {
                                defaultValue: 'Timeout (ms)',
                              })}
                            </label>
                            <input
                              type="number"
                              value={formData.embedding_timeout}
                              onChange={(e) => {
                                setFormData({ ...formData, embedding_timeout: e.target.value });
                              }}
                              placeholder="e.g. 30000"
                              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
                            />
                          </div>
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                            {t('components.provider.config.providerOptionsJson', {
                              defaultValue: 'Provider Options (JSON)',
                            })}
                          </label>
                          <textarea
                            value={formData.embedding_provider_options_json}
                            onChange={(e) => {
                              setFormData({
                                ...formData,
                                embedding_provider_options_json: e.target.value,
                              });
                            }}
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
                {showRerankerFields && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      {category === 'reranker'
                        ? t('components.provider.config.rerankerModel', {
                            defaultValue: 'Reranker Model',
                          })
                        : t('components.provider.config.rerankerModelOptional', {
                            defaultValue: 'Reranker Model (Optional)',
                          })}
                    </label>
                    {useCustomModel.reranker ? (
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={formData.reranker_model}
                          onChange={(e) => {
                            setFormData({ ...formData, reranker_model: e.target.value });
                          }}
                          placeholder={t('components.provider.config.customModelPlaceholder', {
                            defaultValue: 'Enter custom model name',
                          })}
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary focus:border-transparent"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setUseCustomModel({ ...useCustomModel, reranker: false });
                            setFormData({
                              ...formData,
                              reranker_model: availableModels.rerank[0] ?? '',
                            });
                          }}
                          className="px-3 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
                          title={t('components.provider.config.usePresetModel', {
                            defaultValue: 'Use preset model',
                          })}
                        >
                          <List size={18} />
                        </button>
                      </div>
                    ) : (
                      <Select
                        showSearch={{ onSearch: searchModels, filterOption: filterModelOption }}
                        allowClear
                        value={formData.reranker_model || undefined}
                        onChange={(value) => {
                          if (value === '__custom__') {
                            setUseCustomModel({ ...useCustomModel, reranker: true });
                            setFormData({ ...formData, reranker_model: '' });
                          } else {
                            setFormData({ ...formData, reranker_model: value || '' });
                          }
                        }}
                        options={getRerankerOptions()}
                        className="w-full h-[42px] custom-ant-select"
                        disabled={isLoadingModels}
                        placeholder={t('components.provider.config.selectOrEnterCustomModel', {
                          defaultValue: 'Select or enter custom model...',
                        })}
                      />
                    )}
                  </div>
                )}

                {/* Pool & Routing (load-balancing / auto-routing) */}
                {showLlmFields && (
                  <div className="mt-4 p-4 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/40 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
                          {t('components.provider.config.poolRouting', {
                            defaultValue: 'Pool & Routing',
                          })}
                        </h4>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                          {t('components.provider.config.poolRoutingDescription', {
                            defaultValue:
                              'Controls whether this provider participates in the tenant LLM pool (load balancing + auto-routing). Turn off to silence a broken provider without disabling it entirely.',
                          })}
                        </p>
                      </div>
                      <label className="flex items-center gap-2 cursor-pointer shrink-0 ml-4">
                        <input
                          type="checkbox"
                          checked={formData.pool_enabled}
                          onChange={(e) => {
                            setFormData({ ...formData, pool_enabled: e.target.checked });
                          }}
                          className="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary"
                        />
                        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                          {t('components.provider.config.poolEnabled', {
                            defaultValue: 'Pool enabled',
                          })}
                        </span>
                      </label>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                          {t('components.provider.config.poolWeight', {
                            defaultValue: 'Pool weight',
                          })}
                          <span className="text-slate-400 font-normal ml-1">
                            {t('components.provider.config.poolWeightHint', {
                              defaultValue: '(>= 0, default 1.0)',
                            })}
                          </span>
                        </label>
                        <InputNumber
                          value={formData.pool_weight}
                          onChange={(v) => {
                            setFormData({
                              ...formData,
                              pool_weight: typeof v === 'number' && v >= 0 ? v : 1.0,
                            });
                          }}
                          min={0}
                          step={0.1}
                          disabled={!formData.pool_enabled}
                          className="w-full"
                        />
                      </div>

                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                          {t('components.provider.config.modelTier', {
                            defaultValue: 'Model tier',
                          })}
                          <span className="text-slate-400 font-normal ml-1">
                            ({t('common.optional', { defaultValue: 'Optional' })})
                          </span>
                        </label>
                        <Select
                          value={formData.model_tier || undefined}
                          onChange={(value) => {
                            setFormData({
                              ...formData,
                              model_tier: value ?? '',
                            });
                          }}
                          allowClear
                          placeholder="auto"
                          options={[
                            {
                              value: 'small',
                              label: t('components.provider.config.modelTierSmall', {
                                defaultValue: 'small',
                              }),
                            },
                            {
                              value: 'medium',
                              label: t('components.provider.config.modelTierMedium', {
                                defaultValue: 'medium',
                              }),
                            },
                            {
                              value: 'large',
                              label: t('components.provider.config.modelTierLarge', {
                                defaultValue: 'large',
                              }),
                            },
                          ]}
                          className="w-full h-[36px] custom-ant-select"
                          disabled={!formData.pool_enabled}
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                        {t('components.provider.config.secondaryModels', {
                          defaultValue: 'Secondary models',
                        })}
                        <span className="text-slate-400 font-normal ml-1">
                          {t('components.provider.config.secondaryModelsHint', {
                            defaultValue: '(extra model names sharing this API key)',
                          })}
                        </span>
                      </label>
                      <Select
                        mode="tags"
                        value={formData.secondary_models}
                        onChange={(values: string[]) => {
                          setFormData({ ...formData, secondary_models: values });
                        }}
                        tokenSeparators={[',', ' ']}
                        placeholder={t('components.provider.config.secondaryModelsPlaceholder', {
                          defaultValue: 'Type a model name and press Enter',
                        })}
                        className="w-full custom-ant-select"
                        disabled={!formData.pool_enabled}
                      />
                    </div>
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
                    {showLlmFields && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">
                          {t('components.provider.config.primaryModel', {
                            defaultValue: 'Primary Model:',
                          })}
                        </span>
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
                              {t('components.provider.config.custom', { defaultValue: 'Custom' })}
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    {showLlmFields && formData.llm_small_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">
                          {t('components.provider.config.smallModel', {
                            defaultValue: 'Small Model:',
                          })}
                        </span>
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
                              {t('components.provider.config.custom', { defaultValue: 'Custom' })}
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    {showEmbeddingFields && formData.embedding_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">
                          {t('components.provider.config.embedding', {
                            defaultValue: 'Embedding:',
                          })}
                        </span>
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
                              {t('components.provider.config.custom', { defaultValue: 'Custom' })}
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    {showRerankerFields && formData.reranker_model && (
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-500">
                          {t('components.provider.config.reranker', { defaultValue: 'Reranker:' })}
                        </span>
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
                              {t('components.provider.config.custom', { defaultValue: 'Custom' })}
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">
                        {t('components.provider.config.status', { defaultValue: 'Status:' })}
                      </span>
                      <span
                        className={`font-medium ${
                          formData.is_active ? 'text-green-600' : 'text-slate-500'
                        }`}
                      >
                        {formData.is_active
                          ? t('common.status.active')
                          : t('common.status.inactive')}
                      </span>
                    </div>
                    {/* RTC Configuration Summary */}
                    {(formData.provider_type === 'volcengine' ||
                      formData.provider_type.startsWith('volcengine_')) &&
                      (formData.config.rtc_app_id ||
                        formData.config.volc_ak ||
                        formData.config.doubao_endpoint_id) && (
                        <div className="border-t border-slate-200 dark:border-slate-600 pt-2 mt-2">
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <Phone size={14} className="text-primary" />
                            <span className="text-xs font-medium text-slate-500">
                              {t('components.provider.config.rtcTitle', {
                                defaultValue: 'Voice & Video Call (RTC)',
                              })}
                            </span>
                          </div>
                          {formData.config.rtc_app_id && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.rtcAppId', {
                                  defaultValue: 'RTC App ID:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                {formData.config.rtc_app_id}
                              </span>
                            </div>
                          )}
                          {formData.config.rtc_app_key && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.rtcAppKey', {
                                  defaultValue: 'RTC App Key:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                ********
                              </span>
                            </div>
                          )}
                          {formData.config.volc_ak && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.accessKey', {
                                  defaultValue: 'Access Key:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                ********
                              </span>
                            </div>
                          )}
                          {formData.config.volc_sk && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.secretKey', {
                                  defaultValue: 'Secret Key:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                ********
                              </span>
                            </div>
                          )}
                          {formData.config.speech_app_id && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.speechAppId', {
                                  defaultValue: 'Speech App ID:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                {formData.config.speech_app_id}
                              </span>
                            </div>
                          )}
                          {formData.config.speech_access_token && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.speechAccessToken', {
                                  defaultValue: 'Speech Access Token:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                ********
                              </span>
                            </div>
                          )}
                          {formData.config.doubao_endpoint_id && (
                            <div className="flex justify-between text-sm">
                              <span className="text-slate-500">
                                {t('components.provider.config.endpointId', {
                                  defaultValue: 'Endpoint ID:',
                                })}
                              </span>
                              <span className="font-medium text-slate-900 dark:text-white">
                                {formData.config.doubao_endpoint_id}
                              </span>
                            </div>
                          )}
                        </div>
                      )}
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
              type="button"
              onClick={
                currentStep === 'provider'
                  ? onClose
                  : () => {
                      setCurrentStep(
                        steps[steps.findIndex((s) => s.key === currentStep) - 1]?.key ?? 'provider'
                      );
                    }
              }
              className="px-4 py-2 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
            >
              {currentStep === 'provider'
                ? t('common.cancel', { defaultValue: 'Cancel' })
                : t('common.back', { defaultValue: 'Back' })}
            </button>

            <div className="flex items-center gap-3">
              {currentStep === 'review' ? (
                <button
                  type="button"
                  onClick={() => {
                    void handleSubmit();
                  }}
                  disabled={isSubmitting}
                  className="px-6 py-2.5 bg-primary text-white font-medium rounded-lg hover:bg-primary-dark transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <span className="flex items-center gap-2">
                      <Loader2 size={18} className="animate-spin motion-reduce:animate-none" />
                      Saving...
                    </span>
                  ) : (
                    'Save Provider'
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setCurrentStep(
                      steps[steps.findIndex((s) => s.key === currentStep) + 1]?.key ?? 'review'
                    );
                  }}
                  disabled={!canProceed()}
                  className="px-6 py-2.5 bg-primary text-white font-medium rounded-lg hover:bg-primary-dark transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
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
