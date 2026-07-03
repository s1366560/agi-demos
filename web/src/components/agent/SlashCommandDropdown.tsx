/**
 * SlashCommandDropdown - Autocomplete dropdown for /commands and /skills
 *
 * Shows available commands and skills when user types "/" at the start of input.
 * Supports keyboard navigation (up/down/enter/escape) and click selection.
 */

import {
  Fragment,
  useState,
  useEffect,
  useRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  forwardRef,
  memo,
} from 'react';

import { useTranslation } from 'react-i18next';

import { Zap, Terminal } from 'lucide-react';

import { commandAPI } from '@/services/commandService';
import { skillAPI } from '@/services/skillService';

import type { CommandInfo, SkillResponse, SlashItem } from '@/types/agent';

const COMMAND_HINTS: Record<
  string,
  { labelKey: string; fallback: string; tone: 'blue' | 'amber' | 'slate' }
> = {
  plan: {
    labelKey: 'agent.slashCommand.hint.mode',
    fallback: 'Mode',
    tone: 'blue',
  },
  goal: {
    labelKey: 'agent.slashCommand.hint.checkpoint',
    fallback: 'Checkpoint',
    tone: 'blue',
  },
  status: {
    labelKey: 'agent.slashCommand.hint.readOnly',
    fallback: 'Read-only',
    tone: 'slate',
  },
  review: {
    labelKey: 'agent.slashCommand.hint.review',
    fallback: 'Review',
    tone: 'amber',
  },
};

function commandHint(command: CommandInfo) {
  return COMMAND_HINTS[command.name] ?? null;
}

function commandHintClass(tone: 'blue' | 'amber' | 'slate'): string {
  if (tone === 'blue') {
    return 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300';
  }
  if (tone === 'amber') {
    return 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-300';
  }
  return 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300';
}

export interface SlashCommandDropdownHandle {
  getSelectedItem: () => SlashItem | null;
}

interface SlashCommandDropdownProps {
  query: string;
  visible: boolean;
  onSelect: (item: SlashItem) => void;
  onClose: () => void;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
}

export const SlashCommandDropdown = memo(
  forwardRef<SlashCommandDropdownHandle, SlashCommandDropdownProps>(
    ({ query, visible, onSelect, selectedIndex, onSelectedIndexChange }, ref) => {
      const { t } = useTranslation();
      const [commands, setCommands] = useState<CommandInfo[]>([]);
      const [skills, setSkills] = useState<SkillResponse[]>([]);
      const [loading, setLoading] = useState(false);
      const [loaded, setLoaded] = useState(false);
      const listRef = useRef<HTMLDivElement>(null);
      const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());

      // Fetch commands and skills once when dropdown opens
      useEffect(() => {
        if (!visible || loaded) return;

        let cancelled = false;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLoading(true);

        void Promise.all([
          commandAPI.list().catch(() => ({ commands: [] })),
          skillAPI.list({ status: 'active', limit: 50 }).catch(() => ({ skills: [] })),
        ]).then(([cmdRes, skillRes]) => {
          if (!cancelled) {
            setCommands(Array.isArray(cmdRes.commands) ? cmdRes.commands : []);
            setSkills(Array.isArray(skillRes.skills) ? skillRes.skills : []);
            setLoaded(true);
            setLoading(false);
          }
        });

        return () => {
          cancelled = true;
        };
      }, [visible, loaded]);

      // Reset loaded state when dropdown closes
      useEffect(() => {
        if (!visible) {
          // eslint-disable-next-line react-hooks/set-state-in-effect
          setLoaded(false);
        }
      }, [visible]);

      const filteredCommands = useMemo(
        () =>
          commands.filter((cmd) => {
            if (!query) return true;
            const q = query.toLowerCase();
            return (
              cmd.name.toLowerCase().includes(q) ||
              (cmd.description || '').toLowerCase().includes(q)
            );
          }),
        [commands, query]
      );

      const filteredSkills = useMemo(
        () =>
          skills.filter((skill) => {
            if (!query) return true;
            const q = query.toLowerCase();
            return (
              skill.name.toLowerCase().includes(q) ||
              (skill.description || '').toLowerCase().includes(q)
            );
          }),
        [skills, query]
      );

      const unifiedList: SlashItem[] = useMemo(
        () => [
          ...filteredCommands.map((cmd) => ({ kind: 'command' as const, data: cmd })),
          ...filteredSkills.map((skill) => ({ kind: 'skill' as const, data: skill })),
        ],
        [filteredCommands, filteredSkills]
      );

      // Expose imperative handle for parent to get selected item
      useImperativeHandle(
        ref,
        () => ({
          getSelectedItem: () => {
            if (unifiedList.length === 0) return null;
            const idx = Math.min(selectedIndex, unifiedList.length - 1);
            return unifiedList[idx] ?? null;
          },
        }),
        [unifiedList, selectedIndex]
      );

      // Scroll selected item into view
      useEffect(() => {
        const item = itemRefs.current.get(selectedIndex);
        if (item) {
          item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      }, [selectedIndex]);

      // Clamp selected index when filtered list changes
      useEffect(() => {
        if (selectedIndex >= unifiedList.length && unifiedList.length > 0) {
          onSelectedIndexChange(Math.max(0, unifiedList.length - 1));
        }
      }, [unifiedList.length, selectedIndex, onSelectedIndexChange]);

      const handleItemClick = useCallback(
        (item: SlashItem) => {
          onSelect(item);
        },
        [onSelect]
      );

      if (!visible) return null;

      return (
        <div
          ref={listRef}
          className="absolute bottom-full left-0 right-0 mb-1 z-30 max-h-[280px] overflow-y-auto
          rounded-lg border border-slate-200 dark:border-slate-700
          bg-slate-50 dark:bg-slate-800
          shadow-lg shadow-slate-200/40 dark:shadow-slate-950/20"
        >
          {/* Header */}
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-700/50">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
              {loading
                ? t('agent.slashCommand.loading', 'Loading...')
                : query
                  ? unifiedList.length === 0
                    ? t('agent.slashCommand.noMatch', 'No matches for "{{query}}"', { query })
                    : t('agent.slashCommand.matching', 'Matching "{{query}}"', { query })
                  : t('agent.slashCommand.title', 'Commands & Skills')}
            </span>
          </div>

          {/* List */}
          {loading ? (
            <div className="px-3 py-4 text-center text-sm text-slate-400">
              {t('agent.slashCommand.loading', 'Loading...')}
            </div>
          ) : unifiedList.length === 0 ? (
            <div className="px-3 py-4 text-center text-sm text-slate-400">
              {query
                ? t('agent.slashCommand.noMatch', 'No matches for "{{query}}"', { query })
                : t('agent.slashCommand.noItems', 'No commands or skills available')}
            </div>
          ) : (
            <div className="py-1">
              {unifiedList.map((item, index) => {
                const isFirstCommand = item.kind === 'command' && index === 0;
                const isFirstSkill = item.kind === 'skill' && index === filteredCommands.length;
                const hint = item.kind === 'command' ? commandHint(item.data) : null;

                return (
                  <Fragment
                    key={`${item.kind}-${item.kind === 'command' ? item.data.name : item.data.id}`}
                  >
                    {isFirstCommand && (
                      <div className="px-3 py-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 bg-slate-50/50 dark:bg-slate-800/50">
                        {t('agent.slashCommand.groupCommands', 'Commands')}
                      </div>
                    )}
                    {isFirstSkill && (
                      <div className="px-3 py-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 bg-slate-50/50 dark:bg-slate-800/50">
                        {t('agent.slashCommand.groupSkills', 'Skills')}
                      </div>
                    )}
                    <div
                      ref={(el) => {
                        if (el) itemRefs.current.set(index, el);
                      }}
                      onClick={() => {
                        handleItemClick(item);
                      }}
                      onMouseEnter={() => {
                        onSelectedIndexChange(index);
                      }}
                      className={`
                        px-3 py-2 cursor-pointer flex items-start gap-3 transition-colors
                        ${
                          index === selectedIndex
                            ? 'bg-primary/8 dark:bg-primary/15'
                            : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                        }
                      `}
                    >
                      {item.kind === 'command' ? (
                        <>
                          {/* Command Icon */}
                          <div className="mt-0.5 flex-shrink-0 w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                            <Terminal size={14} className="text-amber-500" />
                          </div>
                          {/* Command Content */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                                /{item.data.name}
                              </span>
                              <span className="px-1.5 py-0.5 rounded text-2xs font-medium bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
                                {item.data.category}
                              </span>
                              {hint ? (
                                <span
                                  className={`px-1.5 py-0.5 rounded text-2xs font-medium ${commandHintClass(hint.tone)}`}
                                >
                                  {t(hint.labelKey, hint.fallback)}
                                </span>
                              ) : null}
                            </div>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-1">
                              {item.data.description}
                            </p>
                            <p className="mt-1 text-2xs text-slate-400 dark:text-slate-500">
                              {t('agent.slashCommand.commandBehavior', {
                                defaultValue:
                                  'Runs as a slash command; mutations still follow project permissions.',
                              })}
                            </p>
                          </div>
                        </>
                      ) : (
                        <>
                          {/* Skill Icon */}
                          <div className="mt-0.5 flex-shrink-0 w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-700 flex items-center justify-center">
                            <Zap size={14} className="text-primary" />
                          </div>
                          {/* Skill Content */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                                /{item.data.name}
                              </span>
                              {item.data.scope !== 'project' && (
                                <span className="px-1.5 py-0.5 rounded text-2xs font-medium bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
                                  {item.data.scope}
                                </span>
                              )}
                              <span className="px-1.5 py-0.5 rounded text-2xs font-medium bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                                {t('agent.slashCommand.hint.skill', 'Skill')}
                              </span>
                            </div>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-1">
                              {item.data.description}
                            </p>
                            <p className="mt-1 text-2xs text-slate-400 dark:text-slate-500">
                              {t('agent.slashCommand.skillBehavior', {
                                defaultValue:
                                  'Pins this skill to the next prompt without sending immediately.',
                              })}
                            </p>
                          </div>
                        </>
                      )}
                    </div>
                  </Fragment>
                );
              })}
            </div>
          )}

          {/* Footer hint */}
          <div className="px-3 py-1.5 border-t border-slate-100 dark:border-slate-700/50 flex items-center gap-3 text-2xs text-slate-400">
            <span>
              <kbd className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-700 font-mono">
                &uarr;&darr;
              </kbd>{' '}
              navigate
            </span>
            <span>
              <kbd className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-700 font-mono">
                Enter
              </kbd>{' '}
              select
            </span>
            <span>
              <kbd className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-700 font-mono">
                Esc
              </kbd>{' '}
              dismiss
            </span>
          </div>
        </div>
      );
    }
  )
);

SlashCommandDropdown.displayName = 'SlashCommandDropdown';

export default SlashCommandDropdown;
