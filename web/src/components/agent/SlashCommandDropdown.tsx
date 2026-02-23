/**
 * SlashCommandDropdown - Skill autocomplete dropdown for /skill-name commands
 *
 * Shows available skills when user types "/" at the start of input.
 * Supports keyboard navigation (up/down/enter/escape) and click selection.
 */

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useImperativeHandle,
  forwardRef,
  memo,
} from 'react';

import { useTranslation } from 'react-i18next';

import { Zap, Hash, Brain, Sparkles } from 'lucide-react';

import { skillAPI } from '@/services/skillService';

import type { SkillResponse } from '@/types/agent';

export interface SlashCommandDropdownHandle {
  getSelectedSkill: () => SkillResponse | null;
}

interface SlashCommandDropdownProps {
  query: string;
  visible: boolean;
  onSelect: (skill: SkillResponse) => void;
  onClose: () => void;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
}

const triggerTypeIcon = (type: string) => {
  switch (type) {
    case 'keyword':
      return <Hash size={12} className="text-blue-500" />;
    case 'semantic':
      return <Brain size={12} className="text-purple-500" />;
    case 'hybrid':
      return <Sparkles size={12} className="text-amber-500" />;
    default:
      return <Zap size={12} className="text-slate-400" />;
  }
};

export const SlashCommandDropdown = memo(
  forwardRef<SlashCommandDropdownHandle, SlashCommandDropdownProps>(
    ({ query, visible, onSelect, selectedIndex, onSelectedIndexChange }, ref) => {
      const { t } = useTranslation();
      const [skills, setSkills] = useState<SkillResponse[]>([]);
      const [loading, setLoading] = useState(false);
      const [loaded, setLoaded] = useState(false);
      const listRef = useRef<HTMLDivElement>(null);
      const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());

      // Fetch skills once when dropdown opens
      useEffect(() => {
        if (!visible || loaded) return;

        let cancelled = false;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLoading(true);

        skillAPI
          .list({ status: 'active', limit: 50 })
          .then((res) => {
            if (!cancelled) {
              setSkills(res.skills || []);
              setLoaded(true);
              setLoading(false);
            }
          })
          .catch(() => {
            if (!cancelled) {
              setSkills([]);
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

      // Filter skills by query
      const filteredSkills = skills.filter((skill) => {
        if (!query) return true;
        const q = query.toLowerCase();
        return (
          skill.name.toLowerCase().includes(q) ||
          (skill.description ?? '').toLowerCase().includes(q)
        );
      });

      // Expose imperative handle for parent to get selected skill
      useImperativeHandle(
        ref,
        () => ({
          getSelectedSkill: () => {
            if (filteredSkills.length === 0) return null;
            const idx = Math.min(selectedIndex, filteredSkills.length - 1);
            return filteredSkills[idx] ?? null;
          },
        }),
        [filteredSkills, selectedIndex]
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
        if (selectedIndex >= filteredSkills.length) {
          onSelectedIndexChange(Math.max(0, filteredSkills.length - 1));
        }
      }, [filteredSkills.length, selectedIndex, onSelectedIndexChange]);

      const handleItemClick = useCallback(
        (skill: SkillResponse) => {
          onSelect(skill);
        },
        [onSelect]
      );

      if (!visible) return null;

      return (
        <div
          ref={listRef}
          className="absolute bottom-full left-0 right-0 mb-1 z-30 max-h-[280px] overflow-y-auto
          rounded-xl border border-slate-200/80 dark:border-slate-700/80
          bg-white/95 dark:bg-slate-800/95 backdrop-blur-md
          shadow-xl shadow-slate-200/30 dark:shadow-black/30"
        >
          {/* Header */}
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-700/50">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
              {loading
                ? t('agent.slashCommand.loading', 'Loading skills...')
                : query
                  ? t('agent.slashCommand.matching', 'Skills matching "{{query}}"', { query })
                  : t('agent.slashCommand.title', 'Skills')}
            </span>
          </div>

          {/* Skills list */}
          {loading ? (
            <div className="px-3 py-4 text-center text-sm text-slate-400">
              {t('agent.slashCommand.loading', 'Loading...')}
            </div>
          ) : filteredSkills.length === 0 ? (
            <div className="px-3 py-4 text-center text-sm text-slate-400">
              {query
                ? t('agent.slashCommand.noMatch', 'No skills matching "{{query}}"', { query })
                : t('agent.slashCommand.noSkills', 'No active skills available')}
            </div>
          ) : (
            <div className="py-1">
              {filteredSkills.map((skill, index) => (
                <div
                  key={skill.id}
                  ref={(el) => {
                    if (el) itemRefs.current.set(index, el);
                  }}
                  onClick={() => handleItemClick(skill)}
                  onMouseEnter={() => onSelectedIndexChange(index)}
                  className={`
                  px-3 py-2 cursor-pointer flex items-start gap-3 transition-colors
                  ${
                    index === selectedIndex
                      ? 'bg-primary/8 dark:bg-primary/15'
                      : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                  }
                `}
                >
                  {/* Icon */}
                  <div className="mt-0.5 flex-shrink-0 w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-700 flex items-center justify-center">
                    <Zap size={14} className="text-primary" />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                        /{skill.name}
                      </span>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                        {triggerTypeIcon(skill.trigger_type)}
                        {skill.trigger_type}
                      </span>
                      {skill.scope !== 'project' && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
                          {skill.scope}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-1">
                      {skill.description}
                    </p>
                  </div>

                  {/* Usage count */}
                  {skill.usage_count > 0 && (
                    <span className="flex-shrink-0 text-[10px] text-slate-400 mt-1">
                      {skill.usage_count} uses
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Footer hint */}
          <div className="px-3 py-1.5 border-t border-slate-100 dark:border-slate-700/50 flex items-center gap-3 text-[10px] text-slate-400">
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
