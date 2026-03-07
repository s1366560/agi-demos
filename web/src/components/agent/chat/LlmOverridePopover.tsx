import { memo, useCallback, useState } from 'react';

import { InputNumber, Popover, Slider } from 'antd';
import { Settings2 } from 'lucide-react';

import { useAgentV3Store } from '@/stores/agentV3';

import type { ActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';

import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

import type { LLMConfigOverrides } from '@/types/memory';

interface LlmOverridePopoverProps {
  conversationId: string | null;
  disabled?: boolean;
  capabilities?: ActiveModelCapabilities;
}

export const LlmOverridePopover = memo<LlmOverridePopoverProps>(
  ({ conversationId, disabled, capabilities }) => {
    const [open, setOpen] = useState(false);
    const [localOverrides, setLocalOverrides] = useState<LLMConfigOverrides>({});

    const syncFromStore = useCallback(() => {
      if (!conversationId) {
        setLocalOverrides({});
        return;
      }
      const state = useAgentV3Store.getState();
      const cs = state.conversationStates.get(conversationId);
      const storeOverrides = (cs?.appModelContext as Record<string, unknown> | null)
        ?.llm_overrides as LLMConfigOverrides | undefined;
      setLocalOverrides(storeOverrides || {});
    }, [conversationId]);

    const handleOpenChange = useCallback(
      (visible: boolean) => {
        if (visible) {
          syncFromStore();
        }
        setOpen(visible);
      },
      [syncFromStore]
    );

    const handleParamChange = (
      key: keyof Omit<LLMConfigOverrides, 'stop' | 'response_format'>,
      value: number | null
    ) => {
      const newOverrides: LLMConfigOverrides = { ...localOverrides };
      if (value === null) {
        const { [key]: _, ...rest } = newOverrides;
        setLocalOverrides(rest);

        if (conversationId) {
          const state = useAgentV3Store.getState();
          const isEmpty = Object.keys(rest).length === 0;
          state.setLlmOverrides(conversationId, isEmpty ? null : rest);
        }
        return;
      }

      newOverrides[key] = value;
      setLocalOverrides(newOverrides);

      if (conversationId) {
        const state = useAgentV3Store.getState();
        state.setLlmOverrides(conversationId, newOverrides);
      }
    };

    const handleReset = () => {
      setLocalOverrides({});
      if (conversationId) {
        useAgentV3Store.getState().setLlmOverrides(conversationId, null);
      }
    };

    const isActive = Object.keys(localOverrides).length > 0;

    // Resolve capability flags (default to permissive when capabilities not provided)
    const supportsTemperature = capabilities?.supportsTemperature ?? true;
    const supportsTopP = capabilities?.supportsTopP ?? true;
    const supportsFrequencyPenalty = capabilities?.supportsFrequencyPenalty ?? true;
    const supportsPresencePenalty = capabilities?.supportsPresencePenalty ?? true;
    const temperatureRange = capabilities?.temperatureRange ?? [0, 2];
    const topPRange = capabilities?.topPRange ?? [0, 1];
    const maxOutputTokens = capabilities?.maxOutputTokens ?? 128000;
    const modelName = capabilities?.model?.name;

    const hasAnyControl =
      supportsTemperature || supportsTopP || supportsFrequencyPenalty || supportsPresencePenalty;

    const content = (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div className="flex flex-col">
            <span className="font-bold text-slate-800 dark:text-slate-100">LLM Parameters</span>
            {modelName && (
              <span className="text-[10px] text-slate-400 dark:text-slate-500 truncate max-w-[200px]">
                {modelName}
              </span>
            )}
          </div>
          {isActive && (
            <button
              type="button"
              onClick={handleReset}
              className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
            >
              Reset
            </button>
          )}
        </div>

        <div className="flex flex-col gap-3">
          {/* Temperature */}
          {supportsTemperature && (
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Temperature
              </span>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <Slider
                    min={temperatureRange[0]}
                    max={temperatureRange[1]}
                    step={0.01}
                    value={localOverrides.temperature ?? 1}
                    onChange={(val) => {
                      handleParamChange('temperature', val);
                    }}
                  />
                </div>
                <InputNumber<number>
                  min={temperatureRange[0]}
                  max={temperatureRange[1]}
                  step={0.01}
                  size="small"
                  className="w-20"
                  value={localOverrides.temperature ?? null}
                  onChange={(val) => {
                    handleParamChange('temperature', val);
                  }}
                />
              </div>
            </div>
          )}

          {/* Top P */}
          {supportsTopP && (
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Top P</span>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <Slider
                    min={topPRange[0]}
                    max={topPRange[1]}
                    step={0.01}
                    value={localOverrides.top_p ?? 1}
                    onChange={(val) => {
                      handleParamChange('top_p', val);
                    }}
                  />
                </div>
                <InputNumber<number>
                  min={topPRange[0]}
                  max={topPRange[1]}
                  step={0.01}
                  size="small"
                  className="w-20"
                  value={localOverrides.top_p ?? null}
                  onChange={(val) => {
                    handleParamChange('top_p', val);
                  }}
                />
              </div>
            </div>
          )}

          {/* Max Tokens (always shown -- every model has output token limits) */}
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Max Tokens
            </span>
            <InputNumber<number>
              min={1}
              max={maxOutputTokens}
              size="small"
              className="w-full"
              placeholder={`e.g. 4096 (max ${String(maxOutputTokens)})`}
              value={localOverrides.max_tokens ?? null}
              onChange={(val) => {
                handleParamChange('max_tokens', val);
              }}
            />
          </div>

          {/* Frequency Penalty */}
          {supportsFrequencyPenalty && (
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Freq. Penalty
              </span>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <Slider
                    min={-2}
                    max={2}
                    step={0.1}
                    value={localOverrides.frequency_penalty ?? 0}
                    onChange={(val) => {
                      handleParamChange('frequency_penalty', val);
                    }}
                  />
                </div>
                <InputNumber<number>
                  min={-2}
                  max={2}
                  step={0.1}
                  size="small"
                  className="w-20"
                  value={localOverrides.frequency_penalty ?? null}
                  onChange={(val) => {
                    handleParamChange('frequency_penalty', val);
                  }}
                />
              </div>
            </div>
          )}

          {/* Presence Penalty */}
          {supportsPresencePenalty && (
            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Pres. Penalty
              </span>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <Slider
                    min={-2}
                    max={2}
                    step={0.1}
                    value={localOverrides.presence_penalty ?? 0}
                    onChange={(val) => {
                      handleParamChange('presence_penalty', val);
                    }}
                  />
                </div>
                <InputNumber<number>
                  min={-2}
                  max={2}
                  step={0.1}
                  size="small"
                  className="w-20"
                  value={localOverrides.presence_penalty ?? null}
                  onChange={(val) => {
                    handleParamChange('presence_penalty', val);
                  }}
                />
              </div>
            </div>
          )}

          {/* No controls available message */}
          {!hasAnyControl && (
            <div className="text-xs text-slate-400 dark:text-slate-500 text-center py-2">
              No tunable parameters for this model
            </div>
          )}
        </div>
      </div>
    );

    return (
      <Popover
        content={content}
        trigger="click"
        open={open}
        onOpenChange={handleOpenChange}
        placement="top"
        styles={{ root: { width: 320 } }}
        arrow={false}
        destroyOnHidden
      >
        <div>
          <LazyTooltip title="LLM Parameters">
            <LazyButton
              type="text"
              size="small"
              icon={<Settings2 size={18} />}
              disabled={disabled}
              className={`
                text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                hover:bg-slate-100 dark:hover:bg-slate-700/50
                rounded-lg h-8 w-8 flex items-center justify-center
                ${isActive ? 'text-primary bg-primary/5' : ''}
              `}
            />
          </LazyTooltip>
        </div>
      </Popover>
    );
  }
);

LlmOverridePopover.displayName = 'LlmOverridePopover';
