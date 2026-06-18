/**
 * SubAgentList - SubAgent management page.
 * Slim orchestrator composing SubAgentStats, SubAgentFilters, SubAgentGrid, SubAgentEmptyState.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { Dropdown, message, Spin } from 'antd';
import { ChevronDown, ChevronLeft, ChevronRight, Copy, Plus } from 'lucide-react';

import { SubAgentEmptyState } from '../../components/subagent/SubAgentEmptyState';
import { SubAgentFilters } from '../../components/subagent/SubAgentFilters';
import { SubAgentGrid } from '../../components/subagent/SubAgentGrid';
import { SubAgentModal } from '../../components/subagent/SubAgentModal';
import { SubAgentStats } from '../../components/subagent/SubAgentStats';
import { useDebounce } from '../../hooks/useDebounce';
import { useProjectStore } from '../../stores/project';
import {
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
  useSubAgentLoading,
  useSubAgentTemplates,
  useSubAgentTotal,
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

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;

export const SubAgentList: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string | undefined }>();

  // Local UI state
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortField, setSortField] = useState<SortField>('name');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSubAgent, setEditingSubAgent] = useState<SubAgentResponse | null>(null);
  const [importProjectId, setImportProjectId] = useState<string | null>(null);
  const debouncedSearch = useDebounce(search, 300);

  // Store data
  const subagentsData = useSubAgentData();
  const templates = useSubAgentTemplates();
  const isLoading = useSubAgentLoading();
  const error = useSubAgentError();
  const totalSubAgents = useSubAgentTotal();
  const enabledCount = useEnabledSubAgentsCount();
  const avgSuccessRate = useAverageSuccessRate();
  const totalInvocations = useTotalInvocations();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const tenantOptions = useMemo(() => (tenantId ? { tenant_id: tenantId } : undefined), [tenantId]);
  const tenantProjects = useMemo(
    () => (tenantId ? projects.filter((project) => project.tenant_id === tenantId) : []),
    [projects, tenantId]
  );

  const projectNameById = useMemo(
    () => new Map(tenantProjects.map((project) => [project.id, project.name])),
    [tenantProjects]
  );

  const importProjectOptions = useMemo(() => {
    const seen = new Set<string>();
    const options = tenantProjects.map((project) => {
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
  }, [subagentsData, tenantProjects]);

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

  const subagentQueryParams = useMemo(() => {
    const trimmedSearch = debouncedSearch.trim();
    return {
      ...(tenantOptions ?? {}),
      limit: pageSize,
      offset: (page - 1) * pageSize,
      search: trimmedSearch || undefined,
      enabled_only: statusFilter === 'all' ? undefined : statusFilter === 'enabled',
      sort: sortField,
    };
  }, [debouncedSearch, page, pageSize, sortField, statusFilter, tenantOptions]);

  // Server-filtered + server-sorted page; local sort keeps mocked tests deterministic.
  const visibleSubagents = useMemo(
    () => [...subagentsData].sort(SORT_FNS[sortField]),
    [subagentsData, sortField]
  );

  // Load data on mount
  useEffect(() => {
    if (!tenantOptions) {
      return;
    }

    void listSubAgents(subagentQueryParams);
  }, [listSubAgents, subagentQueryParams, tenantOptions]);

  useEffect(() => {
    if (!tenantOptions) {
      return;
    }

    void listTemplates(tenantOptions);
  }, [listTemplates, tenantOptions]);

  useEffect(() => {
    if (!tenantId) {
      return;
    }

    void listProjects(tenantId, { page_size: 100 }).catch(() => {
      message.error(t('tenant.subagents.messages.projectsLoadFailed', 'Failed to load projects'));
    });
  }, [tenantId, listProjects, t]);

  // Sync filters to store
  useEffect(() => {
    setFilters({
      search: debouncedSearch,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
    });
  }, [debouncedSearch, statusFilter, setFilters]);

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

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
  }, []);

  const handleStatusFilterChange = useCallback((filter: StatusFilter) => {
    setStatusFilter(filter);
    setPage(1);
  }, []);

  const handleSortChange = useCallback((sort: SortField) => {
    setSortField(sort);
    setPage(1);
  }, []);

  const handlePageSizeChange = useCallback((nextPageSize: number) => {
    setPageSize(nextPageSize);
    setPage(1);
  }, []);

  const handleEdit = useCallback((subagent: SubAgentResponse) => {
    setEditingSubAgent(subagent);
    setIsModalOpen(true);
  }, []);

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      if (!tenantOptions) {
        return;
      }

      try {
        await toggleSubAgent(id, enabled, tenantOptions);
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
    [toggleSubAgent, tenantOptions, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (!tenantOptions) {
        return;
      }

      try {
        await deleteSubAgent(id, tenantOptions);
        message.success(t('tenant.subagents.messages.deleteSuccess', 'SubAgent deleted'));
      } catch {
        // Error handled by store
      }
    },
    [deleteSubAgent, tenantOptions, t]
  );

  const handleCreateFromTemplate = useCallback(
    async (templateId: string) => {
      if (!tenantOptions) {
        return;
      }

      try {
        const created = await createFromTemplate(templateId, tenantOptions);
        message.success(
          t('tenant.subagents.messages.createFromTemplateSuccess', 'SubAgent created from template')
        );
        setEditingSubAgent(created);
        setIsModalOpen(true);
      } catch {
        // Error handled by store
      }
    },
    [createFromTemplate, tenantOptions, t]
  );

  const handleRefresh = useCallback(() => {
    if (!tenantOptions) {
      return;
    }

    void listSubAgents(subagentQueryParams);
  }, [listSubAgents, subagentQueryParams, tenantOptions]);

  const handleImportFilesystem = useCallback(
    async (name: string) => {
      if (!tenantOptions) {
        return;
      }

      try {
        await importFilesystem(name, importProjectId ?? undefined, tenantOptions);
        await listSubAgents(subagentQueryParams);
        message.success(
          t('tenant.subagents.messages.importSuccess', 'SubAgent imported to database')
        );
      } catch {
        // Error handled by store
      }
    },
    [importFilesystem, importProjectId, listSubAgents, subagentQueryParams, tenantOptions, t]
  );

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
    if (tenantOptions) {
      void listSubAgents(subagentQueryParams);
    }
  }, [listSubAgents, subagentQueryParams, tenantOptions]);

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

  const totalPages = Math.max(1, Math.ceil(totalSubAgents / pageSize));
  const safePage = Math.min(page, totalPages);
  const rangeStart = totalSubAgents === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const rangeEnd = Math.min(safePage * pageSize, totalSubAgents);
  const hasPreviousPage = page > 1;
  const hasNextPage = page < totalPages;
  const hasFilters = search.trim() !== '' || statusFilter !== 'all';

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
        total={totalSubAgents}
        enabledCount={enabledCount}
        avgSuccessRate={Math.round(avgSuccessRate * 100)}
        totalInvocations={totalInvocations}
      />

      {/* Filters */}
      <SubAgentFilters
        search={search}
        onSearchChange={handleSearchChange}
        statusFilter={statusFilter}
        onStatusFilterChange={handleStatusFilterChange}
        sortField={sortField}
        onSortChange={handleSortChange}
        onRefresh={handleRefresh}
      />

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : visibleSubagents.length === 0 ? (
        <SubAgentEmptyState hasFilters={hasFilters} onCreate={handleCreate} />
      ) : (
        <SubAgentGrid
          subagents={visibleSubagents}
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

      {!isLoading && totalSubAgents > 0 && (
        <div
          className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-700 dark:bg-slate-800 sm:flex-row sm:items-center sm:justify-between"
          aria-label={t('common.pagination.label', 'Pagination')}
        >
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.subagents.pagination.summary', {
              defaultValue: '{{start}}-{{end}} of {{total}}',
              start: rangeStart,
              end: rangeEnd,
              total: totalSubAgents,
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span>{t('tenant.subagents.pagination.rowsPerPage', 'Rows')}</span>
              <select
                aria-label={t('tenant.subagents.pagination.rowsPerPage', 'Rows per page')}
                value={pageSize}
                onChange={(event) => {
                  handlePageSizeChange(Number(event.target.value));
                }}
                className="h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
              >
                {PAGE_SIZE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              aria-label={t('tenant.subagents.pagination.previousPage', 'Previous page')}
              disabled={!hasPreviousPage}
              onClick={() => {
                setPage((currentPage) => Math.max(1, currentPage - 1));
              }}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <span className="min-w-20 text-center text-sm text-slate-600 dark:text-slate-300">
              {t('common.pagination.page_info', {
                defaultValue: 'Page {{page}} of {{total}}',
                page: safePage,
                total: totalPages,
              })}
            </span>
            <button
              type="button"
              aria-label={t('tenant.subagents.pagination.nextPage', 'Next page')}
              disabled={!hasNextPage}
              onClick={() => {
                setPage((currentPage) => Math.min(totalPages, currentPage + 1));
              }}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {/* Modal */}
      <SubAgentModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        subagent={editingSubAgent}
        tenantId={tenantId}
      />
    </div>
  );
};

export default SubAgentList;
