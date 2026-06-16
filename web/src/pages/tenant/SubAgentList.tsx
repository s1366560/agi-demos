/**
 * SubAgentList - SubAgent management page.
 * Slim orchestrator composing SubAgentStats, SubAgentFilters, SubAgentGrid, SubAgentEmptyState.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Dropdown, message, Spin } from 'antd';
import { ChevronDown, Copy, Plus } from 'lucide-react';

import { SubAgentEmptyState } from '../../components/subagent/SubAgentEmptyState';
import { SubAgentFilters } from '../../components/subagent/SubAgentFilters';
import { SubAgentGrid } from '../../components/subagent/SubAgentGrid';
import { SubAgentModal } from '../../components/subagent/SubAgentModal';
import { SubAgentStats } from '../../components/subagent/SubAgentStats';
import { useProjectStore } from '../../stores/project';
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
import { useTenantStore } from '../../stores/tenant';

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
  const [importProjectId, setImportProjectId] = useState<string | null>(null);

  // Store data
  const subagentsData = useSubAgentData();
  const filtersData = useSubAgentFiltersData();
  const templates = useSubAgentTemplates();
  const isLoading = useSubAgentLoading();
  const error = useSubAgentError();
  const enabledCount = useEnabledSubAgentsCount();
  const avgSuccessRate = useAverageSuccessRate();
  const totalInvocations = useTotalInvocations();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);

  const projectNameById = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects]
  );

  const importProjectOptions = useMemo(() => {
    const seen = new Set<string>();
    const options = projects.map((project) => {
      seen.add(project.id);
      return { id: project.id, name: project.name };
    });

    for (const subagent of subagentsData) {
      if (subagent.project_id && !seen.has(subagent.project_id)) {
        seen.add(subagent.project_id);
        options.push({
          id: subagent.project_id,
          name: subagent.project_id,
        });
      }
    }

    return options;
  }, [projects, subagentsData]);

  const getSubAgentScopeLabel = useCallback(
    (subagent: SubAgentResponse): string => {
      if (subagent.project_id) {
        return projectNameById.get(subagent.project_id) ?? subagent.project_id;
      }
      return t('tenant.subagents.card.tenantScope', 'Tenant');
    },
    [projectNameById, t]
  );

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
    void listSubAgents();
    void listTemplates();
  }, [listSubAgents, listTemplates]);

  useEffect(() => {
    if (!currentTenant?.id) {
      return;
    }

    void listProjects(currentTenant.id, { page_size: 100 }).catch(() => {
      message.error(t('tenant.subagents.messages.projectsLoadFailed', 'Failed to load projects'));
    });
  }, [currentTenant?.id, listProjects, t]);

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

  useEffect(
    () => () => {
      clearError();
    },
    [clearError]
  );

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
            enabled ? 'SubAgent enabled' : 'SubAgent disabled'
          )
        );
      } catch {
        // Error handled by store
      }
    },
    [toggleSubAgent, t]
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
    [deleteSubAgent, t]
  );

  const handleCreateFromTemplate = useCallback(
    async (templateId: string) => {
      try {
        const created = await createFromTemplate(templateId);
        message.success(
          t('tenant.subagents.messages.createFromTemplateSuccess', 'SubAgent created from template')
        );
        setEditingSubAgent(created);
        setIsModalOpen(true);
      } catch {
        // Error handled by store
      }
    },
    [createFromTemplate, t]
  );

  const handleRefresh = useCallback(() => {
    void listSubAgents();
  }, [listSubAgents]);

  const handleImportFilesystem = useCallback(
    async (name: string) => {
      try {
        await importFilesystem(name, importProjectId ?? undefined);
        message.success(
          t('tenant.subagents.messages.importSuccess', 'SubAgent imported to database')
        );
      } catch {
        // Error handled by store
      }
    },
    [importFilesystem, importProjectId, t]
  );

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
    void listSubAgents();
  }, [listSubAgents]);

  // Template dropdown menu
  const templateMenuItems: MenuProps['items'] = useMemo(() => {
    if (templates.length === 0) {
      return [
        {
          key: 'empty',
          label: t('tenant.subagents.noTemplates', 'No templates available'),
          disabled: true,
        },
      ];
    }
    return templates.map((tpl: SubAgentTemplate) => ({
      key: tpl.name,
      label: (
        <div className="py-1">
          <div className="font-medium text-sm">{tpl.display_name}</div>
          <div className="text-xs text-slate-500">{tpl.description}</div>
        </div>
      ),
      onClick: () => {
        void handleCreateFromTemplate(tpl.name);
      },
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
          <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <span>{t('tenant.subagents.importTarget.label', 'Import target')}</span>
            <select
              aria-label={t('tenant.subagents.importTarget.label', 'Import target')}
              value={importProjectId ?? 'tenant'}
              onChange={(event) => {
                setImportProjectId(event.target.value === 'tenant' ? null : event.target.value);
              }}
              className="h-9 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
            >
              <option value="tenant">{t('tenant.subagents.importTarget.tenant', 'Tenant')}</option>
              {importProjectOptions.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
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
          onToggle={(id, enabled) => {
            void handleToggle(id, enabled);
          }}
          onEdit={handleEdit}
          onDelete={(id) => {
            void handleDelete(id);
          }}
          onImport={(name) => {
            void handleImportFilesystem(name);
          }}
          getScopeLabel={getSubAgentScopeLabel}
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
