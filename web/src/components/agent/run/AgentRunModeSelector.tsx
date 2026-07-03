import { memo, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Popover } from 'antd';
import { Lock, Play, ShieldCheck, Workflow } from 'lucide-react';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import type { AgentRunMode } from './agentRunViewModel';

export interface AgentRunModeSelectorProps {
  mode: AgentRunMode;
  disabled?: boolean | undefined;
  onModeChange?: ((mode: AgentRunMode) => void) | undefined;
}

const MODE_ICON: Record<AgentRunMode, React.ReactNode> = {
  plan: <Workflow size={14} />,
  build: <Play size={14} />,
  auto: <ShieldCheck size={14} />,
  readOnly: <Lock size={14} />,
};

export const AgentRunModeSelector = memo<AgentRunModeSelectorProps>(
  ({ mode, disabled, onModeChange }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    const options = useMemo(
      () => [
        {
          mode: 'plan' as const,
          label: t('agent.run.mode.plan', { defaultValue: 'Plan' }),
          description: t('agent.run.mode.planDescription', {
            defaultValue: 'Explore and propose a plan before editing.',
          }),
        },
        {
          mode: 'build' as const,
          label: t('agent.run.mode.build', { defaultValue: 'Build' }),
          description: t('agent.run.mode.buildDescription', {
            defaultValue: 'Run the normal edit and verify loop.',
          }),
        },
        {
          mode: 'auto' as const,
          label: t('agent.run.mode.auto', { defaultValue: 'Auto' }),
          description: t('agent.run.mode.autoDescription', {
            defaultValue: 'Build mode with fewer interruptions when policy allows.',
          }),
        },
        {
          mode: 'readOnly' as const,
          label: t('agent.run.mode.readOnly', { defaultValue: 'Read-only' }),
          description: t('agent.run.mode.readOnlyDescription', {
            defaultValue: 'Plan-mode execution with no file mutations.',
          }),
        },
      ],
      [t]
    );

    const activeOption = options.find((option) => option.mode === mode) ?? {
      mode: 'build' as const,
      label: t('agent.run.mode.build', { defaultValue: 'Build' }),
      description: t('agent.run.mode.buildDescription', {
        defaultValue: 'Run the normal edit and verify loop.',
      }),
    };

    const content = (
      <div className="w-72 p-1" data-testid="agent-run-mode-menu">
        <div className="px-2 pb-2 pt-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {t('agent.run.modeSelector.title', { defaultValue: 'Agent mode' })}
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t('agent.run.modeSelector.description', {
              defaultValue:
                'Auto and Read-only are UI-level intent presets in this release; backend approvals still use HITL.',
            })}
          </p>
        </div>
        <div className="space-y-1">
          {options.map((option) => (
            <button
              key={option.mode}
              type="button"
              onClick={() => {
                onModeChange?.(option.mode);
                setOpen(false);
              }}
              className={`flex w-full items-start gap-2 rounded-md px-2 py-2 text-left transition-colors ${
                option.mode === mode
                  ? 'bg-primary/10 text-primary dark:bg-primary/15'
                  : 'text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800'
              }`}
            >
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/70 dark:bg-slate-950/30">
                {MODE_ICON[option.mode]}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{option.label}</span>
                <span className="block text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {option.description}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>
    );

    return (
      <Popover
        content={content}
        trigger="click"
        open={open}
        onOpenChange={setOpen}
        placement="topRight"
        arrow={false}
        styles={{ content: { padding: 0 } }}
      >
        <LazyTooltip
          title={t('agent.run.modeSelector.tooltip', {
            defaultValue: 'Choose agent execution mode',
          })}
        >
          <button
            type="button"
            disabled={disabled}
            aria-label={t('agent.run.modeSelector.aria', {
              defaultValue: 'Choose agent execution mode',
            })}
            className="flex h-8 min-w-[5.75rem] items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 text-xs font-medium text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            data-testid="agent-run-mode-selector"
          >
            {MODE_ICON[mode]}
            <span className="truncate">{activeOption.label}</span>
          </button>
        </LazyTooltip>
      </Popover>
    );
  }
);

AgentRunModeSelector.displayName = 'AgentRunModeSelector';
