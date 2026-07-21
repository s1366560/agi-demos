/**
 * SearchResults - Extracted from EnhancedSearch
 *
 * Displays the search results in grid or list view.
 */

import React, { memo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import {
  FileText,
  MessageSquare,
  ImageIcon,
  Link as LinkIcon,
  Network,
  Target,
  Folder,
  Copy,
  Check,
  ChevronDown,
  Grid,
  List,
} from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

export interface SearchResult {
  content: string;
  score: number;
  metadata: {
    type: string;
    name?: string | undefined;
    uuid?: string | undefined;
    depth?: number | undefined;
    created_at?: string | undefined;
    tags?: string[] | undefined;
    [key: string]: unknown;
  };
  source: string;
}

interface SearchResultsProps {
  results: SearchResult[];
  loading: boolean;
  isResultsCollapsed: boolean;
  viewMode: 'grid' | 'list';
  copiedId: string | null;
  selectedSubgraphIds: string[];
  onResultsCollapseToggle: () => void;
  onViewModeChange: (mode: 'grid' | 'list') => void;
  onResultClick: (result: SearchResult) => void;
  onCopyId: (id: string, e: React.MouseEvent) => void;
}

export const SearchResults = memo<SearchResultsProps>(
  ({
    results,
    loading,
    isResultsCollapsed,
    viewMode,
    copiedId,
    selectedSubgraphIds,
    onResultsCollapseToggle,
    onViewModeChange,
    onResultClick,
    onCopyId,
  }) => {
    const { t } = useTranslation();

    const getScoreColor = useCallback((score: number) => {
      if (score >= 0.8) return 'text-emerald-500';
      if (score >= 0.6) return 'text-violet-500';
      if (score >= 0.4) return 'text-amber-500';
      return 'text-slate-400';
    }, []);

    const getIconForType = useCallback((type: string) => {
      switch (type.toLowerCase()) {
        case 'document':
        case 'pdf':
        case 'file':
          return <FileText className="w-5 h-5" />;
        case 'thread':
        case 'slack':
        case 'message':
          return <MessageSquare className="w-5 h-5" />;
        case 'asset':
        case 'img':
        case 'image':
          return <ImageIcon className="w-5 h-5" />;
        case 'reference':
        case 'web':
        case 'jira':
        case 'link':
          return <LinkIcon className="w-5 h-5" />;
        case 'episode':
        case 'memory':
          return <MessageSquare className="w-5 h-5 text-blue-500" />;
        case 'person':
        case 'user':
          return <FileText className="w-5 h-5 text-purple-500" />;
        case 'organization':
        case 'company':
          return <Network className="w-5 h-5 text-indigo-500" />;
        case 'location':
        case 'place':
          return <Target className="w-5 h-5 text-red-500" />;
        case 'event':
          return <Target className="w-5 h-5 text-amber-500" />;
        case 'concept':
        case 'topic':
          return <Folder className="w-5 h-5 text-emerald-500" />;
        case 'product':
          return <FileText className="w-5 h-5 text-cyan-500" />;
        default:
          return <Network className="w-5 h-5 text-slate-400" />;
      }
    }, []);

    return (
      <section
        className={`
            flex min-h-0 min-w-0 flex-col gap-3 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 ease-in-out
            ${isResultsCollapsed ? 'h-10 overflow-hidden' : 'flex-1'}
        `}
      >
        <div className="flex shrink-0 select-none flex-col gap-2 rounded-md px-1 py-1 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="button"
            onClick={onResultsCollapseToggle}
            aria-expanded={!isResultsCollapsed}
            className="flex min-w-0 flex-wrap items-center gap-3 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-slate-100/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/10 dark:hover:bg-slate-900/70 dark:focus-visible:ring-slate-50/10"
          >
            <div
              className={`transition-transform duration-300 motion-reduce:transition-none ${isResultsCollapsed ? '-rotate-90' : 'rotate-0'}`}
            >
              <ChevronDown className="h-4 w-4 text-slate-400" aria-hidden="true" />
            </div>
            <h2 className="text-base font-semibold text-slate-950 dark:text-slate-50">
              {t('project.search.results.title')}
            </h2>
            <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {results.length} {t('project.search.results.items')}
            </span>
          </button>
          <div className="flex items-center gap-3 self-end sm:self-auto">
            <div
              className="flex items-center rounded-md border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-950/30"
              role="group"
              aria-label={t('project.search.results.view_mode', 'Result view mode')}
            >
              <button
                type="button"
                aria-label={t('project.search.actions.view_grid')}
                aria-pressed={viewMode === 'grid'}
                title={t('project.search.actions.view_grid')}
                onClick={() => {
                  onViewModeChange('grid');
                }}
                className={`rounded p-1.5 shadow-sm transition-colors ${viewMode === 'grid' ? 'bg-slate-100 text-slate-950 dark:bg-slate-800 dark:text-slate-50' : 'text-slate-500 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-900'}`}
              >
                <Grid className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label={t('project.search.actions.view_list')}
                aria-pressed={viewMode === 'list'}
                title={t('project.search.actions.view_list')}
                onClick={() => {
                  onViewModeChange('list');
                }}
                className={`rounded p-1.5 shadow-sm transition-colors ${viewMode === 'list' ? 'bg-slate-100 text-slate-950 dark:bg-slate-800 dark:text-slate-50' : 'text-slate-500 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-900'}`}
              >
                <List className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        <div
          className={`custom-scrollbar flex-1 overflow-y-auto pr-1 ${isResultsCollapsed ? 'opacity-0' : 'opacity-100'} transition-opacity duration-200`}
        >
          <div
            className={`gap-3 pb-4 ${viewMode === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3' : 'flex flex-col'}`}
          >
            {/* Empty state for completed searches with no matches */}
            {results.length === 0 && !loading && <EmptyResultView viewMode={viewMode} />}

            {results.length === 0 && loading && <LoadingResultView viewMode={viewMode} />}

            {/* Dynamic Results */}
            {results.map((result, index) => {
              const isSelected = Boolean(
                result.metadata.uuid && selectedSubgraphIds.includes(result.metadata.uuid)
              );
              return (
                <SearchResultCard
                  key={result.metadata.uuid ?? index}
                  result={result}
                  viewMode={viewMode}
                  isSelected={isSelected}
                  copiedId={copiedId}
                  getScoreColor={getScoreColor}
                  getIconForType={getIconForType}
                  onClick={() => {
                    onResultClick(result);
                  }}
                  onCopyId={onCopyId}
                />
              );
            })}
          </div>
        </div>
      </section>
    );
  }
);
SearchResults.displayName = 'SearchResults';

// Sub-components
interface SearchResultCardProps {
  result: SearchResult;
  viewMode: 'grid' | 'list';
  isSelected: boolean;
  copiedId: string | null;
  getScoreColor: (score: number) => string;
  getIconForType: (type: string) => React.ReactNode;
  onClick: () => void;
  onCopyId: (id: string, e: React.MouseEvent) => void;
}

const SearchResultCard = memo<SearchResultCardProps>(
  ({
    result,
    viewMode,
    isSelected,
    copiedId,
    getScoreColor,
    getIconForType,
    onClick,
    onCopyId,
  }) => {
    const { t } = useTranslation();

    return (
      <div
        role="button"
        tabIndex={0}
        aria-pressed={isSelected}
        onClick={onClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onClick();
          }
        }}
        className={`
                group cursor-pointer rounded-md border bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.04)] transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-surface-dark dark:hover:bg-slate-900/60 dark:focus-visible:ring-slate-50/20
                ${
                  isSelected
                    ? 'border-slate-950 ring-1 ring-slate-950 dark:border-slate-50 dark:ring-slate-50'
                    : 'border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700'
                }
                ${viewMode === 'grid' ? 'flex h-full flex-col p-4' : 'flex items-start gap-4 p-3'}
            `}
      >
        <div
          className={`flex ${viewMode === 'grid' ? 'items-start justify-between mb-3' : 'shrink-0'}`}
        >
          <div className="flex items-center gap-2">
            <div className="rounded-md bg-slate-100 p-2 text-slate-600 dark:bg-slate-900 dark:text-slate-400">
              {getIconForType(result.metadata.type || 'document')}
            </div>
            {viewMode === 'grid' && (
              <div className="flex flex-col">
                <span className="text-2xs font-medium uppercase tracking-wide text-slate-400">
                  {result.metadata.type || t('project.search.results.resultType', 'Result')}
                </span>
                <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                  {result.source}
                </span>
              </div>
            )}
          </div>
          {viewMode === 'grid' && (
            <div className="flex flex-col items-end">
              <span className={`text-sm font-bold tabular-nums ${getScoreColor(result.score)}`}>
                {Math.round(result.score * 100)}%
              </span>
              <span className="text-2xs text-slate-400">
                {t('project.search.results.relevance')}
              </span>
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-1">
            <h3 className="line-clamp-1 text-sm font-semibold text-slate-950 transition-colors group-hover:text-slate-700 dark:text-slate-50 dark:group-hover:text-slate-200">
              {result.metadata.name || t('project.search.results.untitled')}
            </h3>
            {viewMode === 'list' && (
              <div className="flex items-center gap-3 shrink-0">
                {result.metadata.uuid && (
                  <NodeIdCopyButton
                    uuid={result.metadata.uuid}
                    copiedId={copiedId}
                    onCopyId={onCopyId}
                  />
                )}
                <div className="flex flex-col items-end">
                  <span
                    className={`text-sm font-bold tabular-nums ${getScoreColor(result.score)} leading-none`}
                  >
                    {Math.round(result.score * 100)}%
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Node ID for Grid View */}
          {viewMode === 'grid' && result.metadata.uuid && (
            <NodeIdCopyButton uuid={result.metadata.uuid} copiedId={copiedId} onCopyId={onCopyId} />
          )}

          <p className="mb-3 line-clamp-2 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
            {result.content}
          </p>

          <div
            className={`flex items-center justify-between ${viewMode === 'grid' ? 'mt-auto border-t border-slate-100 pt-3 dark:border-slate-800' : ''}`}
          >
            <div className="flex gap-2">
              {result.metadata.tags &&
                Array.isArray(result.metadata.tags) &&
                result.metadata.tags.map((tag: string, i: number) => (
                  <span
                    key={i}
                    className="rounded bg-slate-100 px-1.5 py-0.5 text-2xs font-medium text-slate-400 dark:bg-slate-900"
                  >
                    #{tag}
                  </span>
                ))}
            </div>
            <span className="text-2xs text-slate-400 font-medium">
              {result.metadata.created_at
                ? formatDateOnly(result.metadata.created_at)
                : t('project.search.results.unknown_date')}
            </span>
          </div>
        </div>
      </div>
    );
  }
);
SearchResultCard.displayName = 'SearchResultCard';

interface NodeIdCopyButtonProps {
  uuid: string;
  copiedId: string | null;
  onCopyId: (id: string, e: React.MouseEvent) => void;
}

const NodeIdCopyButton = memo<NodeIdCopyButtonProps>(({ uuid, copiedId, onCopyId }) => {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      className="group/id flex items-center gap-1.5 rounded bg-slate-100 px-2 py-0.5 font-mono text-2xs text-slate-500 transition-colors hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-900 dark:hover:bg-slate-800 dark:focus-visible:ring-slate-50/20"
      onClick={(e) => {
        onCopyId(uuid, e);
      }}
      aria-label={t('project.search.results.copy_id')}
      title={t('project.search.results.copy_id')}
    >
      <span>{uuid.slice(0, 8)}…</span>
      {copiedId === uuid ? (
        <Check className="w-3 h-3 text-emerald-500" aria-hidden="true" />
      ) : (
        <Copy
          className="h-3 w-3 opacity-0 transition-opacity hover:text-slate-950 group-hover/id:opacity-100 group-focus-within/id:opacity-100 dark:hover:text-slate-50"
          aria-hidden="true"
        />
      )}
    </button>
  );
});
NodeIdCopyButton.displayName = 'NodeIdCopyButton';

const EmptyResultView = memo<{ viewMode: 'grid' | 'list' }>(({ viewMode }) => {
  const { t } = useTranslation();

  return (
    <div
      className={`
        flex min-h-56 flex-col items-center justify-center rounded-md border border-dashed border-slate-200 bg-white px-6 py-10 text-center shadow-[0_0_0_1px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-surface-dark
        ${viewMode === 'grid' ? 'col-span-full' : ''}
    `}
    >
      <div className="mb-4 rounded-md bg-slate-100 p-3 text-slate-400 dark:bg-slate-900 dark:text-slate-500">
        <Target className="h-6 w-6" />
      </div>
      <h3 className="text-sm font-semibold text-slate-950 dark:text-slate-50">
        {t('project.search.results.empty_title')}
      </h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
        {t('project.search.results.empty_description')}
      </p>
    </div>
  );
});
EmptyResultView.displayName = 'EmptyResultView';

const LoadingResultView = memo<{ viewMode: 'grid' | 'list' }>(({ viewMode }) => (
  <div
    className={`rounded-md border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-surface-dark ${
      viewMode === 'grid' ? 'col-span-full' : ''
    }`}
    role="status"
    aria-busy="true"
  >
    <div className="space-y-3">
      <div className="h-4 w-40 animate-pulse rounded bg-slate-200 motion-reduce:animate-none dark:bg-slate-800" />
      <div className="h-3 w-full animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-900" />
      <div className="h-3 w-2/3 animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-900" />
    </div>
  </div>
));
LoadingResultView.displayName = 'LoadingResultView';
