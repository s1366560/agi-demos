import { memo, useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import { ModelSwitchView } from '@business/agent/ui/web/chat/ModelSwitchView';
import { useShallow } from 'zustand/react/shallow';

import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';
import { useProviderStore } from '@/stores/provider';

import { agentService } from '@/services/agentService';

import { findModelInCatalog, normalizeProviderType } from '@/utils/modelCatalog';

import type { ProviderConfig } from '@/types/memory';

import type { TFunction } from 'i18next';

interface ModelSwitchPopoverProps {
  conversationId: string | null;
  projectId?: string | undefined;
  disabled?: boolean;
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

const getDefaultProvider = (providers: ProviderConfig[]): ProviderConfig | undefined =>
  providers.find((p) => p.is_default && p.is_active);

export const ModelSwitchPopover = memo<ModelSwitchPopoverProps>(
  ({ conversationId, projectId, disabled }) => {
    const { t } = useTranslation();
    const [isOpen, setIsOpen] = useState(false);

    const { providers, modelCatalog } = useProviderStore(
      useShallow((s) => ({
        providers: s.providers,
        modelCatalog: s.modelCatalog,
      }))
    );

    const modelOverride = useAgentV3Store((state) => {
      if (!conversationId) return null;
      const convState = state.conversationStates.get(conversationId);
      const ctx = convState?.appModelContext as Record<string, unknown> | null;
      const raw = ctx?.llm_model_override;
      if (typeof raw !== 'string') return null;
      const trimmed = raw.trim();
      return trimmed.length > 0 ? trimmed : null;
    });

    const defaultProvider = useMemo(() => getDefaultProvider(providers), [providers]);
    const defaultModel = defaultProvider?.llm_model?.trim() || null;
    const activeProviderHints = useMemo(() => {
      const hints = new Set<string>();
      for (const p of providers) {
        if (!p.is_active) continue;
        const normalized = normalizeProviderType(p.provider_type);
        if (normalized) hints.add(normalized);
      }
      return hints;
    }, [providers]);
    const overrideModelMeta = useMemo(
      () => (modelOverride ? findModelInCatalog(modelOverride, modelCatalog) : null),
      [modelCatalog, modelOverride]
    );

    const isAutoOverride = modelOverride?.toLowerCase() === 'auto';

    const visibleModels = useMemo(() => {
      let filtered = modelCatalog;
      if (activeProviderHints.size > 0 && modelCatalog.length > 0) {
        const providerFiltered = modelCatalog.filter((m) =>
          activeProviderHints.has((m.provider || '').toLowerCase())
        );
        if (providerFiltered.length > 0) {
          filtered = providerFiltered;
        }
      }

      const names = new Set<string>();
      filtered.forEach((m) => {
        const name = m.name.trim();
        if (name) names.add(name);
      });
      if (defaultModel) names.add(defaultModel);

      return Array.from(names).sort((a, b) => a.localeCompare(b));
    }, [activeProviderHints, defaultModel, modelCatalog]);

    const catalogLoaded = modelCatalog.length > 0;
    const isOverrideValid =
      isAutoOverride ||
      Boolean(
        modelOverride &&
        (!catalogLoaded ||
          (overrideModelMeta &&
            (activeProviderHints.size === 0 ||
              activeProviderHints.has((overrideModelMeta.provider || '').toLowerCase()))))
      );
    const activeModelOverride = isOverrideValid ? modelOverride : null;

    const ensureModelDataLoaded = useCallback(async () => {
      const state = useProviderStore.getState();

      if (state.providers.length === 0) {
        await state.fetchProviders();
      }

      const catalog = useProviderStore.getState().modelCatalog;
      if (catalog.length === 0) {
        await useProviderStore.getState().fetchModelCatalog();
      }
    }, []);

    useEffect(() => {
      if (!isOpen || !conversationId || !modelOverride || catalogLoaded) return;
      if (isAutoOverride) return;
      if (!isOverrideValid) {
        useAgentV3Store.getState().setLlmModelOverride(conversationId, null);
        return;
      }
      if (overrideModelMeta && overrideModelMeta.name !== modelOverride) {
        useAgentV3Store.getState().setLlmModelOverride(conversationId, overrideModelMeta.name);
      }
    }, [
      catalogLoaded,
      conversationId,
      isAutoOverride,
      isOverrideValid,
      isOpen,
      modelOverride,
      overrideModelMeta,
    ]);

    const persistOverride = useCallback(
      (override: string | null) => {
        if (!projectId) return;
        agentService
          .updateConversationConfig(conversationId ?? '', projectId, {
            llm_model_override: override,
          })
          .catch((err: unknown) => {
            void message.error(
              err instanceof Error
                ? err.message
                : tFallback(t, 'agent.modelSwitch.updateFailed', 'Failed to update model override')
            );
            console.error('ModelSwitchPopover: update config failed', err);
          });
      },
      [conversationId, projectId, t]
    );

    // Direct selection: one click on a list entry applies the override.
    const handleSelect = useCallback(
      (value: string | null) => {
        if (!conversationId) return;
        useAgentV3Store.getState().setLlmModelOverride(conversationId, value);
        persistOverride(value);
        setIsOpen(false);
      },
      [conversationId, persistOverride]
    );

    return (
      <ModelSwitchView
        activeModelOverride={activeModelOverride}
        defaultModel={defaultModel}
        visibleModels={visibleModels}
        modelsLoading={!catalogLoaded}
        disabled={disabled}
        onOpen={() => {
          setIsOpen(true);
          void ensureModelDataLoaded().catch(console.error);
        }}
        onSelect={handleSelect}
      />
    );
  }
);
ModelSwitchPopover.displayName = 'ModelSwitchPopover';
