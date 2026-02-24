/**
 * WebSearchResultCard component
 *
 * Displays formatted web search results from Tavily API.
 */

import { useState } from 'react';

import { formatDateTime, formatDateOnly } from '@/utils/date';

import { MaterialIcon } from './shared';

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
    <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <MaterialIcon name="language" size={18} className="text-blue-500" />
          <span className="font-semibold text-slate-900 dark:text-white">Web Search Results</span>
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              cached
                ? 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-600 dark:text-cyan-400'
                : 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
            }`}
          >
            {cached ? 'Cached' : 'Live'}
          </span>
        </div>
        {timestamp && (
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <MaterialIcon name="schedule" size={12} />
            {formatTimestamp(timestamp)}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4 space-y-3">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Found {totalResults} result(s) for &quot;{query}&quot;
        </p>

        {/* Results - 2 Column Grid */}
        <div className="grid grid-cols-2 gap-3">
          {results.map((result, index) => (
            <div
              key={index}
              className="p-3 rounded-lg border bg-slate-50 dark:bg-slate-900/20 border-slate-200 dark:border-slate-800"
            >
              <div className="space-y-2">
                {/* Title and Score */}
                <div className="flex items-start justify-between gap-2">
                  <a
                    href={result.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline flex-1"
                  >
                    {index + 1}. {result.title}
                  </a>
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 whitespace-nowrap">
                    {result.score.toFixed(2)}
                  </span>
                </div>

                {/* URL */}
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <MaterialIcon name="link" size={12} />
                  <span className="font-mono truncate">{result.url}</span>
                </div>

                {/* Published Date */}
                {result.published_date && (
                  <div className="text-xs text-slate-500">
                    Published: {formatDateOnly(result.published_date)}
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
                      onClick={() => { toggleExpand(index); }}
                      className="ml-2 text-blue-500 hover:underline"
                    >
                      {expanded.has(index) ? 'Show less' : 'Show more'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default WebSearchResultCard;
