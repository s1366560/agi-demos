/**
 * SearchConfig - Extracted from EnhancedSearch
 *
 * Displays the configuration sidebar for search parameters and filters.
 */

import { memo, useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Sliders, Filter, X, Plus, Minus, ChevronDown, HelpCircle, Network } from 'lucide-react';

export type SearchMode = 'semantic' | 'graphTraversal' | 'temporal' | 'faceted' | 'community';
export type ConfigTab = 'params' | 'filters';
export type RetrievalMode = 'hybrid' | 'nodeDistance';

interface SearchConfigProps {
  searchMode: SearchMode;
  configTab: ConfigTab;
  isConfigOpen: boolean;
  showMobileConfig: boolean;

  // Semantic search params
  retrievalMode: RetrievalMode;
  strategy: string;
  focalNode: string;
  crossEncoder: string;

  // Graph traversal params
  maxDepth: number;
  relationshipTypes: string[];

  // Temporal params
  timeRange: string;
  customTimeRange: { since?: string | undefined; until?: string | undefined };

  // Faceted params
  selectedEntityTypes: string[];
  selectedTags: string[];
  availableTags: string[];

  // Community params
  communityUuid: string;
  includeEpisodes: boolean;

  // Callbacks
  onMobileConfigClose: () => void;
  onConfigTabChange: (tab: ConfigTab) => void;
  onRetrievalModeChange: (mode: RetrievalMode) => void;
  onStrategyChange: (strategy: string) => void;
  onFocalNodeChange: (value: string) => void;
  onCrossEncoderChange: (encoder: string) => void;
  onMaxDepthChange: (depth: number) => void;
  onRelationshipTypesChange: (types: string[]) => void;
  onTimeRangeChange: (range: string) => void;
  onCustomTimeRangeChange: (range: {
    since?: string | undefined;
    until?: string | undefined;
  }) => void;
  onSelectedEntityTypesChange: (types: string[]) => void;
  onSelectedTagsChange: (tags: string[]) => void;
  onIncludeEpisodesChange: (include: boolean) => void;

  // Tooltip
  showTooltip: string | null;
  onShowTooltip: (tooltip: string | null) => void;
}

export const SearchConfig = memo<SearchConfigProps>(
  ({
    searchMode,
    configTab,
    isConfigOpen,
    showMobileConfig,
    retrievalMode,
    strategy,
    focalNode,
    crossEncoder,
    maxDepth,
    relationshipTypes,
    timeRange,
    customTimeRange,
    selectedEntityTypes,
    selectedTags,
    availableTags,
    communityUuid: _communityUuid, // Not used in current UI
    includeEpisodes,
    onMobileConfigClose,
    onConfigTabChange,
    onRetrievalModeChange,
    onStrategyChange,
    onFocalNodeChange,
    onCrossEncoderChange,
    onMaxDepthChange,
    onRelationshipTypesChange,
    onTimeRangeChange,
    onCustomTimeRangeChange,
    onSelectedEntityTypesChange,
    onSelectedTagsChange,
    onIncludeEpisodesChange,
    showTooltip,
    onShowTooltip,
  }) => {
    const { t } = useTranslation();

    const toggleRelationshipType = useCallback(
      (rel: string) => {
        onRelationshipTypesChange(
          relationshipTypes.includes(rel)
            ? relationshipTypes.filter((r) => r !== rel)
            : [...relationshipTypes, rel]
        );
      },
      [relationshipTypes, onRelationshipTypesChange]
    );

    const toggleEntityType = useCallback(
      (type: string) => {
        onSelectedEntityTypesChange(
          selectedEntityTypes.includes(type)
            ? selectedEntityTypes.filter((t) => t !== type)
            : [...selectedEntityTypes, type]
        );
      },
      [selectedEntityTypes, onSelectedEntityTypesChange]
    );

    const toggleTag = useCallback(
      (tag: string) => {
        onSelectedTagsChange(
          selectedTags.includes(tag)
            ? selectedTags.filter((t) => t !== tag)
            : [...selectedTags, tag]
        );
      },
      [selectedTags, onSelectedTagsChange]
    );

    return (
      <>
        {/* Mobile Backdrop */}
        {showMobileConfig && (
          <div
            className="fixed inset-0 z-40 bg-slate-950/60 lg:hidden"
            onClick={onMobileConfigClose}
          />
        )}

        <aside
          className={`
                fixed inset-y-0 right-0 z-50 w-80 bg-slate-50 dark:bg-slate-950 lg:relative lg:z-0 lg:h-full lg:w-[300px] lg:shrink-0 lg:transform-none lg:bg-transparent transition-[color,background-color,border-color,box-shadow,opacity,transform,width] duration-300 ease-in-out
                ${showMobileConfig ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'}
                ${!isConfigOpen ? 'lg:w-0 lg:overflow-hidden lg:opacity-0 lg:p-0' : ''}
            `}
        >
          <div className="flex h-full flex-1 flex-col overflow-hidden rounded-md bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-surface-dark dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]">
            <div className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-slate-50">
                <Sliders className="h-4 w-4 text-slate-500" />
                {t('project.search.config.title')}
              </h2>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                  {t('project.search.config.advanced')}
                </span>
                <button
                  type="button"
                  onClick={onMobileConfigClose}
                  aria-label={t('common.close')}
                  className="rounded p-1 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-950 dark:hover:bg-slate-800 dark:hover:text-slate-50 lg:hidden"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>

            <div className="border-b border-slate-200 p-3 dark:border-slate-800">
              <ConfigTabSelector currentTab={configTab} onTabChange={onConfigTabChange} />
            </div>

            {/* Tab Content */}
            <div className="custom-scrollbar flex flex-1 flex-col gap-5 overflow-y-auto p-4">
              {searchMode === 'semantic' && configTab === 'params' && (
                <SemanticSearchParams
                  retrievalMode={retrievalMode}
                  strategy={strategy}
                  focalNode={focalNode}
                  crossEncoder={crossEncoder}
                  onRetrievalModeChange={onRetrievalModeChange}
                  onStrategyChange={onStrategyChange}
                  onFocalNodeChange={onFocalNodeChange}
                  onCrossEncoderChange={onCrossEncoderChange}
                  showTooltip={showTooltip}
                  onShowTooltip={onShowTooltip}
                />
              )}

              {searchMode === 'graphTraversal' && configTab === 'params' && (
                <GraphTraversalParams
                  maxDepth={maxDepth}
                  relationshipTypes={relationshipTypes}
                  onMaxDepthChange={onMaxDepthChange}
                  onToggleRelationshipType={toggleRelationshipType}
                />
              )}

              {searchMode === 'temporal' && (
                <TemporalFilters
                  timeRange={timeRange}
                  customTimeRange={customTimeRange}
                  onTimeRangeChange={onTimeRangeChange}
                  onCustomTimeRangeChange={onCustomTimeRangeChange}
                />
              )}

              {searchMode === 'faceted' && (
                <FacetedFilters
                  selectedEntityTypes={selectedEntityTypes}
                  selectedTags={selectedTags}
                  availableTags={availableTags}
                  onToggleEntityType={toggleEntityType}
                  onToggleTag={toggleTag}
                />
              )}

              {searchMode === 'community' && (
                <CommunityFilters
                  includeEpisodes={includeEpisodes}
                  onIncludeEpisodesChange={onIncludeEpisodesChange}
                />
              )}
            </div>
          </div>
        </aside>
      </>
    );
  }
);
SearchConfig.displayName = 'SearchConfig';

// Sub-components
interface ConfigTabSelectorProps {
  currentTab: ConfigTab;
  onTabChange: (tab: ConfigTab) => void;
}

const ConfigTabSelector = memo<ConfigTabSelectorProps>(({ currentTab, onTabChange }) => {
  const { t } = useTranslation();

  return (
    <div className="flex shrink-0 rounded-md border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-950/30">
      <button
        type="button"
        onClick={() => {
          onTabChange('params');
        }}
        className={`flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-xs font-medium transition-[color,background-color,border-color,box-shadow,opacity] ${currentTab === 'params' ? 'bg-white text-slate-950 shadow-[0_0_0_1px_rgba(15,23,42,0.08)] dark:bg-slate-800 dark:text-slate-50' : 'text-slate-500 hover:text-slate-950 dark:text-slate-400 dark:hover:text-slate-50'}`}
      >
        <Sliders className="h-3.5 w-3.5" />
        {t('project.search.config.params')}
      </button>
      <button
        type="button"
        onClick={() => {
          onTabChange('filters');
        }}
        className={`flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-xs font-medium transition-[color,background-color,border-color,box-shadow,opacity] ${currentTab === 'filters' ? 'bg-white text-slate-950 shadow-[0_0_0_1px_rgba(15,23,42,0.08)] dark:bg-slate-800 dark:text-slate-50' : 'text-slate-500 hover:text-slate-950 dark:text-slate-400 dark:hover:text-slate-50'}`}
      >
        <Filter className="h-3.5 w-3.5" />
        {t('project.search.config.filters')}
      </button>
    </div>
  );
});
ConfigTabSelector.displayName = 'ConfigTabSelector';

interface SemanticSearchParamsProps {
  retrievalMode: RetrievalMode;
  strategy: string;
  focalNode: string;
  crossEncoder: string;
  onRetrievalModeChange: (mode: RetrievalMode) => void;
  onStrategyChange: (strategy: string) => void;
  onFocalNodeChange: (value: string) => void;
  onCrossEncoderChange: (encoder: string) => void;
  showTooltip: string | null;
  onShowTooltip: (tooltip: string | null) => void;
}

const SemanticSearchParams = memo<SemanticSearchParamsProps>(
  ({
    retrievalMode,
    strategy,
    focalNode,
    crossEncoder,
    onRetrievalModeChange,
    onStrategyChange,
    onFocalNodeChange,
    onCrossEncoderChange,
    showTooltip,
    onShowTooltip,
  }) => (
    <>
      <RetrievalModeSelector value={retrievalMode} onChange={onRetrievalModeChange} />
      <StrategySelector value={strategy} onChange={onStrategyChange} />
      <FocalNodeInput
        value={focalNode}
        onChange={onFocalNodeChange}
        disabled={retrievalMode !== 'nodeDistance'}
        showTooltip={showTooltip === 'focal'}
        onShowTooltip={() => {
          onShowTooltip('focal');
        }}
        onHideTooltip={() => {
          onShowTooltip(null);
        }}
      />
      <CrossEncoderSelector value={crossEncoder} onChange={onCrossEncoderChange} />
    </>
  )
);
SemanticSearchParams.displayName = 'SemanticSearchParams';

const RetrievalModeSelector = memo<{
  value: RetrievalMode;
  onChange: (mode: RetrievalMode) => void;
}>(({ value, onChange }) => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
        {t('project.search.params.retrieval_mode')}
      </label>
      <div className="flex rounded-md border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-950/30">
        <button
          type="button"
          onClick={() => {
            onChange('hybrid');
          }}
          className={`flex-1 rounded px-2 py-2 text-xs font-medium transition-[color,background-color,border-color,box-shadow,opacity] ${value === 'hybrid' ? 'bg-white text-slate-950 shadow-[0_0_0_1px_rgba(15,23,42,0.08)] dark:bg-slate-800 dark:text-slate-50' : 'text-slate-500 hover:text-slate-950 dark:text-slate-400 dark:hover:text-slate-50'}`}
        >
          {t('project.search.params.hybrid')}
        </button>
        <button
          type="button"
          onClick={() => {
            onChange('nodeDistance');
          }}
          className={`flex-1 rounded px-2 py-2 text-xs font-medium transition-[color,background-color,border-color,box-shadow,opacity] ${value === 'nodeDistance' ? 'bg-white text-slate-950 shadow-[0_0_0_1px_rgba(15,23,42,0.08)] dark:bg-slate-800 dark:text-slate-50' : 'text-slate-500 hover:text-slate-950 dark:text-slate-400 dark:hover:text-slate-50'}`}
        >
          {t('project.search.params.node_distance')}
        </button>
      </div>
    </div>
  );
});
RetrievalModeSelector.displayName = 'RetrievalModeSelector';

const StrategySelector = memo<{ value: string; onChange: (value: string) => void }>(
  ({ value, onChange }) => {
    const { t } = useTranslation();

    return (
      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {t('project.search.params.strategy')}
        </label>
        <div className="relative">
          <select
            aria-label={t('project.search.params.strategy')}
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            className="w-full cursor-pointer appearance-none rounded-md border border-slate-200 bg-slate-50 py-2.5 pl-3 pr-8 text-xs text-slate-700 shadow-sm transition-colors hover:bg-slate-100 focus:border-slate-400 focus:ring-1 focus:ring-slate-400 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <option value="COMBINED_HYBRID_SEARCH_RRF">
              {t('project.search.options.strategies.COMBINED_HYBRID_SEARCH_RRF')}
            </option>
            <option value="EDGE_HYBRID_SEARCH_CROSS_ENCODER">
              {t('project.search.options.strategies.EDGE_HYBRID_SEARCH_CROSS_ENCODER')}
            </option>
            <option value="HYBRID_MMR">{t('project.search.options.strategies.HYBRID_MMR')}</option>
            <option value="STANDARD_DENSE">
              {t('project.search.options.strategies.STANDARD_DENSE')}
            </option>
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
            <ChevronDown className="w-4 h-4" />
          </div>
        </div>
      </div>
    );
  }
);
StrategySelector.displayName = 'StrategySelector';

const FocalNodeInput = memo<{
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  showTooltip: boolean;
  onShowTooltip: () => void;
  onHideTooltip: () => void;
}>(({ value, onChange, disabled, showTooltip, onShowTooltip, onHideTooltip }) => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {t('project.search.params.focal_node')}
        </label>
        <div className="relative">
          <HelpCircle
            className="h-4 w-4 cursor-help text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
            onMouseEnter={onShowTooltip}
            onMouseLeave={onHideTooltip}
          />
          {showTooltip && (
            <div className="absolute right-0 top-6 z-50 w-64 rounded-md bg-slate-950 p-2 text-xs text-white shadow-lg dark:bg-slate-700">
              <p className="font-semibold mb-1">{t('project.search.params.focal_tooltip.title')}</p>
              <p>{t('project.search.params.focal_tooltip.desc')}</p>
            </div>
          )}
        </div>
      </div>
      <div className="relative group">
        <input
          aria-label={t('project.search.params.focal_node')}
          className="w-full rounded-md border border-slate-200 bg-slate-50 py-2.5 pl-9 pr-3 text-xs text-slate-700 transition-shadow placeholder:text-slate-400 focus:border-slate-400 focus:ring-1 focus:ring-slate-400 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200"
          placeholder={t('project.search.params.focalPlaceholder', 'e.g. node-1234-uuid...')}
          type="text"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
          }}
          disabled={disabled}
        />
        <Network className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400 transition-colors group-focus-within:text-slate-700 dark:group-focus-within:text-slate-200" />
      </div>
    </div>
  );
});
FocalNodeInput.displayName = 'FocalNodeInput';

const CrossEncoderSelector = memo<{ value: string; onChange: (value: string) => void }>(
  ({ value, onChange }) => {
    const { t } = useTranslation();

    return (
      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {t('project.search.params.cross_encoder')}
        </label>
        <div className="relative">
          <select
            aria-label={t('project.search.params.cross_encoder')}
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            className="w-full cursor-pointer appearance-none rounded-md border border-slate-200 bg-slate-50 py-2.5 pl-3 pr-8 text-xs text-slate-700 shadow-sm transition-colors hover:bg-slate-100 focus:border-slate-400 focus:ring-1 focus:ring-slate-400 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <option value="openai">{t('project.search.options.cross_encoders.openai')}</option>
            <option value="gemini">{t('project.search.options.cross_encoders.gemini')}</option>
            <option value="bge">{t('project.search.options.cross_encoders.bge')}</option>
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
            <ChevronDown className="w-4 h-4" />
          </div>
        </div>
      </div>
    );
  }
);
CrossEncoderSelector.displayName = 'CrossEncoderSelector';

interface GraphTraversalParamsProps {
  maxDepth: number;
  relationshipTypes: string[];
  onMaxDepthChange: (depth: number) => void;
  onToggleRelationshipType: (type: string) => void;
}

const GraphTraversalParams = memo<GraphTraversalParamsProps>(
  ({ maxDepth, relationshipTypes, onMaxDepthChange, onToggleRelationshipType }) => {
    const { t } = useTranslation();

    return (
      <>
        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {t('project.search.params.max_depth')}
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                onMaxDepthChange(Math.max(1, maxDepth - 1));
              }}
              aria-label={t('project.search.params.decrease_max_depth', 'Decrease max depth')}
              title={t('project.search.params.decrease_max_depth', 'Decrease max depth')}
              className="rounded-md border border-slate-200 bg-slate-50 p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Minus className="w-4 h-4" />
            </button>
            <span className="flex-1 text-center font-semibold text-slate-950 dark:text-slate-50">
              {maxDepth}
            </span>
            <button
              type="button"
              onClick={() => {
                onMaxDepthChange(Math.min(5, maxDepth + 1));
              }}
              aria-label={t('project.search.params.increase_max_depth', 'Increase max depth')}
              title={t('project.search.params.increase_max_depth', 'Increase max depth')}
              className="rounded-md border border-slate-200 bg-slate-50 p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {t('project.search.params.relationship_types')}
          </label>
          <div className="flex flex-wrap gap-1.5">
            {['RELATES_TO', 'MENTIONS', 'PART_OF', 'CONTAINS', 'BELONGS_TO'].map((rel) => (
              <button
                key={rel}
                type="button"
                onClick={() => {
                  onToggleRelationshipType(rel);
                }}
                className={`rounded px-2 py-1 text-2xs font-medium transition-colors ${
                  relationshipTypes.includes(rel)
                    ? 'bg-slate-950 text-white dark:bg-slate-50 dark:text-slate-950'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800'
                }`}
              >
                {rel}
              </button>
            ))}
          </div>
        </div>
      </>
    );
  }
);
GraphTraversalParams.displayName = 'GraphTraversalParams';

interface TemporalFiltersProps {
  timeRange: string;
  customTimeRange: { since?: string | undefined; until?: string | undefined };
  onTimeRangeChange: (range: string) => void;
  onCustomTimeRangeChange: (range: {
    since?: string | undefined;
    until?: string | undefined;
  }) => void;
}

const TemporalFilters = memo<TemporalFiltersProps>(
  ({ timeRange, customTimeRange, onTimeRangeChange, onCustomTimeRangeChange }) => {
    const { t } = useTranslation();

    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            {t('project.search.filters.time_range')}
          </h3>
          <button
            type="button"
            onClick={() => {
              onTimeRangeChange('all');
              onCustomTimeRangeChange({});
            }}
            className="text-xs text-blue-600 hover:underline font-medium"
          >
            {t('project.search.filters.reset')}
          </button>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer group transition-colors">
            <input
              className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
              name="time"
              type="radio"
              checked={timeRange === 'all'}
              onChange={() => {
                onTimeRangeChange('all');
              }}
            />
            <span className="text-xs text-slate-700 dark:text-slate-300">
              {t('project.search.filters.all_time')}
            </span>
          </label>
          <label
            className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer group ${timeRange === 'last30' ? 'bg-blue-600/5 border border-blue-600/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}
          >
            <input
              className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
              name="time"
              type="radio"
              checked={timeRange === 'last30'}
              onChange={() => {
                onTimeRangeChange('last30');
              }}
            />
            <span
              className={`text-xs font-medium ${timeRange === 'last30' ? 'text-blue-600 dark:text-blue-400' : 'text-slate-700 dark:text-slate-300'}`}
            >
              {t('project.search.filters.last_30')}
            </span>
          </label>
          <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer group transition-colors">
            <input
              className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
              name="time"
              type="radio"
              checked={timeRange === 'custom'}
              onChange={() => {
                onTimeRangeChange('custom');
              }}
            />
            <span className="text-xs text-slate-700 dark:text-slate-300">
              {t('project.search.filters.custom')}
            </span>
          </label>
        </div>

        {timeRange === 'custom' && (
          <div className="flex flex-col gap-3">
            <div>
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 block">
                {t('project.search.filters.from')}
              </label>
              <input
                type="datetime-local"
                value={customTimeRange.since || ''}
                onChange={(e) => {
                  onCustomTimeRangeChange({
                    ...customTimeRange,
                    since: e.target.value ? new Date(e.target.value).toISOString() : undefined,
                  });
                }}
                className="w-full text-xs py-2.5 px-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 text-slate-700 dark:text-slate-200"
              />
            </div>
            <div>
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 block">
                {t('project.search.filters.to')}
              </label>
              <input
                type="datetime-local"
                value={customTimeRange.until || ''}
                onChange={(e) => {
                  onCustomTimeRangeChange({
                    ...customTimeRange,
                    until: e.target.value ? new Date(e.target.value).toISOString() : undefined,
                  });
                }}
                className="w-full text-xs py-2.5 px-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 text-slate-700 dark:text-slate-200"
              />
            </div>
          </div>
        )}
      </div>
    );
  }
);
TemporalFilters.displayName = 'TemporalFilters';

interface FacetedFiltersProps {
  selectedEntityTypes: string[];
  selectedTags: string[];
  availableTags: string[];
  onToggleEntityType: (type: string) => void;
  onToggleTag: (tag: string) => void;
}

const FacetedFilters = memo<FacetedFiltersProps>(
  ({ selectedEntityTypes, selectedTags, availableTags, onToggleEntityType, onToggleTag }) => {
    const { t } = useTranslation();
    const [isAddingTag, setIsAddingTag] = useState(false);
    const [newTag, setNewTag] = useState('');
    const displayTags = Array.from(new Set([...availableTags, ...selectedTags]));

    const submitNewTag = () => {
      const tag = newTag.trim().replace(/^#+/, '');
      if (!tag) return;
      if (!selectedTags.includes(tag)) {
        onToggleTag(tag);
      }
      setNewTag('');
      setIsAddingTag(false);
    };

    return (
      <>
        <div className="flex flex-col gap-3">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            {t('project.search.filters.entity_types')}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {['Person', 'Organization', 'Location', 'Event', 'Concept', 'Product'].map((type) => (
              <button
                type="button"
                key={type}
                onClick={() => {
                  onToggleEntityType(type);
                }}
                className={`px-2 py-1 rounded-md text-2xs font-medium transition-colors ${
                  selectedEntityTypes.includes(type)
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        </div>

        <div className="h-px bg-slate-100 dark:bg-slate-700 my-1"></div>

        <div className="flex flex-col gap-3">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            {t('project.search.filters.tags')}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {displayTags.map((tag) => (
              <button
                type="button"
                key={tag}
                onClick={() => {
                  onToggleTag(tag);
                }}
                className={`px-2 py-1 rounded-md text-2xs font-medium transition-colors ${
                  selectedTags.includes(tag)
                    ? 'bg-blue-600/10 text-blue-600 border border-blue-600/10'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 border border-transparent'
                }`}
              >
                #{tag}
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                setIsAddingTag(true);
              }}
              className="px-2 py-1 rounded-md bg-white dark:bg-slate-800 text-slate-400 dark:text-slate-500 border border-dashed border-slate-300 dark:border-slate-600 hover:border-blue-600/50 hover:text-blue-600 text-2xs font-medium transition-colors flex items-center gap-1"
            >
              <Plus className="w-3 h-3" /> {t('project.search.filters.add_tag')}
            </button>
            {isAddingTag && (
              <span className="inline-flex items-center gap-1">
                <input
                  aria-label={t('project.search.filters.new_tag_label', {
                    defaultValue: 'New tag',
                  })}
                  value={newTag}
                  onChange={(event) => {
                    setNewTag(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      submitNewTag();
                    }
                    if (event.key === 'Escape') {
                      setNewTag('');
                      setIsAddingTag(false);
                    }
                  }}
                  className="w-24 rounded-md border border-slate-300 bg-white px-2 py-1 text-2xs text-slate-700 outline-none focus:border-blue-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
                  placeholder={t('project.search.filters.new_tag_placeholder', {
                    defaultValue: 'Tag',
                  })}
                />
                <button
                  type="button"
                  aria-label={t('project.search.filters.confirm_add_tag', {
                    defaultValue: 'Add tag',
                  })}
                  onClick={submitNewTag}
                  className="rounded-md bg-blue-600 px-2 py-1 text-2xs font-medium text-white hover:bg-blue-700"
                >
                  {t('common.add')}
                </button>
                <button
                  type="button"
                  aria-label={t('project.search.filters.cancel_add_tag', {
                    defaultValue: 'Cancel tag entry',
                  })}
                  onClick={() => {
                    setNewTag('');
                    setIsAddingTag(false);
                  }}
                  className="rounded-md px-2 py-1 text-2xs font-medium text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                >
                  {t('common.cancel')}
                </button>
              </span>
            )}
          </div>
        </div>
      </>
    );
  }
);
FacetedFilters.displayName = 'FacetedFilters';

interface CommunityFiltersProps {
  includeEpisodes: boolean;
  onIncludeEpisodesChange: (include: boolean) => void;
}

const CommunityFilters = memo<CommunityFiltersProps>(
  ({ includeEpisodes, onIncludeEpisodesChange }) => {
    const { t } = useTranslation();

    return (
      <>
        <div className="flex flex-col gap-2">
          <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            {t('project.search.filters.results')}
          </label>
          <label className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer transition-colors">
            <input
              type="checkbox"
              checked={includeEpisodes}
              onChange={(e) => {
                onIncludeEpisodesChange(e.target.checked);
              }}
              className="w-4 h-4 text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 rounded"
            />
            <span className="text-xs text-slate-700 dark:text-slate-300">
              {t('project.search.filters.include_episodes')}
            </span>
          </label>
        </div>

        <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
          <p className="text-xs text-blue-800 dark:text-blue-300">
            {t('project.search.filters.community_info')}
          </p>
        </div>
      </>
    );
  }
);
CommunityFilters.displayName = 'CommunityFilters';
