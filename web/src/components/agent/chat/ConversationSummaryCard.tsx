/**
 * ConversationSummaryCard - Shows auto-generated conversation summary
 * Displayed at the top of a conversation's message area.
 */
import { memo, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import { FileText, RefreshCw, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';

interface ConversationSummaryCardProps {
  summary: string | null;
  conversationId: string;
  onRegenerate?: (() => Promise<void>) | undefined;
}

export const ConversationSummaryCard = memo<ConversationSummaryCardProps>(
  ({ summary, onRegenerate }) => {
    const { t } = useTranslation();
    const [collapsed, setCollapsed] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [regenerating, setRegenerating] = useState(false);

    const handleRegenerate = useCallback(async () => {
      if (!onRegenerate) return;
      setRegenerating(true);
      try {
        await onRegenerate();
      } catch {
        void message.error(
          t('agent.summary.regenerateError', 'Failed to regenerate summary. Please try again.')
        );
      } finally {
        setRegenerating(false);
      }
    }, [onRegenerate, t]);

    if (!summary) return null;
    if (collapsed) {
      return (
        <button
          type="button"
          onClick={() => {
            setCollapsed(false);
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors mx-auto mb-4"
        >
          <FileText size={12} />
          {t('agent.summary.showSummary', 'Show summary')}
          <ChevronDown size={12} />
        </button>
      );
    }

    return (
      <div className="mx-4 mb-4 px-4 py-3 bg-slate-50/70 dark:bg-slate-900/35 border border-slate-200/45 dark:border-slate-800/45 rounded-md shadow-[0_1px_2px_rgba(15,23,42,0.02)] animate-fade-in-up">
        <div className="flex items-start gap-2">
          <FileText size={14} className="text-primary mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium text-primary">
                {t('agent.summary.title', 'Conversation Summary')}
              </span>
              <button
                type="button"
                onClick={() => {
                  setCollapsed(true);
                }}
                aria-label={t('agent.summary.collapse', 'Collapse summary')}
                title={t('agent.summary.collapse', 'Collapse summary')}
                className="p-0.5 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400"
              >
                <ChevronUp size={12} />
              </button>
              {onRegenerate && (
                <button
                  type="button"
                  onClick={() => {
                    void handleRegenerate();
                  }}
                  disabled={regenerating}
                  className="p-0.5 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400"
                  aria-label={t('agent.summary.regenerate', 'Regenerate summary')}
                  title={t('agent.summary.regenerate', 'Regenerate summary')}
                >
                  {regenerating ? (
                    <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
                  ) : (
                    <RefreshCw size={12} />
                  )}
                </button>
              )}
            </div>
            <p
              className={`text-sm text-slate-600 dark:text-slate-300 leading-relaxed ${
                expanded ? '' : 'line-clamp-2'
              }`}
            >
              {summary}
            </p>
            <button
              type="button"
              onClick={() => {
                setExpanded((prev) => !prev);
              }}
              aria-expanded={expanded}
              className="mt-1 text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 rounded"
            >
              {expanded
                ? t('agent.summary.showLess', 'Show less')
                : t('agent.summary.showMore', 'Show more')}
            </button>
          </div>
        </div>
      </div>
    );
  }
);
ConversationSummaryCard.displayName = 'ConversationSummaryCard';
