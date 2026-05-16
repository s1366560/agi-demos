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
            flex flex-col gap-3 min-h-0 min-w-0 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 ease-in-out
            ${isResultsCollapsed ? 'h-10 overflow-hidden' : 'flex-1'}
        `}
      >
        <div
          className="flex shrink-0 cursor-pointer select-none flex-col gap-2 rounded-lg p-1 px-1 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/50 sm:flex-row sm:items-center sm:justify-between"
          onClick={onResultsCollapseToggle}
        >
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <div
              className={`transition-transform duration-300 ${isResultsCollapsed ? '-rotate-90' : 'rotate-0'}`}
            >
              <ChevronDown className="w-4 h-4 text-slate-400" />
            </div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white">
              {t('project.search.results.title')}
            </h2>
            <span className="px-2 py-0.5 rounded-full bg-slate-200 dark:bg-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300">
              {results.length} {t('project.search.results.items')}
            </span>
          </div>
          <div
            className="flex items-center gap-3 self-end sm:self-auto"
            onClick={(e) => {
              e.stopPropagation();
            }}
          >
            <div className="flex items-center bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-lg p-0.5">
              <button
                type="button"
                aria-label={t('project.search.actions.view_grid')}
                title={t('project.search.actions.view_grid')}
                onClick={() => {
                  onViewModeChange('grid');
                }}
                className={`p-1.5 rounded shadow-sm transition-colors ${viewMode === 'grid' ? 'bg-slate-100 dark:bg-slate-700 text-slate-900 dark:text-white' : 'hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400'}`}
              >
                <Grid className="w-4 h-4" />
              </button>
              <button
                type="button"
                aria-label={t('project.search.actions.view_list')}
                title={t('project.search.actions.view_list')}
                onClick={() => {
                  onViewModeChange('list');
                }}
                className={`p-1.5 rounded shadow-sm transition-colors ${viewMode === 'list' ? 'bg-slate-100 dark:bg-slate-700 text-slate-900 dark:text-white' : 'hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400'}`}
              >
                <List className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <div
          className={`custom-scrollbar flex-1 overflow-y-auto pr-1 ${isResultsCollapsed ? 'opacity-0' : 'opacity-100'} transition-opacity duration-200`}
        >
          <div
            className={`gap-4 pb-4 ${viewMode === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3' : 'flex flex-col'}`}
          >
            {/* Empty state for completed searches with no matches */}
            {results.length === 0 && !loading && <EmptyResultView viewMode={viewMode} />}

            {/* Dynamic Results */}
            {results.map((result, index) => {
              const isSelected = Boolean(
                result.metadata.uuid && selectedSubgraphIds.includes(result.metadata.uuid)
              );
              return (
                <SearchResultCard
                  key={index}
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
        onClick={onClick}
        className={`
                bg-white dark:bg-[#1e212b] rounded-xl shadow-sm border transition-[color,background-color,border-color,box-shadow,opacity,transform] group hover:shadow-md hover:shadow-blue-600/5 cursor-pointer
                ${
                  isSelected
                    ? 'border-blue-600 dark:border-blue-500 ring-1 ring-blue-600 dark:ring-blue-500'
                    : 'border-slate-200 dark:border-slate-800 hover:border-blue-600/40 dark:hover:border-blue-600/40'
                }
                ${viewMode === 'grid' ? 'p-4 flex flex-col h-full' : 'p-3 flex items-start gap-4'}
            `}
      >
        <div
          className={`flex ${viewMode === 'grid' ? 'items-start justify-between mb-3' : 'shrink-0'}`}
        >
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
              {getIconForType(result.metadata.type || 'document')}
            </div>
            {viewMode === 'grid' && (
              <div className="flex flex-col">
                <span className="text-2xs font-bold text-slate-400 uppercase tracking-wide">
                  {result.metadata.type || t('project.search.results.resultType', 'Result')}
                </span>
                <span className="text-xs font-bold text-slate-600 dark:text-slate-400">
                  {result.source}
                </span>
              </div>
            )}
          </div>
          {viewMode === 'grid' && (
            <div className="flex flex-col items-end">
              <span className={`text-sm font-bold ${getScoreColor(result.score)}`}>
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
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white group-hover:text-blue-600 transition-colors line-clamp-1">
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
                  <span className={`text-sm font-bold ${getScoreColor(result.score)} leading-none`}>
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

          <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed mb-3 line-clamp-2">
            {result.content}
          </p>

          <div
            className={`flex items-center justify-between ${viewMode === 'grid' ? 'mt-auto pt-3 border-t border-slate-50 dark:border-slate-800' : ''}`}
          >
            <div className="flex gap-2">
              {result.metadata.tags &&
                Array.isArray(result.metadata.tags) &&
                result.metadata.tags.map((tag: string, i: number) => (
                  <span
                    key={i}
                    className="text-2xs text-slate-400 font-medium bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded"
                  >
                    #{tag}
                  </span>
                ))}
            </div>
            <span className="text-2xs text-slate-400 font-medium">
              {result.metadata.created_at || t('project.search.results.unknown_date')}
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
    <div
      className="flex items-center gap-1.5 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-2xs text-slate-500 font-mono hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors group/id"
      onClick={(e) => {
        onCopyId(uuid, e);
      }}
      title={t('project.search.results.copy_id')}
    >
      <span>{uuid.slice(0, 8)}...</span>
      {copiedId === uuid ? (
        <Check className="w-3 h-3 text-emerald-500" />
      ) : (
        <Copy className="w-3 h-3 hover:text-blue-600 opacity-0 group-hover/id:opacity-100 transition-opacity" />
      )}
    </div>
  );
});
NodeIdCopyButton.displayName = 'NodeIdCopyButton';

const EmptyResultView = memo<{ viewMode: 'grid' | 'list' }>(({ viewMode }) => {
  const { t } = useTranslation();

  return (
    <div
      className={`
        flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white px-6 py-10 text-center shadow-sm dark:border-slate-800 dark:bg-[#1e212b]
        ${viewMode === 'grid' ? 'col-span-full' : ''}
    `}
    >
      <div className="mb-4 rounded-lg bg-slate-50 p-3 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
        <Target className="h-6 w-6" />
      </div>
      <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
        {t('project.search.results.empty_title')}
      </h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
        {t('project.search.results.empty_description')}
      </p>
    </div>
  );
});
EmptyResultView.displayName = 'EmptyResultView';
