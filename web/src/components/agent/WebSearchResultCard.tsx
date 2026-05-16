/**
 * WebSearchResultCard component
 *
 * Displays formatted web search results from Tavily API.
 */

import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Globe, Clock, Link } from 'lucide-react';

import { formatDateTime, formatDateOnly } from '@/utils/date';

export interface SearchResult {
  title: string;
  url: string;
  content: string;
  score: number;
  published_date?: string | undefined;
}

export interface WebSearchResultCardProps {
  results: SearchResult[];
  query: string;
  totalResults: number;
  cached?: boolean | undefined;
  timestamp?: string | undefined;
}

export function WebSearchResultCard({
  results,
  query,
  totalResults,
  cached = false,
  timestamp,
}: WebSearchResultCardProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggleExpand = (index: number) => {
    const newExpanded = new Set(expanded);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpanded(newExpanded);
  };

  const formatTimestamp = (ts?: string) => {
    if (!ts) return null;
    return formatDateTime(ts);
  };

  return (
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-md overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Globe size={18} className="text-blue-500" />
          <span className="font-semibold text-slate-900 dark:text-white">
            {t('components.webSearchResult.title', { defaultValue: 'Web Search Results' })}
          </span>
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              cached
                ? 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-600 dark:text-cyan-400'
                : 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
            }`}
          >
            {cached
              ? t('components.webSearchResult.source.cached', { defaultValue: 'Cached' })
              : t('components.webSearchResult.source.live', { defaultValue: 'Live' })}
          </span>
        </div>
        {timestamp && (
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <Clock size={12} />
            {formatTimestamp(timestamp)}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4 space-y-3">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {t('components.webSearchResult.resultSummary', {
            defaultValue: 'Found {{count}} results for "{{query}}"',
            count: totalResults,
            query,
          })}
        </p>

        {/* Results - 2 Column Grid */}
        {results.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {results.map((result, index) => (
              <div
                key={result.url}
                className="p-3 rounded-md border bg-slate-50 dark:bg-slate-900/20 border-slate-200 dark:border-slate-800 min-w-0"
              >
                <div className="space-y-2 min-w-0">
                  {/* Title and Score */}
                  <div className="flex items-start justify-between gap-2 min-w-0">
                    <a
                      href={result.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline flex-1 min-w-0 break-words"
                    >
                      {index + 1}. {result.title}
                    </a>
                    <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 whitespace-nowrap">
                      {result.score.toFixed(2)}
                    </span>
                  </div>

                  {/* URL */}
                  <div className="flex items-center gap-1 text-xs text-slate-500 min-w-0">
                    <Link size={12} className="shrink-0" />
                    <span className="font-mono truncate min-w-0">{result.url}</span>
                  </div>

                  {/* Published Date */}
                  {result.published_date && (
                    <div className="text-xs text-slate-500">
                      {t('components.webSearchResult.published', {
                        defaultValue: 'Published: {{date}}',
                        date: formatDateOnly(result.published_date),
                      })}
                    </div>
                  )}

                  {/* Content Preview */}
                  <div className="text-xs text-slate-600 dark:text-slate-400">
                    {expanded.has(index) || result.content.length <= 200 ? (
                      <p>{result.content}</p>
                    ) : (
                      <p>{result.content.slice(0, 200)}...</p>
                    )}
                    {result.content.length > 200 && (
                      <button
                        type="button"
                        onClick={() => {
                          toggleExpand(index);
                        }}
                        aria-expanded={expanded.has(index)}
                        className="ml-2 text-blue-500 hover:underline"
                      >
                        {expanded.has(index)
                          ? t('components.webSearchResult.showLess', { defaultValue: 'Show less' })
                          : t('components.webSearchResult.showMore', { defaultValue: 'Show more' })}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-slate-200 dark:border-slate-800 px-3 py-6 text-center text-sm text-slate-500">
            {t('components.webSearchResult.empty', {
              defaultValue: 'No search results to display',
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default WebSearchResultCard;
