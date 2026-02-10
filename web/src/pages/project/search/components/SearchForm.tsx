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
  MessageSquare,
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
  onHistoryToggle: () => void;
  onHistoryItemClick: (item: { query: string; mode: string }) => void;
  onExportResults?: () => void;
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
    onHistoryToggle,
    onHistoryItemClick,
    onExportResults: _onExportResults, // Intentionally unused - for future feature
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

    return (
      <header className="flex flex-col gap-4 px-6 pt-6 pb-2 shrink-0">
        {/* Search Mode Selector */}
        <div className="flex flex-wrap gap-2 items-center">
          <SearchModeButton
            mode="semantic"
            currentMode={searchMode}
            onClick={() => onSearchModeChange('semantic')}
            icon={<Search className="w-4 h-4" />}
            label={t('project.search.modes.semantic')}
          />
          <SearchModeButton
            mode="graphTraversal"
            currentMode={searchMode}
            onClick={() => onSearchModeChange('graphTraversal')}
            icon={<Network className="w-4 h-4" />}
            label={t('project.search.modes.graph')}
          />
          <SearchModeButton
            mode="temporal"
            currentMode={searchMode}
            onClick={() => onSearchModeChange('temporal')}
            icon={<Grid className="w-4 h-4" />}
            label={t('project.search.modes.temporal')}
          />
          <SearchModeButton
            mode="faceted"
            currentMode={searchMode}
            onClick={() => onSearchModeChange('faceted')}
            icon={<Network className="w-4 h-4" />}
            label={t('project.search.modes.faceted')}
          />
          <SearchModeButton
            mode="community"
            currentMode={searchMode}
            onClick={() => onSearchModeChange('community')}
            icon={<Grid className="w-4 h-4" />}
            label={t('project.search.modes.community')}
          />
          <div className="flex-1"></div>

          {/* Search History & Export */}
          {searchHistory.length > 0 && (
            <HistoryButton
              showHistory={showHistory}
              count={searchHistory.length}
              onClick={onHistoryToggle}
            />
          )}
        </div>

        {/* Search History Dropdown */}
        {showHistory && searchHistory.length > 0 && (
          <SearchHistoryDropdown history={searchHistory} onItemClick={onHistoryItemClick} />
        )}

        <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
          <div className="flex-1 w-full flex gap-3">
            <label className="flex-1 relative group">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                {searchMode === 'graphTraversal' ? (
                  <Network className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                ) : searchMode === 'community' ? (
                  <Grid className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                ) : (
                  <Search className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                )}
              </div>
              <input
                className="block w-full pl-10 pr-12 py-3 bg-white dark:bg-[#1e212b] border border-transparent focus:border-blue-600/50 ring-0 focus:ring-4 focus:ring-blue-600/10 rounded-xl text-sm placeholder-slate-400 text-slate-900 dark:text-white shadow-sm transition-all"
                placeholder={getPlaceholder()}
                type="text"
                value={getInputValue()}
                onChange={(e) => {
                  if (searchMode === 'graphTraversal') onStartEntityUuidChange(e.target.value);
                  else if (searchMode === 'community') onCommunityUuidChange(e.target.value);
                  else onQueryChange(e.target.value);
                }}
                onFocus={() => onSearchFocusChange(true)}
                onBlur={() => onSearchFocusChange(false)}
                onKeyDown={handleSearchKeyDown}
              />
              {(searchMode === 'semantic' ||
                searchMode === 'temporal' ||
                searchMode === 'faceted') && (
                <div className="absolute inset-y-0 right-0 pr-2 flex items-center">
                  <button
                    onClick={onVoiceSearch}
                    className={`p-1.5 rounded-lg transition-colors ${
                      isListening
                        ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 animate-pulse'
                        : 'text-slate-400 hover:text-blue-600 hover:bg-slate-100 dark:hover:bg-slate-700'
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
              onClick={onSearch}
              disabled={loading}
              className="h-[46px] px-6 bg-blue-600 hover:bg-blue-600/90 text-white text-sm font-semibold rounded-lg shadow-md shadow-blue-600/20 flex items-center gap-2 transition-all active:scale-95 shrink-0 disabled:opacity-50"
            >
              <span>
                {loading
                  ? t('project.search.actions.searching')
                  : t('project.search.actions.retrieve')}
              </span>
              <Search className="w-5 h-5" />
            </button>
            <div className="hidden lg:flex items-center">
              <button
                onClick={onConfigToggle}
                className={`p-3 h-[46px] rounded-lg transition-colors border ${
                  isConfigOpen
                    ? 'border-transparent text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                    : 'border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                }`}
                title={isConfigOpen ? 'Collapse Config' : 'Expand Config'}
              >
                {isConfigOpen ? (
                  <PanelRightClose className="w-5 h-5" />
                ) : (
                  <PanelRightOpen className="w-5 h-5" />
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
      onClick={onClick}
      className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${
        mode === currentMode
          ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
          : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
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

const HistoryButton = memo<HistoryButtonProps>(({ showHistory, count, onClick }) => (
  <button
    onClick={onClick}
    className={`px-3 py-2 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
      showHistory
        ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
        : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
    }`}
  >
    <MessageSquare className="w-3.5 h-3.5" />
    History ({count})
  </button>
));
HistoryButton.displayName = 'HistoryButton';

interface SearchHistoryDropdownProps {
  history: Array<{ query: string; mode: string; timestamp: number }>;
  onItemClick: (item: { query: string; mode: string }) => void;
}

const SearchHistoryDropdown = memo<SearchHistoryDropdownProps>(({ history, onItemClick }) => (
  <div className="bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-xl shadow-lg p-3 max-h-64 overflow-y-auto">
    <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Recent</div>
    {history.map((item, idx) => (
      <button
        key={idx}
        onClick={() => onItemClick(item)}
        className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors flex items-center justify-between group"
      >
        <div className="flex flex-col">
          <span className="text-sm text-slate-900 dark:text-white truncate max-w-md">
            {item.query}
          </span>
          <span className="text-xs text-slate-500 capitalize">{item.mode}</span>
        </div>
        <span className="text-xs text-slate-400">
          {formatTimeOnly(item.timestamp)}
        </span>
      </button>
    ))}
  </div>
));
SearchHistoryDropdown.displayName = 'SearchHistoryDropdown';
