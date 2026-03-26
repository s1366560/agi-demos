import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Bot, ChevronDown, Check } from 'lucide-react';

import { useDefinitions, useListDefinitions } from '@/stores/agentDefinitions';

export interface AgentSwitcherProps {
  activeAgentId?: string | undefined;
  onSelect: (agentId: string) => void;
  className?: string | undefined;
  disabled?: boolean | undefined;
}

export const AgentSwitcher: React.FC<AgentSwitcherProps> = ({
  activeAgentId,
  onSelect,
  className = '',
  disabled = false,
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  useEffect(() => {
    if (definitions.length === 0) {
      listDefinitions().catch((err: unknown) => {
        console.error('Failed to load agent definitions', err);
      });
    }
  }, [definitions.length, listDefinitions]);

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

  const enabledDefinitions = useMemo(() => {
    return definitions.filter((d) => d.enabled);
  }, [definitions]);

  const activeAgent = useMemo(() => {
    if (!activeAgentId) return null;
    return definitions.find((d) => d.id === activeAgentId) || null;
  }, [definitions, activeAgentId]);

  const openMenu = useCallback(() => {
    const activeIndex = enabledDefinitions.findIndex((d) => d.id === activeAgentId);
    setSelectedIndex(activeIndex >= 0 ? activeIndex : 0);
    setIsOpen(true);
  }, [enabledDefinitions, activeAgentId]);

  useEffect(() => {
    if (!isOpen || !listRef.current) return;
    const item = listRef.current.children[selectedIndex] as HTMLElement | undefined;
    item?.scrollIntoView({ block: 'nearest' });
  }, [isOpen, selectedIndex]);

  const handleSelect = useCallback(
    (agentId: string) => {
      onSelect(agentId);
      setIsOpen(false);
    },
    [onSelect]
  );

  const handleTriggerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (disabled) return;

      if (!isOpen && (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        openMenu();
        return;
      }

      if (!isOpen) return;

      if (event.key === 'Escape') {
        event.preventDefault();
        setIsOpen(false);
        return;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, enabledDefinitions.length - 1));
        return;
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
        return;
      }

      if (event.key === 'Enter') {
        event.preventDefault();
        const target = enabledDefinitions[selectedIndex];
        if (target) {
          handleSelect(target.id);
        }
      }
    },
    [disabled, isOpen, enabledDefinitions, selectedIndex, handleSelect, openMenu]
  );

  return (
    <div className={`relative inline-block ${className}`} ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          if (disabled) return;
          if (isOpen) {
            setIsOpen(false);
            return;
          }
          openMenu();
        }}
        disabled={disabled}
        onKeyDown={handleTriggerKeyDown}
        className={`group flex h-8 items-center gap-1.5 px-2 text-sm rounded-lg transition-colors ${
          disabled
            ? 'cursor-not-allowed text-slate-400 dark:text-slate-500 opacity-40'
            : `text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 ${
                isOpen ? 'text-primary bg-primary/5' : ''
              }`
        }`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <Bot
          size={16}
          className={`shrink-0 ${disabled ? 'text-slate-400 dark:text-slate-500' : 'text-current'}`}
        />
        <span className="max-w-[152px] truncate min-w-0 text-xs font-medium">
          {activeAgent
            ? activeAgent.display_name || activeAgent.name
            : t('agent.selectAgent', 'Select Agent')}
        </span>
        <ChevronDown
          size={12}
          className={`shrink-0 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-2xl">
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-700/50">
            <span className="text-xs text-slate-400">
              {t('agent.availableAgents', 'Available Agents')}
            </span>
          </div>
          <div
            ref={listRef}
            className="max-h-64 overflow-y-auto py-1"
            role="listbox"
            aria-label={t('agent.availableAgents', 'Available Agents')}
          >
            {enabledDefinitions.length === 0 ? (
              <div className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400 italic text-center">
                {t('agent.noAgentsAvailable', 'No agents available')}
              </div>
            ) : (
              enabledDefinitions.map((agent, index) => {
                const isSelected = agent.id === activeAgentId;
                const isFocused = index === selectedIndex;
                return (
                  <button
                    key={agent.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      handleSelect(agent.id);
                    }}
                    onMouseEnter={() => {
                      setSelectedIndex(index);
                    }}
                    className={`w-full text-left px-3 py-2 flex items-center justify-between rounded-md text-sm transition-colors cursor-pointer ${
                      isFocused || isSelected
                        ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                        : 'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'
                    }`}
                  >
                    <div className="flex flex-col overflow-hidden mr-2 min-w-0">
                      <span className="font-medium truncate max-w-full">
                        {agent.display_name || agent.name}
                      </span>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        <span
                          className={`text-[10px] leading-none px-1.5 py-0.5 rounded-sm border ${
                            agent.source === 'database'
                              ? 'bg-purple-50 text-purple-600 border-purple-200 dark:bg-purple-900/20 dark:text-purple-400 dark:border-purple-800/50'
                              : 'bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/20 dark:text-orange-400 dark:border-orange-800/50'
                          }`}
                        >
                          {agent.source === 'database' ? 'DB' : 'System'}
                        </span>
                        <span className="text-[10px] leading-none text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          {t('agent.enabled', 'Enabled')}
                        </span>
                      </div>
                    </div>
                    {isSelected && (
                      <Check size={16} className="text-blue-600 dark:text-blue-400 shrink-0" />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
};
