/**
 * SearchConfig - Extracted from EnhancedSearch
 *
 * Displays the configuration sidebar for search parameters and filters.
 */

import { memo, useCallback } from 'react';

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
  customTimeRange: { since?: string; until?: string };

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
  onCustomTimeRangeChange: (range: { since?: string; until?: string }) => void;
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
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 lg:hidden"
            onClick={onMobileConfigClose}
          />
        )}

        <aside
          className={`
                fixed inset-y-0 right-0 z-50 w-80 bg-slate-50 dark:bg-[#121520] lg:bg-transparent transition-all duration-300 ease-in-out lg:relative lg:transform-none lg:z-0 flex flex-col gap-6 shrink-0 h-full
                ${showMobileConfig ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'}
                ${!isConfigOpen && 'lg:w-0 lg:overflow-hidden lg:opacity-0 lg:p-0'}
            `}
        >
          <div className="flex-1 flex flex-col gap-5 p-5 bg-white dark:bg-[#1e212b] rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-y-auto custom-scrollbar h-full">
            <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-slate-800 shrink-0">
              <h2 className="text-sm font-bold text-slate-800 dark:text-white flex items-center gap-2">
                <Sliders className="w-5 h-5 text-blue-600" />
                {t('project.search.config.title')}
              </h2>
              <div className="flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 bg-blue-600/10 text-blue-600 rounded font-medium">
                  Advanced
                </span>
                <button
                  onClick={onMobileConfigClose}
                  className="lg:hidden p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg text-slate-500 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Internal Tabs */}
            <ConfigTabSelector currentTab={configTab} onTabChange={onConfigTabChange} />

            {/* Tab Content */}
            <div className="flex-1 flex flex-col gap-6 overflow-y-auto custom-scrollbar pr-1">
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

const ConfigTabSelector = memo<ConfigTabSelectorProps>(({ currentTab, onTabChange }) => (
  <div className="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-lg shrink-0">
    <button
      onClick={() => onTabChange('params')}
      className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center justify-center gap-1.5 ${currentTab === 'params' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
    >
      <Sliders className="w-3.5 h-3.5" />
      Parameters
    </button>
    <button
      onClick={() => onTabChange('filters')}
      className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center justify-center gap-1.5 ${currentTab === 'filters' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
    >
      <Filter className="w-3.5 h-3.5" />
      Filters
    </button>
  </div>
));
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
        onShowTooltip={() => onShowTooltip('focal')}
        onHideTooltip={() => onShowTooltip(null)}
      />
      <CrossEncoderSelector value={crossEncoder} onChange={onCrossEncoderChange} />
    </>
  )
);
SemanticSearchParams.displayName = 'SemanticSearchParams';

const RetrievalModeSelector = memo<{
  value: RetrievalMode;
  onChange: (mode: RetrievalMode) => void;
}>(({ value, onChange }) => (
  <div className="flex flex-col gap-2">
    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
      Retrieval Mode
    </label>
    <div className="bg-slate-100 dark:bg-slate-800 p-1 rounded-lg flex">
      <button
        onClick={() => onChange('hybrid')}
        className={`flex-1 py-2 px-2 rounded-md shadow-sm text-xs font-semibold transition-all ${value === 'hybrid' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white ring-1 ring-black/5 dark:ring-white/10' : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'}`}
      >
        Hybrid
      </button>
      <button
        onClick={() => onChange('nodeDistance')}
        className={`flex-1 py-2 px-2 rounded-md text-xs font-medium transition-all ${value === 'nodeDistance' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white ring-1 ring-black/5 dark:ring-white/10' : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'}`}
      >
        Node Distance
      </button>
    </div>
  </div>
));
RetrievalModeSelector.displayName = 'RetrievalModeSelector';

const StrategySelector = memo<{ value: string; onChange: (value: string) => void }>(
  ({ value, onChange }) => (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
        Strategy Recipe
      </label>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full text-xs py-2.5 pl-3 pr-8 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 focus:border-blue-600 text-slate-700 dark:text-slate-200 appearance-none shadow-sm cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
        >
          <option value="COMBINED_HYBRID_SEARCH_RRF">Combined Hybrid (RRF)</option>
          <option value="EDGE_HYBRID_SEARCH_CROSS_ENCODER">Edge Hybrid (Cross-Encoder)</option>
          <option value="HYBRID_MMR">Hybrid Search (MMR)</option>
          <option value="STANDARD_DENSE">Standard Dense Only</option>
        </select>
        <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
          <ChevronDown className="w-4 h-4" />
        </div>
      </div>
    </div>
  )
);
StrategySelector.displayName = 'StrategySelector';

const FocalNodeInput = memo<{
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  showTooltip: boolean;
  onShowTooltip: () => void;
  onHideTooltip: () => void;
}>(({ value, onChange, disabled, showTooltip, onShowTooltip, onHideTooltip }) => (
  <div className="flex flex-col gap-2">
    <div className="flex items-center justify-between">
      <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
        Focal Node UUID
      </label>
      <div className="relative">
        <HelpCircle
          className="w-4 h-4 text-slate-400 cursor-help hover:text-blue-600"
          onMouseEnter={onShowTooltip}
          onMouseLeave={onHideTooltip}
        />
        {showTooltip && (
          <div className="absolute right-0 top-6 w-64 p-2 bg-slate-900 dark:bg-slate-700 text-white text-xs rounded-lg shadow-lg z-50">
            <p className="font-semibold mb-1">Focal Node</p>
            <p>Use a specific node as the focal point for proximity-based retrieval.</p>
          </div>
        )}
      </div>
    </div>
    <div className="relative group">
      <input
        className="w-full text-xs py-2.5 pl-9 pr-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 focus:border-blue-600 text-slate-700 dark:text-slate-200 placeholder-slate-400 transition-shadow disabled:opacity-50"
        placeholder="e.g. node-1234-uuid..."
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      />
      <Network className="absolute left-2.5 top-2.5 w-4 h-4 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
    </div>
  </div>
));
FocalNodeInput.displayName = 'FocalNodeInput';

const CrossEncoderSelector = memo<{ value: string; onChange: (value: string) => void }>(
  ({ value, onChange }) => (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
        Cross-Encoder Client
      </label>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full text-xs py-2.5 pl-3 pr-8 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 focus:border-blue-600 text-slate-700 dark:text-slate-200 appearance-none shadow-sm cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
        >
          <option value="openai">OpenAI</option>
          <option value="gemini">Gemini</option>
          <option value="bge">BGE</option>
        </select>
        <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
          <ChevronDown className="w-4 h-4" />
        </div>
      </div>
    </div>
  )
);
CrossEncoderSelector.displayName = 'CrossEncoderSelector';

interface GraphTraversalParamsProps {
  maxDepth: number;
  relationshipTypes: string[];
  onMaxDepthChange: (depth: number) => void;
  onToggleRelationshipType: (type: string) => void;
}

const GraphTraversalParams = memo<GraphTraversalParamsProps>(
  ({ maxDepth, relationshipTypes, onMaxDepthChange, onToggleRelationshipType }) => (
    <>
      <div className="flex flex-col gap-2">
        <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Max Depth
        </label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onMaxDepthChange(Math.max(1, maxDepth - 1))}
            className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            <Minus className="w-4 h-4" />
          </button>
          <span className="flex-1 text-center font-bold text-slate-900 dark:text-white">
            {maxDepth}
          </span>
          <button
            onClick={() => onMaxDepthChange(Math.min(5, maxDepth + 1))}
            className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Relationship Types
        </label>
        <div className="flex flex-wrap gap-1.5">
          {['RELATES_TO', 'MENTIONS', 'PART_OF', 'CONTAINS', 'BELONGS_TO'].map((rel) => (
            <button
              key={rel}
              onClick={() => onToggleRelationshipType(rel)}
              className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
                relationshipTypes.includes(rel)
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {rel}
            </button>
          ))}
        </div>
      </div>
    </>
  )
);
GraphTraversalParams.displayName = 'GraphTraversalParams';

interface TemporalFiltersProps {
  timeRange: string;
  customTimeRange: { since?: string; until?: string };
  onTimeRangeChange: (range: string) => void;
  onCustomTimeRangeChange: (range: { since?: string; until?: string }) => void;
}

const TemporalFilters = memo<TemporalFiltersProps>(
  ({ timeRange, customTimeRange, onTimeRangeChange, onCustomTimeRangeChange }) => (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Time Range</h3>
        <button
          onClick={() => {
            onTimeRangeChange('all');
            onCustomTimeRangeChange({});
          }}
          className="text-xs text-blue-600 hover:underline font-medium"
        >
          Reset
        </button>
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer group transition-colors">
          <input
            className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
            name="time"
            type="radio"
            checked={timeRange === 'all'}
            onChange={() => onTimeRangeChange('all')}
          />
          <span className="text-xs text-slate-700 dark:text-slate-300">All Time</span>
        </label>
        <label
          className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer group ${timeRange === 'last30' ? 'bg-blue-600/5 border border-blue-600/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}
        >
          <input
            className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
            name="time"
            type="radio"
            checked={timeRange === 'last30'}
            onChange={() => onTimeRangeChange('last30')}
          />
          <span
            className={`text-xs font-medium ${timeRange === 'last30' ? 'text-blue-600 dark:text-blue-400' : 'text-slate-700 dark:text-slate-300'}`}
          >
            Last 30 Days
          </span>
        </label>
        <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer group transition-colors">
          <input
            className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
            name="time"
            type="radio"
            checked={timeRange === 'custom'}
            onChange={() => onTimeRangeChange('custom')}
          />
          <span className="text-xs text-slate-700 dark:text-slate-300">Custom Range</span>
        </label>
      </div>

      {timeRange === 'custom' && (
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 block">
              From
            </label>
            <input
              type="datetime-local"
              value={customTimeRange.since || ''}
              onChange={(e) =>
                onCustomTimeRangeChange({
                  ...customTimeRange,
                  since: e.target.value ? new Date(e.target.value).toISOString() : undefined,
                })
              }
              className="w-full text-xs py-2.5 px-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 text-slate-700 dark:text-slate-200"
            />
          </div>
          <div>
            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 block">
              To
            </label>
            <input
              type="datetime-local"
              value={customTimeRange.until || ''}
              onChange={(e) =>
                onCustomTimeRangeChange({
                  ...customTimeRange,
                  until: e.target.value ? new Date(e.target.value).toISOString() : undefined,
                })
              }
              className="w-full text-xs py-2.5 px-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 text-slate-700 dark:text-slate-200"
            />
          </div>
        </div>
      )}
    </div>
  )
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
  ({ selectedEntityTypes, selectedTags, availableTags, onToggleEntityType, onToggleTag }) => (
    <>
      <div className="flex flex-col gap-3">
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Entity Types</h3>
        <div className="flex flex-wrap gap-1.5">
          {['Person', 'Organization', 'Location', 'Event', 'Concept', 'Product'].map((type) => (
            <button
              key={type}
              onClick={() => onToggleEntityType(type)}
              className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
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
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Tags</h3>
        <div className="flex flex-wrap gap-1.5">
          {availableTags.map((tag) => (
            <button
              key={tag}
              onClick={() => onToggleTag(tag)}
              className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
                selectedTags.includes(tag)
                  ? 'bg-blue-600/10 text-blue-600 border border-blue-600/10'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 border border-transparent'
              }`}
            >
              #{tag}
            </button>
          ))}
          <button className="px-2 py-1 rounded-md bg-white dark:bg-slate-800 text-slate-400 dark:text-slate-500 border border-dashed border-slate-300 dark:border-slate-600 hover:border-blue-600/50 hover:text-blue-600 text-[10px] font-medium transition-colors flex items-center gap-1">
            <Plus className="w-3 h-3" /> Add
          </button>
        </div>
      </div>
    </>
  )
);
FacetedFilters.displayName = 'FacetedFilters';

interface CommunityFiltersProps {
  includeEpisodes: boolean;
  onIncludeEpisodesChange: (include: boolean) => void;
}

const CommunityFilters = memo<CommunityFiltersProps>(
  ({ includeEpisodes, onIncludeEpisodesChange }) => (
    <>
      <div className="flex flex-col gap-2">
        <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Results</label>
        <label className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer transition-colors">
          <input
            type="checkbox"
            checked={includeEpisodes}
            onChange={(e) => onIncludeEpisodesChange(e.target.checked)}
            className="w-4 h-4 text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 rounded"
          />
          <span className="text-xs text-slate-700 dark:text-slate-300">Include Episodes</span>
        </label>
      </div>

      <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
        <p className="text-xs text-blue-800 dark:text-blue-300">
          Community search finds all entities and episodes within a specific community.
        </p>
      </div>
    </>
  )
);
CommunityFilters.displayName = 'CommunityFilters';
