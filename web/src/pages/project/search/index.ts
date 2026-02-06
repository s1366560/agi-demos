/**
 * Search components barrel export
 */

export { SearchForm } from './components/SearchForm';
export { SearchResults } from './components/SearchResults';
export { SearchConfig } from './components/SearchConfig';

export type { SearchMode } from './components/SearchForm';
export type { SearchResult } from './components/SearchResults';
export type {
  SearchMode as ConfigSearchMode,
  ConfigTab,
  RetrievalMode,
} from './components/SearchConfig';

// Compound component types
export type {
  EnhancedSearchRootProps,
  EnhancedSearchFormProps,
  EnhancedSearchConfigProps,
  EnhancedSearchResultsProps,
  EnhancedSearchGraphProps,
  EnhancedSearchErrorProps,
  EnhancedSearchHistoryProps,
  EnhancedSearchCompound,
  EnhancedSearchContextValue,
  SearchParams,
  SearchHistoryEntry,
  CustomTimeRange,
  TimeRange,
  ResultsViewMode,
} from './types';
