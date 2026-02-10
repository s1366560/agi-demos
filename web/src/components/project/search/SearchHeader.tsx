/**
 * SearchHeader - Search mode selector and input header
 *
 * A composite component part of EnhancedSearch.
 * Extracts the header section with search mode selection and input.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import {
  Search,
  Network,
  ArrowUpDown,
  Filter,
  Grid,
  Mic,
  ArrowRight,
  Sliders,
  PanelRightClose,
  PanelRightOpen,
  MessageSquare,
  Download,
} from 'lucide-react';
import { formatTimeOnly } from '@/utils/date';

import type { SearchMode } from '@/hooks/useSearchState';

export interface SearchHeaderProps {
  // Search mode
  searchMode: SearchMode;
  setSearchMode: (mode: SearchMode) => void;

  // Input values
  query: string;
  startEntityUuid: string;
  communityUuid: string;

  // Input handlers
  setQuery: (query: string) => void;
  setStartEntityUuid: (uuid: string) => void;
  setCommunityUuid: (uuid: string) => void;
  onSearch: () => void;

  // UI state
  loading: boolean;
  isSearchFocused: boolean;
  isConfigOpen: boolean;
  isListening: boolean;
  showHistory: boolean;

  // UI handlers
  setIsSearchFocused: (focused: boolean) => void;
  toggleConfigOpen: () => void;
  setShowHistory: (show: boolean) => void;
  setShowMobileConfig: (show: boolean) => void;
  onVoiceSearch: () => void;

  // History
  searchHistory: Array<{ query: string; mode: string; timestamp: number }>;

  // Results
  hasResults: boolean;
  onExportResults: () => void;

  // Mobile
  isMobile?: boolean;
}

/**
 * SearchHeader component
 *
 * Displays the search mode selector buttons and the search input field.
 *
 * @example
 * <SearchHeader
 *   searchMode="semantic"
 *   setSearchMode={setSearchMode}
 *   query={query}
 *   setQuery={setQuery}
 *   onSearch={handleSearch}
 *   loading={loading}
 *   {...otherProps}
 * />
 */
export function SearchHeader({
  searchMode,
  setSearchMode,
  query,
  startEntityUuid,
  communityUuid,
  setQuery,
  setStartEntityUuid,
  setCommunityUuid,
  onSearch,
  loading,
  isSearchFocused,
  isConfigOpen,
  isListening,
  showHistory,
  setIsSearchFocused,
  toggleConfigOpen,
  setShowHistory,
  setShowMobileConfig,
  onVoiceSearch,
  searchHistory,
  hasResults,
  onExportResults,
  isMobile = false,
}: SearchHeaderProps) {
  const { t } = useTranslation();

  const getInputValue = () => {
    if (searchMode === 'graphTraversal') return startEntityUuid;
    if (searchMode === 'community') return communityUuid;
    return query;
  };

  const handleInputChange = (value: string) => {
    if (searchMode === 'graphTraversal') {
      setStartEntityUuid(value);
    } else if (searchMode === 'community') {
      setCommunityUuid(value);
    } else {
      setQuery(value);
    }
  };

  const getPlaceholder = () => {
    if (searchMode === 'graphTraversal') return t('project.search.input.placeholder.graph');
    if (searchMode === 'community') return t('project.search.input.placeholder.community');
    if (isSearchFocused) return '';
    return t('project.search.input.placeholder.default');
  };

  const getInputIcon = () => {
    if (searchMode === 'graphTraversal') return Network;
    if (searchMode === 'community') return Grid;
    return Search;
  };

  const showVoiceButton =
    searchMode === 'semantic' || searchMode === 'temporal' || searchMode === 'faceted';

  return (
    <header className="flex flex-col gap-4 px-6 pt-6 pb-2 shrink-0">
      {/* Search Mode Selector */}
      <div className="flex flex-wrap gap-2 items-center">
        <SearchModeButton
          mode="semantic"
          currentMode={searchMode}
          onClick={() => setSearchMode('semantic')}
          icon={Search}
          label={t('project.search.modes.semantic')}
        />
        <SearchModeButton
          mode="graphTraversal"
          currentMode={searchMode}
          onClick={() => setSearchMode('graphTraversal')}
          icon={Network}
          label={t('project.search.modes.graph')}
        />
        <SearchModeButton
          mode="temporal"
          currentMode={searchMode}
          onClick={() => setSearchMode('temporal')}
          icon={ArrowUpDown}
          label={t('project.search.modes.temporal')}
        />
        <SearchModeButton
          mode="faceted"
          currentMode={searchMode}
          onClick={() => setSearchMode('faceted')}
          icon={Filter}
          label={t('project.search.modes.faceted')}
        />
        <SearchModeButton
          mode="community"
          currentMode={searchMode}
          onClick={() => setSearchMode('community')}
          icon={Grid}
          label={t('project.search.modes.community')}
        />
        <div className="flex-1" />

        {/* Search History & Export */}
        <div className="flex items-center gap-2">
          {searchHistory.length > 0 && (
            <HistoryButton
              count={searchHistory.length}
              show={showHistory}
              onClick={() => setShowHistory(!showHistory)}
              label={t('project.search.actions.history')}
            />
          )}
          {hasResults && (
            <ExportButton onClick={onExportResults} label={t('project.search.actions.export')} />
          )}
        </div>
      </div>

      {/* Search History Dropdown */}
      {showHistory && searchHistory.length > 0 && (
        <SearchHistoryDropdown
          history={searchHistory}
          onSelect={(item) => {
            setQuery(item.query);
            setSearchMode(item.mode as SearchMode);
            setShowHistory(false);
          }}
          getModeLabel={(mode) => mode.replace('graphTraversal', t('project.search.modes.graph'))}
          recentLabel={t('project.search.actions.recent')}
        />
      )}

      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
        <div className="flex-1 w-full flex gap-3">
          {isMobile && <MobileConfigButton onClick={() => setShowMobileConfig(true)} />}
          <SearchInput
            value={getInputValue()}
            onChange={handleInputChange}
            onFocus={() => setIsSearchFocused(true)}
            onBlur={() => setIsSearchFocused(false)}
            onKeyDown={(e) => e.key === 'Enter' && onSearch()}
            placeholder={getPlaceholder()}
            Icon={getInputIcon()}
            showVoiceButton={showVoiceButton}
            isListening={isListening}
            onVoiceSearch={onVoiceSearch}
            listeningLabel={t('project.search.input.listening')}
            voiceSearchLabel={t('project.search.input.voice_search')}
          />
          <SearchButton
            loading={loading}
            onClick={onSearch}
            searchingLabel={t('project.search.actions.searching')}
            retrieveLabel={t('project.search.actions.retrieve')}
          />
          {!isMobile && <ConfigToggle isOpen={isConfigOpen} onClick={toggleConfigOpen} />}
        </div>
      </div>
    </header>
  );
}

// Sub-components for better organization

interface SearchModeButtonProps {
  mode: SearchMode;
  currentMode: SearchMode;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

function SearchModeButton({
  mode,
  currentMode,
  onClick,
  icon: Icon,
  label,
}: SearchModeButtonProps) {
  const isActive = mode === currentMode;

  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${
        isActive
          ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
          : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
      }`}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );
}

interface HistoryButtonProps {
  count: number;
  show: boolean;
  onClick: () => void;
  label: string;
}

function HistoryButton({ count, show, onClick, label }: HistoryButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
        show
          ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
          : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
      }`}
    >
      <MessageSquare className="w-3.5 h-3.5" />
      {label} ({count})
    </button>
  );
}

interface ExportButtonProps {
  onClick: () => void;
  label: string;
}

function ExportButton({ onClick, label }: ExportButtonProps) {
  return (
    <button
      onClick={onClick}
      className="px-3 py-2 rounded-lg text-xs font-semibold bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800 transition-all flex items-center gap-1.5"
    >
      <Download className="w-3.5 h-3.5" />
      {label}
    </button>
  );
}

interface SearchHistoryDropdownProps {
  history: Array<{ query: string; mode: string; timestamp: number }>;
  onSelect: (item: { query: string; mode: string }) => void;
  getModeLabel: (mode: string) => string;
  recentLabel: string;
}

function SearchHistoryDropdown({
  history,
  onSelect,
  getModeLabel,
  recentLabel,
}: SearchHistoryDropdownProps) {
  return (
    <div className="bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-xl shadow-lg p-3 max-h-64 overflow-y-auto">
      <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
        {recentLabel}
      </div>
      {history.map((item, idx) => (
        <button
          key={idx}
          onClick={() => onSelect(item)}
          className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors flex items-center justify-between group"
        >
          <div className="flex flex-col">
            <span className="text-sm text-slate-900 dark:text-white truncate max-w-md">
              {item.query}
            </span>
            <span className="text-xs text-slate-500 capitalize">{getModeLabel(item.mode)}</span>
          </div>
          <span className="text-xs text-slate-400">
            {formatTimeOnly(item.timestamp)}
          </span>
        </button>
      ))}
    </div>
  );
}

interface MobileConfigButtonProps {
  onClick: () => void;
}

function MobileConfigButton({ onClick }: MobileConfigButtonProps) {
  return (
    <button
      onClick={onClick}
      className="lg:hidden p-3 bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-xl text-slate-500 hover:text-blue-600 transition-colors shadow-sm"
    >
      <Sliders className="w-5 h-5" />
    </button>
  );
}

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onFocus: () => void;
  onBlur: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  placeholder: string;
  Icon: React.ComponentType<{ className?: string }>;
  showVoiceButton: boolean;
  isListening: boolean;
  onVoiceSearch: () => void;
  listeningLabel: string;
  voiceSearchLabel: string;
}

function SearchInput({
  value,
  onChange,
  onFocus,
  onBlur,
  onKeyDown,
  placeholder,
  Icon,
  showVoiceButton,
  isListening,
  onVoiceSearch,
  listeningLabel,
  voiceSearchLabel,
}: SearchInputProps) {
  return (
    <label className="flex-1 relative group">
      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
        <Icon className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
      </div>
      <input
        className="block w-full pl-10 pr-12 py-3 bg-white dark:bg-[#1e212b] border border-transparent focus:border-blue-600/50 ring-0 focus:ring-4 focus:ring-blue-600/10 rounded-xl text-sm placeholder-slate-400 text-slate-900 dark:text-white shadow-sm transition-all"
        placeholder={placeholder}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocus}
        onBlur={onBlur}
        onKeyDown={onKeyDown}
      />
      {showVoiceButton && (
        <div className="absolute inset-y-0 right-0 pr-2 flex items-center">
          <button
            onClick={onVoiceSearch}
            className={`p-1.5 rounded-lg transition-colors ${
              isListening
                ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 animate-pulse'
                : 'text-slate-400 hover:text-blue-600 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
            title={isListening ? listeningLabel : voiceSearchLabel}
          >
            <Mic className="w-5 h-5" />
          </button>
        </div>
      )}
    </label>
  );
}

interface SearchButtonProps {
  loading: boolean;
  onClick: () => void;
  searchingLabel: string;
  retrieveLabel: string;
}

function SearchButton({ loading, onClick, searchingLabel, retrieveLabel }: SearchButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="h-[46px] px-6 bg-blue-600 hover:bg-blue-600/90 text-white text-sm font-semibold rounded-lg shadow-md shadow-blue-600/20 flex items-center gap-2 transition-all active:scale-95 shrink-0 disabled:opacity-50"
    >
      <span>{loading ? searchingLabel : retrieveLabel}</span>
      <ArrowRight className="w-5 h-5" />
    </button>
  );
}

interface ConfigToggleProps {
  isOpen: boolean;
  onClick: () => void;
}

function ConfigToggle({ isOpen, onClick }: ConfigToggleProps) {
  return (
    <div className="hidden lg:flex items-center">
      <button
        onClick={onClick}
        className={`p-3 h-[46px] rounded-lg transition-colors border ${
          isOpen
            ? 'border-transparent text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
            : 'border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
        }`}
        title={isOpen ? 'Collapse Config' : 'Expand Config'}
      >
        {isOpen ? <PanelRightClose className="w-5 h-5" /> : <PanelRightOpen className="w-5 h-5" />}
      </button>
    </div>
  );
}

export default SearchHeader;
