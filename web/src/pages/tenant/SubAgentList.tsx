/**
 * SubAgentList Compound Component
 *
 * A compound component pattern for managing SubAgents with modular sub-components.
 *
 * @example
 * ```tsx
 * import { SubAgentList } from './SubAgentList';
 *
 * <SubAgentList />
 * // Or with sub-components for custom layout:
 * <SubAgentList>
 *   <SubAgentList.Header />
 *   <SubAgentList.Stats />
 *   <SubAgentList.FilterBar />
 *   <SubAgentList.Grid />
 * </SubAgentList>
 * ```
 */

import React, { useCallback, useEffect, useState, useMemo, useContext } from 'react';

import { message, Popconfirm, Dropdown, Switch, Empty, Spin, Tooltip } from 'antd';

import { SubAgentModal } from '../../components/subagent/SubAgentModal';
import {
  useSubAgentData,
  useSubAgentFiltersData,
  filterSubAgents,
  useSubAgentLoading,
  useSubAgentTemplates,
  useSubAgentTemplatesLoading,
  useSubAgentError,
  useEnabledSubAgentsCount,
  useAverageSuccessRate,
  useTotalInvocations,
  useListSubAgents,
  useListTemplates,
  useToggleSubAgent,
  useDeleteSubAgent,
  useCreateFromTemplate,
  useSetSubAgentFilters,
  useClearSubAgentError,
} from '../../stores/subagent';

import type { SubAgentResponse, SubAgentTemplate } from '../../types/agent';
import type { MenuProps } from 'antd';

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'SubAgents',
  subtitle: 'Manage your specialized AI agents for different tasks',
  createNew: 'Create SubAgent',
  fromTemplate: 'From Template',
  noTemplates: 'No templates available',

  // Stats
  stats: {
    total: 'Total SubAgents',
    enabled: 'Enabled',
    successRate: 'Success Rate',
    invocations: 'Total Invocations',
  },

  // Filters
  searchPlaceholder: 'Search subagents...',
  allStatus: 'All Status',
  enabledOnly: 'Enabled Only',
  disabledOnly: 'Disabled Only',
  refresh: 'Refresh',

  // Card
  inheritModel: 'Inherit',
  triggerKeywords: 'Trigger Keywords',
  allTools: 'All Tools',
  tools: 'Tools',
  skills: 'Skills',
  invocations: 'Invocations',
  successRate: 'Success Rate',
  avgTime: 'Avg Time',
  enabled: 'Enabled',
  disabled: 'Disabled',
  edit: 'Edit',
  delete: 'Delete',
  deleteConfirm: 'Are you sure you want to delete this SubAgent?',

  // Messages
  empty: 'No subagents yet. Create your first one to get started.',
  noResults: 'No subagents match your search criteria.',
  createFirst: 'Create SubAgent',
  enableSuccess: 'SubAgent enabled successfully',
  disableSuccess: 'SubAgent disabled successfully',
  deleteSuccess: 'SubAgent deleted successfully',
  createFromTemplateSuccess: 'SubAgent created from template successfully',
  cancel: 'Cancel',
} as const;

// ============================================================================
// Marker Symbols
// ============================================================================

const HeaderMarker = Symbol('SubAgentList.Header');
const StatsMarker = Symbol('SubAgentList.Stats');
const FilterBarMarker = Symbol('SubAgentList.FilterBar');
const StatusBadgeMarker = Symbol('SubAgentList.StatusBadge');
const CardMarker = Symbol('SubAgentList.Card');
const LoadingMarker = Symbol('SubAgentList.Loading');
const EmptyMarker = Symbol('SubAgentList.Empty');
const GridMarker = Symbol('SubAgentList.Grid');

// ============================================================================
// Context
// ============================================================================

interface SubAgentListState {
  search: string;
  statusFilter: 'all' | 'enabled' | 'disabled';
  modelFilter: string;
  total: number;
  enabledCount: number;
  avgSuccessRate: number;
  totalInvocations: number;
  subagents: SubAgentResponse[];
  templates: SubAgentTemplate[];
  filteredSubagents: SubAgentResponse[];
  isLoadingSubAgents: boolean;
  isLoadingTemplates: boolean;
  isToggling: Set<string>;
  isDeleting: Set<string>;
  error: string | null;
}

interface SubAgentListActions {
  setSearch: (search: string) => void;
  setStatusFilter: (filter: 'all' | 'enabled' | 'disabled') => void;
  setModelFilter: (filter: string) => void;
  handleCreate: () => void;
  handleCreateFromTemplate: (templateId: string) => void;
  handleEdit: (subagent: SubAgentResponse) => void;
  handleToggle: (id: string, enabled: boolean) => void;
  handleDelete: (id: string) => void;
  handleRefresh: () => void;
  clearError: () => void;
}

interface SubAgentListContextType {
  state: SubAgentListState;
  actions: SubAgentListActions;
}

const SubAgentListContext = React.createContext<SubAgentListContextType | null>(null);

const useSubAgentListContext = (): SubAgentListContextType => {
  const context = useContext(SubAgentListContext);
  if (!context) {
    throw new Error('SubAgentList sub-components must be used within SubAgentList');
  }
  return context;
};

// Optional hook for testing - returns null if not in context
const useSubAgentListContextOptional = (): SubAgentListContextType | null => {
  return useContext(SubAgentListContext);
};

// ============================================================================
// Main Component
// ============================================================================

interface SubAgentListProps {
  className?: string;
}

const SubAgentListInternal: React.FC<SubAgentListProps> = ({ className = '' }) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [modelFilter, setModelFilter] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSubAgent, setEditingSubAgent] = useState<SubAgentResponse | null>(null);

  // Store hooks
  const subagentsData = useSubAgentData();
  const filtersData = useSubAgentFiltersData();
  const templates = useSubAgentTemplates();
  const isLoadingSubAgents = useSubAgentLoading();
  const isLoadingTemplates = useSubAgentTemplatesLoading();
  const error = useSubAgentError();
  const enabledCount = useEnabledSubAgentsCount();
  const avgSuccessRate = useAverageSuccessRate();
  const totalInvocations = useTotalInvocations();

  // Action hooks
  const listSubAgents = useListSubAgents();
  const listTemplates = useListTemplates();
  const toggleSubAgent = useToggleSubAgent();
  const deleteSubAgent = useDeleteSubAgent();
  const createFromTemplate = useCreateFromTemplate();
  const setFilters = useSetSubAgentFilters();
  const clearError = useClearSubAgentError();

  // Compute filtered subagents
  const filteredSubagents = useMemo(
    () =>
      filterSubAgents(subagentsData, {
        ...filtersData,
        search,
        enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
      }),
    [subagentsData, filtersData, search, statusFilter]
  );

  // Context state
  const state: SubAgentListState = {
    search,
    statusFilter,
    modelFilter,
    total: filteredSubagents.length,
    enabledCount,
    avgSuccessRate: Math.round(avgSuccessRate * 100),
    totalInvocations,
    subagents: subagentsData,
    templates,
    filteredSubagents,
    isLoadingSubAgents,
    isLoadingTemplates,
    isToggling: new Set<string>(),
    isDeleting: new Set<string>(),
    error,
  };

  // Context actions
  const actions: SubAgentListActions = {
    setSearch,
    setStatusFilter,
    setModelFilter,
    handleCreate: useCallback(() => {
      setEditingSubAgent(null);
      setIsModalOpen(true);
    }, []),
    handleCreateFromTemplate: useCallback(
      async (templateId: string) => {
        try {
          const created = await createFromTemplate(templateId);
          message.success(TEXTS.createFromTemplateSuccess);
          setEditingSubAgent(created);
          setIsModalOpen(true);
        } catch {
          // Error handled by store
        }
      },
      [createFromTemplate]
    ),
    handleEdit: useCallback((subagent: SubAgentResponse) => {
      setEditingSubAgent(subagent);
      setIsModalOpen(true);
    }, []),
    handleToggle: useCallback(
      async (id: string, enabled: boolean) => {
        try {
          await toggleSubAgent(id, enabled);
          message.success(enabled ? TEXTS.enableSuccess : TEXTS.disableSuccess);
        } catch {
          // Error handled by store
        }
      },
      [toggleSubAgent]
    ),
    handleDelete: useCallback(
      async (id: string) => {
        try {
          await deleteSubAgent(id);
          message.success(TEXTS.deleteSuccess);
        } catch {
          // Error handled by store
        }
      },
      [deleteSubAgent]
    ),
    handleRefresh: useCallback(() => {
      listSubAgents();
    }, [listSubAgents]),
    clearError,
  };

  // Load data on mount
  useEffect(() => {
    listSubAgents();
    listTemplates();
  }, [listSubAgents, listTemplates]);

  // Update filters when search or status changes
  useEffect(() => {
    setFilters({
      search,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
    });
  }, [search, statusFilter, setFilters]);

  // Clear error on unmount
  useEffect(() => {
    return () => clearError();
  }, [clearError]);

  // Show error message
  useEffect(() => {
    if (error) {
      message.error(error);
    }
  }, [error]);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
    listSubAgents();
  }, [listSubAgents]);

  return (
    <SubAgentListContext.Provider value={{ state, actions }}>
      <div className={className || 'max-w-full mx-auto w-full flex flex-col gap-8'}>
        <SubAgentList.Header />
        <SubAgentList.Stats />
        <SubAgentList.FilterBar />
        <div className="p-4 border-t border-slate-200 dark:border-slate-700">
          {state.isLoadingSubAgents ? (
            <SubAgentList.Loading />
          ) : state.filteredSubagents.length === 0 ? (
            <SubAgentList.Empty />
          ) : (
            <SubAgentList.Grid
              subagents={state.filteredSubagents}
              onToggle={actions.handleToggle}
              onEdit={actions.handleEdit}
              onDelete={actions.handleDelete}
            />
          )}
        </div>
        <SubAgentModal
          isOpen={isModalOpen}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
          subagent={editingSubAgent}
        />
      </div>
    </SubAgentListContext.Provider>
  );
};

SubAgentListInternal.displayName = 'SubAgentList';

// ============================================================================
// Header Sub-Component
// ============================================================================

interface HeaderProps {
  onCreate?: () => void;
  onCreateFromTemplate?: (templateId: string) => void;
  templates?: SubAgentTemplate[];
}

const HeaderInternal: React.FC<HeaderProps> = (props) => {
  // Only use context if props are not provided (for testing)
  const hasProps =
    props.onCreate !== undefined ||
    props.onCreateFromTemplate !== undefined ||
    props.templates !== undefined;
  const context = hasProps ? null : useSubAgentListContextOptional();
  const state = context?.state;
  const actions = context?.actions;

  // Use props if provided, otherwise use context
  const templates = props.templates ?? state?.templates ?? [];
  const handleCreate = props.onCreate ?? actions?.handleCreate;
  const handleCreateFromTemplate = props.onCreateFromTemplate ?? actions?.handleCreateFromTemplate;

  if (!handleCreate) return null;

  // Template dropdown menu
  const templateMenuItems: MenuProps['items'] = useMemo(() => {
    if (templates.length === 0) {
      return [
        {
          key: 'empty',
          label: TEXTS.noTemplates,
          disabled: true,
        },
      ];
    }
    return templates.map((template: SubAgentTemplate) => ({
      key: template.name,
      label: (
        <div className="py-1">
          <div className="font-medium">{template.display_name}</div>
          <div className="text-xs text-slate-500">{template.description}</div>
        </div>
      ),
      onClick: () => handleCreateFromTemplate?.(template.name),
    }));
  }, [templates, handleCreateFromTemplate]);

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{TEXTS.title}</h1>
        <p className="text-sm text-slate-500 mt-1">{TEXTS.subtitle}</p>
      </div>
      <div className="flex items-center gap-3">
        <Dropdown menu={{ items: templateMenuItems }} trigger={['click']}>
          <button className="inline-flex items-center justify-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
            <span className="material-symbols-outlined text-lg">content_copy</span>
            {TEXTS.fromTemplate}
            <span className="material-symbols-outlined text-lg">expand_more</span>
          </button>
        </Dropdown>
        <button
          onClick={handleCreate}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          {TEXTS.createNew}
        </button>
      </div>
    </div>
  );
};

HeaderInternal.displayName = 'SubAgentList.Header';

// ============================================================================
// Stats Sub-Component
// ============================================================================

interface StatsProps {
  total?: number;
  enabledCount?: number;
  avgSuccessRate?: number;
  totalInvocations?: number;
}

const StatsInternal: React.FC<StatsProps> = (props) => {
  // Only use context if props are not provided (for testing)
  const hasProps =
    props.total !== undefined ||
    props.enabledCount !== undefined ||
    props.avgSuccessRate !== undefined ||
    props.totalInvocations !== undefined;
  const context = hasProps ? null : useSubAgentListContextOptional();
  const state = context?.state;

  // Use props if provided, otherwise use context
  const total = props.total ?? state?.total ?? 0;
  const enabledCount = props.enabledCount ?? state?.enabledCount ?? 0;
  const avgSuccessRate = props.avgSuccessRate ?? state?.avgSuccessRate ?? 0;
  const totalInvocations = props.totalInvocations ?? state?.totalInvocations ?? 0;

  const StatsCard: React.FC<{
    title: string;
    value: string | number;
    icon: string;
    iconColor: string;
  }> = ({ title, value, icon, iconColor }) => (
    <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-700">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{title}</p>
        <span className={`material-symbols-outlined ${iconColor}`}>{icon}</span>
      </div>
      <p className="text-2xl font-bold text-slate-900 dark:text-white mt-2">{value}</p>
    </div>
  );

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      <StatsCard
        title={TEXTS.stats.total}
        value={total}
        icon="smart_toy"
        iconColor="text-slate-400"
      />
      <StatsCard
        title={TEXTS.stats.enabled}
        value={enabledCount}
        icon="check_circle"
        iconColor="text-green-500"
      />
      <StatsCard
        title={TEXTS.stats.successRate}
        value={`${avgSuccessRate}%`}
        icon="trending_up"
        iconColor="text-blue-500"
      />
      <StatsCard
        title={TEXTS.stats.invocations}
        value={totalInvocations.toLocaleString()}
        icon="bolt"
        iconColor="text-purple-500"
      />
    </div>
  );
};

StatsInternal.displayName = 'SubAgentList.Stats';

// ============================================================================
// FilterBar Sub-Component
// ============================================================================

interface FilterBarProps {
  search?: string;
  onSearchChange?: (value: string) => void;
  statusFilter?: 'all' | 'enabled' | 'disabled';
  onStatusFilterChange?: (filter: 'all' | 'enabled' | 'disabled') => void;
  modelFilter?: string;
  onModelFilterChange?: (filter: string) => void;
  onRefresh?: () => void;
}

const FilterBarInternal: React.FC<FilterBarProps> = (props) => {
  // Only use context if props are not provided (for testing)
  const hasProps =
    props.onSearchChange !== undefined ||
    props.onStatusFilterChange !== undefined ||
    props.onRefresh !== undefined;
  const context = hasProps ? null : useSubAgentListContextOptional();
  const state = context?.state;
  const actions = context?.actions;

  // Use props if provided, otherwise use context
  const search = props.search ?? state?.search ?? '';
  const setSearch = props.onSearchChange ?? actions?.setSearch;
  const statusFilter = props.statusFilter ?? state?.statusFilter ?? 'all';
  const setStatusFilter = props.onStatusFilterChange ?? actions?.setStatusFilter;
  const handleRefresh = props.onRefresh ?? actions?.handleRefresh;

  if (!setSearch || !setStatusFilter || !handleRefresh) return null;

  return (
    <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-700">
      <div className="p-4 flex flex-col sm:flex-row gap-4 justify-between items-center">
        {/* Search */}
        <div className="relative w-full sm:w-96">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <span className="material-symbols-outlined text-slate-400">search</span>
          </div>
          <input
            type="text"
            className="block w-full pl-10 pr-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            placeholder={TEXTS.searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3">
          <select
            className="appearance-none bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 pr-8 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary-500"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'enabled' | 'disabled')}
          >
            <option value="all">{TEXTS.allStatus}</option>
            <option value="enabled">{TEXTS.enabledOnly}</option>
            <option value="disabled">{TEXTS.disabledOnly}</option>
          </select>
          <button
            onClick={handleRefresh}
            className="p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
            title={TEXTS.refresh}
          >
            <span className="material-symbols-outlined">refresh</span>
          </button>
        </div>
      </div>
    </div>
  );
};

FilterBarInternal.displayName = 'SubAgentList.FilterBar';

// ============================================================================
// StatusBadge Sub-Component
// ============================================================================

interface StatusBadgeProps {
  enabled: boolean;
}

const StatusBadgeInternal: React.FC<StatusBadgeProps> = React.memo(({ enabled }) => (
  <span
    className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
      enabled
        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
        : 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300'
    }`}
  >
    <span
      className={`h-1.5 w-1.5 rounded-full ${enabled ? 'bg-green-500' : 'bg-slate-400'}`}
    ></span>
    {enabled ? TEXTS.enabled : TEXTS.disabled}
  </span>
));

StatusBadgeInternal.displayName = 'SubAgentList.StatusBadge';

// ============================================================================
// Card Sub-Component
// ============================================================================

interface CardProps {
  subagent: SubAgentResponse;
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: (subagent: SubAgentResponse) => void;
  onDelete: (id: string) => void;
}

const CardInternal: React.FC<CardProps> = React.memo(({ subagent, onToggle, onEdit, onDelete }) => {
  const handleToggle = useCallback(
    (checked: boolean) => {
      onToggle(subagent.id, checked);
    },
    [subagent.id, onToggle]
  );

  const handleEdit = useCallback(() => {
    onEdit(subagent);
  }, [subagent, onEdit]);

  const handleDelete = useCallback(() => {
    onDelete(subagent.id);
  }, [subagent.id, onDelete]);

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-primary-300 dark:hover:border-primary-700 transition-colors overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: subagent.color + '20' }}
            >
              <span className="material-symbols-outlined" style={{ color: subagent.color }}>
                smart_toy
              </span>
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-white">
                {subagent.display_name}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">{subagent.name}</p>
            </div>
          </div>
          <Switch checked={subagent.enabled} onChange={handleToggle} size="small" />
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-4">
        {/* Model */}
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-sm text-slate-400">memory</span>
          <span className="text-sm text-slate-600 dark:text-slate-300">
            {subagent.model === 'inherit' ? TEXTS.inheritModel : subagent.model}
          </span>
        </div>

        {/* Trigger Keywords */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="material-symbols-outlined text-sm text-slate-400">label</span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {TEXTS.triggerKeywords}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {subagent.trigger.keywords.slice(0, 4).map((keyword, idx) => (
              <span
                key={idx}
                className="px-2 py-0.5 text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded"
              >
                {keyword}
              </span>
            ))}
            {subagent.trigger.keywords.length > 4 && (
              <Tooltip title={subagent.trigger.keywords.slice(4).join(', ')}>
                <span className="px-2 py-0.5 text-xs bg-slate-100 dark:bg-slate-700 text-slate-500 rounded cursor-help">
                  +{subagent.trigger.keywords.length - 4}
                </span>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Tools Count */}
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1 text-slate-500 dark:text-slate-400">
            <span className="material-symbols-outlined text-sm">build</span>
            <span>
              {subagent.allowed_tools.includes('*')
                ? TEXTS.allTools
                : `${subagent.allowed_tools.length} ${TEXTS.tools}`}
            </span>
          </div>
          {subagent.allowed_skills.length > 0 && (
            <div className="flex items-center gap-1 text-slate-500 dark:text-slate-400">
              <span className="material-symbols-outlined text-sm">auto_awesome</span>
              <span>
                {subagent.allowed_skills.length} {TEXTS.skills}
              </span>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="pt-3 border-t border-slate-100 dark:border-slate-700 grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-lg font-semibold text-slate-900 dark:text-white">
              {subagent.total_invocations}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">{TEXTS.invocations}</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-slate-900 dark:text-white">
              {Math.round(subagent.success_rate * 100)}%
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">{TEXTS.successRate}</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-slate-900 dark:text-white">
              {subagent.avg_execution_time_ms > 0
                ? `${Math.round(subagent.avg_execution_time_ms / 1000)}s`
                : '-'}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">{TEXTS.avgTime}</p>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-100 dark:border-slate-700 flex items-center justify-between">
        <StatusBadgeInternal enabled={subagent.enabled} />
        <div className="flex items-center gap-2">
          <button
            onClick={handleEdit}
            className="p-1.5 text-slate-500 hover:text-primary-600 dark:text-slate-400 dark:hover:text-primary-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
            title={TEXTS.edit}
          >
            <span className="material-symbols-outlined text-lg">edit</span>
          </button>
          <Popconfirm
            title={TEXTS.deleteConfirm}
            onConfirm={handleDelete}
            okText={TEXTS.delete}
            cancelText={TEXTS.cancel}
            okButtonProps={{ danger: true }}
          >
            <button
              className="p-1.5 text-slate-500 hover:text-red-600 dark:text-slate-400 dark:hover:text-red-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
              title={TEXTS.delete}
            >
              <span className="material-symbols-outlined text-lg">delete</span>
            </button>
          </Popconfirm>
        </div>
      </div>
    </div>
  );
});

CardInternal.displayName = 'SubAgentList.Card';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC = () => (
  <div className="flex items-center justify-center py-12">
    <Spin size="large" />
  </div>
);

LoadingInternal.displayName = 'SubAgentList.Loading';

// ============================================================================
// Empty Sub-Component
// ============================================================================

interface EmptyProps {
  search?: string;
  statusFilter?: 'all' | 'enabled' | 'disabled';
  onCreate?: () => void;
}

const EmptyInternal: React.FC<EmptyProps> = (props) => {
  // Only use context if props are not provided (for testing)
  const hasProps =
    props.search !== undefined || props.statusFilter !== undefined || props.onCreate !== undefined;
  const context = hasProps ? null : useSubAgentListContextOptional();
  const state = context?.state;
  const actions = context?.actions;

  // Use props if provided, otherwise use context
  const search = props.search ?? state?.search ?? '';
  const statusFilter = props.statusFilter ?? state?.statusFilter ?? 'all';
  const handleCreate = props.onCreate ?? actions?.handleCreate;

  return (
    <Empty
      description={
        <span className="text-slate-500 dark:text-slate-400">
          {search || statusFilter !== 'all' ? TEXTS.noResults : TEXTS.empty}
        </span>
      }
    >
      {!search && statusFilter === 'all' && handleCreate && (
        <button
          onClick={handleCreate}
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          {TEXTS.createFirst}
        </button>
      )}
    </Empty>
  );
};

EmptyInternal.displayName = 'SubAgentList.Empty';

// ============================================================================
// Grid Sub-Component
// ============================================================================

interface GridProps {
  subagents: SubAgentResponse[];
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: (subagent: SubAgentResponse) => void;
  onDelete: (id: string) => void;
}

const GridInternal: React.FC<GridProps> = React.memo(
  ({ subagents, onToggle, onEdit, onDelete }) => (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {subagents.map((subagent) => (
        <CardInternal
          key={subagent.id}
          subagent={subagent}
          onToggle={onToggle}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
);

GridInternal.displayName = 'SubAgentList.Grid';

// ============================================================================
// Attach Sub-Components to Main Component
// ============================================================================

const attachMarker = <P extends object>(component: React.FC<P>, marker: symbol) => {
  (component as any)[marker] = true;
  return component;
};

// Export the compound component
export const SubAgentList = Object.assign(SubAgentListInternal, {
  Header: attachMarker(HeaderInternal, HeaderMarker),
  Stats: attachMarker(StatsInternal, StatsMarker),
  FilterBar: attachMarker(FilterBarInternal, FilterBarMarker),
  StatusBadge: attachMarker(StatusBadgeInternal, StatusBadgeMarker),
  Card: attachMarker(CardInternal, CardMarker),
  Loading: attachMarker(LoadingInternal, LoadingMarker),
  Empty: attachMarker(EmptyInternal, EmptyMarker),
  Grid: attachMarker(GridInternal, GridMarker),
  useContext: useSubAgentListContext,
});

export default SubAgentList;
