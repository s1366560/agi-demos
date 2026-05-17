/**
 * ToolExecutionLive - Live tool execution display
 *
 * Shows tool execution in progress with pulsing animation and status.
 */

import { useTranslation } from 'react-i18next';

import {
  CheckCircle,
  XCircle,
  Search,
  Globe,
  Network,
  History,
  PlusCircle,
  FileText,
  Puzzle,
} from 'lucide-react';

export type ToolExecutionStatus = 'preparing' | 'running' | 'completed' | 'failed';

export interface ToolExecutionLiveProps {
  /** Name of the tool being executed */
  toolName: string;
  /** Current status */
  status?: ToolExecutionStatus | undefined;
  /** Tool input parameters */
  toolInput?: Record<string, unknown> | undefined;
  /** Execution mode */
  executionMode?: string | undefined;
  /** Result count (for search tools) */
  resultCount?: number | undefined;
  /** Whether to show details expanded */
  expanded?: boolean | undefined;
}

/**
 * ToolExecutionLive component
 *
 * @example
 * <ToolExecutionLive
 *   toolName="Memory Search"
 *   status="running"
 *   toolInput={{ query: "project trends", limit: 10 }}
 * />
 */
export function ToolExecutionLive({
  toolName,
  status = 'running',
  toolInput,
  executionMode = 'semantic',
  resultCount,
  expanded = true,
}: ToolExecutionLiveProps) {
  const { t } = useTranslation();

  const getStatusBadge = () => {
    switch (status) {
      case 'preparing':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none" />
            {t('components.toolExecutionLive.status.preparing', { defaultValue: 'Preparing' })}
          </span>
        );
      case 'running':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse motion-reduce:animate-none" />
            {t('components.toolExecutionLive.status.running', { defaultValue: 'Running' })}
          </span>
        );
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400">
            <CheckCircle size={14} />
            {t('components.toolExecutionLive.status.success', { defaultValue: 'Success' })}
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
            <XCircle size={14} />
            {t('components.toolExecutionLive.status.failed', { defaultValue: 'Failed' })}
          </span>
        );
    }
  };

  const getToolIcon = (name: string) => {
    const lowerName = name.toLowerCase();
    if (
      lowerName.includes('web_search') ||
      (lowerName.includes('web') && lowerName.includes('search'))
    )
      return Globe;
    if (
      lowerName.includes('web_scrape') ||
      lowerName.includes('scrape') ||
      lowerName.includes('web')
    )
      return Globe;
    if (lowerName.includes('search') || lowerName.includes('memory')) return Search;
    if (lowerName.includes('entity')) return Network;
    if (lowerName.includes('episode')) return History;
    if (lowerName.includes('create')) return PlusCircle;
    if (lowerName.includes('graph') || lowerName.includes('query')) return Network;
    if (lowerName.includes('summary')) return FileText;
    return Puzzle;
  };

  const ToolIcon = getToolIcon(toolName);
  const getRunningContent = () => {
    const lowerName = toolName.toLowerCase();

    if (
      lowerName.includes('web_search') ||
      (lowerName.includes('web') && lowerName.includes('search'))
    ) {
      return {
        title: t('components.toolExecutionLive.running.webTitle', {
          defaultValue: 'Fetching web context',
        }),
        description: t('components.toolExecutionLive.running.webDescription', {
          defaultValue: 'Collecting and ranking remote sources before returning results.',
        }),
      };
    }

    if (lowerName.includes('scrape') || lowerName.includes('web')) {
      return {
        title: t('components.toolExecutionLive.running.scrapeTitle', {
          defaultValue: 'Reading remote content',
        }),
        description: t('components.toolExecutionLive.running.scrapeDescription', {
          defaultValue: 'Loading page content and extracting structured evidence.',
        }),
      };
    }

    if (lowerName.includes('search') || lowerName.includes('memory')) {
      return {
        title: t('components.toolExecutionLive.running.searchTitle', {
          defaultValue: 'Searching knowledge graph',
        }),
        description: t('components.toolExecutionLive.running.searchDescription', {
          defaultValue: 'Finding relevant entities, memories, and relationships.',
        }),
      };
    }

    if (lowerName.includes('create')) {
      return {
        title: t('components.toolExecutionLive.running.createTitle', {
          defaultValue: 'Creating resource',
        }),
        description: t('components.toolExecutionLive.running.createDescription', {
          defaultValue: 'Validating input and writing the requested resource.',
        }),
      };
    }

    if (lowerName.includes('graph') || lowerName.includes('query')) {
      return {
        title: t('components.toolExecutionLive.running.graphTitle', {
          defaultValue: 'Querying graph data',
        }),
        description: t('components.toolExecutionLive.running.graphDescription', {
          defaultValue: 'Running the graph query and preparing a concise result set.',
        }),
      };
    }

    return {
      title: t('components.toolExecutionLive.running.defaultTitle', {
        defaultValue: 'Executing tool',
      }),
      description: t('components.toolExecutionLive.running.defaultDescription', {
        defaultValue: 'Processing the request and waiting for the tool response.',
      }),
    };
  };
  const runningContent = status === 'running' ? getRunningContent() : null;

  return (
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-md overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-3">
          {/* Tool Icon */}
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
            {/* eslint-disable-next-line react-hooks/static-components */}
            <ToolIcon size={18} />
          </div>

          {/* Tool Name */}
          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white">{toolName}</h4>
            {executionMode && <p className="text-xs text-slate-500">{executionMode}</p>}
          </div>
        </div>

        {/* Status Badge */}
        {getStatusBadge()}
      </div>

      {/* Content */}
      {expanded && (
        <div className="p-4 space-y-4">
          {/* Query Parameters */}
          {toolInput && (
            <div>
              <h5 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                {t('components.toolExecutionLive.queryParameters', {
                  defaultValue: 'Query Parameters',
                })}
              </h5>
              <div className="bg-slate-900 dark:bg-slate-950 rounded-md p-3 overflow-x-auto">
                <pre className="text-xs text-slate-300 font-mono">
                  {JSON.stringify(toolInput, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Execution Mode */}
          {executionMode && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-600 dark:text-slate-400">
                {t('components.toolExecutionLive.executionMode', {
                  defaultValue: 'Execution Mode',
                })}
              </span>
              <span className="text-sm font-medium text-slate-900 dark:text-white">
                {executionMode}
              </span>
            </div>
          )}

          {/* Live progress */}
          {runningContent && (
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="flex items-start gap-3" aria-live="polite">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  {/* eslint-disable-next-line react-hooks/static-components */}
                  <ToolIcon size={20} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    {runningContent.title}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {runningContent.description}
                  </p>
                  <div className="mt-3 grid gap-2 text-xs text-slate-600 dark:text-slate-400 sm:grid-cols-3">
                    <div className="flex items-center gap-2 rounded-md bg-white px-3 py-2 dark:bg-slate-950">
                      <CheckCircle size={14} className="text-emerald-500" />
                      <span>
                        {t('components.toolExecutionLive.running.inputAccepted', {
                          defaultValue: 'Input accepted',
                        })}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 rounded-md bg-white px-3 py-2 dark:bg-slate-950">
                      <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse motion-reduce:animate-none" />
                      <span>
                        {t('components.toolExecutionLive.running.modeActive', {
                          defaultValue: '{{mode}} mode active',
                          mode: executionMode,
                        })}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 rounded-md bg-white px-3 py-2 dark:bg-slate-950">
                      <span className="h-2 w-2 rounded-full bg-primary animate-pulse motion-reduce:animate-none" />
                      <span>
                        {resultCount !== undefined
                          ? t('components.toolExecutionLive.running.partialResults', {
                              defaultValue: '{{count}} partial results',
                              count: resultCount,
                            })
                          : t('components.toolExecutionLive.running.awaitingResponse', {
                              defaultValue: 'Awaiting response',
                            })}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Results Summary (for completed state) */}
          {status === 'completed' && resultCount !== undefined && (
            <div className="flex items-center justify-between p-3 bg-emerald-50 dark:bg-emerald-900/20 rounded-md">
              <div className="flex items-center gap-2">
                <CheckCircle size={18} className="text-emerald-500" />
                <span className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
                  {t('components.toolExecutionLive.searchCompleted', {
                    defaultValue: 'Search completed',
                  })}
                </span>
              </div>
              <span className="text-sm text-slate-600 dark:text-slate-400">
                {t('components.toolExecutionLive.resultsFound', {
                  defaultValue: '{{count}} results found',
                  count: resultCount,
                })}
              </span>
            </div>
          )}

          {/* Error State */}
          {status === 'failed' && (
            <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 rounded-md">
              <XCircle size={18} className="text-red-500" />
              <span className="text-sm font-medium text-red-700 dark:text-red-400">
                {t('components.toolExecutionLive.failedMessage', {
                  defaultValue: 'Tool execution failed. Please try again.',
                })}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ToolExecutionLive;
