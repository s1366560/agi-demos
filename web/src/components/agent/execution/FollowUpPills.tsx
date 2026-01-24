/**
 * FollowUpPills - Suggested follow-up questions
 *
 * Displays clickable suggestion pills for common follow-up queries.
 */

import { MaterialIcon } from '../shared';

export interface FollowUpPillsProps {
  /** Suggested follow-up questions */
  suggestions?: string[];
  /** Callback when a suggestion is clicked */
  onSuggestionClick?: (suggestion: string) => void;
  /** Maximum number of suggestions to show */
  maxSuggestions?: number;
}

/**
 * FollowUpPills component
 *
 * @example
 * <FollowUpPills
 *   suggestions={[
 *     "What are the key trends?",
 *     "Show me more details",
 *     "Compare with last quarter"
 *   ]}
 *   onSuggestionClick={(s) => sendMessage(s)}
 * />
 */
export function FollowUpPills({
  suggestions = [],
  onSuggestionClick,
  maxSuggestions = 4,
}: FollowUpPillsProps) {
  const displaySuggestions = suggestions.slice(0, maxSuggestions);

  if (displaySuggestions.length === 0) {
    return null;
  }

  return (
    <div className="w-full">
      <p className="text-sm text-slate-500 mb-3">Suggested follow-ups:</p>
      <div className="flex flex-wrap gap-2">
        {displaySuggestions.map((suggestion, index) => (
          <button
            key={index}
            onClick={() => onSuggestionClick?.(suggestion)}
            className="group inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-100 dark:bg-slate-800 hover:bg-primary/10 dark:hover:bg-primary/20 text-slate-700 dark:text-slate-300 hover:text-primary transition-colors text-sm font-medium"
          >
            <span>{suggestion}</span>
            <MaterialIcon
              name="add_circle"
              size={16}
              className="opacity-0 group-hover:opacity-100 transition-opacity text-primary"
            />
          </button>
        ))}
      </div>
    </div>
  );
}

export default FollowUpPills;
