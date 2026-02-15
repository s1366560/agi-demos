/**
 * SuggestionChips - Proactive follow-up suggestion pills
 *
 * Displays clickable suggestion chips below the last assistant message.
 * Chips auto-hide when the user sends a new message.
 */

import React, { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { ArrowUpRight } from 'lucide-react';

interface SuggestionChipsProps {
  suggestions: string[];
  onSelect: (suggestion: string) => void;
  visible?: boolean;
}

export const SuggestionChips: React.FC<SuggestionChipsProps> = memo(
  ({ suggestions, onSelect, visible = true }) => {
    const { t } = useTranslation();

    if (!visible || !suggestions || suggestions.length === 0) return null;

    return (
      <div className="flex items-start gap-3 mb-6 animate-fade-in-up">
        {/* Spacer to align with assistant messages (avatar width + gap) */}
        <div className="w-8 flex-shrink-0" />

        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <p className="text-xs text-slate-400 dark:text-slate-500 mb-2 font-medium">
            {t('agent.suggestions.label', 'Suggested follow-ups')}
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion, index) => (
              <button
                key={index}
                type="button"
                onClick={() => onSelect(suggestion)}
                className="
                  group/chip inline-flex items-center gap-1.5
                  px-3.5 py-2 rounded-full
                  bg-white dark:bg-slate-800
                  border border-slate-200 dark:border-slate-700
                  text-sm text-slate-600 dark:text-slate-300
                  hover:border-primary/50 hover:text-primary dark:hover:text-primary-300
                  hover:bg-primary/5 dark:hover:bg-primary/10
                  hover:shadow-sm
                  transition-all duration-200
                  cursor-pointer
                "
              >
                <span>{suggestion}</span>
                <ArrowUpRight
                  size={12}
                  className="text-slate-300 group-hover/chip:text-primary dark:group-hover/chip:text-primary-300 transition-colors"
                />
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }
);

SuggestionChips.displayName = 'SuggestionChips';
