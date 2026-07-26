import { useEffect, useRef, useState } from 'react';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  FileTextIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

type ConversationSummaryCardProps = {
  conversationId: string;
  summary: string | null;
  regenerationAvailable: boolean;
  onRegenerate?: (conversationId: string) => Promise<void>;
};

export function ConversationSummaryCard({
  conversationId,
  summary,
  regenerationAvailable,
  onRegenerate,
}: ConversationSummaryCardProps) {
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [regenerationFailed, setRegenerationFailed] = useState(false);
  const requestGenerationRef = useRef(0);
  const visibleSummary = summary?.trim() ?? '';

  useEffect(() => {
    requestGenerationRef.current += 1;
    setCollapsed(false);
    setExpanded(false);
    setRegenerating(false);
    setRegenerationFailed(false);
  }, [conversationId]);

  if (!conversationId || !visibleSummary) return null;

  const regenerate = async () => {
    if (!regenerationAvailable || !onRegenerate || regenerating) return;
    const requestGeneration = requestGenerationRef.current + 1;
    requestGenerationRef.current = requestGeneration;
    setRegenerating(true);
    setRegenerationFailed(false);
    try {
      await onRegenerate(conversationId);
    } catch {
      if (requestGeneration === requestGenerationRef.current) {
        setRegenerationFailed(true);
      }
    } finally {
      if (requestGeneration === requestGenerationRef.current) {
        setRegenerating(false);
      }
    }
  };

  return (
    <section className="conversation-summary-card" aria-label={t('session.conversationSummaryTitle')}>
      <header>
        <span className="conversation-summary-icon" aria-hidden="true">
          <FileTextIcon />
        </span>
        <strong>{t('session.conversationSummaryTitle')}</strong>
        <button
          type="button"
          className="conversation-summary-collapse"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((current) => !current)}
        >
          {collapsed
            ? t('session.conversationSummaryShow')
            : t('session.conversationSummaryCollapse')}
          {collapsed ? <ChevronDownIcon aria-hidden="true" /> : <ChevronUpIcon aria-hidden="true" />}
        </button>
      </header>

      {collapsed ? null : (
        <div className="conversation-summary-body">
          <p className={expanded ? 'is-expanded' : undefined}>{visibleSummary}</p>
          <div className="conversation-summary-actions">
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((current) => !current)}
            >
              {expanded
                ? t('session.conversationSummaryShowLess')
                : t('session.conversationSummaryShowMore')}
            </button>
            <button
              type="button"
              className="conversation-summary-regenerate"
              disabled={!regenerationAvailable || !onRegenerate || regenerating}
              title={
                regenerationAvailable
                  ? t('session.conversationSummaryRegenerate')
                  : t('session.conversationSummaryLocalOnly')
              }
              onClick={() => void regenerate()}
            >
              <ReloadIcon className={regenerating ? 'is-spinning' : undefined} aria-hidden="true" />
              {regenerating
                ? t('session.conversationSummaryRegenerating')
                : t('session.conversationSummaryRegenerate')}
            </button>
          </div>
          {regenerationAvailable ? null : (
            <small className="conversation-summary-local-only">
              {t('session.conversationSummaryLocalOnly')}
            </small>
          )}
          {regenerationFailed ? (
            <div className="conversation-summary-error" role="alert">
              <span>{t('session.conversationSummaryRegenerateError')}</span>
              <button type="button" onClick={() => void regenerate()}>
                {t('session.conversationSummaryRetry')}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
