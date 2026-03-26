/**
 * useActiveModelCapabilities Hook
 *
 * Resolves the effective LLM model's capability flags from the provider store.
 * Uses optional conversation-level model override first, then falls back to
 * the default active provider model, and finds the corresponding
 * ModelCatalogEntry to expose per-model feature support (vision, temperature,
 * penalty params, etc.).
 *
 * Used by LlmOverridePopover to gate parameter controls and by InputBar
 * to gate file-attachment UI based on model capabilities.
 */

import { useMemo } from 'react';

import { useShallow } from 'zustand/react/shallow';

import { useProviderStore } from '@/stores/provider';

import { findModelInCatalog, resolveCatalogProviderHint } from '@/utils/modelCatalog';

import type { ModelCatalogEntry, ProviderConfig } from '@/types/memory';

export interface ActiveModelCapabilities {
  /** The resolved catalog entry, or null when catalog is empty / model not found. */
  model: ModelCatalogEntry | null;
  /** True when the active model supports file / image attachments. */
  supportsAttachment: boolean;
  /** True when the active model supports the temperature parameter. */
  supportsTemperature: boolean;
  /** True when the active model supports the top_p parameter. */
  supportsTopP: boolean;
  /** True when the active model supports the frequency_penalty parameter. */
  supportsFrequencyPenalty: boolean;
  /** True when the active model supports the presence_penalty parameter. */
  supportsPresencePenalty: boolean;
  /** True when the active model supports the seed parameter. */
  supportsSeed: boolean;
  /** True when the active model supports the stop parameter. */
  supportsStop: boolean;
  /** True when the active model supports the response_format parameter. */
  supportsResponseFormat: boolean;
  /** Temperature slider range, e.g. [0, 2]. Falls back to [0, 2]. */
  temperatureRange: [number, number];
  /** Top-P slider range, e.g. [0, 1]. Falls back to [0, 1]. */
  topPRange: [number, number];
  /** Maximum output tokens for the model, used as upper bound for max_tokens input. */
  maxOutputTokens: number;
}

const DEFAULT_TEMPERATURE_RANGE: [number, number] = [0, 2];
const DEFAULT_TOP_P_RANGE: [number, number] = [0, 1];
const DEFAULT_MAX_OUTPUT_TOKENS = 128000;

const matchesProvider = (
  model: ModelCatalogEntry | null,
  providerHint: string | undefined
): boolean => {
  if (!model || !providerHint) return Boolean(model);
  return (model.provider ?? '').toLowerCase() === providerHint;
};

export function useActiveModelCapabilities(modelOverride?: string | null): ActiveModelCapabilities {
  const { providers, modelCatalog } = useProviderStore(
    useShallow((s) => ({
      providers: s.providers,
      modelCatalog: s.modelCatalog,
    }))
  );

  return useMemo(() => {
    // Find the default active provider
    const defaultProvider: ProviderConfig | undefined = providers.find(
      (p) => p.is_default && p.is_active
    );

    const normalizedOverride = modelOverride?.trim();
    const defaultModel = defaultProvider?.llm_model?.trim();
    const providerHint = resolveCatalogProviderHint(
      modelCatalog,
      defaultModel,
      defaultProvider?.provider_type
    );
    const defaultModelMeta = defaultModel ? findModelInCatalog(defaultModel, modelCatalog) : null;
    const overrideModelMeta = normalizedOverride
      ? findModelInCatalog(normalizedOverride, modelCatalog)
      : null;
    const shouldApplyOverride = matchesProvider(overrideModelMeta, providerHint);
    const model = shouldApplyOverride ? overrideModelMeta : defaultModelMeta;

    if (!model) {
      // No model resolved -- default to permissive (all params enabled)
      // so the UI doesn't block users when catalog hasn't loaded yet.
      return {
        model: null,
        supportsAttachment: true,
        supportsTemperature: true,
        supportsTopP: true,
        supportsFrequencyPenalty: true,
        supportsPresencePenalty: true,
        supportsSeed: true,
        supportsStop: true,
        supportsResponseFormat: true,
        temperatureRange: DEFAULT_TEMPERATURE_RANGE,
        topPRange: DEFAULT_TOP_P_RANGE,
        maxOutputTokens: DEFAULT_MAX_OUTPUT_TOKENS,
      };
    }

    return {
      model,
      supportsAttachment: model.supports_attachment,
      supportsTemperature: model.supports_temperature,
      supportsTopP: model.supports_top_p !== false,
      supportsFrequencyPenalty: model.supports_frequency_penalty !== false,
      supportsPresencePenalty: model.supports_presence_penalty !== false,
      supportsSeed: model.supports_seed === true,
      supportsStop: model.supports_stop !== false,
      supportsResponseFormat: model.supports_response_format === true,
      temperatureRange: model.temperature_range ?? DEFAULT_TEMPERATURE_RANGE,
      topPRange: model.top_p_range ?? DEFAULT_TOP_P_RANGE,
      maxOutputTokens:
        model.max_output_tokens > 0 ? model.max_output_tokens : DEFAULT_MAX_OUTPUT_TOKENS,
    };
  }, [modelOverride, providers, modelCatalog]);
}
