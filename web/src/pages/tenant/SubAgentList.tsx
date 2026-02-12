/**
 * SubAgentList - SubAgent management page.
 * Slim orchestrator composing SubAgentStats, SubAgentFilters, SubAgentGrid, SubAgentEmptyState.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Dropdown, message, Spin } from 'antd';
import { ChevronDown, Copy, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { SubAgentEmptyState } from '../../components/subagent/SubAgentEmptyState';
import { SubAgentFilters } from '../../components/subagent/SubAgentFilters';
import { SubAgentGrid } from '../../components/subagent/SubAgentGrid';
import { SubAgentModal } from '../../components/subagent/SubAgentModal';
import { SubAgentStats } from '../../components/subagent/SubAgentStats';
import {
  filterSubAgents,
  useAverageSuccessRate,
  useClearSubAgentError,
  useCreateFromTemplate,
  useDeleteSubAgent,
  useEnabledSubAgentsCount,
  useImportFilesystem,
  useListSubAgents,
  useListTemplates,
  useSetSubAgentFilters,
  useSubAgentData,
  useSubAgentError,
  useSubAgentFiltersData,
  useSubAgentLoading,
  useSubAgentTemplates,
  useToggleSubAgent,
  useTotalInvocations,
} from '../../stores/subagent';

import type { StatusFilter, SortField } from '../../components/subagent/SubAgentFilters';
import type { SubAgentResponse, SubAgentTemplate } from '../../types/agent';
import type { MenuProps } from 'antd';

// Sort comparators
const SORT_FNS: Record<SortField, (a: SubAgentResponse, b: SubAgentResponse) => number> = {
  name: (a, b) => a.display_name.localeCompare(b.display_name),
  invocations: (a, b) => b.total_invocations - a.total_invocations,
  success_rate: (a, b) => b.success_rate - a.success_rate,
  recent: (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
};

export const SubAgentList: React.FC = () => {
  const { t } = useTranslation();

  // Local UI state
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortField, setSortField] = useState<SortField>('name');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSubAgent, setEditingSubAgent] = useState<SubAgentResponse | null>(null);

  // Store data
  const subagentsData = useSubAgentData();
  const filtersData = useSubAgentFiltersData();
  const templates = useSubAgentTemplates();
  const isLoading = useSubAgentLoading();
  const error = useSubAgentError();
  const enabledCount = useEnabledSubAgentsCount();
  const avgSuccessRate = useAverageSuccessRate();
  const totalInvocations = useTotalInvocations();

  // Store actions
  const listSubAgents = useListSubAgents();
  const listTemplates = useListTemplates();
  const toggleSubAgent = useToggleSubAgent();
  const deleteSubAgent = useDeleteSubAgent();
  const createFromTemplate = useCreateFromTemplate();
  const importFilesystem = useImportFilesystem();
  const setFilters = useSetSubAgentFilters();
  const clearError = useClearSubAgentError();

  // Filtered + sorted list
  const filteredSubagents = useMemo(() => {
    const filtered = filterSubAgents(subagentsData, {
      ...filtersData,
      search,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
    });
    return [...filtered].sort(SORT_FNS[sortField]);
  }, [subagentsData, filtersData, search, statusFilter, sortField]);

  // Load data on mount
  useEffect(() => {
    listSubAgents();
    listTemplates();
  }, [listSubAgents, listTemplates]);

  // Sync filters to store
  useEffect(() => {
    setFilters({
      search,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
    });
  }, [search, statusFilter, setFilters]);

  // Show + clear errors
  useEffect(() => {
    if (error) message.error(error);
  }, [error]);

  useEffect(() => () => clearError(), [clearError]);

  // Handlers
  const handleCreate = useCallback(() => {
    setEditingSubAgent(null);
    setIsModalOpen(true);
  }, []);

  const handleEdit = useCallback((subagent: SubAgentResponse) => {
    setEditingSubAgent(subagent);
    setIsModalOpen(true);
  }, []);

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await toggleSubAgent(id, enabled);
        message.success(
          t(
            enabled
              ? 'tenant.subagents.messages.enableSuccess'
              : 'tenant.subagents.messages.disableSuccess',
            enabled ? 'SubAgent enabled' : 'SubAgent disabled',
          ),
        );
      } catch {
        // Error handled by store
      }
    },
    [toggleSubAgent, t],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteSubAgent(id);
        message.success(t('tenant.subagents.messages.deleteSuccess', 'SubAgent deleted'));
      } catch {
        // Error handled by store
      }
    },
    [deleteSubAgent, t],
  );

  const handleCreateFromTemplate = useCallback(
    async (templateId: string) => {
      try {
        const created = await createFromTemplate(templateId);
        message.success(
          t('tenant.subagents.messages.createFromTemplateSuccess', 'SubAgent created from template'),
        );
        setEditingSubAgent(created);
        setIsModalOpen(true);
      } catch {
        // Error handled by store
      }
    },
    [createFromTemplate, t],
  );

  const handleRefresh = useCallback(() => listSubAgents(), [listSubAgents]);

  const handleImportFilesystem = useCallback(
    async (name: string) => {
      try {
        await importFilesystem(name);
        message.success(
          t('tenant.subagents.messages.importSuccess', 'SubAgent imported to database'),
        );
      } catch {
        // Error handled by store
      }
    },
    [importFilesystem, t],
  );

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
    listSubAgents();
  }, [listSubAgents]);

  // Template dropdown menu
  const templateMenuItems: MenuProps['items'] = useMemo(() => {
    if (templates.length === 0) {
      return [{ key: 'empty', label: t('tenant.subagents.noTemplates', 'No templates available'), disabled: true }];
    }
    return templates.map((tpl: SubAgentTemplate) => ({
      key: tpl.name,
      label: (
        <div className="py-1">
          <div className="font-medium text-sm">{tpl.display_name}</div>
          <div className="text-xs text-slate-500">{tpl.description}</div>
        </div>
      ),
      onClick: () => handleCreateFromTemplate(tpl.name),
    }));
  }, [templates, handleCreateFromTemplate, t]);

  const hasFilters = search !== '' || statusFilter !== 'all';

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-5 p-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.subagents.title', 'SubAgents')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t('tenant.subagents.subtitle', 'Manage specialized AI agents for different tasks')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Dropdown menu={{ items: templateMenuItems }} trigger={['click']}>
            <button
              type="button"
              className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
            >
              <Copy size={16} />
              {t('tenant.subagents.fromTemplate', 'From Template')}
              <ChevronDown size={14} />
            </button>
          </Dropdown>
          <button
            type="button"
            onClick={handleCreate}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
          >
            <Plus size={16} />
            {t('tenant.subagents.createNew', 'Create SubAgent')}
          </button>
        </div>
      </div>

      {/* Stats */}
      <SubAgentStats
        total={subagentsData.length}
        enabledCount={enabledCount}
        avgSuccessRate={Math.round(avgSuccessRate * 100)}
        totalInvocations={totalInvocations}
      />

      {/* Filters */}
      <SubAgentFilters
        search={search}
        onSearchChange={setSearch}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        sortField={sortField}
        onSortChange={setSortField}
        onRefresh={handleRefresh}
      />

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : filteredSubagents.length === 0 ? (
        <SubAgentEmptyState hasFilters={hasFilters} onCreate={handleCreate} />
      ) : (
        <SubAgentGrid
          subagents={filteredSubagents}
          onToggle={handleToggle}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onImport={handleImportFilesystem}
        />
      )}

      {/* Modal */}
      <SubAgentModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        subagent={editingSubAgent}
      />
    </div>
  );
};

export default SubAgentList;
