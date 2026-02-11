/**
 * ConversationSummaryCard - Shows auto-generated conversation summary
 * Displayed at the top of a conversation's message area.
 */
import { memo, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Sparkles, RefreshCw, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';

interface ConversationSummaryCardProps {
  summary: string | null;
  conversationId: string;
  onRegenerate?: () => Promise<void>;
}

export const ConversationSummaryCard = memo<ConversationSummaryCardProps>(
  ({ summary, onRegenerate }) => {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(false);
    const [regenerating, setRegenerating] = useState(false);

    const handleRegenerate = useCallback(async () => {
      if (!onRegenerate) return;
      setRegenerating(true);
      try {
        await onRegenerate();
      } finally {
        setRegenerating(false);
      }
    }, [onRegenerate]);

    if (!summary) return null;
    if (collapsed) {
      return (
        <button
          onClick={() => setCollapsed(false)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors mx-auto mb-4"
        >
          <Sparkles size={12} />
          {t('agent.summary.showSummary', 'Show summary')}
          <ChevronDown size={12} />
        </button>
      );
    }

    return (
      <div className="mx-4 mb-4 px-4 py-3 bg-gradient-to-r from-primary/5 to-transparent border border-primary/10 rounded-xl animate-fade-in-up">
        <div className="flex items-start gap-2">
          <Sparkles size={14} className="text-primary mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium text-primary">
                {t('agent.summary.title', 'Conversation Summary')}
              </span>
              <button
                onClick={() => setCollapsed(true)}
                className="p-0.5 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400"
              >
                <ChevronUp size={12} />
              </button>
              {onRegenerate && (
                <button
                  onClick={handleRegenerate}
                  disabled={regenerating}
                  className="p-0.5 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400"
                  title={t('agent.summary.regenerate', 'Regenerate summary')}
                >
                  {regenerating ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <RefreshCw size={12} />
                  )}
                </button>
              )}
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">{summary}</p>
          </div>
        </div>
      </div>
    );
  }
);
ConversationSummaryCard.displayName = 'ConversationSummaryCard';
