import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Brain, Check, ChevronDown, Gauge, Rabbit, Turtle } from 'lucide-react';

import {
  THINKING_LEVELS,
  thinkingLevelToEffort,
  useAgentThinkingLevelStore,
  type AgentThinkingLevel,
} from '@/stores/agent/thinkingLevelStore';
import { useAgentV3Store } from '@/stores/agentV3';

import { agentService } from '@/services/agentService';


export interface ThinkingLevelSwitcherProps {
  conversationId: string | null;
  projectId?: string | undefined;
  disabled?: boolean | undefined;
}

const LEVEL_ICONS: Record<AgentThinkingLevel, React.ReactNode> = {
  default: <Gauge size={16} />,
  low: <Rabbit size={16} />,
  medium: <Brain size={16} />,
  high: <Turtle size={16} />,
};

const LEVEL_TITLE_KEYS: Record<AgentThinkingLevel, { key: string; fallback: string }> = {
  default: { key: 'agent.thinkingLevel.default', fallback: 'Thinking: auto' },
  low: { key: 'agent.thinkingLevel.low', fallback: 'Thinking: low' },
  medium: { key: 'agent.thinkingLevel.medium', fallback: 'Thinking: medium' },
  high: { key: 'agent.thinkingLevel.high', fallback: 'Thinking: high' },
};

const LEVEL_DESC_KEYS: Record<AgentThinkingLevel, { key: string; fallback: string }> = {
  default: { key: 'agent.thinkingLevel.defaultDesc', fallback: 'Follow the model default' },
  low: { key: 'agent.thinkingLevel.lowDesc', fallback: 'Fast, brief reasoning' },
  medium: { key: 'agent.thinkingLevel.mediumDesc', fallback: 'Balanced reasoning depth' },
  high: { key: 'agent.thinkingLevel.highDesc', fallback: 'Deepest reasoning, slower' },
};

export const ThinkingLevelSwitcher: React.FC<ThinkingLevelSwitcherProps> = ({
  conversationId,
  projectId,
  disabled = false,
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const level = useAgentThinkingLevelStore(
    (state) =>
      (conversationId ? state.levelsByConversation[conversationId] : undefined) ?? 'default'
  );
  const setThinkingLevel = useAgentThinkingLevelStore((state) => state.setThinkingLevel);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const handleSelect = useCallback(
    (nextLevel: AgentThinkingLevel) => {
      if (conversationId) {
        setThinkingLevel(conversationId, nextLevel);

        // Mirror into the wire payload (merged with other LLM overrides) and
        // persist server-side so the level survives reloads, mirroring the
        // model-switch behavior.
        const effort = thinkingLevelToEffort(nextLevel);
        useAgentV3Store.getState().setReasoningEffort(conversationId, effort ?? null);
        if (projectId) {
          const convState = useAgentV3Store
            .getState()
            .conversationStates.get(conversationId);
          const ctx = convState?.appModelContext ?? null;
          const overrides = (ctx?.llm_overrides as Record<string, unknown> | null) ?? null;
          agentService
            .updateConversationConfig(conversationId, projectId, {
              llm_overrides: overrides,
            })
            .catch((err: unknown) => {
              console.error('ThinkingLevelSwitcher: persist config failed', err);
            });
        }
      }
      setIsOpen(false);
    },
    [conversationId, projectId, setThinkingLevel]
  );

  const handleTriggerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (disabled) return;
      if (event.key === 'Escape' && isOpen) {
        event.preventDefault();
        setIsOpen(false);
      }
    },
    [disabled, isOpen]
  );

  const title = LEVEL_TITLE_KEYS[level];
  const isNonDefault = level !== 'default';

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          if (!disabled) setIsOpen((v) => !v);
        }}
        disabled={disabled}
        onKeyDown={handleTriggerKeyDown}
        title={t('agent.thinkingLevel.label', 'Thinking level')}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={`group flex h-8 items-center gap-1.5 px-2 text-sm rounded-lg transition-colors ${
          disabled
            ? 'cursor-not-allowed text-content-tertiary opacity-40'
            : `text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 ${
                isOpen ? 'text-primary bg-primary/5' : ''
              } ${isNonDefault && !isOpen ? 'text-primary' : ''}`
        }`}
      >
        <span className="shrink-0">{LEVEL_ICONS[level]}</span>
        <span className="hidden max-w-[152px] truncate min-w-0 text-xs font-medium min-[1024px]:inline">
          {t(title.key, title.fallback)}
        </span>
        <ChevronDown
          size={12}
          className={`shrink-0 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 shadow-lg shadow-slate-200/40 dark:shadow-slate-950/20">
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-700/50">
            <span className="text-xs text-slate-400">
              {t('agent.thinkingLevel.title', 'Thinking level')}
            </span>
          </div>
          <div className="py-1" role="listbox" aria-label={t('agent.thinkingLevel.title')}>
            {THINKING_LEVELS.map((candidate) => {
              const isSelected = candidate === level;
              const candidateTitle = LEVEL_TITLE_KEYS[candidate];
              const candidateDesc = LEVEL_DESC_KEYS[candidate];
              return (
                <button
                  key={candidate}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    handleSelect(candidate);
                  }}
                  className={`w-full text-left px-3 py-2 flex items-center justify-between gap-2 rounded-md text-sm transition-colors duration-150 cursor-pointer ${
                    isSelected
                      ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                      : 'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {LEVEL_ICONS[candidate]}
                    <div className="flex flex-col min-w-0">
                      <span className="font-medium truncate">
                        {t(candidateTitle.key, candidateTitle.fallback)}
                      </span>
                      <span className="text-xs text-slate-400 dark:text-slate-500 truncate">
                        {t(candidateDesc.key, candidateDesc.fallback)}
                      </span>
                    </div>
                  </div>
                  {isSelected && (
                    <Check size={16} className="text-blue-600 dark:text-blue-400 shrink-0" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

ThinkingLevelSwitcher.displayName = 'ThinkingLevelSwitcher';
