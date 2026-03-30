import { memo, useCallback, useEffect, useMemo, useState } from 'react';

import { message, Popover, Select } from 'antd';
import { Bot } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useAgentV3Store } from '@/stores/agentV3';
import { useProviderStore } from '@/stores/provider';

import { agentService } from '@/services/agentService';

import { findModelInCatalog, normalizeProviderType } from '@/utils/modelCatalog';

import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

import type { ProviderConfig } from '@/types/memory';

interface ModelSwitchPopoverProps {
  conversationId: string | null;
  projectId?: string | undefined;
  disabled?: boolean;
}

const getDefaultProvider = (providers: ProviderConfig[]): ProviderConfig | undefined =>
  providers.find((p) => p.is_default && p.is_active);

export const ModelSwitchPopover = memo<ModelSwitchPopoverProps>(
  ({ conversationId, projectId, disabled }) => {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);

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
    const isOverrideValid = Boolean(
      modelOverride &&
      (!catalogLoaded ||
        (overrideModelMeta &&
          (activeProviderHints.size === 0 ||
            activeProviderHints.has((overrideModelMeta.provider || '').toLowerCase()))))
    );
    const activeModelOverride = isOverrideValid ? modelOverride : null;
    const effectiveModel = activeModelOverride || defaultModel;

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

    const handleOpenChange = useCallback(
      (visible: boolean) => {
        setOpen(visible);
        if (!visible) return;

        setLoading(true);
        void ensureModelDataLoaded().finally(() => {
          setLoading(false);
        });
      },
      [ensureModelDataLoaded]
    );

    useEffect(() => {
      if (loading || !conversationId || !modelOverride || !catalogLoaded) return;
      if (!isOverrideValid) {
        useAgentV3Store.getState().setLlmModelOverride(conversationId, null);
        return;
      }
      if (overrideModelMeta && overrideModelMeta.name !== modelOverride) {
        useAgentV3Store.getState().setLlmModelOverride(conversationId, overrideModelMeta.name);
      }
    }, [catalogLoaded, conversationId, isOverrideValid, loading, modelOverride, overrideModelMeta]);

    const handleSelect = useCallback(
      (value: string | undefined) => {
        if (!conversationId) return;
        const override = value ?? null;
        useAgentV3Store.getState().setLlmModelOverride(conversationId, override);
        if (projectId) {
          agentService
            .updateConversationConfig(conversationId, projectId, {
              llm_model_override: override,
            })
            .catch((err: unknown) => {
              void message.error(
                err instanceof Error ? err.message : 'Failed to update model override'
              );
              console.error('ModelSwitchPopover: update config failed', err);
            });
        }
      },
      [conversationId, projectId]
    );

    const handleReset = useCallback(() => {
      if (!conversationId) return;
      useAgentV3Store.getState().setLlmModelOverride(conversationId, null);
      if (projectId) {
        agentService
          .updateConversationConfig(conversationId, projectId, {
            llm_model_override: null,
          })
          .catch((err: unknown) => {
            void message.error(
              err instanceof Error ? err.message : 'Failed to reset model override'
            );
            console.error('ModelSwitchPopover: reset config failed', err);
          });
      }
    }, [conversationId, projectId]);

    const isOverrideActive = Boolean(activeModelOverride);

    const content = (
      <div className="w-80 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex flex-col">
            <span className="font-bold text-slate-800 dark:text-slate-100">Model</span>
            {effectiveModel && (
             <span className="text-2xs text-slate-400 dark:text-slate-500 truncate max-w-[220px]">
                 {effectiveModel}
               </span>
            )}
          </div>
          {isOverrideActive && (
            <button
              type="button"
              onClick={handleReset}
              className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
            >
              Reset
            </button>
          )}
        </div>

        <Select
          showSearch
          allowClear
          loading={loading}
          value={activeModelOverride || undefined}
          placeholder={defaultModel ? `Default: ${defaultModel}` : 'Select a model'}
          options={visibleModels.map((name) => ({ value: name, label: name }))}
          onChange={(value) => {
            handleSelect(value);
          }}
          notFoundContent={loading ? 'Loading models...' : 'No models available'}
        />
      </div>
    );

    return (
      <Popover
        content={content}
        trigger="click"
        open={open}
        onOpenChange={handleOpenChange}
        placement="top"
        styles={{ root: { width: 340 } }}
        arrow={false}
        destroyOnHidden
      >
        <div>
          <LazyTooltip title="Switch Model">
            <LazyButton
              type="text"
              size="small"
              icon={<Bot size={18} />}
              disabled={disabled}
              className={`
              text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
              hover:bg-slate-100 dark:hover:bg-slate-700/50
              rounded-lg h-8 w-8 flex items-center justify-center
              ${isOverrideActive ? 'text-primary bg-primary/5' : ''}
            `}
            />
          </LazyTooltip>
        </div>
      </Popover>
    );
  }
);

ModelSwitchPopover.displayName = 'ModelSwitchPopover';
