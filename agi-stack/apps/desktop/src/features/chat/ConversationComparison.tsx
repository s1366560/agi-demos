import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Dialog } from '@radix-ui/themes';
import { ColumnsIcon, Cross2Icon, MagnifyingGlassIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentConversation } from '../../types';
import type { ComposerCatalogClient } from './composerCatalogModel';
import {
  conversationComparisonCandidates,
  conversationComparisonMessages,
  conversationComparisonRequestMatches,
} from './conversationComparisonModel';
import type { ConversationComparisonMessage } from './conversationComparisonModel';

export type ConversationComparisonClient = {
  listConversations: NonNullable<ComposerCatalogClient['listConversations']>;
  getConversationMessages: NonNullable<ComposerCatalogClient['getConversationMessages']>;
};

type ConversationComparisonProps = {
  client: ConversationComparisonClient;
  currentConversation: AgentConversation;
  comparisonConversation: AgentConversation | null;
  onChooseConversation: () => void;
  onClose: () => void;
};

type ConversationComparisonPickerProps = {
  open: boolean;
  client: ConversationComparisonClient;
  currentConversation: AgentConversation;
  onSelect: (conversation: AgentConversation) => void;
  onClose: () => void;
};

type ComparisonMessagesState = {
  status: 'loading' | 'ready' | 'error';
  messages: ConversationComparisonMessage[];
};

export function ConversationComparison({
  client,
  currentConversation,
  comparisonConversation,
  onChooseConversation,
  onClose,
}: ConversationComparisonProps) {
  const { t } = useI18n();
  const [leftRetry, setLeftRetry] = useState(0);
  const [rightRetry, setRightRetry] = useState(0);
  const leftScopeKey = [
    currentConversation.tenant_id,
    currentConversation.project_id,
    currentConversation.id,
  ].join(':');
  const rightScopeKey = comparisonConversation
    ? [
        currentConversation.tenant_id,
        currentConversation.project_id,
        currentConversation.id,
        comparisonConversation.id,
      ].join(':')
    : '';
  const leftState = useConversationComparisonMessages(
    client,
    currentConversation,
    leftScopeKey,
    leftRetry,
  );
  const rightState = useConversationComparisonMessages(
    client,
    comparisonConversation,
    rightScopeKey,
    rightRetry,
  );

  return (
    <section className="conversation-comparison" aria-label={t('chat.comparison.title')}>
      <header className="conversation-comparison-header">
        <div>
          <ColumnsIcon aria-hidden="true" />
          <strong>{t('chat.comparison.title')}</strong>
        </div>
        <div>
          <Button type="button" size="1" variant="soft" onClick={onChooseConversation}>
            {comparisonConversation ? t('chat.comparison.change') : t('chat.comparison.select')}
          </Button>
          <Button
            type="button"
            size="1"
            variant="ghost"
            aria-label={t('chat.comparison.exit')}
            title={t('chat.comparison.exit')}
            onClick={onClose}
          >
            <Cross2Icon />
          </Button>
        </div>
      </header>
      <div className="conversation-comparison-panes">
        <ConversationComparisonPane
          conversation={currentConversation}
          state={leftState}
          label={t('chat.comparison.current')}
          onRetry={() => setLeftRetry((revision) => revision + 1)}
        />
        {comparisonConversation ? (
          <ConversationComparisonPane
            conversation={comparisonConversation}
            state={rightState}
            label={t('chat.comparison.comparison')}
            onRetry={() => setRightRetry((revision) => revision + 1)}
          />
        ) : (
          <section
            className="conversation-comparison-pane is-placeholder"
            aria-label={t('chat.comparison.comparison')}
          >
            <ColumnsIcon aria-hidden="true" />
            <p>{t('chat.comparison.select')}</p>
            <Button type="button" variant="soft" onClick={onChooseConversation}>
              {t('chat.comparison.select')}
            </Button>
          </section>
        )}
      </div>
    </section>
  );
}

export function ConversationComparisonPicker({
  open,
  client,
  currentConversation,
  onSelect,
  onClose,
}: ConversationComparisonPickerProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [catalog, setCatalog] = useState<AgentConversation[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [retryRevision, setRetryRevision] = useState(0);
  const requestGenerationRef = useRef(0);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);
  const catalogScopeKey = [
    currentConversation.tenant_id,
    currentConversation.project_id,
    currentConversation.id,
  ].join(':');

  useEffect(() => {
    if (open) {
      previousFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      wasOpenRef.current = true;
      setQuery('');
      return;
    }
    if (!wasOpenRef.current) return;
    wasOpenRef.current = false;
    const previousFocus = previousFocusRef.current;
    previousFocusRef.current = null;
    if (previousFocus?.isConnected) {
      window.requestAnimationFrame(() => previousFocus.focus());
    }
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    const requestId = requestGenerationRef.current + 1;
    requestGenerationRef.current = requestId;
    const expectedScopeKey = catalogScopeKey;
    setStatus('loading');
    client
      .listConversations(currentConversation.project_id, {
        signal: controller.signal,
      })
      .then((response) => {
        if (
          controller.signal.aborted ||
          requestId !== requestGenerationRef.current ||
          expectedScopeKey !== catalogScopeKey
        ) {
          return;
        }
        setCatalog(response.items);
        setStatus('ready');
      })
      .catch(() => {
        if (controller.signal.aborted || requestId !== requestGenerationRef.current) {
          return;
        }
        setStatus('error');
      });
    return () => {
      controller.abort();
    };
  }, [catalogScopeKey, client, currentConversation.project_id, open, retryRevision]);

  const candidates = useMemo(
    () => conversationComparisonCandidates(catalog, currentConversation, query),
    [catalog, currentConversation, query],
  );

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <Dialog.Content className="conversation-comparison-picker" maxWidth="560px">
        <Dialog.Title>{t('chat.comparison.select')}</Dialog.Title>
        <Dialog.Description>{t('chat.comparison.selectDescription')}</Dialog.Description>
        <label className="conversation-comparison-search">
          <MagnifyingGlassIcon aria-hidden="true" />
          <input
            autoFocus
            type="search"
            value={query}
            disabled={status === 'loading'}
            aria-label={t('chat.comparison.search')}
            placeholder={t('chat.comparison.search')}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <div className="conversation-comparison-picker-list">
          {status === 'loading' ? (
            <div className="conversation-comparison-state" role="status">
              <ReloadIcon className="conversation-comparison-spin" aria-hidden="true" />
              {t('chat.comparison.loadingCatalog')}
            </div>
          ) : status === 'error' ? (
            <div className="conversation-comparison-state is-error" role="alert">
              <span>{t('chat.comparison.catalogFailed')}</span>
              <Button
                type="button"
                size="1"
                variant="soft"
                onClick={() => setRetryRevision((revision) => revision + 1)}
              >
                {t('chat.comparison.retry')}
              </Button>
            </div>
          ) : candidates.length === 0 ? (
            <div className="conversation-comparison-state" role="status">
              {t('chat.comparison.noResults')}
            </div>
          ) : (
            candidates.map((conversation) => (
              <button
                type="button"
                className="conversation-comparison-picker-row"
                key={conversation.id}
                aria-label={`${conversation.title} ${conversation.id}`}
                onClick={() => {
                  onSelect(conversation);
                  onClose();
                }}
              >
                <ColumnsIcon aria-hidden="true" />
                <span>
                  <strong>{conversation.title}</strong>
                  <small>
                    <code>{conversation.id}</code>
                    <span>
                      {t('chat.comparison.messageCount', {
                        count: conversation.message_count,
                      })}
                    </span>
                    {conversation.updated_at ? (
                      <time dateTime={conversation.updated_at}>
                        {formatComparisonDate(conversation.updated_at)}
                      </time>
                    ) : null}
                  </small>
                </span>
              </button>
            ))
          )}
        </div>
        <div className="conversation-comparison-picker-actions">
          <Dialog.Close>
            <Button type="button" variant="soft" color="gray">
              {t('common.cancel')}
            </Button>
          </Dialog.Close>
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function ConversationComparisonPane({
  conversation,
  state,
  label,
  onRetry,
}: {
  conversation: AgentConversation;
  state: ComparisonMessagesState;
  label: string;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <section
      className="conversation-comparison-pane"
      aria-label={t('chat.comparison.paneLabel', {
        label,
        title: conversation.title,
      })}
      aria-busy={state.status === 'loading'}
    >
      <header>
        <span>{label}</span>
        <strong>{conversation.title}</strong>
        <code>{conversation.id}</code>
      </header>
      <div
        className="conversation-comparison-pane-scroll"
        tabIndex={0}
        aria-label={t('chat.comparison.transcriptLabel', {
          title: conversation.title,
        })}
      >
        {state.status === 'loading' ? (
          <div className="conversation-comparison-state" role="status">
            <ReloadIcon className="conversation-comparison-spin" aria-hidden="true" />
            {t('chat.comparison.loading')}
          </div>
        ) : state.status === 'error' ? (
          <div className="conversation-comparison-state is-error" role="alert">
            <span>{t('chat.comparison.loadFailed')}</span>
            <Button type="button" size="1" variant="soft" onClick={onRetry}>
              {t('chat.comparison.retry')}
            </Button>
          </div>
        ) : state.messages.length === 0 ? (
          <div className="conversation-comparison-state" role="status">
            {t('chat.comparison.noMessages')}
          </div>
        ) : (
          state.messages.map((message) => (
            <article
              className={`conversation-comparison-message is-${message.role}`}
              key={message.id}
            >
              <small>
                {t(message.role === 'user' ? 'chat.comparison.user' : 'chat.comparison.assistant')}
                {message.timestampMs > 0 ? (
                  <time dateTime={new Date(message.timestampMs).toISOString()}>
                    {formatComparisonTime(message.timestampMs)}
                  </time>
                ) : null}
              </small>
              <p>{message.content}</p>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

function useConversationComparisonMessages(
  client: ConversationComparisonClient,
  conversation: AgentConversation | null,
  scopeKey: string,
  retryRevision: number,
): ComparisonMessagesState {
  const [state, setState] = useState<ComparisonMessagesState>({
    status: conversation ? 'loading' : 'ready',
    messages: [],
  });
  const requestGenerationRef = useRef(0);

  useEffect(() => {
    if (!conversation || !scopeKey) {
      setState({ status: 'ready', messages: [] });
      return undefined;
    }
    const controller = new AbortController();
    const requestId = requestGenerationRef.current + 1;
    requestGenerationRef.current = requestId;
    const expectedConversationId = conversation.id;
    const expectedScopeKey = scopeKey;
    setState({ status: 'loading', messages: [] });
    client
      .getConversationMessages(expectedConversationId, conversation.project_id, {
        limit: 200,
        signal: controller.signal,
      })
      .then((response) => {
        if (
          controller.signal.aborted ||
          !conversationComparisonRequestMatches({
            requestId,
            currentRequestId: requestGenerationRef.current,
            expectedConversationId,
            responseConversationId: response.conversationId,
            expectedScopeKey,
            currentScopeKey: scopeKey,
          })
        ) {
          return;
        }
        setState({
          status: 'ready',
          messages: conversationComparisonMessages(response.timeline),
        });
      })
      .catch(() => {
        if (controller.signal.aborted || requestId !== requestGenerationRef.current) {
          return;
        }
        setState({ status: 'error', messages: [] });
      });
    return () => {
      controller.abort();
    };
  }, [client, conversation, retryRevision, scopeKey]);

  return state;
}

function formatComparisonDate(value: string): string {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : '';
}

function formatComparisonTime(timestampMs: number): string {
  return new Date(timestampMs).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}
