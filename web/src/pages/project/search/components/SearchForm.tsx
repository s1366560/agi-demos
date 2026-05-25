/**
 * SearchForm - Extracted from EnhancedSearch
 *
 * Handles the search input, mode selection, and voice search.
 */

import React, { memo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Search,
  Mic,
  Network,
  Grid,
  ArrowUpDown,
  Filter,
  MessageSquare,
  Download,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react';

import { formatTimeOnly } from '@/utils/date';

export type SearchMode = 'semantic' | 'graphTraversal' | 'temporal' | 'faceted' | 'community';

interface SearchFormProps {
  searchMode: SearchMode;
  query: string;
  startEntityUuid: string;
  communityUuid: string;
  isSearchFocused: boolean;
  isListening: boolean;
  loading: boolean;
  isConfigOpen: boolean;
  searchHistory: Array<{ query: string; mode: string; timestamp: number }>;
  showHistory: boolean;
  onSearchModeChange: (mode: SearchMode) => void;
  onQueryChange: (value: string) => void;
  onStartEntityUuidChange: (value: string) => void;
  onCommunityUuidChange: (value: string) => void;
  onSearchFocusChange: (focused: boolean) => void;
  onSearch: () => void;
  onVoiceSearch: () => void;
  onConfigToggle: () => void;
  onMobileConfigOpen?: (() => void) | undefined;
  onHistoryToggle: () => void;
  onHistoryItemClick: (item: { query: string; mode: string }) => void;
  onExportResults?: (() => void) | undefined;
  canExportResults?: boolean | undefined;
}

export const SearchForm = memo<SearchFormProps>(
  ({
    searchMode,
    query,
    startEntityUuid,
    communityUuid,
    isSearchFocused,
    isListening,
    loading,
    isConfigOpen,
    searchHistory,
    showHistory,
    onSearchModeChange,
    onQueryChange,
    onStartEntityUuidChange,
    onCommunityUuidChange,
    onSearchFocusChange,
    onSearch,
    onVoiceSearch,
    onConfigToggle,
    onMobileConfigOpen,
    onHistoryToggle,
    onHistoryItemClick,
    onExportResults,
    canExportResults = false,
  }) => {
    const { t } = useTranslation();

    const handleSearchKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
          onSearch();
        }
      },
      [onSearch]
    );

    const getInputValue = useCallback(() => {
      if (searchMode === 'graphTraversal') return startEntityUuid;
      if (searchMode === 'community') return communityUuid;
      return query;
    }, [searchMode, startEntityUuid, communityUuid, query]);

    const getPlaceholder = useCallback(() => {
      if (searchMode === 'graphTraversal') return t('project.search.input.placeholder.graph');
      if (searchMode === 'community') return t('project.search.input.placeholder.community');
      if (isSearchFocused) return '';
      return t('project.search.input.placeholder.default');
    }, [searchMode, isSearchFocused, t]);

    const getInputLabel = useCallback(() => {
      if (searchMode === 'graphTraversal') return t('project.search.input.label.graph');
      if (searchMode === 'community') return t('project.search.input.label.community');
      return t('project.search.input.label.default');
    }, [searchMode, t]);

    return (
      <header className="flex shrink-0 flex-col gap-4 px-4 pb-2 pt-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 inline-flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
              <Network className="h-4 w-4" aria-hidden="true" />
              <span>{t('project.search.eyebrow', 'Knowledge retrieval')}</span>
            </div>
            <h1 className="text-[22px] font-semibold leading-7 text-slate-950 dark:text-slate-50">
              {t('project.search.title', 'Deep Search')}
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-500 dark:text-slate-400">
              {t(
                'project.search.subtitle',
                'Search memory, traverse graph context, and inspect matching subgraphs.'
              )}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {searchHistory.length > 0 && (
              <HistoryButton
                showHistory={showHistory}
                count={searchHistory.length}
                onClick={onHistoryToggle}
              />
            )}
            {onExportResults && (
              <button
                type="button"
                onClick={onExportResults}
                disabled={!canExportResults}
                aria-label={t('project.search.actions.export')}
                title={t('project.search.actions.export')}
                className="inline-flex h-9 w-9 items-center justify-center rounded border border-slate-200 bg-white text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/10 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-800 dark:bg-slate-900/30 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:bg-slate-900 dark:hover:text-slate-50 dark:focus-visible:ring-slate-50/10"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Search Mode Selector */}
        <div className="flex max-w-full items-center gap-1 overflow-x-auto rounded-md border border-slate-200 bg-white p-1 shadow-[0_0_0_1px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-950/30">
          <SearchModeButton
            mode="semantic"
            currentMode={searchMode}
            onClick={() => {
              onSearchModeChange('semantic');
            }}
            icon={<Search className="h-4 w-4" />}
            label={t('project.search.modes.semantic')}
          />
          <SearchModeButton
            mode="graphTraversal"
            currentMode={searchMode}
            onClick={() => {
              onSearchModeChange('graphTraversal');
            }}
            icon={<Network className="h-4 w-4" />}
            label={t('project.search.modes.graph')}
          />
          <SearchModeButton
            mode="temporal"
            currentMode={searchMode}
            onClick={() => {
              onSearchModeChange('temporal');
            }}
            icon={<ArrowUpDown className="h-4 w-4" />}
            label={t('project.search.modes.temporal')}
          />
          <SearchModeButton
            mode="faceted"
            currentMode={searchMode}
            onClick={() => {
              onSearchModeChange('faceted');
            }}
            icon={<Filter className="h-4 w-4" />}
            label={t('project.search.modes.faceted')}
          />
          <SearchModeButton
            mode="community"
            currentMode={searchMode}
            onClick={() => {
              onSearchModeChange('community');
            }}
            icon={<Grid className="h-4 w-4" />}
            label={t('project.search.modes.community')}
          />
        </div>

        {/* Search History Dropdown */}
        {showHistory && searchHistory.length > 0 && (
          <SearchHistoryDropdown history={searchHistory} onItemClick={onHistoryItemClick} />
        )}

        <div className="flex flex-col items-start justify-between gap-4 rounded-md border border-slate-200 bg-white p-2 shadow-[0_0_0_1px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-slate-950/30 md:flex-row md:items-center">
          <div className="flex w-full flex-1 gap-2">
            {onMobileConfigOpen && (
              <button
                type="button"
                onClick={onMobileConfigOpen}
                aria-label={t('project.search.config.title')}
                title={t('project.search.config.title')}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded border border-slate-200 text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:bg-slate-900 dark:hover:text-slate-50 lg:hidden"
              >
                <PanelRightOpen className="h-4 w-4" />
              </button>
            )}
            <label className="flex-1 relative group">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                {searchMode === 'graphTraversal' ? (
                  <Network className="h-4 w-4 text-slate-400 transition-colors group-focus-within:text-slate-950 dark:group-focus-within:text-slate-50" />
                ) : searchMode === 'community' ? (
                  <Grid className="h-4 w-4 text-slate-400 transition-colors group-focus-within:text-slate-950 dark:group-focus-within:text-slate-50" />
                ) : (
                  <Search className="h-4 w-4 text-slate-400 transition-colors group-focus-within:text-slate-950 dark:group-focus-within:text-slate-50" />
                )}
              </div>
              <input
                aria-label={getInputLabel()}
                className="block h-10 w-full rounded border border-transparent bg-transparent pl-10 pr-12 text-sm text-slate-950 outline-none transition-[color,background-color,border-color,box-shadow,opacity] placeholder:text-slate-400 focus:border-slate-300 focus:bg-slate-50 focus:ring-2 focus:ring-slate-950/10 dark:text-slate-50 dark:focus:border-slate-700 dark:focus:bg-slate-900/50 dark:focus:ring-slate-50/10"
                placeholder={getPlaceholder()}
                type="text"
                value={getInputValue()}
                onChange={(e) => {
                  if (searchMode === 'graphTraversal') onStartEntityUuidChange(e.target.value);
                  else if (searchMode === 'community') onCommunityUuidChange(e.target.value);
                  else onQueryChange(e.target.value);
                }}
                onFocus={() => {
                  onSearchFocusChange(true);
                }}
                onBlur={() => {
                  onSearchFocusChange(false);
                }}
                onKeyDown={handleSearchKeyDown}
              />
              {(searchMode === 'semantic' ||
                searchMode === 'temporal' ||
                searchMode === 'faceted') && (
                <div className="absolute inset-y-0 right-0 flex items-center pr-2">
                  <button
                    type="button"
                    onClick={onVoiceSearch}
                    className={`rounded p-1.5 transition-colors ${
                      isListening
                        ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 animate-pulse motion-reduce:animate-none'
                        : 'text-slate-400 hover:bg-slate-100 hover:text-slate-950 dark:hover:bg-slate-800 dark:hover:text-slate-50'
                    }`}
                    title={
                      isListening
                        ? t('project.search.input.listening')
                        : t('project.search.input.voice_search')
                    }
                  >
                    <Mic className="w-5 h-5" />
                  </button>
                </div>
              )}
            </label>
            <button
              type="button"
              onClick={onSearch}
              disabled={loading}
              className="inline-flex h-10 shrink-0 items-center gap-2 rounded bg-slate-950 px-5 text-sm font-semibold text-white transition-[color,background-color,border-color,box-shadow,opacity] hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-950/20 disabled:opacity-50 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus:ring-slate-50/20"
            >
              <span>
                {loading
                  ? t('project.search.actions.searching')
                  : t('project.search.actions.retrieve')}
              </span>
              <Search className="h-4 w-4" />
            </button>
            <div className="hidden lg:flex items-center">
              <button
                type="button"
                onClick={onConfigToggle}
                className={`inline-flex h-10 w-10 items-center justify-center rounded border transition-colors ${
                  isConfigOpen
                    ? 'border-transparent text-slate-400 hover:bg-slate-100 hover:text-slate-950 dark:hover:bg-slate-800 dark:hover:text-slate-50'
                    : 'border-slate-300 bg-slate-100 text-slate-950 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-50'
                }`}
                title={isConfigOpen ? 'Collapse Config' : 'Expand Config'}
              >
                {isConfigOpen ? (
                  <PanelRightClose className="h-4 w-4" />
                ) : (
                  <PanelRightOpen className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
        </div>
      </header>
    );
  }
);
SearchForm.displayName = 'SearchForm';

// Sub-components
interface SearchModeButtonProps {
  mode: SearchMode;
  currentMode: SearchMode;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

const SearchModeButton = memo<SearchModeButtonProps>(
  ({ mode, currentMode, onClick, icon, label }) => (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-9 shrink-0 items-center gap-2 rounded px-3 text-sm font-medium transition-[color,background-color,border-color,box-shadow,opacity] focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:focus:ring-slate-50/10 ${
        mode === currentMode
          ? 'bg-slate-950 text-white shadow-[0_0_0_1px_rgba(15,23,42,0.08)] dark:bg-slate-50 dark:text-slate-950'
          : 'text-slate-500 hover:bg-slate-50 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-50'
      }`}
    >
      {icon}
      {label}
    </button>
  )
);
SearchModeButton.displayName = 'SearchModeButton';

interface HistoryButtonProps {
  showHistory: boolean;
  count: number;
  onClick: () => void;
}

const HistoryButton = memo<HistoryButtonProps>(({ showHistory, count, onClick }) => {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-9 items-center gap-1.5 rounded border px-3 text-xs font-medium transition-[color,background-color,border-color,box-shadow,opacity] ${
        showHistory
          ? 'border-slate-300 bg-slate-100 text-slate-950 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-50'
          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900/30 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:bg-slate-900 dark:hover:text-slate-50'
      }`}
    >
      <MessageSquare className="h-3.5 w-3.5" />
      {t('project.search.actions.history')} ({count})
    </button>
  );
});
HistoryButton.displayName = 'HistoryButton';

interface SearchHistoryDropdownProps {
  history: Array<{ query: string; mode: string; timestamp: number }>;
  onItemClick: (item: { query: string; mode: string }) => void;
}

const SearchHistoryDropdown = memo<SearchHistoryDropdownProps>(({ history, onItemClick }) => {
  const { t } = useTranslation();

  return (
    <div className="max-h-64 overflow-y-auto rounded-md border border-slate-200 bg-white p-2 shadow-[0_8px_24px_-16px_rgba(15,23,42,0.30)] dark:border-slate-800 dark:bg-slate-950">
      <div className="mb-2 px-2 text-xs font-medium text-slate-500 dark:text-slate-400">
        {t('project.search.actions.recent')}
      </div>
      {history.map((item, idx) => (
        <button
          key={idx}
          type="button"
          onClick={() => {
            onItemClick(item);
          }}
          className="group flex w-full items-center justify-between rounded px-3 py-2 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-900"
        >
          <div className="flex flex-col">
            <span className="max-w-md truncate text-sm text-slate-950 dark:text-slate-50">
              {item.query}
            </span>
            <span className="text-xs text-slate-500 capitalize">{item.mode}</span>
          </div>
          <span className="text-xs text-slate-400">{formatTimeOnly(item.timestamp)}</span>
        </button>
      ))}
    </div>
  );
});
SearchHistoryDropdown.displayName = 'SearchHistoryDropdown';
