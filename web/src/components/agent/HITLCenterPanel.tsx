/**
 * HITLCenterPanel — Track B P2-3 phase-2 (b-fe-hitl-center).
 *
 * Centralized list of pending HITL requests for a conversation with
 * category / request-type / visibility badges. Reuses the existing
 * ``/agent/hitl/conversations/{id}/pending`` endpoint for now; once
 * the new ``pending_reviews`` table (from ``b-hitl-policy``) is
 * exposed it can be swapped in without UI changes.
 *
 * Agent First note: the UI only *displays* what the backend classified
 * (``request_type``, ``metadata.category`` / ``metadata.visibility``).
 * It never classifies content itself.
 */

import { memo, useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Loader2, X } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { restApi } from '../../services/agent/restApi';
import { useAgentV3Store } from '../../stores/agentV3';
import { formatDateTime } from '../../utils/date';

import type { DecisionOption, HITLRequestFromApi } from '../../types/hitl.unified';

export interface HITLCenterPanelProps {
  conversationId: string | null;
  onSelectRequest?: (requestId: string) => void;
  className?: string;
  autoRefreshMs?: number;
}

type FilterType = 'all' | 'clarification' | 'decision' | 'env_var';

const filterOptions: FilterType[] = ['all', 'clarification', 'decision', 'env_var'];

const badgeBase =
  'inline-flex h-[18px] items-center rounded-full border border-slate-200 bg-slate-100 px-2 text-[11px] font-medium text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100';

const actionBtnBase =
  'inline-flex h-[26px] items-center rounded border border-slate-200 px-2 text-[11px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50';

function getMetaString(metadata: Record<string, unknown> | undefined, key: string): string | null {
  if (!metadata) return null;
  const v = metadata[key];
  return typeof v === 'string' ? v : null;
}

/** Pick a decision option's stable identifier for the response payload. */
function decisionOptionKey(option: DecisionOption): string {
  return option.id || option.label;
}

export const HITLCenterPanel = memo<HITLCenterPanelProps>(
  ({ conversationId, onSelectRequest, className, autoRefreshMs = 5000 }) => {
    const { t } = useTranslation();
    const [requests, setRequests] = useState<HITLRequestFromApi[]>([]);
    const [filter, setFilter] = useState<FilterType>('all');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<Error | null>(null);
    const [resolving, setResolving] = useState<{ id: string; accept: boolean } | null>(null);
    const [resolveError, setResolveError] = useState<string | null>(null);

    const { respondToDecision, respondToClarification, respondToPermission } = useAgentV3Store(
      useShallow((state) => ({
        respondToDecision: state.respondToDecision,
        respondToClarification: state.respondToClarification,
        respondToPermission: state.respondToPermission,
      }))
    );

    const fetchPending = useCallback(async () => {
      if (!conversationId) {
        setRequests([]);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const requestType = filter === 'all' ? undefined : filter;
        const resp = await restApi.getPendingHITLRequests(conversationId, requestType);
        setRequests(resp.requests);
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setLoading(false);
      }
    }, [conversationId, filter]);

    useEffect(() => {
      void fetchPending();
      if (!conversationId || !autoRefreshMs) return;
      const id = setInterval(() => {
        void fetchPending();
      }, autoRefreshMs);
      return () => {
        clearInterval(id);
      };
    }, [fetchPending, conversationId, autoRefreshMs]);

    const visible = useMemo(() => requests, [requests]);

    /**
     * Resolve an HITL request inline.
     *
     * - decision: Accept = first option, Reject = last option (declines via the
     *   final option in the canonical list).
     * - permission: Accept = granted=true, Reject = granted=false.
     * - clarification / env_var: requires user input — defer to InlineHITLCard
     *   via onSelectRequest, no inline resolution here.
     */
    const handleResolve = useCallback(
      async (req: HITLRequestFromApi, accept: boolean) => {
        setResolving({ id: req.id, accept });
        setResolveError(null);
        try {
          if (req.request_type === 'decision') {
            const opts = (req.options ?? []) as DecisionOption[];
            if (!opts.length) {
              throw new Error('decision request has no options');
            }
            const target = accept ? opts[0] : opts[opts.length - 1];
            if (!target) {
              throw new Error('decision request has no options');
            }
            await respondToDecision(req.id, decisionOptionKey(target));
          } else if (req.request_type === 'permission') {
            await respondToPermission(req.id, accept);
          } else if (req.request_type === 'clarification' && !accept) {
            await respondToClarification(req.id, '');
          } else {
            onSelectRequest?.(req.id);
            return;
          }
          setRequests((prev) => prev.filter((r) => r.id !== req.id));
        } catch (err) {
          setResolveError(err instanceof Error ? err.message : String(err));
        } finally {
          setResolving(null);
          void fetchPending();
        }
      },
      [
        fetchPending,
        onSelectRequest,
        respondToClarification,
        respondToDecision,
        respondToPermission,
      ]
    );

    if (!conversationId) return null;

    const filterLabels: Record<FilterType, string> = {
      all: t('agent.hitl.center.filter.all', { defaultValue: 'All' }),
      clarification: t('agent.hitl.center.filter.clarification', { defaultValue: 'Clarification' }),
      decision: t('agent.hitl.center.filter.decision', { defaultValue: 'Decision' }),
      env_var: t('agent.hitl.center.filter.envVar', { defaultValue: 'Env var' }),
    };

    return (
      <aside
        className={className}
        data-testid="hitl-center-panel"
        aria-label={t('agent.hitl.center.aria', { defaultValue: 'Pending HITL requests' })}
      >
        <header className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {t('agent.hitl.center.title', { defaultValue: 'HITL Center' })}
            {visible.length > 0 && (
              <span className="ml-2 rounded-full bg-slate-900 px-1.5 text-[10px] font-medium text-slate-50 dark:bg-slate-100 dark:text-slate-900">
                {visible.length}
              </span>
            )}
          </h3>
          <select
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value as FilterType);
            }}
            className="h-[26px] rounded border border-slate-200 bg-white px-2 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            aria-label={t('agent.hitl.center.filterAria', {
              defaultValue: 'Filter by HITL type',
            })}
          >
            {filterOptions.map((opt) => (
              <option key={opt} value={opt}>
                {filterLabels[opt]}
              </option>
            ))}
          </select>
        </header>

        {loading && visible.length === 0 && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('agent.hitl.center.loading', { defaultValue: 'Loading…' })}
          </p>
        )}

        {error && (
          <div className="flex items-center gap-2">
            <p className="text-sm text-red-600 dark:text-red-400">
              {t('agent.hitl.center.error', { defaultValue: 'Failed to load HITL requests' })}
            </p>
            <button
              type="button"
              onClick={() => {
                void fetchPending();
              }}
              className="rounded border border-red-200 px-2 py-0.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/30"
            >
              {t('common.retry', 'Retry')}
            </button>
          </div>
        )}

        {!loading && !error && visible.length === 0 && (
          <p className="text-sm text-slate-400 dark:text-slate-500">
            {t('agent.hitl.center.empty', { defaultValue: 'No pending requests.' })}
          </p>
        )}

        {resolveError && (
          <div
            className="mb-2 flex items-start justify-between gap-2"
            role="alert"
            data-testid="hitl-resolve-error"
          >
            <p className="text-xs text-red-600 dark:text-red-400">{resolveError}</p>
            <button
              type="button"
              onClick={() => {
                setResolveError(null);
              }}
              aria-label={t('agent.hitl.center.dismissError', 'Dismiss error')}
              className="shrink-0 rounded p-0.5 text-red-400 transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/50 dark:hover:bg-red-950/30 dark:hover:text-red-300"
            >
              <X size={12} />
            </button>
          </div>
        )}

        <ul className="space-y-2">
          {visible.map((req) => {
            const category = getMetaString(req.metadata, 'category');
            const visibility = getMetaString(req.metadata, 'visibility');
            const isResolving = resolving?.id === req.id;
            const decisionOptions =
              req.request_type === 'decision' ? ((req.options ?? []) as DecisionOption[]) : [];
            const acceptOptionLabel = decisionOptions[0]?.label;
            const rejectOptionLabel = decisionOptions[decisionOptions.length - 1]?.label;
            const supportsInlineResolve =
              req.request_type === 'decision' || req.request_type === 'permission';
            return (
              <li
                key={req.id}
                className="rounded-md border border-slate-200 bg-white px-3 py-2 hover:border-primary dark:border-slate-800 dark:bg-slate-900 dark:hover:border-primary-500"
                data-testid="hitl-center-item"
              >
                <button
                  type="button"
                  className="block w-full cursor-pointer text-left"
                  onClick={() => {
                    onSelectRequest?.(req.id);
                  }}
                >
                  <div className="mb-1 flex items-center gap-1">
                    <span className={badgeBase} data-testid="hitl-type-badge">
                      {req.request_type}
                    </span>
                    {category && (
                      <span className={badgeBase} title="category">
                        {category}
                      </span>
                    )}
                    {visibility && (
                      <span className={badgeBase} title="visibility">
                        {visibility}
                      </span>
                    )}
                  </div>
                  <p className="line-clamp-2 text-sm text-slate-900 dark:text-slate-100">
                    {req.question}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
                    {formatDateTime(req.created_at)}
                  </p>
                </button>
                <div className="mt-2 flex items-center justify-end gap-2">
                  {supportsInlineResolve ? (
                    <>
                      <button
                        type="button"
                        className={`${actionBtnBase} border-primary bg-primary text-white hover:bg-primary-600 dark:border-primary-500 dark:bg-primary-500 dark:hover:bg-primary-600`}
                        disabled={isResolving}
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleResolve(req, true);
                        }}
                        data-testid="hitl-accept-btn"
                      >
                        {isResolving && resolving.accept ? (
                          <Loader2
                            size={12}
                            className="mr-1 animate-spin motion-reduce:animate-none"
                          />
                        ) : null}
                        {acceptOptionLabel
                          ? t('agent.hitl.center.acceptOption', {
                              defaultValue: 'Accept: {{option}}',
                              option: acceptOptionLabel,
                            })
                          : t('agent.hitl.center.accept', { defaultValue: 'Accept' })}
                      </button>
                      <button
                        type="button"
                        className={`${actionBtnBase} bg-white text-slate-900 hover:border-slate-900 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-slate-100`}
                        disabled={isResolving}
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleResolve(req, false);
                        }}
                        data-testid="hitl-reject-btn"
                      >
                        {isResolving && !resolving.accept ? (
                          <Loader2
                            size={12}
                            className="mr-1 animate-spin motion-reduce:animate-none"
                          />
                        ) : null}
                        {rejectOptionLabel
                          ? t('agent.hitl.center.rejectOption', {
                              defaultValue: 'Reject: {{option}}',
                              option: rejectOptionLabel,
                            })
                          : t('agent.hitl.center.reject', { defaultValue: 'Reject' })}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className={`${actionBtnBase} bg-white text-slate-900 hover:border-slate-900 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-slate-100`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectRequest?.(req.id);
                      }}
                      data-testid="hitl-open-btn"
                    >
                      {t('agent.hitl.center.open', { defaultValue: 'Open' })}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </aside>
    );
  }
);

HITLCenterPanel.displayName = 'HITLCenterPanel';
